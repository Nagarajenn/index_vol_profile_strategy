"""Synthetic symbol-days for Opportunity Matrix v1 tests (no DB, no network)."""

from datetime import date, datetime, time, timedelta

import pandas as pd

from config.settings import IST
from opportunity_matrix_v1.loader import DayData

STEP = 50.0
ATM = 23400.0


def make_day(d=date(2026, 9, 17), fut_path=None, expiry=None, symbol="NIFTY", und_frozen_from=None, implied_path=None, spread_pct=0.3):
    n = 420
    start = datetime.combine(d, time(14, 55), tzinfo=IST)
    times = [start + timedelta(seconds=5 * k) for k in range(n)]
    fut = list(fut_path) if fut_path is not None else [ATM + ((k % 7) - 3) * 0.8 for k in range(n)]
    fut = (fut + [fut[-1]] * n)[:n]
    legs, opt = {}, {}
    for typ in ("CE", "PE"):
        for off in range(-5, 6):
            strike = ATM + off * STEP
            legs[(typ, off)] = dict(strike=strike, security_id=1000 + off)
            m = off if typ == "CE" else -off
            delta = max(0.1, min(0.9, 0.5 - 0.12 * m))
            base = max(25.0, 100.0 - 30.0 * m)
            s = []
            for k, f in enumerate(fut):
                mv = (f - fut[0]) if typ == "CE" else (fut[0] - f)
                mid = max(1.0, base + delta * mv)
                h = mid * spread_pct / 200
                s.append(dict(bid=round(mid - h, 2), ask=round(mid + h, 2), mid=mid, spread_pct=spread_pct, quote_age=1.0, volume=100.0,
                              cum_volume=1000.0 + k, oi=5000.0, oi_delta=0.0, depth_imb=0.0, quality="OK"))
            opt[(typ, off)] = s
    frozen_i = None if und_frozen_from is None else next(k for k, t in enumerate(times) if t.time() >= und_frozen_from)
    und = ["VALID" if (frozen_i is None or k < frozen_i) else "FROZEN" for k in range(n)]
    idx = [fut[k] - 20 if und[k] == "VALID" else fut[frozen_i - 1] - 20 for k in range(n)]
    lr_px = [idx[k] if und[k] == "VALID" else idx[frozen_i - 1] for k in range(n)]
    lr_ts = [times[k] if und[k] == "VALID" else times[frozen_i - 1] for k in range(n)]
    imp = list(implied_path) if implied_path is not None else [f - 20 for f in fut]
    trans = [dict(pcr_oi=1.0, pcr_volume=1.0, straddle=200.0, implied_spot=imp[k], implied_iqr=1.0, implied_n=8, implied_quality="OK",
                  ce_volume=100.0, pe_volume=100.0, ce_oi_delta=0.0, pe_oi_delta=0.0) for k in range(n)]
    cstart = datetime.combine(d, time(9, 15), tzinfo=IST)
    rows = []
    for m in range(375):
        ts = cstart + timedelta(minutes=m)
        p = ATM - 20 + 3.0 * ((m % 11) - 5) + 0.05 * m
        rows.append(dict(timestamp=ts, open=p, high=p + 4, low=p - 4, close=p + 1, volume=1000.0 + (m % 13) * 50))
    candles = pd.DataFrame(rows)
    chain = []
    for m in range(0, 80):
        ts = datetime.combine(d, time(14, 15), tzinfo=IST) + timedelta(minutes=m, seconds=20)
        oc = {}
        for off in range(-7, 8):
            k = ATM + off * STEP
            oc[f"{k:.6f}"] = {t: dict(top_bid_price=99.5 - off * 5 * (1 if t == "ce" else -1) + m * 0.1, top_ask_price=100.5 - off * 5 * (1 if t == "ce" else -1) + m * 0.1,
                                      implied_volatility=12.0 + m * 0.01, oi=4000 + m * 10, volume=10000 + m * 100,
                                      greeks=dict(delta=0.5, gamma=0.001, theta=-3.0, vega=2.0)) for t in ("ce", "pe")}
        chain.append((ts, ATM - 20 + m * 0.05, oc))
    return DayData(symbol=symbol, trade_date=d, expiry=expiry or date(2026, 9, 22), strike_step=STEP, band_atm=ATM, universe_resolved_at="14:54:00",
                   times=times, fut_bid=[f - 0.5 for f in fut], fut_ask=[f + 0.5 for f in fut], fut_mid=fut, fut_last=fut, fut_trades=[3] * n,
                   fut_status=["VALID"] * n, idx_close=idx, und_status=und, last_reliable_px=lr_px, last_reliable_ts=lr_ts, legs=legs, opt=opt,
                   trans=trans, candles=candles, chain=chain, daily_close=ATM, news=[], news_feed_active=False)


def burst_path(start_bar=90, step=3.0, bars=4, base=ATM):
    """Quiet noise, then a clean up-burst of `bars` x `step` points at bar start_bar (15:02:30 for 90)."""
    p = [base + ((k % 5) - 2) * 0.3 for k in range(420)]
    for k in range(start_bar, 420):
        p[k] = p[k] + step * min(bars, k - start_bar + 1)
    return p
