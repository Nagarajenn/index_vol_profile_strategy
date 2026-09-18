"""Synthetic 5-second sessions for 12A tests (no DB, no network)."""

from datetime import date, datetime, timedelta

from config.settings import IST
from scalp_12a.models import Leg, Quote, SessionBars, Thresholds

DAY = date(2026, 9, 21)
STEP = 50.0
ATM = 23400.0


def times_from(start="14:55:00", n=420, day=DAY):
    t0 = datetime.combine(day, datetime.strptime(start, "%H:%M:%S").time(), tzinfo=IST)
    return [t0 + timedelta(seconds=5 * i) for i in range(n)]


def make_session(fut_path, start="14:55:00", day=DAY, expiry=None, spread_pct=0.3, volume=100.0,
                 option_fn=None, symbol="NIFTY", offsets=range(-5, 6)):
    """Options priced off the futures path: CE mid = base + delta*(f - f0), PE mirrored.

    ``option_fn(key, i, f, default_quote)`` can override any quote (return None for missing).
    """
    n = len(fut_path)
    times = times_from(start, n, day)
    f0 = fut_path[0]
    legs, quotes = {}, {}
    for typ in ("CE", "PE"):
        for off in offsets:
            strike = ATM + off * STEP
            legs[(typ, off)] = Leg(typ, off, strike, 1000 + off + (0 if typ == "CE" else 100))
            m = off if typ == "CE" else -off               # +OTM / -ITM
            delta = max(0.1, min(0.9, 0.5 - 0.12 * m))
            base = max(25.0, 100.0 - 30.0 * m)
            series = []
            for i, f in enumerate(fut_path):
                move = (f - f0) if typ == "CE" else (f0 - f)
                mid = max(1.0, base + delta * move)
                half = mid * spread_pct / 200.0
                q = Quote(round(mid - half, 2), round(mid + half, 2), mid, spread_pct, 1.0, volume, 0.0)
                if option_fn is not None:
                    q = option_fn((typ, off), i, f, q)
                series.append(q)
            quotes[(typ, off)] = series
    return SessionBars(symbol, day, expiry, ATM, STEP, times, list(fut_path), [True] * n, [None] * n, legs, quotes)


def thresholds(thr30=10.0, weak=7.0, thr180=25.0):
    return Thresholds(thr30, weak, thr180, ("2026-09-17", "2026-09-18"), True)


def flat_then(n_flat, moves, level=23400.0, n_after=60):
    """Flat futures for n_flat bars, then per-bar increments ``moves``, then flat."""
    path = [level] * n_flat
    for m in moves:
        path.append(path[-1] + m)
    path += [path[-1]] * n_after
    return path
