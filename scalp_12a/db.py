"""12A database access: its OWN connection (application_name=scalp12a).

Reads HR tables (hr_*) and the 1-minute context tables read-only; writes
only scalp12a_* tables. It never writes to HR, 11D (paper_*) or pipeline
tables -- pinned by tests/test_scalp12a_isolation.py.
"""

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

import psycopg

from config.settings import DB_SCHEMA, IST, require_database_url
from scalp_12a.config import STRATEGY_VERSION, ScalpConfig
from scalp_12a.exits import OPEN
from scalp_12a.models import Candidate, Leg, Quote, SessionBars

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
WRITABLE_TABLES = ("scalp12a_shadow_sessions", "scalp12a_candidates")
HR_OK_STATUSES = ("RUNNING", "COMPLETED", "COMPLETED_WITH_GAPS")


def connect(statement_timeout_ms: int = 15000) -> psycopg.Connection:
    options = f"-c search_path={DB_SCHEMA},public -c statement_timeout={statement_timeout_ms} -c lock_timeout=2000"
    return psycopg.connect(require_database_url(), autocommit=True, application_name="scalp12a", options=options)


def apply_schema(conn) -> None:
    conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- reading HR
def hr_session_ids(conn, until: date | None = None) -> list[tuple[date, str, str]]:
    sql = "SELECT trading_date, session_id, status FROM hr_capture_sessions WHERE status = ANY(%s)"
    params: list = [list(HR_OK_STATUSES)]
    if until:
        sql += " AND trading_date <= %s"
        params.append(until)
    return [tuple(r) for r in conn.execute(sql + " ORDER BY trading_date", params).fetchall()]


def load_session(conn, session_id: str, trading_date: date, symbol: str, until: datetime | None = None) -> SessionBars | None:
    cfg = conn.execute("SELECT config FROM hr_capture_sessions WHERE session_id=%s", (session_id,)).fetchone()
    uni = (cfg[0] or {}).get("universe", {}).get(symbol) if cfg else None
    if not uni:
        return None
    expiry = date.fromisoformat(uni["expiry"]) if uni.get("expiry") else None
    legs = {}
    for ot, off, strike, sid in conn.execute(
            "SELECT option_type, atm_offset, strike, security_id FROM hr_instruments WHERE session_id=%s AND symbol=%s "
            "AND instrument_type='OPTIDX'", (session_id, symbol)).fetchall():
        legs[(ot, int(off))] = Leg(ot, int(off), float(strike), int(sid) if sid is not None else None)
    lim = " AND bar_ts <= %s" if until else ""
    p = (session_id, symbol) + ((until,) if until else ())
    bars = conn.execute(
        "SELECT instrument_type, bar_ts, close, update_count FROM hr_ohlc_5s WHERE session_id=%s AND symbol=%s "
        f"AND instrument_type IN ('FUTIDX','INDEX'){lim} ORDER BY bar_ts", p).fetchall()
    opts = conn.execute(
        "SELECT option_type, atm_offset, bar_ts, bid, ask, mid, spread_pct, quote_age_s, volume_delta, depth_imbalance "
        f"FROM hr_option_5s WHERE session_id=%s AND symbol=%s{lim} ORDER BY bar_ts", p).fetchall()
    stamps = [r[1] for r in bars] + [r[2] for r in opts]
    if not stamps:
        return None
    start = datetime.combine(trading_date, time(14, 55), tzinfo=IST)
    end = max(stamps).astimezone(IST)
    times = []
    t = start
    while t <= end:
        times.append(t)
        t += timedelta(seconds=5)
    pos = {ts: i for i, ts in enumerate(times)}
    n = len(times)
    fut, upd, idx = [None] * n, [False] * n, [None] * n
    for itype, ts, close, uc in bars:
        i = pos.get(ts.astimezone(IST))
        if i is None:
            continue
        if itype == "FUTIDX":
            fut[i] = float(close) if close is not None else None
            upd[i] = bool(uc)
        else:
            idx[i] = float(close) if close is not None else None
    quotes = {k: [None] * n for k in legs}
    for ot, off, ts, bid, ask, mid, sp, age, vd, di in opts:
        i = pos.get(ts.astimezone(IST))
        key = (ot, int(off))
        if i is None or key not in quotes:
            continue
        f = lambda v: float(v) if v is not None else None
        quotes[key][i] = Quote(f(bid), f(ask), f(mid), f(sp), f(age), f(vd), f(di))
    return SessionBars(symbol, trading_date, expiry, float(uni["band_atm_strike"]), float(uni["strike_step"]),
                       times, fut, upd, idx, legs, quotes)


