"""Historical replay of 13A against the same sessions 12D/12E used (spec 24), plus the
leakage audit.

12C produces the candidates; 13A decides whether each survives its gates. The comparison is
therefore like-for-like: identical signal stream, different selectivity.

Dev / validation / unseen splitting (spec 25) is by DATE and is done here, not by the caller,
so the split cannot drift between runs.
"""

from datetime import date

from option_risk_12b.engine import prepare
from option_risk_12b.option_snapshot import shift
from scalp_decision_12c import loader
from scalp_decision_12c.engine import decide_prepared
from live_scalping_13a import engine as EN
from live_scalping_13a import features as FE
from live_scalping_13a import position as POS
from live_scalping_13a import risk_brake as RB
from live_scalping_13a.config import BUY_CE, BUY_PE, DEFAULT
from position_sim_12c.lots import lot_size

LEVELS_COLS = ("as_of", "close", "vwap_now", "today_poc", "today_vah", "today_val", "support_low",
               "support_high", "resistance_low", "resistance_high", "trend_label")
SESSION_OPEN, SESSION_LAST = "09:15", "15:30"


def levels_for(conn, symbol, d) -> dict:
    rows = conn.execute(
        f"""select to_char(as_of at time zone 'Asia/Kolkata','HH24:MI'), {', '.join(LEVELS_COLS[1:])}
            from levels_snapshots where symbol=%s and (as_of at time zone 'Asia/Kolkata')::date=%s
            order by as_of""", (symbol, d)).fetchall()
    return {r[0]: dict(zip(LEVELS_COLS, r)) for r in rows}


def base_decisions(symbol, d, series, cmap, levels) -> list[dict]:
    """12C's own stream, unmodified and read-only."""
    out, cur = [], None
    for m in sorted(x for x in series if SESSION_OPEN <= x <= SESSION_LAST):
        cur = levels.get(m, cur)
        r = decide_prepared(symbol, d, series, cmap, cur, minute=m)
        if r.get("status") != "OK":
            continue
        e = r["entry"]
        out.append(dict(minute=m, decision=e["decision"], confirmation=e["confirmation"],
                        atm=(r.get("option_state") or {}).get("atm_strike")))
    return out


def replay_session(conn, symbol: str, d: date, cfg=DEFAULT) -> dict:
    """One symbol-day under 13A. Returns decisions, positions and rejection counts."""
    snaps = loader.load_snapshots(conn, symbol, d, start="09:00")
    if not snaps:
        return dict(symbol=symbol, session_date=str(d), decisions=[], positions=[], rejections={})
    series, cmap = prepare(snaps, loader.load_candles(conn, symbol, d, start="09:00"))
    base = base_decisions(symbol, d, series, cmap, levels_for(conn, symbol, d))
    risk = RB.RiskState()
    decisions, positions, rejections = [], [], {}
    open_pos: POS.Position | None = None

    for row in base:
        m, strike = row["minute"], row["atm"]
        expiry = series[m].get("expiry") if m in series else None
        qty, _ = lot_size(symbol, expiry) if expiry else (None, "")

        # manage an open position first -- risk lock never stops management
        if open_pos is not None:
            card = open_pos.mark(series, m)
            if card.get("priced") and card["stop_breached"]:
                open_pos.close(series, m, "STOP_LOSS")
            elif row["decision"] in (BUY_CE, BUY_PE) and row["decision"][-2:] != open_pos.side:
                open_pos.close(series, m, "SIGNAL_FLIP")
            elif m >= SESSION_LAST:
                open_pos.close(series, m, "SESSION_END")
            if open_pos.status == POS.CLOSED:
                if open_pos.realised_pnl is not None:
                    risk.record_close(open_pos.realised_pnl)
                positions.append(open_pos.to_dict())
                open_pos = None

        out = EN.decide(series, m, row["decision"], row["confirmation"], strike, risk,
                        position_open=open_pos is not None, quantity=qty, cfg=cfg)
        decisions.append(EN.audit_row(out))
        rr = out.get("primary_rejection_reason")
        if rr:
            rejections[rr] = rejections.get(rr, 0) + 1

        if out["decision"] in (BUY_CE, BUY_PE) and open_pos is None:
            open_pos = POS.open_position(series, m, symbol, d, out["side"], strike, qty,
                                         out["quality"], cfg)

    if open_pos is not None:
        last = max(series)
        open_pos.mark(series, last)
        open_pos.close(series, last, "SESSION_END")
        if open_pos.realised_pnl is not None:
            risk.record_close(open_pos.realised_pnl)
        positions.append(open_pos.to_dict())

    return dict(symbol=symbol, session_date=str(d), decisions=decisions, positions=positions,
                rejections=rejections, base_signals=sum(1 for b in base if b["decision"] in (BUY_CE, BUY_PE)),
                base_minutes=len(base), risk=RB.evaluate(risk, cfg))


# ---------------------------------------------------------------- leakage audit
AUDIT_FIELDS = ("underlying", "bid", "ask", "mid", "spread", "delta", "iv", "theta",
                "und_pre_1m", "und_pre_3m", "und_pre_5m", "opt_pre_3m", "opt_pre_5m",
                "regime_lookback_pct", "regime_recent_pct", "premium_range_position",
                "volume_ratio", "oi_pct_3m", "dist_from_local_high_pct", "dist_from_local_low_pct")


def leakage_audit(conn, symbol: str, d: date, cfg=DEFAULT, sample: int = 30) -> dict:
    """Recompute each decision's features with all later minutes deleted; they must be identical."""
    snaps = loader.load_snapshots(conn, symbol, d, start="09:00")
    if not snaps:
        return dict(symbol=symbol, checked=0, mismatches=[], passed=True, note="no data")
    series, cmap = prepare(snaps, loader.load_candles(conn, symbol, d, start="09:00"))
    base = base_decisions(symbol, d, series, cmap, levels_for(conn, symbol, d))
    cands = [b for b in base if b["decision"] in (BUY_CE, BUY_PE) and b["atm"]][:sample]
    mismatches, checked = [], 0
    for b in cands:
        m, side = b["minute"], b["decision"][-2:]
        full = FE.build(series, m, side, b["atm"], cfg)
        trunc = FE.build({k: v for k, v in series.items() if k <= m}, m, side, b["atm"], cfg)
        checked += 1
        for f in AUDIT_FIELDS:
            if full.get(f) != trunc.get(f):
                mismatches.append(dict(minute=m, field=f, full=full.get(f), truncated=trunc.get(f)))
        # the regime verdict itself must also be identical
        if G_state(full, cfg) != G_state(trunc, cfg):
            mismatches.append(dict(minute=m, field="regime", full=G_state(full, cfg),
                                   truncated=G_state(trunc, cfg)))
    return dict(symbol=symbol, session_date=str(d), checked=checked,
                fields_compared=len(AUDIT_FIELDS) + 1, mismatches=mismatches,
                passed=not mismatches)


def G_state(f, cfg):
    from live_scalping_13a.gates import regime
    return regime(f, cfg)["state"]


# ---------------------------------------------------------------- date splitting (spec 25)
def split_dates(days: list, dev_frac: float = 0.5, val_frac: float = 0.25) -> dict:
    """Chronological, never random: a random split would leak later regimes into development."""
    days = sorted(days)
    n = len(days)
    a, b = int(n * dev_frac), int(n * (dev_frac + val_frac))
    return dict(development=days[:a], validation=days[a:b], unseen=days[b:])
