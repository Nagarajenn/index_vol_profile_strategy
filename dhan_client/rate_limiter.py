import threading
import time


class MinIntervalLimiter:
    """Blocks until at least `min_interval_sec` has passed since the last call.

    Dhan's Option Chain API is rate-limited to 1 request / 3 seconds; this
    guards any code path that calls it so we never trip that limit.
    """

    def __init__(self, min_interval_sec: float):
        self._min_interval = min_interval_sec
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            remaining = self._min_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
            self._last_call = time.monotonic()


option_chain_limiter = MinIntervalLimiter(min_interval_sec=3.0)
