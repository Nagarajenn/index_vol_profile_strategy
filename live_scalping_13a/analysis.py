"""Aggregate a 13A replay and compare it against the unfiltered 12D baseline (spec 24).

Every grouped figure carries its N. A period with too few trades is reported as
INSUFFICIENT SAMPLE and its averages are shown but explicitly not interpreted.
"""

import statistics as st
from collections import Counter


def _num(xs):
    return [x for x in xs if isinstance(x, (int, float))]


def drawdown(pnls: list) -> float:
    """Maximum peak-to-trough of the cumulative realised curve."""
    peak, worst, cum = 0.0, 0.0, 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        worst = min(worst, cum - peak)
    return round(worst, 2)


def max_consecutive_losses(pnls: list) -> int:
    run, worst = 0, 0
    for p in pnls:
        run = run + 1 if p <= 0 else 0
        worst = max(worst, run)
    return worst


def summarise(positions: list[dict], label: str, min_sample: int = 20) -> dict:
    pnl = _num([p.get("realised_pnl") for p in positions])
    per_unit = _num([p.get("realised_pnl_per_unit") for p in positions])
    holds = _num([p.get("hold_minutes") for p in positions])
    return dict(
        label=label, trades=len(positions), priced=len(pnl),
        sufficient=len(positions) >= min_sample,
        note=None if len(positions) >= min_sample else "INSUFFICIENT SAMPLE",
        wins=sum(1 for x in pnl if x > 0), losses=sum(1 for x in pnl if x <= 0),
        win_rate=round(sum(1 for x in pnl if x > 0) / len(pnl) * 100, 1) if pnl else None,
        mean_pnl=round(st.fmean(pnl), 2) if pnl else None,
        median_pnl=round(st.median(pnl), 2) if pnl else None,
        total_pnl=round(sum(pnl), 2) if pnl else None,
        mean_pnl_per_unit=round(st.fmean(per_unit), 3) if per_unit else None,
        max_drawdown=drawdown(pnl) if pnl else None,
        max_consecutive_losses=max_consecutive_losses(pnl) if pnl else None,
        mean_hold_minutes=round(st.fmean(holds), 1) if holds else None,
        by_side=dict(Counter(p["side"] for p in positions)),
        by_quality=dict(Counter(p.get("quality") for p in positions)),
        by_exit=dict(Counter(p.get("exit_reason") for p in positions)),
    )


def baseline_from_12d(conn, days: list, config_hash: str | None = None) -> list[dict]:
    """The unfiltered 12D positions for the same sessions, for a like-for-like comparison."""
    if not days:
        return []
    q = """select market, side, hold_minutes, exit_reason, final_pnl, final_pnl_per_unit
           from sl12d_signals where session_date = any(%s)"""
    args = [days]
    if config_hash:
        q += " and config_hash = %s"
        args.append(config_hash)
    rows = conn.execute(q, args).fetchall()
    return [dict(market=r[0], side=r[1], hold_minutes=r[2], exit_reason=r[3],
                 realised_pnl=r[4], realised_pnl_per_unit=r[5], quality=None) for r in rows]


def compare(period_name: str, thirteen_a: list[dict], twelve_d: list[dict],
            rejections: dict, min_sample: int = 20) -> dict:
    a = summarise(thirteen_a, f"13A {period_name}", min_sample)
    b = summarise(twelve_d, f"12D {period_name}", min_sample)
    removed = sum(rejections.get(k, 0) for k in
                  ("REGIME_RANGE", "REGIME_REVERSING", "REGIME_AGAINST", "REGIME_UNKNOWN"))
    return dict(
        period=period_name, thirteen_a=a, twelve_d=b,
        trades_removed_pct=round((1 - a["trades"] / b["trades"]) * 100, 1) if b["trades"] else None,
        rejections=dict(sorted(rejections.items(), key=lambda x: -x[1])),
        removed_by_regime=removed,
        removed_by_timing=rejections.get("TIMING_EXTENDED", 0),
        removed_by_option=rejections.get("OPTION_NOT_CONFIRMED", 0),
        removed_by_underlying=rejections.get("UNDERLYING_NOT_CONFIRMED", 0),
        removed_by_spread=rejections.get("SPREAD_TOO_WIDE", 0),
        removed_by_economics=rejections.get("ECONOMICS_INSUFFICIENT", 0),
        removed_by_quality=rejections.get("QUALITY_TOO_LOW", 0),
        removed_by_risk_lock=rejections.get("RISK_LOCKED", 0),
    )


def daily_review(decisions: list[dict], positions: list[dict], rejections: dict) -> dict:
    """Spec 31: the end-of-session review."""
    pnl = _num([p.get("realised_pnl") for p in positions])
    dec = Counter(d["decision"] for d in decisions)
    return dict(
        total_decisions=len(decisions), buy_ce=dec.get("BUY_CE", 0), buy_pe=dec.get("BUY_PE", 0),
        wait=dec.get("WAIT", 0), trades=len(positions),
        wins=sum(1 for x in pnl if x > 0), losses=sum(1 for x in pnl if x <= 0),
        realised_pnl=round(sum(pnl), 2) if pnl else 0.0,
        max_drawdown=drawdown(pnl) if pnl else 0.0,
        max_consecutive_losses=max_consecutive_losses(pnl) if pnl else 0,
        rejected_range=rejections.get("REGIME_RANGE", 0),
        rejected_reversing=rejections.get("REGIME_REVERSING", 0),
        rejected_extended=rejections.get("TIMING_EXTENDED", 0),
        rejected_underlying=rejections.get("UNDERLYING_NOT_CONFIRMED", 0),
        rejected_option=rejections.get("OPTION_NOT_CONFIRMED", 0),
        rejected_spread=rejections.get("SPREAD_TOO_WIDE", 0),
        rejected_economics=rejections.get("ECONOMICS_INSUFFICIENT", 0),
        rejected_quality=rejections.get("QUALITY_TOO_LOW", 0),
        rejected_risk_lock=rejections.get("RISK_LOCKED", 0),
        rejected_no_base_signal=rejections.get("NO_BASE_SIGNAL", 0),
        rejected_position_open=rejections.get("POSITION_OPEN", 0),
    )
