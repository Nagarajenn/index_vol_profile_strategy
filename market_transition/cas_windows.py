"""Dual-resolution pre/post-3pm transition detail (Phase 7B).

Per an explicit user correction: DO NOT use a uniform resolution across
14:30-15:15. Two different grains, for two different purposes:

  - PRE-3PM (14:30-14:59): six 5-minute decision windows -- how the market's
    state EVOLVES as 3pm approaches. This is "forecast information": every
    field here answers "what did we know by the end of this window".
  - POST-3PM (15:00-15:15): sixteen native 1-minute rows -- how the
    transition actually MANIFESTS, minute by minute -- plus a single
    17th checkpoint at 15:30 (the NSE Closing Auction Session's actual
    settlement print, often the most consequential move of the day for
    options; 15:16-15:29 itself isn't tracked). This is "actual outcome"
    -- never mixed with the pre-3pm section.

Entirely a presentation/analysis layer over the same 1-min raw_candles /
option_chain_* history everything else in this package reads. Never a
replacement storage grain -- the underlying 1-min data stays exactly as
it is in the Feature Store; this module only aggregates it for display and
for the leakage-safe forecast in cas_forecast.py.

No DB access of its own (same discipline as every other module in this
package) -- `option_lookup_fn` and `classified_events` are supplied by the
caller (scripts/run_cas_windowed_analysis.py).
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable

import pandas as pd

from analytics.institutional_bias import classify_institutional_bias
from config.settings import IST
from analytics.volume_intelligence.intervals import _bucket_baseline
from analytics.volume_intelligence.proxy import attach_buy_sell_columns
from analytics.volume_profile import compute_volume_profile
from analytics.vwap import compute_vwap
from market_transition.feature_extraction import _time_between
from market_transition.market_regime import classify_market_regime
from option_chain.summary import OptionChainSummary

PRE_WINDOW_BOUNDARIES: list[tuple[time, time]] = [
    (time(14, 30), time(14, 34)),
    (time(14, 35), time(14, 39)),
    (time(14, 40), time(14, 44)),
    (time(14, 45), time(14, 49)),
    (time(14, 50), time(14, 54)),
    (time(14, 55), time(14, 59)),
]
POST_MINUTE_START = time(15, 0)
POST_MINUTE_END = time(15, 15)  # inclusive -- 16 native 1-min rows

# NSE's Closing Auction Session (cash CAS runs 15:15-15:35; F&O close
# extended to 15:40) settles the day's actual closing print here -- the
# native 1-min post-transition table above stops at 15:15, silently
# missing this move even though it's often the single most consequential
# price action of the day for options (settlement-relevant). Tracked as
# ONE additional checkpoint row, not densified minute-by-minute like
# 15:00-15:15 -- volume/OI signals are already known to be less reliable
# once the closing auction begins (see the panel's own disclaimer), so a
# single anchor point at the actual close is the honest resolution for
# now; a proper multi-minute or leakage-safe-forecast treatment of
# 15:16-15:35 is future work, not this checkpoint.
CLOSING_SNAPSHOT_TIME = time(15, 30)

NEWS_RISK_WINDOW_MINUTES = 30
SEVERITY_MAX = 5  # classified_events.severity is 1-5 -- scaled to 0-100


@dataclass
class PreTransitionWindow:
    window_index: int  # 1-6
    window_label: str  # "14:30-14:34"
    open: float | None
    close: float | None
    high: float | None
    low: float | None
    net_point_change: float | None
    pct_change: float | None
    volume: float
    rvol_pct: float | None
    volume_acceleration_ratio: float | None
    buy_volume_estimate: float
    sell_volume_estimate: float
    dominance_ratio: float
    dominant_side: str
    vwap_at_window_end: float | None
    price_distance_from_vwap: float | None
    price_distance_from_vwap_pct: float | None
    vwap_slope: float | None
    poc_at_window_end: float | None
    poc_change_during_window: float | None
    poc_slope: float | None
    vah: float | None
    val: float | None
    pcr: float | None
    pcr_change: float | None
    call_oi_change: float | None
    put_oi_change: float | None
    iv_change: float | None
    option_pressure_score: float | None
    market_regime: str | None
    institutional_bias_label: str | None
    institutional_bias_score: int | None
    news_risk_score: int | None
    data_quality_flag: str | None = None


@dataclass
class PostTransitionMinute:
    minute_offset: int  # 0-15 (0 = 15:00, 15 = 15:15); 16 = the single 15:30 closing-print checkpoint (see CLOSING_SNAPSHOT_TIME)
    minute_time: str  # "15:00".."15:15", or "15:30" for the closing checkpoint
    close: float
    price_change: float
    volume: float
    rvol_pct: float | None
    dominance_ratio: float
    dominant_side: str
    poc_change: float | None
    vwap_change: float | None
    pcr_change: float | None
    call_oi_change: float | None
    put_oi_change: float | None
    iv_change: float | None
    option_pressure_score: float | None
    range_expansion: float
    transition_shock_score: float
    is_closing_snapshot: bool = False  # True only for the 15:30 row -- 15:16-15:29 isn't tracked at all
    data_quality_flag: str | None = None


def _dominant_side(ratio: float) -> str:
    if ratio >= 0.55:
        return "buy"
    if ratio <= 0.45:
        return "sell"
    return "balanced"


def _option_reading(option_lookup_fn: Callable[[time], dict | None], at_time: time) -> dict | None:
    """Normalizes a db_reader.get_option_summary_near-shaped row into just
    the fields this module diffs between checkpoints. Averages call/put IV
    into one atm_iv reading (the spec asks for a single "IV change", not
    two)."""
    row = option_lookup_fn(at_time)
    if row is None:
        return None
    call_iv, put_iv = row.get("atm_iv_call"), row.get("atm_iv_put")
    atm_iv = (call_iv + put_iv) / 2 if call_iv is not None and put_iv is not None else None
    return {
        "pcr": row.get("pcr"),
        "call_oi_change_near_atm": row.get("call_oi_change_near_atm"),
        "put_oi_change_near_atm": row.get("put_oi_change_near_atm"),
        "atm_iv": atm_iv,
        "spot": row.get("spot"),
        "atm_strike": row.get("atm_strike"),
        "raw_row": row,
    }


def _diff(curr: dict | None, prev: dict | None, key: str) -> float | None:
    if curr is None or prev is None or curr.get(key) is None or prev.get(key) is None:
        return None
    return curr[key] - prev[key]


def _option_pressure_score(
    pcr_change: float | None, call_oi_change: float | None, put_oi_change: float | None, iv_change: float | None
) -> float | None:
    """Deterministic composite in [-1, 1]: positive = bullish option
    positioning pressure building between the two checkpoints (PCR falling,
    put OI building relative to call OI, IV cooling), negative = bearish.
    A documented starting heuristic (tunable later, same stance as every
    other composite score in this codebase) combining the same signal
    families institutional_bias.py already uses for a single-snapshot
    level read -- here read as a rate-of-change between two checkpoints
    instead. Returns None (never a fabricated 0) when nothing is available
    to compute from."""
    components: list[float] = []
    if pcr_change is not None:
        components.append(max(-1.0, min(1.0, -pcr_change)))
    if call_oi_change is not None and put_oi_change is not None and (call_oi_change or put_oi_change):
        total = abs(call_oi_change) + abs(put_oi_change)
        components.append((put_oi_change - call_oi_change) / total if total else 0.0)
    if iv_change is not None:
        components.append(max(-1.0, min(1.0, -iv_change / 2.0)))
    if not components:
        return None
    return sum(components) / len(components)


def _institutional_bias(option_reading: dict | None, current_price: float) -> tuple[str | None, int | None]:
    if option_reading is None or option_reading.get("spot") is None:
        return None, None
    row = option_reading["raw_row"]
    summary = OptionChainSummary(
        expiry="",
        spot=row["spot"],
        atm_strike=row["atm_strike"],
        pcr=row["pcr"],
        call_oi_change_near_atm=row["call_oi_change_near_atm"],
        put_oi_change_near_atm=row["put_oi_change_near_atm"],
        total_call_oi=row["total_call_oi"],
        total_put_oi=row["total_put_oi"],
        atm_iv_call=row["atm_iv_call"],
        atm_iv_put=row["atm_iv_put"],
        max_call_oi_strike=row["max_call_oi_strike"],
        max_put_oi_strike=row["max_put_oi_strike"],
    )
    bias = classify_institutional_bias(summary, current_price=current_price)
    return (bias.label, bias.score) if bias.available else (None, None)


def _news_risk_near(classified_events: list[dict], at_time: time, session_date: date, window_minutes: int = NEWS_RISK_WINDOW_MINUTES) -> int | None:
    """Max severity (scaled 0-100) among events classified in the trailing
    `window_minutes` before `at_time` -- gated on classified_at (never
    published_at), matching this project's established anti-leakage
    convention for news. None (not 0) when no relevant event falls in the
    window -- a quiet window is honestly "no reading", not "zero risk"."""
    cutoff = datetime.combine(session_date, at_time, tzinfo=IST)
    window_start = cutoff - timedelta(minutes=window_minutes)
    severities = [
        e["severity"]
        for e in classified_events
        if e.get("severity") is not None and e.get("classified_at") is not None
        # classified_at comes back tz-aware (whatever the DB driver reports,
        # typically UTC) -- convert to IST rather than stripping tzinfo, or
        # a 5.5-hour offset would silently misalign every comparison.
        and window_start <= e["classified_at"].astimezone(IST) <= cutoff
    ]
    if not severities:
        return None
    return round(max(severities) / SEVERITY_MAX * 100)


def _rvol_pct(window_volume: float, historical_by_date: dict[date, pd.DataFrame], start_elapsed: float, end_elapsed: float) -> float | None:
    baseline = _bucket_baseline(historical_by_date, start_elapsed, end_elapsed)
    if baseline is None or baseline <= 0:
        return None
    return window_volume / baseline * 100


def _typical_1min_range(today_candles: pd.DataFrame) -> float:
    """Average (high-low) across today's candles so far -- used only to
    scale a single minute's ATR-normalized move for the shock score, a
    scaling convenience (not a statistical claim) since the day's own ATR
    is a full-session figure, not a per-minute one."""
    if today_candles.empty:
        return 0.0
    ranges = today_candles["high"] - today_candles["low"]
    return float(ranges[ranges > 0].mean()) if (ranges > 0).any() else 0.0


def build_pre_transition_windows(
    today_candles: pd.DataFrame,
    historical_by_date: dict[date, pd.DataFrame],
    option_lookup_fn: Callable[[time], dict | None],
    classified_events: list[dict],
    bin_size: float,
    session_date: date,
) -> list[PreTransitionWindow]:
    """`today_candles` is the FULL day's 1-min candles (from session open) --
    needed because VWAP/POC/market-regime are all cumulative-from-open
    reads, not just this window's own candles."""
    if today_candles.empty:
        return []

    session_start = today_candles["timestamp"].iloc[0]
    vwap_series = compute_vwap(today_candles)

    windows: list[PreTransitionWindow] = []
    prev_close: float | None = None
    prev_vwap: float | None = None
    prev_poc: float | None = None
    prev_option: dict | None = None
    prev_volume: float | None = None

    for idx, (w_start, w_end) in enumerate(PRE_WINDOW_BOUNDARIES, start=1):
        window = _time_between(today_candles, w_start, w_end)
        if window.empty:
            windows.append(
                PreTransitionWindow(
                    window_index=idx, window_label=f"{w_start:%H:%M}-{w_end:%H:%M}",
                    open=None, close=None, high=None, low=None, net_point_change=None, pct_change=None,
                    volume=0.0, rvol_pct=None, volume_acceleration_ratio=None,
                    buy_volume_estimate=0.0, sell_volume_estimate=0.0, dominance_ratio=0.5, dominant_side="balanced",
                    vwap_at_window_end=None, price_distance_from_vwap=None, price_distance_from_vwap_pct=None, vwap_slope=None,
                    poc_at_window_end=None, poc_change_during_window=None, poc_slope=None, vah=None, val=None,
                    pcr=None, pcr_change=None, call_oi_change=None, put_oi_change=None, iv_change=None, option_pressure_score=None,
                    market_regime=None, institutional_bias_label=None, institutional_bias_score=None, news_risk_score=None,
                    data_quality_flag="no_candles_in_window",
                )
            )
            continue

        o, c = float(window["open"].iloc[0]), float(window["close"].iloc[-1])
        h, l = float(window["high"].max()), float(window["low"].min())
        net_change = c - (prev_close if prev_close is not None else o)
        pct_change = (net_change / prev_close * 100) if prev_close else None

        enriched = attach_buy_sell_columns(window)
        buy_vol, sell_vol = float(enriched["buy_volume"].sum()), float(enriched["sell_volume"].sum())
        dom_ratio = buy_vol / (buy_vol + sell_vol) if (buy_vol + sell_vol) > 0 else 0.5

        volume = float(window["volume"].sum())
        start_elapsed = (datetime.combine(session_date, w_start) - session_start.replace(tzinfo=None)).total_seconds() / 60
        end_elapsed = start_elapsed + 5
        rvol_pct = _rvol_pct(volume, historical_by_date, start_elapsed, end_elapsed)
        vol_accel = (volume / prev_volume) if prev_volume else None

        cumulative = today_candles[today_candles["timestamp"] <= window["timestamp"].iloc[-1]]
        vwap_end = float(vwap_series.loc[cumulative.index[-1]]) if len(cumulative) else None
        vwap_slope = (vwap_end - prev_vwap) if (vwap_end is not None and prev_vwap is not None) else None
        dist_from_vwap = (c - vwap_end) if vwap_end is not None else None
        dist_from_vwap_pct = (dist_from_vwap / vwap_end * 100) if (dist_from_vwap is not None and vwap_end) else None

        vp = compute_volume_profile(cumulative, bin_size)
        poc = vp.poc if vp else None
        vah = vp.vah if vp else None
        val = vp.val if vp else None
        poc_change = (poc - prev_poc) if (poc is not None and prev_poc is not None) else None

        option_reading = _option_reading(option_lookup_fn, w_end)
        pcr = option_reading["pcr"] if option_reading else None
        pcr_change = _diff(option_reading, prev_option, "pcr")
        call_oi_change = _diff(option_reading, prev_option, "call_oi_change_near_atm")
        put_oi_change = _diff(option_reading, prev_option, "put_oi_change_near_atm")
        iv_change = _diff(option_reading, prev_option, "atm_iv")
        pressure = _option_pressure_score(pcr_change, call_oi_change, put_oi_change, iv_change)
        bias_label, bias_score = _institutional_bias(option_reading, c)

        regime = classify_market_regime(cumulative, historical_by_date)
        news_risk = _news_risk_near(classified_events, w_end, session_date)

        windows.append(
            PreTransitionWindow(
                window_index=idx, window_label=f"{w_start:%H:%M}-{w_end:%H:%M}",
                open=o, close=c, high=h, low=l, net_point_change=net_change, pct_change=pct_change,
                volume=volume, rvol_pct=rvol_pct, volume_acceleration_ratio=vol_accel,
                buy_volume_estimate=buy_vol, sell_volume_estimate=sell_vol,
                dominance_ratio=dom_ratio, dominant_side=_dominant_side(dom_ratio),
                vwap_at_window_end=vwap_end, price_distance_from_vwap=dist_from_vwap,
                price_distance_from_vwap_pct=dist_from_vwap_pct, vwap_slope=vwap_slope,
                poc_at_window_end=poc, poc_change_during_window=poc_change,
                poc_slope=poc_change,  # slope across one window == the change itself at this resolution
                vah=vah, val=val,
                pcr=pcr, pcr_change=pcr_change, call_oi_change=call_oi_change, put_oi_change=put_oi_change,
                iv_change=iv_change, option_pressure_score=pressure,
                market_regime=regime, institutional_bias_label=bias_label, institutional_bias_score=bias_score,
                news_risk_score=news_risk,
            )
        )

        prev_close, prev_vwap, prev_poc, prev_option, prev_volume = c, vwap_end, poc, option_reading, volume

    return windows