def load_context_fn(conn, trading_date: date):
    """1-minute structural CONTEXT (never a veto): latest levels row at/before ts, plus the 11D decision."""
    rows = {}
    for sym, as_of, close, vwap, poc, vah, val, trend, bias in conn.execute(
            "SELECT symbol, as_of, close, vwap_now, today_poc, today_vah, today_val, trend_label, institutional_bias_label "
            "FROM levels_snapshots WHERE as_of::date=%s AND as_of::time >= '14:30' ORDER BY as_of", (trading_date,)).fetchall():
        rows.setdefault(sym, []).append((as_of, dict(close=close, vwap=vwap, poc=poc, vah=vah, val=val, trend=trend, bias=bias)))
    d11 = {sym: dict(decision=dec, reason=reason, verdict=verdict)
           for sym, dec, reason, verdict in conn.execute(
               "SELECT symbol, decision, no_trade_reason, transition_verdict FROM paper_decisions WHERE session_date=%s",
               (trading_date,)).fetchall()}

    def ctx(symbol, ts):
        latest = None
        for as_of, v in rows.get(symbol, []):
            if as_of <= ts:
                latest = (as_of, v)
        out = {"control_11d": d11.get(symbol)}
        if latest:
            v = dict(latest[1])
            v["as_of"] = latest[0].isoformat()
            if v.get("close") is not None and v.get("vwap") is not None:
                v["price_vs_vwap"] = round(v["close"] - v["vwap"], 2)
            out["levels_1min"] = v
        return out
    return ctx


# ---------------------------------------------------------------- writing
def _r(v, nd=4):
    return None if v is None else round(float(v), nd)


def candidate_row(c: Candidate, source: str, config_hash: str, thresholds: dict, is_expiry: bool,
                  detected_wall_ts: datetime | None) -> dict:
    e, s, rk, cf, x, px = c.event, c.selection, c.risk, c.counterfactual, c.counterfactual_exit, c.policy_exit
    leg = s.leg if s and s.leg else None
    latency = None
    if detected_wall_ts is not None:
        latency = (detected_wall_ts - (c.bar_ts + timedelta(seconds=5))).total_seconds()
    complete = bool(cf and cf.complete and (x is None or x.reason != OPEN))
    return dict(
        trading_date=c.trading_date, symbol=c.symbol, source=source, strategy_version=STRATEGY_VERSION,
        config_hash=config_hash, event_bar_ts=c.bar_ts, detected_wall_ts=detected_wall_ts,
        detection_latency_s=_r(latency, 2), market_mode=c.mode, is_expiry_day=is_expiry,
        event_type=e.event_type, event_strength=e.strength, direction="UP" if e.direction > 0 else "DOWN",
        event_metrics=json.dumps(dict(r15=_r(e.r15), r30=_r(e.r30), r180=_r(e.r180), r180_prior=_r(e.r180_prior),
                                      r300=_r(e.r300), displacement=_r(e.displacement), origin=_r(e.origin_price),
                                      consistency=_r(e.consistency))),
        thresholds=json.dumps(thresholds), confirmation=json.dumps(c.confirmation, default=str),
        context=json.dumps(c.context, default=str),
        option_type=leg.option_type if leg else None, strike=leg.strike if leg else None,
        atm_offset=leg.atm_offset if leg else None, security_id=leg.security_id if leg else None,
        selection=json.dumps(dict(response_pct=_r(s.response_pct), score=s.score, considered=s.considered,
                                  rejections=s.rejections, spread_pct=_r(s.quote.spread_pct) if s.quote else None,
                                  quote_ask=_r(s.quote.ask) if s.quote else None) if s else {}),
        counterfactual_leg_source=c.counterfactual_leg_source,
        entry_ref_ask=_r(rk.entry_ref_ask) if rk else None, stop_price=_r(rk.stop_price) if rk else None,
        target_price=_r(rk.target_price) if rk else None, quantity=rk.quantity if rk else None,
        rupee_risk=_r(rk.rupee_risk, 2) if rk else None,
        underlying_invalidation=_r(rk.underlying_invalidation) if rk else None,
        max_hold_seconds=rk.max_hold_seconds if rk else None,
        passed_gates=c.passed_gates, would_trade=c.would_trade, no_trade_reasons=list(c.no_trade_reasons),
        satisfied_risk_rules=(rk is not None and not rk.reasons),
        entry_ts=cf.entry_ts if cf else None, entry_ask=_r(cf.entry_ask) if cf else None,
        entry_spread_pct=_r(cf.entry_spread_pct) if cf else None, mfe_pct=_r(cf.mfe_pct) if cf else None,
        mae_pct=_r(cf.mae_pct) if cf else None, t_mfe_s=cf.t_mfe_s if cf else None, t_mae_s=cf.t_mae_s if cf else None,
        horizon_exit_pct=json.dumps({str(k): _r(v) for k, v in cf.horizon_exit_pct.items()}) if cf else None,
        horizon_mfe_pct=json.dumps({str(k): _r(v) for k, v in cf.horizon_mfe_pct.items()}) if cf else None,
        horizon_mae_pct=json.dumps({str(k): _r(v) for k, v in cf.horizon_mae_pct.items()}) if cf else None,
        underlying_move=_r(cf.underlying_move) if cf else None,
        cf_exit_reason=x.reason if x else None,
        cf_exit_ts=x.exit_ts if x else None,
        cf_exit_bid=_r(x.exit_bid) if x else None, cf_exit_pnl_pct=_r(x.pnl_pct) if x else None,
        cf_hold_seconds=x.hold_seconds if x else None, cf_peak_gain_pct=_r(x.peak_gain_pct) if x else None,
        cf_giveback_pct=_r(x.peak_gain_pct - x.pnl_pct) if x and x.pnl_pct is not None and x.peak_gain_pct is not None else None,
        policy_exit_reason=px.reason if px else None, policy_exit_pnl_pct=_r(px.pnl_pct) if px else None,
        policy_exit_rupees=_r(px.pnl_pct / 100.0 * px.entry_ask * rk.quantity, 2) if px and px.pnl_pct is not None and rk else None,
        outcome_complete=complete, data_quality=c.data_quality,
        **_opportunity_cols(c.opportunity),
    )


