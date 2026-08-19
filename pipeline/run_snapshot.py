import logging
from datetime import date, datetime, timedelta

import pandas as pd

from analytics.levels import compute_levels
from charting.chart_builder import build_overlays, render_chart
from config.instruments import INSTRUMENTS
from config.settings import CHART_BACKSTOP_MINUTES, SNAPSHOT_ROOT
from db import reader as db_reader
from db import writer as db_writer
from decision.decision_card import build_decision_card
from dhan_client.client import fetch_daily_candles, fetch_intraday_candles
from option_chain.fetch import get_option_chain
from option_chain.summary import summarize_option_chain
from quant_features import live as quant_live

logger = logging.getLogger(__name__)


def _fetch_context(symbol: str, as_of_date: date, lookback_days: int = 8):
    candles_1min = fetch_intraday_candles(symbol, as_of_date - timedelta(days=lookback_days), as_of_date, interval=1)
    day_df = candles_1min[candles_1min["timestamp"].dt.date == as_of_date].reset_index(drop=True)

    prior_days = sorted(d for d in candles_1min["timestamp"].dt.date.unique() if d < as_of_date)
    prior_day_df = candles_1min[candles_1min["timestamp"].dt.date == prior_days[-1]] if prior_days else None

    daily = fetch_daily_candles(symbol, as_of_date - timedelta(days=10), as_of_date)
    prior_daily_rows = daily[daily["timestamp"].dt.date < as_of_date]
    prior_day_ohlc = None
    if len(prior_daily_rows):
        row = prior_daily_rows.iloc[-1]
        prior_day_ohlc = {"high": row["high"], "low": row["low"], "close": row["close"]}

    return candles_1min, day_df, prior_day_df, daily, prior_day_ohlc


def should_render_chart(
    symbol: str,
    current_trend_label: str | None,
    current_poc: float | None,
    now: datetime,
    mode: str,
    bin_size: float,
    force_chart: bool = False,
    get_last_chart_row_fn=db_reader.get_last_chart_row,
) -> tuple[bool, str | None]:
    """Decides whether this snapshot should render+save a chart PNG.

    Backfill mode: the caller (pipeline/backfill.py) already decides via a
    static checkpoint-time list and passes that decision in as `force_chart`.

    Live mode: event-driven -- render on the first tick of the session, a
    trend-label flip, a POC move of at least one volume-profile bin since
    the last *charted* row (comparing against the last chart rather than
    the last computed value gives free hysteresis against an A-B-A flicker
    across a couple of ticks), or a time backstop so quiet/choppy stretches
    still get periodic training coverage. The baseline is always re-read
    from Postgres (never cached in memory), so a mid-day process restart
    needs no special handling.
    """
    if mode == "backfill":
        return force_chart, ("backfill_checkpoint" if force_chart else None)

    baseline = get_last_chart_row_fn(symbol, "live", now.date())
    if baseline is None:
        return True, "first_of_session"
    if current_trend_label != baseline["trend_label"]:
        return True, "trend_change"
    if current_poc is not None and baseline["today_poc"] is not None and abs(current_poc - baseline["today_poc"]) >= bin_size:
        return True, "poc_change"
    if (now - baseline["as_of"]) >= timedelta(minutes=CHART_BACKSTOP_MINUTES):
        return True, "interval_backstop"
    return False, None


