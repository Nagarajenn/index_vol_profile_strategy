"""M4 smoke test: render a real 5-min SENSEX chart with all M4 overlays."""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics.breakout_boxes import detect_breakout_boxes
from analytics.resample import resample_series_last, resample_to_interval
from analytics.support_resistance import build_candidates, cluster_zones, nearest_support_resistance
from analytics.swings import detect_swings
from analytics.trendlines import fit_trendlines
from analytics.volume_profile import compute_volume_profile
from analytics.vwap import compute_vwap
from charting.chart_builder import render_chart
from config.instruments import INSTRUMENTS
from config.settings import PROJECT_ROOT
from dhan_client.client import fetch_daily_candles, fetch_intraday_candles


def main():
    symbol = "SENSEX"
    meta = INSTRUMENTS[symbol]
    today = date.today()

    candles_1min = fetch_intraday_candles(symbol, today - timedelta(days=8), today, interval=1)
    last_day = candles_1min["timestamp"].dt.date.max()
    day_df = candles_1min[candles_1min["timestamp"].dt.date == last_day].reset_index(drop=True)

    prior_days = sorted(candles_1min["timestamp"].dt.date.unique())
    prior_day = prior_days[prior_days.index(last_day) - 1] if len(prior_days) > 1 else None
    yesterday_vp = None
    if prior_day is not None:
        prior_df = candles_1min[candles_1min["timestamp"].dt.date == prior_day]
        yesterday_vp = compute_volume_profile(prior_df, meta["volume_profile_bin_size"])

    daily = fetch_daily_candles(symbol, today - timedelta(days=10), today)
    prior_daily = daily[daily["timestamp"].dt.date < last_day].iloc[-1] if len(daily) else None

    vwap_1min = compute_vwap(day_df)
    today_vp = compute_volume_profile(day_df, meta["volume_profile_bin_size"])
    candles_5min = resample_to_interval(day_df, 5)
    vwap_5min = resample_series_last(vwap_1min, day_df["timestamp"], 5)

    swings = detect_swings(candles_5min)
    trendlines = fit_trendlines(swings, candles_5min)
    boxes = detect_breakout_boxes(candles_5min)

    current_price = candles_5min["close"].iloc[-1]
    confirmed_swings = [s for s in swings if s.confirmed]
    candidates = build_candidates(
        current_price=current_price,
        round_number_step=meta["round_number_step"],
        prior_day_high=prior_daily["high"] if prior_daily is not None else None,
        prior_day_low=prior_daily["low"] if prior_daily is not None else None,
        prior_day_close=prior_daily["close"] if prior_daily is not None else None,
        today_vp=today_vp,
        yesterday_vp=yesterday_vp,
        confirmed_swings=confirmed_swings,
    )
    zones = cluster_zones(candidates, meta["sr_cluster_tolerance_pct"])
    support, resistance = nearest_support_resistance(zones, current_price)

    overlays = {
        "swing_highs": [(s.timestamp, s.price) for s in swings if s.kind == "high"],
        "swing_lows": [(s.timestamp, s.price) for s in swings if s.kind == "low"],
        "trendlines": [{"points": t.points, "direction": t.direction} for t in trendlines],
        "sr_zones": (
            ([{"low": support.low, "high": support.high, "kind": "support"}] if support else [])
            + ([{"low": resistance.low, "high": resistance.high, "kind": "resistance"}] if resistance else [])
        ),
        "breakout_boxes": [
            {"t_start": b.t_start, "t_end": b.t_end, "p_low": b.p_low, "p_high": b.p_high, "status": b.status}
            for b in boxes
        ],
    }

    out_path = PROJECT_ROOT / "logs" / "smoke_test_m4_chart.png"
    render_chart(
        candles_5min=candles_5min,
        vwap_5min=vwap_5min,
        volume_profile=today_vp,
        symbol=symbol,
        as_of=day_df["timestamp"].iloc[-1].to_pydatetime(),
        out_path=out_path,
        prior_day_poc=yesterday_vp.poc if yesterday_vp else None,
        overlays=overlays,
    )
    print("Saved chart to", out_path)
    print("current price:", current_price)
    print("swings:", [(s.kind, s.price, s.confirmed) for s in swings])
    print("trendlines:", [(t.direction, t.r2, t.touch_count) for t in trendlines])
    print("breakout boxes:", [(b.status, b.p_low, b.p_high) for b in boxes])
    print("support:", support, "resistance:", resistance)


if __name__ == "__main__":
    main()
