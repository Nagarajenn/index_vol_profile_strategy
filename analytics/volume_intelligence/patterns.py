"""Volume-spike-triggered price-shape patterns: Absorption Detection,
Exhaustion Detection. Both depend on rvol.py's spike output -- neither is
meaningful without an actual volume spike to anchor the pattern.
"""

import pandas as pd

from .models import AbsorptionSignal, ExhaustionSignal, VolumeSpike

ABSORPTION_RANGE_WINDOW = 10
ABSORPTION_RANGE_RATIO_MAX = 0.6

EXHAUSTION_WINDOW = 10
EXHAUSTION_CONSISTENCY_MIN = 0.6
EXHAUSTION_WICK_RATIO_MIN = 0.4


def compute_absorption(enriched: pd.DataFrame, spike: VolumeSpike) -> AbsorptionSignal:
    """High volume (a spike) with a small price range relative to recent
    bars -- a documented "someone is absorbing supply/demand without
    letting price move" pattern hint, not a definitive claim (same spirit
    as this codebase's Profile Shape/Opening Type heuristics)."""
    if len(enriched) < ABSORPTION_RANGE_WINDOW + 1:
        return AbsorptionSignal(detected=False, range_ratio=None, volume_multiple=spike.multiple, side_hint="undetermined")

    prior_window = enriched.iloc[-(ABSORPTION_RANGE_WINDOW + 1) : -1]
    avg_range = float((prior_window["high"] - prior_window["low"]).mean())
    current = enriched.iloc[-1]
    current_range = float(current["high"] - current["low"])

    if avg_range <= 0:
        return AbsorptionSignal(detected=False, range_ratio=None, volume_multiple=spike.multiple, side_hint="undetermined")

    range_ratio = current_range / avg_range
    detected = bool(spike.is_spike and range_ratio <= ABSORPTION_RANGE_RATIO_MAX)
    side_hint = ("buy_absorption" if current["mfm"] >= 0 else "sell_absorption") if detected else "undetermined"

    return AbsorptionSignal(detected=detected, range_ratio=range_ratio, volume_multiple=spike.multiple, side_hint=side_hint)


def compute_exhaustion(enriched: pd.DataFrame, spike: VolumeSpike) -> ExhaustionSignal:
    """A volume climax (the trailing window's own volume peak) after an
    extended, consistent directional move, with a rejection wick on the
    move's own side -- a documented "blow-off" pattern hint often
    preceding a reversal, not a guarantee. Note: unlike absorption, this
    does not require spike.is_spike -- "is_climax" (this bar being the
    window's own volume peak) is the operative check here, which a
    genuine blow-off satisfies even on a session with generally modest
    volume."""
    if len(enriched) < EXHAUSTION_WINDOW:
        return ExhaustionSignal(detected=False, direction=None, move_over_window=None, volume_multiple=spike.multiple, wick_ratio=None)

    window = enriched.tail(EXHAUSTION_WINDOW)
    closes = window["close"].to_numpy()
    net_move = float(closes[-1] - closes[0])

    diffs = pd.Series(closes).diff().dropna()
    if net_move == 0 or diffs.empty:
        consistency = 0.0
    else:
        matching = int((diffs * (1 if net_move > 0 else -1) > 0).sum())
        consistency = matching / len(diffs)

    volumes = window["volume"].to_numpy()
    is_climax = bool(volumes[-1] == volumes.max())

    current = enriched.iloc[-1]
    rng = float(current["high"] - current["low"])
    if rng <= 0:
        wick_ratio = 0.0
    elif net_move > 0:
        wick_ratio = float((current["high"] - current["close"]) / rng)
    else:
        wick_ratio = float((current["close"] - current["low"]) / rng)

    extended_move = net_move != 0 and consistency >= EXHAUSTION_CONSISTENCY_MIN
    detected = bool(extended_move and is_climax and wick_ratio >= EXHAUSTION_WICK_RATIO_MIN)
    direction = ("up" if net_move > 0 else "down") if net_move != 0 else None

    return ExhaustionSignal(detected=detected, direction=direction, move_over_window=net_move, volume_multiple=spike.multiple, wick_ratio=wick_ratio)
