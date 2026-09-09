"""Builds the paper agent's view of the market at a cutoff time.

Every field is READ from an existing component -- the Decision Card's own
levels_snapshots row, the CAS pre-transition windows, the frozen CAS
forecast, the option chain. This module computes almost nothing itself;
it is an adapter, not a parallel technical-analysis engine.

LEAKAGE CONTRACT: every DB read here is clamped with `at_or_before=cutoff`
(or filters candles to `time <= cutoff`). Nothing here can see a price
later than the cutoff it was handed, which is what makes the 14:59
decision reproducible no matter how much post-3pm data exists. Proven by
tests/test_paper_leakage.py.
"""

import logging
from datetime import date, datetime, time, timedelta

import pandas as pd

from analytics.breakout_boxes import compute_atr
from config.instruments import INSTRUMENTS
from db import reader as db_reader
from paper_trading.models import DataQuality, MarketStateWindow, PaperMarketState

logger = logging.getLogger(__name__)

REQUIRED_FOR_DECISION = ("spot", "atr_14", "trend_label", "vwap")


def _atr_14(candles: pd.DataFrame) -> float | None:
    """Prior-day-anchored ATR(14) from daily bars, reusing
    analytics.breakout_boxes.compute_atr unmodified -- the same function
    Phase 7A magnitude tiers use, so one ATR means one thing project-wide."""
    if candles.empty:
        return None
    daily = candles.set_index("timestamp").resample("1D").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")
    ).dropna()
    if len(daily) < 15:
        return None
    series = compute_atr(daily, period=14)
    return float(series.iloc[-1]) if not series.empty and pd.notna(series.iloc[-1]) else None


def _momentum(day_candles: pd.DataFrame, minutes: int) -> float | None:
    sub = day_candles.tail(minutes + 1)
    if len(sub) < 2:
        return None
    return float(sub["close"].iloc[-1] - sub["close"].iloc[0])


def strike_step(symbol: str) -> float:
    """Reuses config.instruments existing per-symbol round_number_step,
    which already encodes real strike spacing (SENSEX 100, NIFTY 50)."""
    return float(INSTRUMENTS[symbol]["round_number_step"])


def _quality(state: PaperMarketState, missing: list[str]) -> DataQuality:
    """A field the DECISION needs missing => INSUFFICIENT (which forces NO
    TRADE). Anything else missing only degrades quality; the agent can
    still form a view, with fewer supporting factors and lower confidence."""
    if any(getattr(state, f) is None for f in REQUIRED_FOR_DECISION):
        return "INSUFFICIENT"
    if missing:
        return "DEGRADED"
    return "GOOD"


