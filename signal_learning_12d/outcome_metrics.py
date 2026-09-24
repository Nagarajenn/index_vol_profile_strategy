"""MFE / MAE and horizon outcomes, measured strictly AFTER the entry minute.

Direction of the discipline: entry is the ASK (what a buyer pays), every later mark is the BID
(what a seller receives). Never LTP, never the midpoint -- an excursion measured on a price you
could not have transacted at is not an excursion, it is a number.

This is the only module in 12D permitted to look at minutes after the signal, and it may do so
only to SCORE an outcome, never to influence a decision that was already taken.
"""

from option_risk_12b.option_snapshot import shift
from option_risk_12b.option_state import leg
from signal_learning_12d.config import HORIZONS


def quote(series: dict, minute: str, side: str, strike: float | None) -> dict:
    if strike is None or minute not in series:
        return dict(status="UNAVAILABLE", bid=None, ask=None, ltp=None)
    q = leg(series, minute, side, strike) or {}
    ok = q.get("bid") is not None and q.get("ask") is not None
    return dict(status="OK" if ok else "UNAVAILABLE", bid=q.get("bid"), ask=q.get("ask"), ltp=q.get("ltp"))


def forward_marks(series: dict, entry_minute: str, side: str, strike: float | None,
                  last_minute: str | None = None) -> list[tuple[str, float]]:
    """Every (minute, bid) strictly after the entry minute, in order. Missing minutes are simply
    absent -- nothing is interpolated or carried forward."""
    out = []
    for m in sorted(x for x in series if x > entry_minute and (last_minute is None or x <= last_minute)):
        q = quote(series, m, side, strike)
        if q["status"] == "OK":
            out.append((m, q["bid"]))
    return out


def _excursion(marks: list, entry_price: float) -> dict:
    if not marks or entry_price is None:
        return dict(mfe_per_unit=None, mae_per_unit=None, time_to_mfe=None, time_to_mae=None,
                    mfe_pct=None, mae_pct=None)
    diffs = [(m, round(b - entry_price, 2)) for m, b in marks]
    best_m, best = max(diffs, key=lambda x: x[1])
    worst_m, worst = min(diffs, key=lambda x: x[1])
    # MFE/MAE are excursions FROM the entry, so a position that only ever lost has MFE <= 0.
    return dict(mfe_per_unit=best, mae_per_unit=worst,
                time_to_mfe=_minutes_between(marks[0][0], best_m) + 1,
                time_to_mae=_minutes_between(marks[0][0], worst_m) + 1,
                mfe_pct=round(best / entry_price * 100, 3), mae_pct=round(worst / entry_price * 100, 3))


def _minutes_between(a: str, b: str) -> int:
    def idx(x):
        h, m = (int(v) for v in x.split(":"))
        return h * 60 + m
    return idx(b) - idx(a)


def horizon_metrics(series: dict, entry_minute: str, entry_price: float | None, side: str,
                    strike: float | None, horizons=HORIZONS) -> dict:
    """Outcome, MFE and MAE at each fixed horizon after entry, plus the full-window excursion.

    A horizon that runs past the end of available data yields None rather than being clipped to
    the last known price -- a truncated horizon is missing information, not a flat outcome."""
    out = {}
    all_marks = forward_marks(series, entry_minute, side, strike)
    for h in horizons:
        end = shift(entry_minute, h)
        marks = [(m, b) for m, b in all_marks if m <= end]
        reached = any(m == end for m, _ in all_marks)
        ex = _excursion(marks, entry_price)
        out[f"mfe_{h}m"] = ex["mfe_per_unit"]
        out[f"mae_{h}m"] = ex["mae_per_unit"]
        if reached and entry_price is not None:
            bid_at = next(b for m, b in all_marks if m == end)
            out[f"outcome_{h}m"] = round(bid_at - entry_price, 2)
            out[f"outcome_{h}m_pct"] = round((bid_at - entry_price) / entry_price * 100, 3)
        else:
            out[f"outcome_{h}m"] = None
            out[f"outcome_{h}m_pct"] = None
        out[f"horizon_{h}m_complete"] = reached
    full = _excursion(all_marks, entry_price)
    out.update(mfe_per_unit=full["mfe_per_unit"], mae_per_unit=full["mae_per_unit"],
               mfe_pct=full["mfe_pct"], mae_pct=full["mae_pct"],
               time_to_mfe=full["time_to_mfe"], time_to_mae=full["time_to_mae"],
               marks_observed=len(all_marks))
    return out


def realised(entry_price: float | None, exit_bid: float | None, quantity: int | None) -> dict:
    if entry_price is None or exit_bid is None:
        return dict(final_pnl_per_unit=None, final_pnl=None, final_pnl_pct=None)
    per_unit = round(exit_bid - entry_price, 2)
    return dict(final_pnl_per_unit=per_unit,
                final_pnl=round(per_unit * quantity, 2) if quantity else None,
                final_pnl_pct=round(per_unit / entry_price * 100, 3))