def _build_one_minute(
    row: pd.Series,
    offset: int,
    today_candles: pd.DataFrame,
    vwap_series: pd.Series,
    historical_by_date: dict[date, pd.DataFrame],
    option_lookup_fn: Callable[[time], dict | None],
    bin_size: float,
    session_date: date,
    session_start,
    typical_range: float,
    ranges: list[float],
    state: dict,
    is_closing_snapshot: bool = False,
) -> PostTransitionMinute:
    """One row's worth of computation, factored out so the native
    15:00-15:15 loop and the single 15:30 closing-snapshot checkpoint
    share identical logic. `state` carries prev_close/prev_vwap/prev_poc/
    prev_option and is mutated in place so the caller's next call (whether
    the next native minute or the closing snapshot) diffs against this
    row correctly."""
    minute_time = row["timestamp"].time()
    close = float(row["close"])
    prev_close = state["prev_close"]
    price_change = close - prev_close if prev_close is not None else 0.0
    rng = float(row["high"]) - float(row["low"])
    ranges.append(rng)
    # For the closing snapshot, this compares against the last 10 TRACKED
    # minutes (ending 15:15), not the last 10 minutes of clock time --
    # 15:16-15:29 isn't sampled, so there's no other baseline available.
    range_expansion = (rng / (sum(ranges[-11:-1]) / len(ranges[-11:-1]))) if len(ranges) > 1 and sum(ranges[-11:-1]) > 0 else 1.0

    enriched = attach_buy_sell_columns(today_candles[today_candles["timestamp"] <= row["timestamp"]].tail(1))
    buy_vol, sell_vol = float(enriched["buy_volume"].sum()), float(enriched["sell_volume"].sum())
    dom_ratio = buy_vol / (buy_vol + sell_vol) if (buy_vol + sell_vol) > 0 else 0.5

    volume = float(row["volume"])
    start_elapsed = (datetime.combine(session_date, minute_time) - session_start.replace(tzinfo=None)).total_seconds() / 60
    rvol_pct = _rvol_pct(volume, historical_by_date, start_elapsed, start_elapsed + 1)

    cumulative = today_candles[today_candles["timestamp"] <= row["timestamp"]]
    vwap_now = float(vwap_series.loc[cumulative.index[-1]]) if len(cumulative) else None
    prev_vwap = state["prev_vwap"]
    vwap_change = (vwap_now - prev_vwap) if (vwap_now is not None and prev_vwap is not None) else None

    vp = compute_volume_profile(cumulative, bin_size)
    poc = vp.poc if vp else None
    prev_poc = state["prev_poc"]
    poc_change = (poc - prev_poc) if (poc is not None and prev_poc is not None) else None

    option_reading = _option_reading(option_lookup_fn, minute_time)
    prev_option = state["prev_option"]
    pcr_change = _diff(option_reading, prev_option, "pcr")
    call_oi_change = _diff(option_reading, prev_option, "call_oi_change_near_atm")
    put_oi_change = _diff(option_reading, prev_option, "put_oi_change_near_atm")
    iv_change = _diff(option_reading, prev_option, "atm_iv")
    pressure = _option_pressure_score(pcr_change, call_oi_change, put_oi_change, iv_change)

    atr_component = min(abs(price_change) / typical_range, 1.0) if typical_range else 0.0
    rvol_component = min(rvol_pct / 300, 1.0) if rvol_pct is not None else 0.0
    range_component = min(range_expansion / 3.0, 1.0)
    dominance_component = abs(dom_ratio - 0.5) * 2
    pressure_component = abs(pressure) if pressure is not None else 0.0
    shock_score = round(
        100
        * max(
            0.0,
            min(
                1.0,
                0.25 * atr_component + 0.25 * rvol_component + 0.20 * range_component
                + 0.15 * dominance_component + 0.15 * pressure_component,
            ),
        ),
        1,
    )

    minute = PostTransitionMinute(
        minute_offset=offset, minute_time=f"{minute_time:%H:%M}",
        close=close, price_change=price_change, volume=volume, rvol_pct=rvol_pct,
        dominance_ratio=dom_ratio, dominant_side=_dominant_side(dom_ratio),
        poc_change=poc_change, vwap_change=vwap_change,
        pcr_change=pcr_change, call_oi_change=call_oi_change, put_oi_change=put_oi_change, iv_change=iv_change,
        option_pressure_score=pressure, range_expansion=round(range_expansion, 2),
        transition_shock_score=shock_score, is_closing_snapshot=is_closing_snapshot,
    )

    state["prev_close"], state["prev_vwap"], state["prev_poc"], state["prev_option"] = close, vwap_now, poc, option_reading
    return minute


