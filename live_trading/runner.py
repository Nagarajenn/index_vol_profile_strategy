"""One tick of the live trader: read the market, ask 12C, run the guards, act or refuse.

Stateless by design -- every tick rebuilds its view from Postgres and from the minute data
the pipeline has already captured. A mid-session restart therefore needs no recovery logic,
and no counter can drift out of step with the rows that back it.

This module never imports pipeline.live_loop and is never imported by it. The two processes
coordinate only through the database.
"""

from datetime import date, datetime

from config.settings import IST
from live_trading import VERSION, broker, journal, state
from live_trading.config import DEFAULT, DRY_RUN_DEFAULT, LOTS_PER_ENTRY
from live_trading.contracts import limit_price, resolve
from live_trading.guards import EntryContext, check, correlation_id
from live_trading.trigger import candidate
from option_risk_12b.engine import prepare
from option_risk_12b.option_state import leg
from scalp_decision_12c import loader
from scalp_decision_12c.config import DEFAULT as DECISION_CFG
from scalp_decision_12c.engine import decide_prepared

LEVELS_COLS = ("as_of", "close", "vwap_now", "today_poc", "today_vah", "today_val", "support_low",
               "support_high", "resistance_low", "resistance_high", "trend_label")


def _levels_by_minute(read, symbol: str, d: date) -> dict:
    rows = read.execute(
        f"""select to_char(as_of at time zone 'Asia/Kolkata','HH24:MI'), {', '.join(LEVELS_COLS[1:])}
            from levels_snapshots where symbol=%s and (as_of at time zone 'Asia/Kolkata')::date=%s
            order by as_of""", (symbol, d)).fetchall()
    return {r[0]: dict(zip(LEVELS_COLS, r)) for r in rows}


def _decisions(symbol: str, d: date, series, cmap, levels: dict, upto: str):
    """Replay 12C minute by minute up to `upto`. Each minute sees only its own causal inputs."""
    rows, cur = [], None
    for m in sorted(x for x in series if "09:15" <= x <= upto):
        cur = levels.get(m, cur)
        out = decide_prepared(symbol, d, series, cmap, cur, minute=m)
        rows.append((m, out))
    return rows


def tick(symbol: str, now: datetime | None = None, dry_run: bool = DRY_RUN_DEFAULT, cfg=DEFAULT) -> dict:
    """Evaluate one minute. Returns a summary dict; every outcome is journalled."""
    now = now or datetime.now(IST)
    d = now.date()
    read, write = loader.connect(), state.connect()
    try:
        return _tick(symbol, d, now, read, write, dry_run, cfg)
    finally:
        read.close()
        write.close()


