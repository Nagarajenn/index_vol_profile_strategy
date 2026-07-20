from datetime import date

import pandas as pd

from db.reader import load_levels_for_backtest


def load_snapshots(symbol: str, start_date: date | None = None, end_date: date | None = None) -> pd.DataFrame:
    """Load snapshots for backtesting from Postgres (levels_snapshots)."""
    return load_levels_for_backtest(symbol, start_date=start_date, end_date=end_date)
