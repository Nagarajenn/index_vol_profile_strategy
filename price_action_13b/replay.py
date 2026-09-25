"""13A vs 13B on identical sessions, plus the leakage audit.

The comparison is strictly like-for-like: the SAME 12C candidates run through the SAME 13A
gates. The only difference is that 13B may veto a surviving BUY. 13A itself is imported and
used unmodified.

What happens to a rejected candidate is measured, not assumed: for every trade 13B blocked, the
forward path of the option is followed so the report can say whether the block avoided an
adverse move or gave up a favourable one.
"""

from datetime import date

from option_risk_12b.engine import prepare
from option_risk_12b.option_snapshot import shift
from position_sim_12c.lots import lot_size
from scalp_decision_12c import loader
from live_scalping_13a import engine as EN13A
from live_scalping_13a import position as POS
from live_scalping_13a import replay as RP13A
from live_scalping_13a import risk_brake as RB
from live_scalping_13a.config import BUY_CE, BUY_PE
from live_scalping_13a.config import DEFAULT as CFG13A
from price_action_13b import VERSION
from price_action_13b import bars as B
from price_action_13b import decide as D
from price_action_13b.config import DEFAULT

SESSION_LAST = "15:30"


def _excursions(series, minute, side, strike, entry_ask, horizon=10) -> dict:
    """What the option did AFTER the candidate minute. Used only to score outcomes, never to
    decide anything."""
    from live_scalping_13a.features import quote
    marks = []
    for k in range(1, horizon + 1):
        q = quote(series, shift(minute, k), side, strike)
        if q["bid"] is not None:
            marks.append(q["bid"])
    if not marks or entry_ask is None:
        return dict(mfe=None, mae=None, end=None)
    diffs = [round(m - entry_ask, 2) for m in marks]
    return dict(mfe=max(diffs), mae=min(diffs), end=diffs[-1])


def replay_session(conn, symbol: str, d: date, cfg=DEFAULT) -> dict:
    """One symbol-day under both engines."""
    snaps = loader.load_snapshots(conn, symbol, d, start="09:00")
    if not snaps:
        return None
    series, cmap = prepare(snaps, loader.load_candles(conn, symbol, d, start="09:00"))
    levels_by_min = RP13A.levels_for(conn, symbol, d)
    base = RP13A.base_decisions(symbol, d, series, cmap, levels_by_min)

    out = dict(symbol=symbol, session_date=str(d), a=_run(series, cmap, levels_by_min, base,
                                                          symbol, d, None, cfg),
               b=_run(series, cmap, levels_by_min, base, symbol, d, cfg, cfg))
    return out