def _opportunity_cols(o) -> dict:
    if o is None:
        return dict(detection_timing="UNKNOWN")
    return dict(
        event_start_ts=o.event_start_ts, event_start_fut=_r(o.event_start_fut), detection_bar_end_ts=o.detection_bar_end_ts,
        detection_fut=_r(o.detection_fut), detection_option_mid=_r(o.detection_option_mid),
        detection_option_ask=_r(o.detection_option_ask), entry_fut=_r(o.entry_fut),
        realized_at_detection=_r(o.realized_at_detection), realized_at_entry=_r(o.realized_at_entry),
        fut_mfe_after_detection=_r(o.fut_mfe_after_detection), fut_mae_after_detection=_r(o.fut_mae_after_detection),
        t_fut_mfe_after_detection_s=o.t_fut_mfe_after_detection_s, t_fut_mae_after_detection_s=o.t_fut_mae_after_detection_s,
        remaining_after_entry=_r(o.remaining_after_entry), total_event_move=_r(o.total_move),
        remaining_fraction_at_detection=_r(o.remaining_fraction_at_detection),
        remaining_fraction_at_entry=_r(o.remaining_fraction_at_entry),
        option_move_before_entry_pct=_r(o.option_move_before_entry_pct), detection_timing=o.timing)


def upsert_candidate(conn, row: dict) -> None:
    cols = list(row)
    keep_first = ("detected_wall_ts", "detection_latency_s")
    updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols
                        if c not in keep_first + ("trading_date", "symbol", "source", "config_hash", "event_bar_ts"))
    sql = (f"INSERT INTO scalp12a_candidates ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
           f"ON CONFLICT (trading_date, symbol, source, config_hash, event_bar_ts) DO UPDATE SET {updates}, updated_at=now()")
    conn.execute(sql, [row[c] for c in cols])


def upsert_session(conn, trading_date, source, config_hash, hr_session_id, status, thresholds, bars, stale,
                   n_cand, n_trade, reasons, notes=None) -> None:
    conn.execute(
        "INSERT INTO scalp12a_shadow_sessions (trading_date, source, strategy_version, config_hash, hr_session_id, status, "
        "thresholds, bars_evaluated, stale_bars, candidates, would_trade, session_reasons, notes) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (trading_date, source, config_hash) DO UPDATE SET "
        "hr_session_id=EXCLUDED.hr_session_id, status=EXCLUDED.status, thresholds=EXCLUDED.thresholds, "
        "bars_evaluated=EXCLUDED.bars_evaluated, stale_bars=EXCLUDED.stale_bars, candidates=EXCLUDED.candidates, "
        "would_trade=EXCLUDED.would_trade, session_reasons=EXCLUDED.session_reasons, notes=EXCLUDED.notes, updated_at=now()",
        (trading_date, source, STRATEGY_VERSION, config_hash, hr_session_id, status, json.dumps(thresholds), bars, stale,
         n_cand, n_trade, json.dumps(reasons), notes))


def thresholds_json(thr) -> dict:
    return dict(thr30_event=_r(thr.thr30_event), thr30_weak=_r(thr.thr30_weak), thr180_event=_r(thr.thr180_event),
                history_days=list(thr.history_days), sufficient=thr.sufficient)
