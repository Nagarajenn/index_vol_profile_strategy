"""Buy/sell proxy derived signals: Dominance, Cumulative Pressure, Volume
Momentum -- all pure functions of the per-candle buy/sell proxy columns
attached by proxy.py ("mfm", "buy_volume", "sell_volume"). All three answer
"which side has volume, and for how long" -- distinct from rvol.py, which
answers "how much volume, relative to a baseline."
"""

import pandas as pd

from .models import BuySellDominance, CumulativePressure, DominantSide, MomentumLabel, VolumeMomentum

DEFAULT_DOMINANCE_WINDOW = 8
DOMINANCE_BUY_THRESHOLD = 0.55
DOMINANCE_SELL_THRESHOLD = 0.45

DEFAULT_MOMENTUM_SPAN = 8
MOMENTUM_THRESHOLD = 0.15
MOMENTUM_STRONG_THRESHOLD = 0.35
MOMENTUM_STRONG_STREAK_MIN = 5


def _dominant_side(ratio: float) -> DominantSide:
    if ratio >= DOMINANCE_BUY_THRESHOLD:
        return "buy"
    if ratio <= DOMINANCE_SELL_THRESHOLD:
        return "sell"
    return "balanced"


def _trailing_streak(values: pd.Series, side: DominantSide) -> int:
    """Counts trailing values (walking backward from the most recent) whose
    sign matches `side` ("buy" -> positive, "sell" -> negative), stopping
    at the first mismatch or a zero/balanced value. Used for both the raw
    per-candle mfm streak (dominance) and the smoothed EMA-sign streak
    (momentum) -- same counting technique, different input series."""
    if side == "balanced":
        return 0
    count = 0
    for value in values.to_numpy()[::-1]:
        if side == "buy" and value > 0:
            count += 1
        elif side == "sell" and value < 0:
            count += 1
        else:
            break
    return count


def compute_buy_sell_dominance(enriched: pd.DataFrame, window_minutes: int = DEFAULT_DOMINANCE_WINDOW) -> BuySellDominance:
    """`enriched` must already have mfm/buy_volume/sell_volume columns
    (proxy.attach_buy_sell_columns). Looks at the trailing `window_minutes`
    candles (fewer near session open)."""
    if enriched.empty:
        return BuySellDominance(window_minutes=0, buy_volume=0.0, sell_volume=0.0, dominance_ratio=0.5, dominant_side="balanced", consecutive_dominant_minutes=0)

    window = enriched.tail(window_minutes)
    buy = float(window["buy_volume"].sum())
    sell = float(window["sell_volume"].sum())
    ratio = buy / (buy + sell) if (buy + sell) > 0 else 0.5
    side = _dominant_side(ratio)
    streak = _trailing_streak(enriched["mfm"], side)

    return BuySellDominance(
        window_minutes=len(window), buy_volume=buy, sell_volume=sell, dominance_ratio=ratio, dominant_side=side, consecutive_dominant_minutes=streak
    )


def compute_cumulative_pressure(enriched: pd.DataFrame) -> CumulativePressure:
    """Running session-total buy vs. sell proxy volume -- money-flow-volume
    style, not a rolling window like dominance."""
    if enriched.empty:
        return CumulativePressure(cum_buy_volume=0.0, cum_sell_volume=0.0, net_pressure=0.0, pressure_ratio=0.5)

    cum_buy = float(enriched["buy_volume"].sum())
    cum_sell = float(enriched["sell_volume"].sum())
    ratio = cum_buy / (cum_buy + cum_sell) if (cum_buy + cum_sell) > 0 else 0.5

    return CumulativePressure(cum_buy_volume=cum_buy, cum_sell_volume=cum_sell, net_pressure=cum_buy - cum_sell, pressure_ratio=ratio)


def _momentum_label(normalized: float, streak: int) -> MomentumLabel:
    if normalized >= MOMENTUM_STRONG_THRESHOLD and streak >= MOMENTUM_STRONG_STREAK_MIN:
        return "Strong Buy Momentum"
    if normalized >= MOMENTUM_THRESHOLD:
        return "Buy Momentum"
    if normalized <= -MOMENTUM_STRONG_THRESHOLD and streak >= MOMENTUM_STRONG_STREAK_MIN:
        return "Strong Sell Momentum"
    if normalized <= -MOMENTUM_THRESHOLD:
        return "Sell Momentum"
    return "Neutral"


def compute_volume_momentum(enriched: pd.DataFrame, span: int = DEFAULT_MOMENTUM_SPAN) -> VolumeMomentum:
    """Distinct from rvol.py's Acceleration: acceleration measures whether
    TOTAL volume is speeding up; this measures which SIDE has been
    persistently dominant and how strongly, matching the "buy volume has
    dominated the last 8 minutes" style read. `ema` = EMA of the per-candle
    signed money-flow-volume (volume*mfm); `streak_minutes` counts how long
    the EMA itself has held the same sign (not the raw per-candle mfm sign
    -- that's dominance's streak, a deliberately different, noisier basis)."""
    if enriched.empty:
        return VolumeMomentum(ema_signed_volume=0.0, normalized_score=0.0, streak_minutes=0, label="Neutral")

    signed_volume = enriched["volume"] * enriched["mfm"]
    ema = signed_volume.ewm(span=span, adjust=False).mean()
    rolling_avg_volume = enriched["volume"].rolling(span, min_periods=1).mean()

    ema_last = float(ema.iloc[-1])
    rolling_last = float(rolling_avg_volume.iloc[-1])
    normalized = max(-1.0, min(1.0, ema_last / rolling_last)) if rolling_last > 0 else 0.0

    side: DominantSide = "buy" if normalized > 0 else "sell" if normalized < 0 else "balanced"
    streak = _trailing_streak(ema, side)

    return VolumeMomentum(ema_signed_volume=ema_last, normalized_score=normalized, streak_minutes=streak, label=_momentum_label(normalized, streak))
