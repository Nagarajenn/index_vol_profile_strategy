"""Advanced Volume Profile / auction-market-theory metrics, built on top of
the existing session-level `compute_volume_profile()` (analytics/volume_profile.py).

Every function here is a pure function of OHLCV candle DataFrames -- no
database, pipeline, or config-file dependency beyond the bin_size/thresholds
passed in explicitly. That's deliberate: this module is meant to be a
reusable service callable from both the ingestion pipeline and the dashboard
backend (mirroring how `analytics/` is already shared between the two via
the root pyproject.toml editable install).

Explicitly NOT wired into the strategy engine (analytics/confidence_score.py,
analytics/trend_classifier.py, decision/decision_card.py) -- these metrics
are additive/informational only, per the "keep the strategy engine
unchanged for now" instruction.

Several of these metrics (Profile Shape, Opening Type, Rotation Factor) are
inherently fuzzy/discretionary in classic Market Profile literature -- the
implementations below are reasonable, deterministic, clearly documented
heuristics, not a claim of matching any single canonical definition.
"""

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd

from analytics.volume_profile import VolumeProfileResult, compute_volume_profile

# ---- Tunable defaults (all overridable per-call, never read from config
# implicitly, so this module never silently depends on pipeline config) ----
DEFAULT_DEVELOPING_CHECKPOINT_MINUTES = 15
DEFAULT_INITIAL_BALANCE_MINUTES = 60
DEFAULT_OPENING_WINDOW_MINUTES = 30
DEFAULT_ROTATION_PERIOD_MINUTES = 30
DEFAULT_MAX_NODES = 5


@dataclass
class DevelopingPoint:
    """Session-so-far POC/VAH/VAL as of `timestamp` -- one point on the
    "developing" value area path, recomputed from only the candles up to
    that moment (not the full-session profile)."""

    timestamp: datetime
    poc: float
    vah: float
    val: float


@dataclass
class VolumeNode:
    """A High or Low Volume Node: a local peak/trough in the session's
    volume-by-price distribution."""

    price: float
    volume: float
    kind: Literal["hvn", "lvn"]


@dataclass
class ValueMigration:
    poc_shift: float
    poc_shift_pct: float
    direction: Literal["up", "down", "flat"]
    vah_shift: float
    val_shift: float
    intraday_poc_drift: float  # current developing POC vs. the session's first checkpoint


@dataclass
class LevelTest:
    level_name: str
    price: float
    outcome: Literal["accepted", "rejected", "untested"]
    touches: int


@dataclass
class ProfileShapeResult:
    shape: Literal["P", "b", "D", "B"]
    description: str


@dataclass
class InitialBalance:
    ib_high: float
    ib_low: float
    ib_range: float
    end_time: datetime
    is_complete: bool  # False while the session hasn't yet reached the IB window length


@dataclass
class OpeningType:
    type: Literal["Open-Drive", "Open-Test-Drive", "Open-Rejection-Reverse", "Open-Auction"]
    description: str


@dataclass
class RotationFactor:
    value: int  # count of directional sign-flips between successive periods
    periods: int
    label: Literal["Trending", "Rotational"]


@dataclass
class VolumePace:
    pace_pct: float
    today_cumulative: float
    average_cumulative: float
    label: Literal["Above Average", "Average", "Below Average"]


@dataclass
class VolumeProfileIntelligence:
    developing: list[DevelopingPoint] = field(default_factory=list)
    hvns: list[VolumeNode] = field(default_factory=list)
    lvns: list[VolumeNode] = field(default_factory=list)
    migration: ValueMigration | None = None
    level_tests: list[LevelTest] = field(default_factory=list)
    profile_shape: ProfileShapeResult | None = None
    initial_balance: InitialBalance | None = None
    opening_type: OpeningType | None = None
    rotation_factor: RotationFactor | None = None
    volume_pace: VolumePace | None = None


