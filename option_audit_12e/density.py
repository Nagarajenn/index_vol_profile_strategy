"""Signal density, flips and re-entry: is one market move being counted as many opportunities?

Measurement only. No cooldown is proposed and none is applied (spec 20).
"""

import statistics as st
from collections import Counter


def _idx(minute: str) -> int:
    h, m = (int(x) for x in minute.split(":"))
    return h * 60 + m


def density(rows: list[dict]) -> dict:
    """Per symbol-day: how often signals arrive and how far apart they are."""
    out = {}
    by_day = {}
    for r in rows:
        by_day.setdefault((r["market"], r["session_date"]), []).append(r)
    gaps_all, per_hour_all = [], []
    for key, rs in by_day.items():
        rs = sorted(rs, key=lambda x: x["signal_minute"])
        mins = [_idx(r["signal_minute"]) for r in rs]
        gaps = [b - a for a, b in zip(mins, mins[1:])]
        span_hours = ((mins[-1] - mins[0]) / 60) or 1
        gaps_all.extend(gaps)
        per_hour_all.append(len(rs) / span_hours)
        out[f"{key[0]} {key[1]}"] = dict(
            signals=len(rs), first=rs[0]["signal_minute"], last=rs[-1]["signal_minute"],
            median_gap_minutes=st.median(gaps) if gaps else None,
            signals_per_hour=round(len(rs) / span_hours, 2),
            gaps_under_3min=sum(1 for g in gaps if g < 3),
        )
    return dict(per_symbol_day=out,
                overall=dict(median_gap_minutes=st.median(gaps_all) if gaps_all else None,
                             mean_gap_minutes=round(st.fmean(gaps_all), 2) if gaps_all else None,
                             mean_signals_per_hour=round(st.fmean(per_hour_all), 2) if per_hour_all else None,
                             gaps_under_3min=sum(1 for g in gaps_all if g < 3),
                             total_gaps=len(gaps_all)))


def runs(rows: list[dict]) -> dict:
    """Consecutive same-direction signals -- how often one trend produced several entries."""
    by_day = {}
    for r in rows:
        by_day.setdefault((r["market"], r["session_date"]), []).append(r)
    lengths, flips, total = [], 0, 0
    for rs in by_day.values():
        rs = sorted(rs, key=lambda x: x["signal_minute"])
        run = 1
        for a, b in zip(rs, rs[1:]):
            total += 1
            if a["direction"] == b["direction"]:
                run += 1
            else:
                flips += 1
                lengths.append(run)
                run = 1
        lengths.append(run)
    c = Counter(lengths)
    return dict(same_direction_runs=len(lengths),
                mean_run_length=round(st.fmean(lengths), 2) if lengths else None,
                max_run_length=max(lengths) if lengths else None,
                run_length_histogram={str(k): v for k, v in sorted(c.items())},
                direction_changes=flips, transitions=total,
                flip_rate_pct=round(flips / total * 100, 1) if total else None)


def flips(rows: list[dict]) -> dict:
    """Spec 19: when 12C flips side, did the market actually reverse?

    A flip is 'market-confirmed' when the underlying moved against the OLD side over the gap --
    i.e. the flip followed the market. Otherwise the engine changed its mind without the
    underlying doing so."""
    by_day = {}
    for r in rows:
        by_day.setdefault((r["market"], r["session_date"]), []).append(r)
    confirmed, unconfirmed, unknown, gaps, pnls = 0, 0, 0, [], []
    detail = []
    for rs in by_day.values():
        rs = sorted(rs, key=lambda x: x["signal_minute"])
        for a, b in zip(rs, rs[1:]):
            if a["direction"] == b["direction"]:
                continue
            ua, ub = a.get("underlying_at_signal"), b.get("underlying_at_signal")
            gap = _idx(b["signal_minute"]) - _idx(a["signal_minute"])
            gaps.append(gap)
            if a.get("final_pnl_per_unit") is not None:
                pnls.append(a["final_pnl_per_unit"])
            if ua is None or ub is None:
                unknown += 1
                continue
            move = (ub - ua) / ua * 100
            old_wanted_down = a["side"] == "PE"
            # the market moved against the old side => the flip followed the market
            against_old = (move > 0) if old_wanted_down else (move < 0)
            if against_old:
                confirmed += 1
            else:
                unconfirmed += 1
            detail.append(dict(at=b["signal_minute"], market=b["market"], from_=a["direction"],
                               to=b["direction"], gap_minutes=gap, underlying_move_pct=round(move, 3),
                               market_confirmed=against_old, closed_pnl=a.get("final_pnl_per_unit")))
    n = confirmed + unconfirmed
    return dict(flips=n + unknown, market_confirmed=confirmed, not_confirmed=unconfirmed,
                unknown=unknown,
                confirmed_pct=round(confirmed / n * 100, 1) if n else None,
                median_gap_minutes=st.median(gaps) if gaps else None,
                mean_closed_pnl_per_unit=round(st.fmean(pnls), 2) if pnls else None,
                sample=detail[:25])
