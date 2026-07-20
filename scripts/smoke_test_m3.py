"""M3 smoke test: render a real 5-min SENSEX chart with VWAP + volume profile + POC."""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics.resample import resample_series_last, resample_to_interval
from analytics.volume_profile import compute_volume_profile
from analytics.vwap import compute_vwap
from charting.chart_builder import render_chart
from config.instruments import INSTRUMENTS
from config.settings import PROJECT_ROOT
from dhan_client.client import fetch_intraday_candles


def main():
    symbol = "SENSEX"
    today = date.today()
    candles_1min = fetch_intraday_candles(symbol, today - timedelta(days=8), today, interval=1)
    last_day = candles_1min["timestamp"].dt.date.max()
    day_df = candles_1min[candles_1min["timestamp"].dt.date == last_day].reset_index(drop=True)

    prior_days = sorted(candles_1min["timestamp"].dt.date.unique())
    prior_day = prior_days[prior_days.index(last_day) - 1] if len(prior_days) > 1 else None
    prior_day_poc = None
    if prior_day is not None:
        prior_df = candles_1min[candles_1min["timestamp"].dt.date == prior_day]
        prior_vp = compute_volume_profile(prior_df, INSTRUMENTS[symbol]["volume_profile_bin_size"])
        prior_day_poc = prior_vp.poc if prior_vp else None

    vwap_1min = compute_vwap(day_df)
    vp = compute_volume_profile(day_df, INSTRUMENTS[symbol]["volume_profile_bin_size"])

    candles_5min = resample_to_interval(day_df, 5)
    vwap_5min = resample_series_last(vwap_1min, day_df["timestamp"], 5)

    out_path = PROJECT_ROOT / "logs" / "smoke_test_m3_chart.png"
    render_chart(
        candles_5min=candles_5min,
        vwap_5min=vwap_5min,
        volume_profile=vp,
        symbol=symbol,
        as_of=day_df["timestamp"].iloc[-1].to_pydatetime(),
        out_path=out_path,
        prior_day_poc=prior_day_poc,
    )
    print("Saved chart to", out_path)
    print("POC:", vp.poc, "VAH:", vp.vah, "VAL:", vp.val, "prior_day_poc:", prior_day_poc)


if __name__ == "__main__":
    main()
