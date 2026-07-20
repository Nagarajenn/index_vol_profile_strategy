from dataclasses import dataclass

import numpy as np
import pandas as pd

from analytics.swings import SwingPoint
from config.instruments import SR_CLUSTER_TOLERANCE_PCT_DEFAULT, TRENDLINE_MIN_R2

MIN_TOUCH_COUNT = 2


@dataclass
class Trendline:
    points: list  # [(t0, p0), (t1, p1)] — fit line, extended to the last candle
    direction: str  # "up" or "down"
    r2: float | None
    touch_count: int


def _line_fit(xs: np.ndarray, ys: np.ndarray) -> tuple[float, float, float]:
    slope, intercept = np.polyfit(xs, ys, 1)
    pred = slope * xs + intercept
    ss_res = float(np.sum((ys - pred) ** 2))
    ss_tot = float(np.sum((ys - ys.mean()) ** 2))
    r2 = 1.0 if ss_tot == 0 else 1 - ss_res / ss_tot
    return float(slope), float(intercept), r2


def _no_violation(slope, intercept, candles, x_start, x_end, direction, buffer_pct=0.001) -> bool:
    lo, hi = int(round(x_start)), int(round(x_end))
    if hi <= lo:
        return True
    sub = candles.iloc[lo : hi + 1]
    idxs = np.arange(lo, hi + 1)
    line_vals = slope * idxs + intercept
    closes = sub["close"].to_numpy()
    buffer = buffer_pct * closes.mean()
    if direction == "down":
        return not bool(np.any(closes > line_vals + buffer))
    return not bool(np.any(closes < line_vals - buffer))


def _touch_count(slope, intercept, idx_map: dict, all_points: list[SwingPoint], tolerance_pct: float) -> int:
    count = 0
    for p in all_points:
        idx = idx_map.get(p.timestamp)
        if idx is None:
            continue
        line_val = slope * idx + intercept
        if line_val != 0 and abs(p.price - line_val) <= tolerance_pct * abs(line_val):
            count += 1
    return count


def _fit_trendline(
    fit_points: list[SwingPoint],
    all_points_same_kind: list[SwingPoint],
    candles: pd.DataFrame,
    idx_map: dict,
    direction: str,
    min_r2: float,
    tolerance_pct: float,
) -> Trendline | None:
    if len(fit_points) < 2:
        return None

    xs = np.array([idx_map[p.timestamp] for p in fit_points], dtype=float)
    ys = np.array([p.price for p in fit_points], dtype=float)
    slope, intercept, r2 = _line_fit(xs, ys)

    if len(fit_points) >= 3 and r2 < min_r2:
        return _fit_trendline(fit_points[-2:], all_points_same_kind, candles, idx_map, direction, min_r2, tolerance_pct)

    if not _no_violation(slope, intercept, candles, xs.min(), xs.max(), direction):
        if len(fit_points) > 2:
            return _fit_trendline(fit_points[-2:], all_points_same_kind, candles, idx_map, direction, min_r2, tolerance_pct)
        return None

    touches = _touch_count(slope, intercept, idx_map, all_points_same_kind, tolerance_pct)
    if touches < MIN_TOUCH_COUNT:
        return None

    last_idx = len(candles) - 1
    t_start = candles["timestamp"].iloc[int(xs.min())]
    p_start = slope * xs.min() + intercept
    t_end = candles["timestamp"].iloc[last_idx]
    p_end = slope * last_idx + intercept

    return Trendline(points=[(t_start, p_start), (t_end, p_end)], direction=direction, r2=r2, touch_count=touches)


def fit_trendlines(
    swings: list[SwingPoint],
    candles: pd.DataFrame,
    min_r2: float = TRENDLINE_MIN_R2,
    tolerance_pct: float = SR_CLUSTER_TOLERANCE_PCT_DEFAULT,
) -> list[Trendline]:
    """Fit an up-trendline through the last 3 confirmed swing lows and a
    down-trendline through the last 3 confirmed swing highs (falling back to
    the last 2 points if the 3-point fit's R^2 is too low or the line is
    already violated by an intervening close), extended to the latest candle.
    """
    idx_map = {ts: i for i, ts in enumerate(candles["timestamp"])}

    highs = [s for s in swings if s.kind == "high" and s.confirmed]
    lows = [s for s in swings if s.kind == "low" and s.confirmed]

    result = []
    down_tl = _fit_trendline(highs[-3:], highs, candles, idx_map, "down", min_r2, tolerance_pct)
    if down_tl:
        result.append(down_tl)
    up_tl = _fit_trendline(lows[-3:], lows, candles, idx_map, "up", min_r2, tolerance_pct)
    if up_tl:
        result.append(up_tl)
    return result
