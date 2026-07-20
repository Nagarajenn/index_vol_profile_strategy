"""M5 smoke test: full levels + option chain + decision card, real data."""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analytics.levels import compute_levels
from config.instruments import INSTRUMENTS
from decision.decision_card import build_decision_card, format_decision_text
from dhan_client.client import fetch_daily_candles, fetch_intraday_candles
from option_chain.fetch import get_option_chain
from option_chain.summary import summarize_option_chain


def main():
    symbol = "SENSEX"
    meta = INSTRUMENTS[symbol]
    today = date.today()

    candles_1min = fetch_intraday_candles(symbol, today - timedelta(days=8), today, interval=1)
    last_day = candles_1min["timestamp"].dt.date.max()
    day_df = candles_1min[candles_1min["timestamp"].dt.date == last_day].reset_index(drop=True)

    prior_days = sorted(candles_1min["timestamp"].dt.date.unique())
    prior_day_df = None
    if len(prior_days) > 1:
        prior_day = prior_days[prior_days.index(last_day) - 1]
        prior_day_df = candles_1min[candles_1min["timestamp"].dt.date == prior_day]

    daily = fetch_daily_candles(symbol, today - timedelta(days=10), today)
    prior_daily_rows = daily[daily["timestamp"].dt.date < last_day]
    prior_day_ohlc = None
    if len(prior_daily_rows):
        row = prior_daily_rows.iloc[-1]
        prior_day_ohlc = {"high": row["high"], "low": row["low"], "close": row["close"]}

    option_summary = None
    try:
        chain = get_option_chain(symbol)
        option_summary = summarize_option_chain(chain, meta["option_chain_atm_window"])
        print("Option chain expiry:", chain["expiry"], "spot:", chain.get("last_price"))
    except Exception as e:
        print("Option chain fetch failed (market may be closed):", e)

    levels = compute_levels(
        symbol=symbol,
        day_candles_1min=day_df,
        instrument_meta=meta,
        prior_day_candles_1min=prior_day_df,
        prior_day_ohlc=prior_day_ohlc,
        option_summary=option_summary,
    )

    card = build_decision_card(levels)
    print()
    print(format_decision_text(card))
    print()
    print("confidence sub_scores:", card["confidence_sub_scores"])
    print("weights_used:", card["confidence_weights_used"])
    print("institutional_bias_data:", card["institutional_bias_data"])


if __name__ == "__main__":
    main()
