"""Read-only helpers for offline 12C use (validation / CLI). The live path uses the
backend repositories instead. Connection is 12B's read-only connection."""

from datetime import date

from option_risk_12b.loader import connect, load_candles, load_daily_close, load_paper_positions, load_snapshots, session_dates

LEVELS_COLUMNS = ("close", "vwap_now", "today_poc", "today_vah", "today_val", "support_low", "support_high",
                  "resistance_low", "resistance_high", "trend_label")


def load_levels(conn, symbol: str, d: date, at_or_before: str | None = None) -> dict | None:
    q = f"""select {', '.join(LEVELS_COLUMNS)}, to_char(as_of at time zone 'Asia/Kolkata','HH24:MI') as_of
            from levels_snapshots where symbol=%s and (as_of at time zone 'Asia/Kolkata')::date=%s
              and (as_of at time zone 'Asia/Kolkata')::time <= %s::time
            order by as_of desc limit 1"""
    r = conn.execute(q, (symbol, d, at_or_before or "23:59")).fetchone()
    return dict(zip(list(LEVELS_COLUMNS) + ["as_of"], r)) if r else None