def run_snapshot(
    symbol: str,
    mode: str = "live",
    as_of_date: date | None = None,
    day_candles_1min: pd.DataFrame | None = None,
    prior_day_candles_1min: pd.DataFrame | None = None,
    prior_day_ohlc: dict | None = None,
    force_chart: bool = False,
    option_chain_override: tuple[dict, object] | None = None,
    persist_option_chain: bool = True,
) -> dict | None:
    """Runs the full pipeline for one symbol: fetch -> compute -> persist to
    Postgres (raw candles, option chain, computed levels) -> conditionally
    render+record a chart.

    mode="live" also fetches the option chain for institutional-bias context
    and decides chart rendering via should_render_chart(). mode="backfill"
    expects the caller to pass in already-fetched candles (see
    pipeline/backfill.py, which fetches the full window once per symbol and
    persists raw candles itself rather than per-checkpoint here) plus a
    `force_chart` bool driven by its own checkpoint-time list.

    `option_chain_override` is (raw_chain_dict, OptionChainSummary), used
    instead of a fresh fetch -- lets a caller replaying many mode="live"
    checkpoints against the same underlying option chain (e.g.
    pipeline/catch_up_today.py catching up today's session so far) reuse one
    fetch instead of hammering Dhan's rate-limited endpoint once per
    checkpoint for what would be near-identical current OI each time.
    `persist_option_chain=False` skips writing option_chain_raw/summary rows
    even when option_chain is present -- pairs with the override so a caller
    reusing one fetch across many checkpoints doesn't insert the same large
    JSONB payload once per checkpoint under a different fetched_at.

    Returns the decision card dict (with "chart_path"/"chart_triggered_by"
    set if a chart was rendered), or None if there's no candle data for
    as_of_date yet (e.g. called before market open).
    """
    meta = INSTRUMENTS[symbol]
    as_of_date = as_of_date or date.today()
    candles_1min_full = None
    daily = None

    if day_candles_1min is None:
        candles_1min_full, day_candles_1min, prior_day_candles_1min, daily, prior_day_ohlc = _fetch_context(symbol, as_of_date)

    if day_candles_1min is None or day_candles_1min.empty:
        logger.warning("No intraday candles for %s on %s yet — skipping snapshot", symbol, as_of_date)
        return None

    option_summary = None
    option_chain = None
    if option_chain_override is not None:
        option_chain, option_summary = option_chain_override
    elif mode == "live":
        try:
            option_chain = get_option_chain(symbol)
            option_summary = summarize_option_chain(option_chain, meta["option_chain_atm_window"])
        except Exception as e:
            logger.warning("Option chain fetch failed for %s: %s", symbol, e)

    levels = compute_levels(
        symbol=symbol,
        day_candles_1min=day_candles_1min,
        instrument_meta=meta,
        prior_day_candles_1min=prior_day_candles_1min,
        prior_day_ohlc=prior_day_ohlc,
        option_summary=option_summary,
    )
    card = build_decision_card(levels)
    as_of = levels.as_of

    if candles_1min_full is not None:
        db_writer.insert_raw_candles(candles_1min_full, symbol)
    if daily is not None:
        db_writer.insert_daily_candles(daily, symbol)
    if option_chain is not None and persist_option_chain:
        db_writer.insert_option_chain(
            symbol=symbol,
            expiry=option_chain["expiry"],
            fetched_at=as_of,
            spot=option_chain.get("last_price"),
            raw_payload=option_chain,
            summary=option_summary,
        )

    db_writer.insert_levels_snapshot(levels, card, mode)

    if mode == "live":
        try:
            quant_live.write_live_quant_features(
                symbol,
                day_candles_1min,
                prior_day_candles_1min=prior_day_candles_1min,
                prior_day_ohlc=prior_day_ohlc,
                option_chain=option_chain,
                option_summary=option_summary,
            )
        except Exception:
            # Additive/informational only -- must never break the core
            # trading-decision snapshot above, same discipline every other
            # analytics add-on in this app follows (VIE, MTI, etc.).
            logger.exception("Quant feature store live write failed for %s", symbol)

    today_poc = levels.today_vp.poc if levels.today_vp else None
    should_render, trigger = should_render_chart(
        symbol=symbol,
        current_trend_label=levels.trend.label if levels.trend else None,
        current_poc=today_poc,
        now=as_of,
        mode=mode,
        bin_size=meta["volume_profile_bin_size"],
        force_chart=force_chart,
    )

    chart_path = None
    if should_render:
        overlays = build_overlays(levels)
        out_path = SNAPSHOT_ROOT / symbol / as_of.strftime("%Y-%m-%d") / as_of.strftime("%H%M") / "chart.png"
        render_chart(
            candles_5min=levels.candles_5min,
            vwap_5min=levels.vwap_5min,
            volume_profile=levels.today_vp,
            symbol=symbol,
            as_of=as_of,
            out_path=out_path,
            prior_day_poc=levels.yesterday_vp.poc if levels.yesterday_vp else None,
            overlays=overlays,
        )
        db_writer.record_chart(symbol, as_of, str(out_path), trigger)
        chart_path = str(out_path)

    card["chart_path"] = chart_path
    card["chart_triggered_by"] = trigger if should_render else None

    logger.info(
        "%s snapshot as_of=%s mode=%s confidence=%s chart=%s",
        symbol, as_of, mode, card.get("confidence"), chart_path or "-",
    )
    return card