# ---------------------------------------------------------------------------
# 1+2. Developing POC / VAH / VAL
# ---------------------------------------------------------------------------
def compute_developing_levels(
    today_candles: pd.DataFrame,
    bin_size: float,
    value_area_pct: float = 0.70,
    checkpoint_minutes: int = DEFAULT_DEVELOPING_CHECKPOINT_MINUTES,
) -> list[DevelopingPoint]:
    """Recomputes the session's POC/VAH/VAL from only the candles available
    up to each checkpoint, giving a time series showing how the value area
    has developed/migrated through the session so far."""
    if today_candles.empty:
        return []

    start = today_candles["timestamp"].iloc[0]
    end = today_candles["timestamp"].iloc[-1]
    session_minutes = int((end - start).total_seconds() // 60) + 1

    points: list[DevelopingPoint] = []
    elapsed = checkpoint_minutes
    while elapsed <= session_minutes:
        cutoff = start + timedelta(minutes=elapsed)
        window = today_candles[today_candles["timestamp"] <= cutoff]
        vp = compute_volume_profile(window, bin_size, value_area_pct)
        if vp is not None:
            points.append(DevelopingPoint(timestamp=window["timestamp"].iloc[-1], poc=vp.poc, vah=vp.vah, val=vp.val))
        elapsed += checkpoint_minutes

    # Always include the final, full-session-so-far point even if it falls
    # between checkpoints, so "current developing POC" is never stale.
    final_vp = compute_volume_profile(today_candles, bin_size, value_area_pct)
    if final_vp is not None and (not points or points[-1].timestamp != end):
        points.append(DevelopingPoint(timestamp=end, poc=final_vp.poc, vah=final_vp.vah, val=final_vp.val))

    return points


# ---------------------------------------------------------------------------
# 3+4. High/Low Volume Nodes
# ---------------------------------------------------------------------------
def compute_volume_nodes(
    bins: dict[float, float], bin_size: float, max_nodes: int = DEFAULT_MAX_NODES
) -> tuple[list[VolumeNode], list[VolumeNode]]:
    """HVNs are local-maxima bins with volume well above the session median
    (price acted as a magnet/consolidation area); LVNs are local-minima bins
    well below the median (price likely to move through quickly -- "air").
    """
    if len(bins) < 3:
        return [], []

    sorted_prices = sorted(bins)
    volumes = [bins[p] for p in sorted_prices]
    median_vol = statistics.median(volumes)
    if median_vol <= 0:
        return [], []

    hvns: list[VolumeNode] = []
    lvns: list[VolumeNode] = []
    for i, price in enumerate(sorted_prices):
        v = volumes[i]
        left = volumes[i - 1] if i > 0 else None
        right = volumes[i + 1] if i < len(volumes) - 1 else None
        is_local_max = (left is None or v >= left) and (right is None or v >= right)
        is_local_min = (left is None or v <= left) and (right is None or v <= right)
        price_mid = price + bin_size / 2

        if is_local_max and v >= median_vol * 1.5:
            hvns.append(VolumeNode(price=price_mid, volume=v, kind="hvn"))
        elif is_local_min and v <= median_vol * 0.5:
            lvns.append(VolumeNode(price=price_mid, volume=v, kind="lvn"))

    hvns.sort(key=lambda n: -n.volume)
    lvns.sort(key=lambda n: n.volume)
    return hvns[:max_nodes], lvns[:max_nodes]


def _price_range_of(bins: dict[float, float], bin_size: float) -> tuple[float, float]:
    sorted_prices = sorted(bins)
    return sorted_prices[0], sorted_prices[-1] + bin_size


def _has_two_separated_clusters(hvns: list[VolumeNode], lo: float, hi: float) -> bool:
    """Bimodal check: are there 2+ HVN clusters far enough apart (>=25% of
    the session's range) to represent two distinct balance areas rather than
    one continuous distribution?"""
    if len(hvns) < 2:
        return False
    rng = hi - lo
    if rng <= 0:
        return False
    prices = sorted(n.price for n in hvns)
    max_gap = max(b - a for a, b in zip(prices, prices[1:]))
    return max_gap >= 0.25 * rng


# ---------------------------------------------------------------------------
# 7. Profile Shape (P / b / D / B)
# ---------------------------------------------------------------------------
def classify_profile_shape(bins: dict[float, float], poc: float, bin_size: float) -> ProfileShapeResult:
    """P: volume concentrated near the highs, thin base -- short-covering /
    fast markup. b: mirror, volume concentrated near the lows -- long
    liquidation / fast markdown. D: single balanced distribution centered
    near POC -- normal two-sided auction. B: two separated high-volume
    clusters -- the market balanced at two distinct price zones today."""
    if not bins:
        return ProfileShapeResult(shape="D", description="Insufficient data for shape classification.")

    lo, hi = _price_range_of(bins, bin_size)
    rng = hi - lo
    total = sum(bins.values())
    if rng <= 0 or total <= 0:
        return ProfileShapeResult(shape="D", description="Insufficient range/volume for shape classification.")

    hvns, _ = compute_volume_nodes(bins, bin_size)
    if _has_two_separated_clusters(hvns, lo, hi):
        return ProfileShapeResult(
            shape="B",
            description="Double distribution -- two separate balance areas, market accepted two distinct price zones today.",
        )

    poc_position = (poc - lo) / rng  # 0 = bottom of range, 1 = top
    midpoint = lo + rng / 2
    upper_volume = sum(v for p, v in bins.items() if p >= midpoint)
    upper_share = upper_volume / total

    if poc_position >= 0.66 and upper_share >= 0.60:
        return ProfileShapeResult(
            shape="P",
            description="P-shaped -- volume built up near the highs with a thin base; consistent with a short-covering rally or fast markup.",
        )
    if poc_position <= 0.34 and upper_share <= 0.40:
        return ProfileShapeResult(
            shape="b",
            description="b-shaped -- volume built up near the lows with a thin top; consistent with long liquidation or a fast markdown.",
        )
    return ProfileShapeResult(
        shape="D",
        description="Normal/balanced distribution -- a single well-defined POC near the middle of the range.",
    )


# ---------------------------------------------------------------------------
# 5. Value Migration
# ---------------------------------------------------------------------------
def compute_value_migration(
    today_vp: VolumeProfileResult | None,
    yesterday_vp: VolumeProfileResult | None,
    developing: list[DevelopingPoint],
) -> ValueMigration | None:
    if today_vp is None or yesterday_vp is None:
        return None

    poc_shift = today_vp.poc - yesterday_vp.poc
    poc_shift_pct = (poc_shift / yesterday_vp.poc * 100) if yesterday_vp.poc else 0.0
    direction: Literal["up", "down", "flat"] = "up" if poc_shift > 0 else "down" if poc_shift < 0 else "flat"
    intraday_drift = (developing[-1].poc - developing[0].poc) if len(developing) >= 2 else 0.0

    return ValueMigration(
        poc_shift=poc_shift,
        poc_shift_pct=poc_shift_pct,
        direction=direction,
        vah_shift=today_vp.vah - yesterday_vp.vah,
        val_shift=today_vp.val - yesterday_vp.val,
        intraday_poc_drift=intraday_drift,
    )


# ---------------------------------------------------------------------------
# 6. Acceptance / Rejection
# ---------------------------------------------------------------------------
def classify_level_test(candles: pd.DataFrame, level_price: float, tolerance: float) -> tuple[str, int]:
    """A level is "accepted" if price spent multiple bars trading and
    closing inside a small band around it (the market built value there);
    "rejected" if price touched the band but consistently closed away from
    it (the market tested and moved on); "untested" if price never reached
    the band at all."""
    band_lo, band_hi = level_price - tolerance, level_price + tolerance
    touches = 0
    accepted_bars = 0
    for row in candles.itertuples(index=False):
        touched = row.low <= band_hi and row.high >= band_lo
        if not touched:
            continue
        touches += 1
        if band_lo <= row.close <= band_hi:
            accepted_bars += 1

    if touches == 0:
        return "untested", 0
    if accepted_bars >= 3 or (touches >= 2 and accepted_bars / touches >= 0.5):
        return "accepted", touches
    return "rejected", touches


def compute_level_tests(
    today_candles: pd.DataFrame,
    today_vp: VolumeProfileResult | None,
    yesterday_vp: VolumeProfileResult | None,
    bin_size: float,
) -> list[LevelTest]:
    if today_vp is None or today_candles.empty:
        return []

    tests = []
    for name, price in (("VAH", today_vp.vah), ("VAL", today_vp.val), ("POC", today_vp.poc)):
        outcome, touches = classify_level_test(today_candles, price, bin_size)
        tests.append(LevelTest(level_name=name, price=price, outcome=outcome, touches=touches))

    if yesterday_vp is not None:
        outcome, touches = classify_level_test(today_candles, yesterday_vp.poc, bin_size)
        tests.append(LevelTest(level_name="Prior POC", price=yesterday_vp.poc, outcome=outcome, touches=touches))

    return tests


# ---------------------------------------------------------------------------
# 8. Initial Balance
# ---------------------------------------------------------------------------
def compute_initial_balance(
    today_candles: pd.DataFrame, ib_minutes: int = DEFAULT_INITIAL_BALANCE_MINUTES
) -> InitialBalance | None:
    if today_candles.empty:
        return None

    start = today_candles["timestamp"].iloc[0]
    cutoff = start + timedelta(minutes=ib_minutes)
    window = today_candles[today_candles["timestamp"] < cutoff]
    if window.empty:
        return None

    session_end = today_candles["timestamp"].iloc[-1]
    return InitialBalance(
        ib_high=window["high"].max(),
        ib_low=window["low"].min(),
        ib_range=window["high"].max() - window["low"].min(),
        end_time=window["timestamp"].iloc[-1],
        is_complete=session_end >= cutoff,
    )


# ---------------------------------------------------------------------------
# 9. Opening Type
# ---------------------------------------------------------------------------
def classify_opening_type(
    today_candles: pd.DataFrame,
    yesterday_vp: VolumeProfileResult | None,
    window_minutes: int = DEFAULT_OPENING_WINDOW_MINUTES,
) -> OpeningType | None:
    """Approximates Steidlmayer's opening-type taxonomy from the first
    `window_minutes` of the session: Open-Drive (immediate one-way move,
    little retracement), Open-Test-Drive / Open-Rejection-Reverse (an early
    probe in one direction that reverses and drives the other way -- the
    "Reversal" label is used when the reversal is the larger, more decisive
    move), or Open-Auction (a tight, non-directional open)."""
    if today_candles.empty:
        return None

    start = today_candles["timestamp"].iloc[0]
    cutoff = start + timedelta(minutes=window_minutes)
    window = today_candles[today_candles["timestamp"] < cutoff]
    if window.empty:
        return None

    open_price = window["open"].iloc[0]
    w_high, w_low, w_close = window["high"].max(), window["low"].min(), window["close"].iloc[-1]
    rng = w_high - w_low
    up_move = w_high - open_price
    down_move = open_price - w_low
    net_move = w_close - open_price

    reference_range = (yesterday_vp.vah - yesterday_vp.val) if yesterday_vp is not None else None
    is_tight = (
        (reference_range is not None and reference_range > 0 and rng < 0.5 * reference_range)
        or (reference_range is None and open_price > 0 and rng < open_price * 0.001)
    )
    if is_tight:
        return OpeningType(
            type="Open-Auction",
            description="Opened and stayed within a tight range -- no early directional conviction, a balance-type open.",
        )

    if up_move > 0 and down_move > 0 and rng > 0:
        dominant_tested = "up" if up_move > down_move else "down"
        closed_with_reversal = (net_move > 0 and dominant_tested == "down") or (net_move < 0 and dominant_tested == "up")
        reversal_strength = abs(net_move) / rng
        if closed_with_reversal and reversal_strength >= 0.6:
            direction = "higher" if net_move > 0 else "lower"
            tested = "lower" if dominant_tested == "down" else "higher"
            return OpeningType(
                type="Open-Rejection-Reverse",
                description=f"Opened, tested {tested}, was rejected, then reversed with strong conviction {direction}.",
            )
        if closed_with_reversal:
            direction = "higher" if net_move > 0 else "lower"
            tested = "lower" if dominant_tested == "down" else "higher"
            return OpeningType(
                type="Open-Test-Drive",
                description=f"Opened, briefly tested {tested}, then drove {direction}.",
            )

    if net_move != 0 and rng > 0:
        retrace = down_move if net_move > 0 else up_move
        if retrace / rng < 0.25:
            direction = "higher" if net_move > 0 else "lower"
            return OpeningType(
                type="Open-Drive",
                description=f"Opened and drove {direction} immediately with minimal retracement -- strong directional conviction.",
            )

    return OpeningType(
        type="Open-Auction",
        description="No clear directional pattern in the opening window -- treated as balance/auction.",
    )


# ---------------------------------------------------------------------------
# 10. Rotation Factor
# ---------------------------------------------------------------------------
def compute_rotation_factor(
    today_candles: pd.DataFrame, period_minutes: int = DEFAULT_ROTATION_PERIOD_MINUTES
) -> RotationFactor:
    """Splits the session into `period_minutes` blocks; each block after the
    first is scored +1 ("up rotation": new high vs. the previous block,
    no new low), -1 ("down rotation"), or skipped (both/neither -- no clear
    signal). The `value` returned is the number of direction *flips* between
    consecutive rotations -- a high flip rate means price kept reversing
    between up and down blocks (a choppy, two-sided auction); a low flip
    rate means rotations mostly agreed in direction (a trending market)."""
    if today_candles.empty or len(today_candles) < 2:
        return RotationFactor(value=0, periods=0, label="Trending")

    df = today_candles.copy()
    start = df["timestamp"].iloc[0]
    df["period"] = ((df["timestamp"] - start).dt.total_seconds() // (period_minutes * 60)).astype(int)
    grouped = df.groupby("period").agg(high=("high", "max"), low=("low", "min")).reset_index()

    rotations: list[int] = []
    for i in range(1, len(grouped)):
        prev_high, prev_low = grouped.loc[i - 1, "high"], grouped.loc[i - 1, "low"]
        cur_high, cur_low = grouped.loc[i, "high"], grouped.loc[i, "low"]
        made_new_high = cur_high > prev_high
        made_new_low = cur_low < prev_low
        if made_new_high and not made_new_low:
            rotations.append(1)
        elif made_new_low and not made_new_high:
            rotations.append(-1)

    if len(rotations) < 2:
        return RotationFactor(value=0, periods=len(grouped), label="Trending")

    flips = sum(1 for a, b in zip(rotations, rotations[1:]) if a != b)
    label: Literal["Trending", "Rotational"] = "Rotational" if flips / (len(rotations) - 1) >= 0.5 else "Trending"
    return RotationFactor(value=flips, periods=len(grouped), label=label)


# ---------------------------------------------------------------------------
# 11. Volume Pace
# ---------------------------------------------------------------------------
def compute_volume_pace(
    today_candles: pd.DataFrame, historical_by_date: dict, above_threshold_pct: float = 115.0, below_threshold_pct: float = 85.0
) -> VolumePace | None:
    """Compares today's cumulative volume-so-far against the average
    cumulative volume at the same elapsed session time across the supplied
    historical days -- tells you if today is a busier or quieter session
    than normal, independent of price direction."""
    if today_candles.empty or not historical_by_date:
        return None

    session_start = today_candles["timestamp"].iloc[0]
    elapsed_minutes = (today_candles["timestamp"].iloc[-1] - session_start).total_seconds() / 60
    today_cum = float(today_candles["volume"].sum())

    reference_cums: list[float] = []
    for day_df in historical_by_date.values():
        if day_df is None or day_df.empty:
            continue
        day_start = day_df["timestamp"].iloc[0]
        cutoff = day_start + timedelta(minutes=elapsed_minutes)
        window = day_df[day_df["timestamp"] <= cutoff]
        if not window.empty:
            reference_cums.append(float(window["volume"].sum()))

    if not reference_cums:
        return None

    avg_cum = sum(reference_cums) / len(reference_cums)
    pace_pct = (today_cum / avg_cum * 100) if avg_cum > 0 else 100.0
    label: Literal["Above Average", "Average", "Below Average"] = (
        "Above Average" if pace_pct >= above_threshold_pct else "Below Average" if pace_pct <= below_threshold_pct else "Average"
    )
    return VolumePace(pace_pct=pace_pct, today_cumulative=today_cum, average_cumulative=avg_cum, label=label)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def compute_volume_profile_intelligence(
    today_candles: pd.DataFrame,
    historical_by_date: dict,
    bin_size: float,
    value_area_pct: float = 0.70,
    developing_checkpoint_minutes: int = DEFAULT_DEVELOPING_CHECKPOINT_MINUTES,
    initial_balance_minutes: int = DEFAULT_INITIAL_BALANCE_MINUTES,
    opening_window_minutes: int = DEFAULT_OPENING_WINDOW_MINUTES,
    rotation_period_minutes: int = DEFAULT_ROTATION_PERIOD_MINUTES,
) -> VolumeProfileIntelligence:
    """Computes every metric in this module from a single set of inputs.

    `today_candles`: today's 1-min OHLCV candles so far, ascending by time.
    `historical_by_date`: {date: DataFrame} of prior trading days' 1-min
    candles (most recent date used as "yesterday" for migration/acceptance
    comparisons; all supplied days used for the volume-pace reference curve).
    """
    today_vp = compute_volume_profile(today_candles, bin_size, value_area_pct)

    yesterday_vp: VolumeProfileResult | None = None
    if historical_by_date:
        latest_date = max(historical_by_date)
        yesterday_df = historical_by_date.get(latest_date)
        if yesterday_df is not None and not yesterday_df.empty:
            yesterday_vp = compute_volume_profile(yesterday_df, bin_size, value_area_pct)

    developing = compute_developing_levels(today_candles, bin_size, value_area_pct, developing_checkpoint_minutes)

    hvns: list[VolumeNode] = []
    lvns: list[VolumeNode] = []
    profile_shape: ProfileShapeResult | None = None
    if today_vp is not None:
        hvns, lvns = compute_volume_nodes(today_vp.bins, bin_size)
        profile_shape = classify_profile_shape(today_vp.bins, today_vp.poc, bin_size)

    return VolumeProfileIntelligence(
        developing=developing,
        hvns=hvns,
        lvns=lvns,
        migration=compute_value_migration(today_vp, yesterday_vp, developing),
        level_tests=compute_level_tests(today_candles, today_vp, yesterday_vp, bin_size),
        profile_shape=profile_shape,
        initial_balance=compute_initial_balance(today_candles, initial_balance_minutes),
        opening_type=classify_opening_type(today_candles, yesterday_vp, opening_window_minutes),
        rotation_factor=compute_rotation_factor(today_candles, rotation_period_minutes),
        volume_pace=compute_volume_pace(today_candles, historical_by_date),
    )
