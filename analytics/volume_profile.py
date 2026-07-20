import math
from collections import defaultdict
from dataclasses import dataclass

import pandas as pd


@dataclass
class VolumeProfileResult:
    poc: float
    vah: float
    val: float
    total_volume: float
    value_area_volume: float
    bins: dict  # bin_low_price -> volume, for charting the histogram


def _bin_index(price: float, bin_size: float) -> int:
    return math.floor(price / bin_size)


def _distribute_candle(volumes: dict, o: float, h: float, l: float, c: float, v: float, bin_size: float) -> None:
    if v <= 0:
        return

    if h <= l:
        volumes[_bin_index(h, bin_size)] += v
        return

    lo_idx = _bin_index(l, bin_size)
    hi_idx = _bin_index(h, bin_size)
    idxs = list(range(lo_idx, hi_idx + 1))

    price_range = h - l
    half_width = price_range / 2

    uniform_weights = []
    tri_raw = []
    for idx in idxs:
        b_lo = idx * bin_size
        b_hi = b_lo + bin_size
        overlap = max(0.0, min(h, b_hi) - max(l, b_lo))
        uniform_weights.append(overlap / price_range)

        bin_mid = min(max((b_lo + b_hi) / 2, l), h)
        tri_raw.append(max(0.0, 1 - abs(bin_mid - c) / half_width))

    tri_sum = sum(tri_raw)
    tri_weights = [w / tri_sum for w in tri_raw] if tri_sum > 0 else uniform_weights

    for idx, wu, wt in zip(idxs, uniform_weights, tri_weights):
        final_weight = 0.5 * wu + 0.5 * wt
        volumes[idx] += v * final_weight


def _value_area(volumes: dict, bin_size: float, value_area_pct: float):
    total = sum(volumes.values())
    if total <= 0:
        return None

    sorted_idxs = sorted(volumes)
    poc_idx = max(volumes, key=volumes.get)
    poc_pos = sorted_idxs.index(poc_idx)

    lo_pos = hi_pos = poc_pos
    cum = volumes[poc_idx]
    target = total * value_area_pct

    while cum < target and (lo_pos > 0 or hi_pos < len(sorted_idxs) - 1):
        vol_below = volumes[sorted_idxs[lo_pos - 1]] if lo_pos > 0 else -1
        vol_above = volumes[sorted_idxs[hi_pos + 1]] if hi_pos < len(sorted_idxs) - 1 else -1
        if vol_above >= vol_below:
            hi_pos += 1
            cum += volumes[sorted_idxs[hi_pos]]
        else:
            lo_pos -= 1
            cum += volumes[sorted_idxs[lo_pos]]

    val_idx = sorted_idxs[lo_pos]
    vah_idx = sorted_idxs[hi_pos]

    poc_price = poc_idx * bin_size + bin_size / 2
    val_price = val_idx * bin_size
    vah_price = vah_idx * bin_size + bin_size

    return poc_price, val_price, vah_price, cum, total


def compute_volume_profile(candles: pd.DataFrame, bin_size: float, value_area_pct: float = 0.70) -> VolumeProfileResult | None:
    """Approximate volume-at-price from OHLCV candles (not tick data).

    Each candle's volume is spread across the price bins it spans using a
    50/50 blend of a uniform distribution over [low, high] and a triangular
    kernel centered on the candle's close. POC = highest-volume bin
    (represented by its midpoint). Value Area expands outward from POC,
    greedily adding whichever neighboring bin has more volume, until the
    accumulated volume reaches `value_area_pct` of the session total.

    Returns None if `candles` is empty or has zero total volume.
    """
    if candles.empty:
        return None

    volumes: dict[int, float] = defaultdict(float)
    for row in candles.itertuples(index=False):
        _distribute_candle(volumes, row.open, row.high, row.low, row.close, row.volume, bin_size)

    result = _value_area(dict(volumes), bin_size, value_area_pct)
    if result is None:
        return None

    poc_price, val_price, vah_price, va_volume, total_volume = result
    bins_by_price = {idx * bin_size: vol for idx, vol in volumes.items()}

    return VolumeProfileResult(
        poc=poc_price,
        vah=vah_price,
        val=val_price,
        total_volume=total_volume,
        value_area_volume=va_volume,
        bins=bins_by_price,
    )