def _run(series, cmap, levels_by_min, base, symbol, d, pa_cfg, cfg) -> dict:
    """One engine pass. `pa_cfg=None` runs plain 13A; otherwise 13B vetoes as well."""
    risk = RB.RiskState()
    positions, blocked, decisions, open_pos, cur_levels = [], [], [], None, None

    for row in base:
        m, strike = row["minute"], row["atm"]
        cur_levels = levels_by_min.get(m, cur_levels)
        expiry = series[m].get("expiry") if m in series else None
        qty, _ = lot_size(symbol, expiry) if expiry else (None, "")

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

        a = EN13A.decide(series, m, row["decision"], row["confirmation"], strike, risk,
                         position_open=open_pos is not None, quantity=qty, cfg=CFG13A)
        final, pa = a["decision"], None
        if pa_cfg is not None and a["decision"] in (BUY_CE, BUY_PE):
            pa = D.evaluate(cmap, m, a["side"], cur_levels, pa_cfg)
            applied = D.apply(a["decision"], pa, pa_cfg)
            final = applied["final_decision"]
            if applied["price_action_block"]:
                from live_scalping_13a.features import quote
                ask = quote(series, m, a["side"], strike)["ask"]
                blocked.append(dict(minute=m, symbol=symbol, session_date=str(d), side=a["side"],
                                    strike=strike, quality=a["quality"], entry_ask=ask,
                                    confirmation=pa["confirmation"], reason=pa["reason"],
                                    structure=pa["structure"], break_state=pa["break_state"],
                                    setup=pa["setup"], vwap_state=pa["vwap_state"],
                                    volume_state=pa["volume_state"],
                                    **_excursions(series, m, a["side"], strike, ask)))
        decisions.append(dict(minute=m, symbol=symbol, session_date=str(d),
                              thirteen_a=a["decision"], final=final,
                              price_action=(pa or {}).get("confirmation"),
                              pa_reason=(pa or {}).get("reason"),
                              structure=(pa or {}).get("structure"),
                              break_state=(pa or {}).get("break_state"),
                              setup=(pa or {}).get("setup"),
                              vwap_state=(pa or {}).get("vwap_state"),
                              value_state=(pa or {}).get("value_state"),
                              volume_state=(pa or {}).get("volume_state"),
                              rejection=a.get("primary_rejection_reason")))

        if final in (BUY_CE, BUY_PE) and open_pos is None:
            p = POS.open_position(series, m, symbol, d, a["side"], strike, qty, a["quality"], CFG13A)
            if p is not None:
                p.price_action = (pa or {}).get("confirmation")
                open_pos = p

    if open_pos is not None:
        last = max(series)
        open_pos.mark(series, last)
        open_pos.close(series, last, "SESSION_END")
        if open_pos.realised_pnl is not None:
            risk.record_close(open_pos.realised_pnl)
        positions.append(open_pos.to_dict())

    for p in positions:
        p["market"] = symbol
    return dict(positions=positions, blocked=blocked, decisions=decisions)


# ---------------------------------------------------------------- leakage audit (spec 13)
AUDIT_FIELDS = ("confirmation", "structure", "break_state", "break_level", "break_minute",
                "setup", "vwap_state", "vwap_distance_pct", "value_state", "volume_state",
                "volume_ratio", "follow_through", "higher_high", "higher_low", "lower_high",
                "lower_low", "agreeing_factors", "last_completed_bar")


def leakage_audit(conn, symbol: str, d: date, cfg=DEFAULT, sample: int = 40) -> dict:
    """Delete every bar after the signal minute and recompute. Answers must be identical.

    Also asserts the newest bar 13B used is stamped BEFORE the signal minute -- the one-minute
    error that would otherwise be invisible."""
    snaps = loader.load_snapshots(conn, symbol, d, start="09:00")
    if not snaps:
        return dict(symbol=symbol, checked=0, mismatches=[], passed=True, note="no data")
    series, cmap = prepare(snaps, loader.load_candles(conn, symbol, d, start="09:00"))
    levels_by_min = RP13A.levels_for(conn, symbol, d)
    base = [b for b in RP13A.base_decisions(symbol, d, series, cmap, levels_by_min)
            if b["decision"] in (BUY_CE, BUY_PE) and b["atm"]][:sample]

    mismatches, checked, future_bar_used = [], 0, 0
    cur = None
    for b in base:
        m, side = b["minute"], b["decision"][-2:]
        cur = levels_by_min.get(m, cur)
        full = D.evaluate(cmap, m, side, cur, cfg)
        trunc = D.evaluate({k: v for k, v in cmap.items() if k < m}, m, side, cur, cfg)
        checked += 1
        if full.get("last_completed_bar") and full["last_completed_bar"] >= m:
            future_bar_used += 1
            mismatches.append(dict(minute=m, field="last_completed_bar",
                                   full=full["last_completed_bar"],
                                   problem="a bar stamped at or after the signal minute was used"))
        for f in AUDIT_FIELDS:
            if full.get(f) != trunc.get(f):
                mismatches.append(dict(minute=m, field=f, full=full.get(f), truncated=trunc.get(f)))
    return dict(symbol=symbol, session_date=str(d), checked=checked,
                fields_compared=len(AUDIT_FIELDS), mismatches=mismatches,
                future_bar_used=future_bar_used, passed=not mismatches, version=VERSION)
