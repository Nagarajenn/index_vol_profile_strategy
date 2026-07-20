"""M1 smoke test: resolve SENSEX/NIFTY security IDs and fetch a few real candles.

Run: venv\\Scripts\\python.exe scripts\\smoke_test_m1.py
Requires a filled-in .env (see .env.example).
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dhan_client.client import fetch_daily_candles, fetch_expiry_list, fetch_intraday_candles
from dhan_client.scrip_master import resolve_instrument


def main():
    for symbol in ("SENSEX", "NIFTY"):
        print(f"\n=== {symbol} ===")
        instr = resolve_instrument(symbol)
        print("Resolved:", instr)

        today = date.today()
        daily = fetch_daily_candles(symbol, today - timedelta(days=10), today)
        print(f"Daily candles: {len(daily)} rows")
        print(daily.tail(3).to_string())

        intraday = fetch_intraday_candles(symbol, today - timedelta(days=5), today, interval=5)
        print(f"5-min intraday candles: {len(intraday)} rows")
        print(intraday.tail(3).to_string())

        try:
            expiries = fetch_expiry_list(symbol)
            print(f"Expiries: {expiries[:5]}")
        except Exception as e:
            print(f"Expiry list fetch failed: {e}")


if __name__ == "__main__":
    main()