def build_post_transition_minutes(
    today_candles: pd.DataFrame,
    historical_by_date: dict[date, pd.DataFrame],
    option_lookup_fn: Callable[[time], dict | None],
    prior_window: PreTransitionWindow | None,
    bin_size: float,
    session_date: date,
) -> list[PostTransitionMinute]:
    """Native 1-minute resolution, 15:00 through 15:15 inclusive (16 rows),
    plus a single 17th row at 15:30 (CLOSING_SNAPSHOT_TIME) when that
    candle exists -- see its own comment for why. `prior_window` is the
    last pre-transition window (14:55-14:59) so the very first post-3pm
    minute has something to diff against. The shock score's magnitude
    component is scaled by this session's own typical 1-min range
    (_typical_1min_range), not a separately-supplied ATR -- self-contained,
    no dependency on Phase 7A's ATR value (which isn't persisted anywhere
    retrievable at this granularity)."""
    post_window = _time_between(today_candles, POST_MINUTE_START, POST_MINUTE_END)
    if post_window.empty:
        return []

    session_start = today_candles["timestamp"].iloc[0]
    vwap_series = compute_vwap(today_candles)
    typical_range = _typical_1min_range(today_candles)

    state = {
        "prev_close": prior_window.close if prior_window else None,
        "prev_vwap": prior_window.vwap_at_window_end if prior_window else None,
        "prev_poc": prior_window.poc_at_window_end if prior_window else None,
        "prev_option": _option_reading(option_lookup_fn, POST_MINUTE_START) if prior_window else None,
    }
    ranges: list[float] = []

    minutes: list[PostTransitionMinute] = []
    for offset, (_, row) in enumerate(post_window.iterrows()):
        minutes.append(_build_one_minute(
            row, offset, today_candles, vwap_series, historical_by_date, option_lookup_fn,
            bin_size, session_date, session_start, typical_range, ranges, state,
        ))

    # Closing-print checkpoint: a SINGLE extra row at 15:30, not a
    # densified 15:16-15:29 -- see CLOSING_SNAPSHOT_TIME's comment.
    # Skipped (not fabricated) when that candle doesn't exist yet -- a
    # live in-progress session that hasn't reached 15:30, or a historical
    # day with a genuine data gap.
    closing_candle = today_candles[today_candles["timestamp"].dt.time == CLOSING_SNAPSHOT_TIME]
    if not closing_candle.empty:
        minutes.append(_build_one_minute(
            closing_candle.iloc[0], len(minutes), today_candles, vwap_series, historical_by_date, option_lookup_fn,
            bin_size, session_date, session_start, typical_range, ranges, state, is_closing_snapshot=True,
        ))

    return minutes