def build_market_state(
    symbol: str, session_date: date, cutoff: time, now: datetime, history_days: int = 40,
) -> PaperMarketState:
    cutoff_str = cutoff.strftime("%H:%M:%S")
    state = PaperMarketState(symbol=symbol, session_date=session_date, as_of=now)
    missing: list[str] = []

    # ---- underlying candles, clamped to the cutoff --------------------
    candles = db_reader.load_raw_candles(
        symbol, start_date=session_date - timedelta(days=history_days), end_date=session_date)
    if not candles.empty:
        candles["timestamp"] = pd.to_datetime(candles["timestamp"]).dt.tz_convert("Asia/Kolkata")
        candles = candles[
            (candles["timestamp"].dt.date < session_date)
            | (candles["timestamp"].dt.time <= cutoff)
        ]
        day_candles = candles[candles["timestamp"].dt.date == session_date]
        state.atr_14 = _atr_14(candles)
        if not day_candles.empty:
            state.spot = float(day_candles["close"].iloc[-1])
            state.momentum_5min = _momentum(day_candles, 5)
            state.momentum_15min = _momentum(day_candles, 15)
            recent = day_candles.tail(5)
            state.recent_range_5min = float(recent["high"].max() - recent["low"].min())
        else:
            missing.append("today_candles")
    else:
        missing.append("candles")

    # ---- the existing Decision Card state at the cutoff ----------------
    levels = db_reader.get_levels_snapshot_near(symbol, session_date, cutoff_str)
    if levels:
        state.trend_label = levels.get("trend_label")
        state.trend_score = levels.get("trend_score")
        state.vwap = levels.get("vwap_now")
        state.poc = levels.get("today_poc")
        state.vah = levels.get("today_vah")
        state.val = levels.get("today_val")
        state.support_low, state.support_high = levels.get("support_low"), levels.get("support_high")
        state.resistance_low, state.resistance_high = levels.get("resistance_low"), levels.get("resistance_high")
        state.institutional_bias_label = levels.get("institutional_bias_label")
        if state.spot is None:
            state.spot = levels.get("close")
        if state.spot is not None and state.vwap is not None:
            state.distance_from_vwap = round(state.spot - state.vwap, 2)
    else:
        missing.append("levels_snapshot")

    # ---- how the market arrived: the six 14:30-14:59 windows ----------
    windows = db_reader.load_pretransition_windows(symbol, session_date)
    state.pre_windows = [
        MarketStateWindow(
            window_index=w["window_index"], window_label=w["window_label"],
            net_point_change=w["net_point_change"], volume=w["volume"], rvol_pct=w["rvol_pct"],
            dominant_side=w["dominant_side"], price_distance_from_vwap=w["price_distance_from_vwap"],
            poc_change_during_window=w["poc_change_during_window"], pcr=w["pcr"],
        )
        for w in windows
    ]
    if state.pre_windows:
        last = state.pre_windows[-1]
        state.rvol_pct = last.rvol_pct
        state.dominant_side = last.dominant_side
        changes = [w.poc_change_during_window for w in state.pre_windows if w.poc_change_during_window is not None]
        state.poc_migration = round(sum(changes), 2) if changes else None
        vwap_path = [w.price_distance_from_vwap for w in state.pre_windows if w.price_distance_from_vwap is not None]
        if len(vwap_path) >= 2:
            state.vwap_slope = round(vwap_path[-1] - vwap_path[0], 3)
        if last.dominant_side == "buy":
            state.dominance_ratio = 0.6
        elif last.dominant_side == "sell":
            state.dominance_ratio = 0.4
    else:
        missing.append("pre_transition_windows")

    # ---- option chain at the cutoff -----------------------------------
    option_summary = db_reader.get_option_summary_near(symbol, session_date, cutoff_str)
    if option_summary:
        state.atm_strike = option_summary.get("atm_strike")
        state.pcr = option_summary.get("pcr")
        state.atm_iv_call = option_summary.get("atm_iv_call")
        state.atm_iv_put = option_summary.get("atm_iv_put")
        fetched_at = option_summary.get("fetched_at")
        if fetched_at is not None:
            cutoff_dt = pd.Timestamp.combine(pd.Timestamp(session_date), cutoff).tz_localize(
                fetched_at.tzinfo or "Asia/Kolkata")
            state.option_snapshot_age_sec = (cutoff_dt - fetched_at).total_seconds()
    else:
        missing.append("option_chain")

    # ---- the frozen CAS transition forecast ---------------------------
    forecast = db_reader.get_transition_forecast_full(symbol, session_date, "14:59")
    if forecast:
        state.transition_verdict = forecast.get("verdict")
        state.probability_up = forecast.get("probability_up")
        state.probability_down = forecast.get("probability_down")
        state.probability_no_move = forecast.get("probability_no_material_transition")
        state.transition_confidence = forecast.get("confidence_label")
        state.expected_move_low = forecast.get("expected_move_low")
        state.expected_move_high = forecast.get("expected_move_high")
        state.transition_risk_tier = forecast.get("transition_risk_tier")
        state.n_analogs = forecast.get("n_analogs")
    else:
        missing.append("transition_forecast")

    state.missing_fields = missing
    state.data_quality = _quality(state, missing)
    return state
