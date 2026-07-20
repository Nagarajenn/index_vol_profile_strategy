import logging
import time
from datetime import datetime, timedelta

from config.instruments import INSTRUMENTS
from config.settings import IST, LIVE_LOOP_INTERVAL_MIN, SESSION_CLOSE, SESSION_OPEN
from pipeline.run_snapshot import run_snapshot
from pipeline.trading_calendar import is_trading_day

logger = logging.getLogger(__name__)

DATA_LAG_BUFFER_SEC = 15  # let Dhan finish publishing the candle before we fetch it


def _next_boundary(now: datetime, interval_min: int) -> datetime:
    minute = (now.minute // interval_min + 1) * interval_min
    base = now.replace(second=0, microsecond=0)
    if minute >= 60:
        return base.replace(minute=0) + timedelta(hours=1)
    return base.replace(minute=minute)


def _sleep_until(target: datetime) -> None:
    while True:
        remaining = (target - datetime.now(IST)).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 60))


def run_live_loop(
    symbols: list[str] | None = None,
    interval_min: int = LIVE_LOOP_INTERVAL_MIN,
    max_iterations: int | None = None,
) -> None:
    """Blocks forever (or until `max_iterations`), firing a live snapshot for
    every symbol on each `interval_min`-spaced wall-clock boundary during
    market hours (09:15-15:30 IST on trading days), and sleeping through
    nights/weekends/holidays and outside session hours in between.
    """
    symbols = symbols or list(INSTRUMENTS.keys())
    session_open_t = datetime.strptime(SESSION_OPEN, "%H:%M").time()
    session_close_t = datetime.strptime(SESSION_CLOSE, "%H:%M").time()

    iterations = 0
    while True:
        now = datetime.now(IST)
        today = now.date()

        if not is_trading_day(today):
            nxt = today + timedelta(days=1)
            while not is_trading_day(nxt):
                nxt += timedelta(days=1)
            target = datetime.combine(nxt, session_open_t, tzinfo=IST)
            logger.info("%s is not a trading day - sleeping until %s", today, target)
            _sleep_until(target)
            continue

        if now.time() < session_open_t:
            target = datetime.combine(today, session_open_t, tzinfo=IST)
            logger.info("Before market open - sleeping until %s", target)
            _sleep_until(target)
            continue

        if now.time() > session_close_t:
            nxt = today + timedelta(days=1)
            while not is_trading_day(nxt):
                nxt += timedelta(days=1)
            target = datetime.combine(nxt, session_open_t, tzinfo=IST)
            logger.info("After market close - sleeping until %s", target)
            _sleep_until(target)
            continue

        for symbol in symbols:
            try:
                run_snapshot(symbol, mode="live")  # logs its own summary line
            except Exception:
                logger.exception("Live snapshot failed for %s", symbol)

        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            return

        target = _next_boundary(datetime.now(IST), interval_min) + timedelta(seconds=DATA_LAG_BUFFER_SEC)
        _sleep_until(target)