def _tick(symbol, d, now, read, write, dry_run, cfg) -> dict:
    snaps = loader.load_snapshots(read, symbol, d, start="09:00")
    if not snaps:
        journal.log(write, d, "NO_DATA", f"no option snapshots for {symbol}", symbol=symbol)
        return dict(symbol=symbol, action="NO_DATA")
    series, cmap = prepare(snaps, loader.load_candles(read, symbol, d, start="09:00"))
    minute = max(series)                                   # the latest minute the pipeline has captured
    age_min = (now - series[minute]["fetched_at"]).total_seconds() / 60.0

    rows = _decisions(symbol, d, series, cmap, _levels_by_minute(read, symbol, d), minute)
    history = [(m, (o.get("entry") or {}).get("decision")) for m, o in rows if o.get("status") == "OK"]
    out = dict(rows)[minute]
    cand = candidate(out, history, series, minute)

    sess = state.session(write, symbol, d)
    counters = state.refresh_counters(write, symbol, d)
    pos = state.open_position(write, symbol, d)
    last_entry = write.execute(
        """SELECT max(signal_minute) FROM live_orders WHERE symbol=%s AND session_date=%s
           AND status IN ('SENT','FILLED','DRY_RUN')""", (symbol, d)).fetchone()[0]

    if cand is None:
        return dict(symbol=symbol, minute=minute, action="NO_SIGNAL",
                    decision=(out.get("entry") or {}).get("decision"), open_position=bool(pos))

    cid = correlation_id(symbol, d, minute)
    contract, why = resolve(symbol, cand.expiry, cand.strike, cand.side) if (cand.expiry and cand.strike) \
        else (None, "UNKNOWN: no ATM strike or expiry in the snapshot")

    ctx = EntryContext(
        symbol=symbol, session_date=d, now=now, minute=minute, decision=cand.decision,
        confirmation=cand.confirmation, episode_minutes=cand.episode_minutes,
        armed=sess["armed"], halted=sess["halted"], halt_reason=sess["halt_reason"],
        kill_switch=sess["kill_switch"], entries_used=counters["entries_used"],
        open_position=bool(pos), realised_pnl=counters["realised_pnl"], correlation_id=cid,
        already_seen=state.seen(write, cid), last_entry_minute=last_entry,
        contract_ok=contract is not None, contract_reason=why,
        lot_size=contract.lot_size if contract else None, ask=cand.ask, spread_pct=cand.spread_pct,
        snapshot_age_min=round(age_min, 2), cfg=cfg)
    refusals, passed = check(ctx)

    base = dict(correlation_id=cid, symbol=symbol, session_date=d, signal_minute=minute,
                decision=cand.decision, confirmation=cand.confirmation, decision_reason=cand.reason,
                episode_minutes=cand.episode_minutes, option_type=cand.side, strike=cand.strike,
                expiry=cand.expiry, ask=cand.ask, bid=cand.bid, spread_pct=cand.spread_pct,
                entry_cost=ctx.entry_cost, guards_passed=passed, refusal_reasons=refusals or None,
                dry_run=dry_run, evidence=cand.evidence, live_version=VERSION,
                live_config_hash=cfg.config_hash(), decision_config_hash=DECISION_CFG.config_hash(),
                contract_label=contract.label if contract else None,
                security_id=contract.security_id if contract else None,
                exchange_segment=contract.exchange_segment if contract else None,
                lot_size=contract.lot_size if contract else None,
                quantity=(contract.lot_size * LOTS_PER_ENTRY) if contract else None)

    if refusals:
        # Refusals are journalled but NOT written to live_orders: a refused minute must not
        # consume the correlation id, or a later minute that qualifies could be blocked by it.
        journal.log(write, d, "REFUSED", "; ".join(refusals), symbol=symbol, minute=minute,
                    payload=dict(decision=cand.decision, confirmation=cand.confirmation,
                                 episode_minutes=cand.episode_minutes, entry_cost=ctx.entry_cost))
        return dict(symbol=symbol, minute=minute, action="REFUSED", reasons=refusals)

    limit = limit_price(cand.ask, contract.tick_size, cfg.ticks_through)
    req = broker.build_entry(contract, limit, cid, LOTS_PER_ENTRY, cfg)
    # Written BEFORE the send, so a crash mid-flight still leaves a trace of the intent.
    state.record_order(write, dict(base, limit_price=limit, status="PENDING",
                                   broker_request=req.as_dict()))
    journal.log(write, d, "ORDER", f"{cand.decision} {contract.label} qty {req.quantity} limit {limit}",
                symbol=symbol, minute=minute, payload=req.as_dict())

    resp = broker.send(req, dry_run=dry_run)
    status = resp["status"]
    state.update_order(write, cid, status=status, broker_response=resp,
                       broker_order_id=broker.order_id_of(resp))
    if status in ("SENT", "DRY_RUN"):
        state.record_position(write, dict(base, entry_price=limit, entry_at=now,
                                          entry_cost=limit * req.quantity))
        state.refresh_counters(write, symbol, d)
    return dict(symbol=symbol, minute=minute, action=status, contract=contract.label,
                quantity=req.quantity, limit=limit, dry_run=dry_run)


def force_flat(symbol: str, now: datetime | None = None, dry_run: bool = DRY_RUN_DEFAULT, cfg=DEFAULT) -> dict:
    """The one agent-initiated exit: at 15:10 nothing is carried into the close.

    This is the single exception to "the trader manages the exit", agreed 2026-09-23, because
    auto-entry with a purely manual exit leaves an open position with no floor under it."""
    now = now or datetime.now(IST)
    d = now.date()
    read, write = loader.connect(), state.connect()
    try:
        pos = state.open_position(write, symbol, d)
        if not pos:
            return dict(symbol=symbol, action="NOTHING_TO_FLATTEN")
        snaps = loader.load_snapshots(read, symbol, d, start="09:00")
        series, _ = prepare(snaps, [])
        minute = max(series) if series else None
        q = leg(series, minute, pos["option_type"], float(pos["strike"])) if minute else None
        bid = (q or {}).get("bid")
        if bid is None:
            journal.log(write, d, "FORCE_FLAT_BLOCKED", "no two-sided quote to exit against",
                        symbol=symbol, minute=minute)
            return dict(symbol=symbol, action="NO_QUOTE")
        contract, why = resolve(symbol, str(series[minute].get("expiry")), float(pos["strike"]),
                                pos["option_type"])
        if contract is None:
            journal.log(write, d, "FORCE_FLAT_BLOCKED", why, symbol=symbol, minute=minute)
            return dict(symbol=symbol, action="NO_CONTRACT", reason=why)
        limit = limit_price(bid - cfg.ticks_through * contract.tick_size, contract.tick_size, 0)
        req = broker.build_exit(contract, int(pos["quantity"]), limit, pos["correlation_id"], cfg)
        journal.log(write, d, "FORCE_FLAT", f"15:10 flatten {contract.label} at {limit}",
                    symbol=symbol, minute=minute, payload=req.as_dict())
        resp = broker.send(req, dry_run=dry_run)
        pnl = state.close_position(write, pos["correlation_id"], limit, now, "FORCE_FLAT_15_10")
        state.refresh_counters(write, symbol, d)
        return dict(symbol=symbol, action="FLATTENED", contract=contract.label, exit=limit,
                    realised_pnl=pnl, dry_run=dry_run, broker_status=resp["status"])
    finally:
        read.close()
        write.close()
