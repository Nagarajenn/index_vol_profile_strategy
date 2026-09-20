"""Read-only data layer for Opportunity Matrix v1.

The connection is opened with default_transaction_read_only=on, so the database
itself rejects any write. Nothing here writes anywhere.

DayData holds one symbol-day. Every per-bar list is aligned to `times` (5-second
bar START; values are known at bar close = start + 5 s). ``truncate(T)`` returns a
copy containing only information observable at or before T; the leakage tests use
it to prove that features computed at T are identical with and without the future.
"""

import copy
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import pandas as pd
import psycopg

from config.settings import DB_SCHEMA, IST, require_database_url

BAR = timedelta(seconds=5)


def connect() -> psycopg.Connection:
    opts = f"-c search_path={DB_SCHEMA},public -c statement_timeout=300000 -c default_transaction_read_only=on"
    return psycopg.connect(require_database_url(), autocommit=True, application_name="om1_research", options=opts)


@dataclass
class DayData:
    symbol: str
    trade_date: date
    expiry: date | None
    strike_step: float
    band_atm: float
    universe_resolved_at: str | None
    times: list[datetime]                    # 5-s bar starts (HR window)
    fut_bid: list
    fut_ask: list
    fut_mid: list
    fut_last: list
    fut_trades: list
    fut_status: list
    idx_close: list
    und_status: list
    last_reliable_px: list
    last_reliable_ts: list
    legs: dict                               # (type, offset) -> {"strike", "security_id"}
    opt: dict                                # (type, offset) -> list[dict | None]
    trans: list                              # per bar: pcr, straddle, implied spot ...
    candles: pd.DataFrame                    # 1-min index candles for the day (timestamp = minute start)
    chain: list                              # [(fetched_at, spot, payload_oc)] 1-min option-chain snapshots
    daily_close: float | None = None         # OUTCOME only (official close)
    news: list = field(default_factory=list) # [(classified_at, severity)] ; empty + feed_active False -> UNKNOWN
    news_feed_active: bool = False

    @property
    def is_expiry(self) -> bool:
        return self.expiry is not None and self.expiry == self.trade_date

    def __len__(self):
        return len(self.times)

    def known_at(self, i: int) -> datetime:
        return self.times[i] + BAR

    def index_at(self, ts: datetime) -> int:
        """Last 5-s bar whose close is <= ts (-1 if none)."""
        k = -1
        for i, t in enumerate(self.times):
            if t + BAR <= ts:
                k = i
            else:
                break
        return k

    def truncate(self, ts: datetime) -> "DayData":
        """Copy containing only information observable at or before ts."""
        k = self.index_at(ts) + 1
        d = copy.copy(self)
        for name in ("times", "fut_bid", "fut_ask", "fut_mid", "fut_last", "fut_trades", "fut_status", "idx_close",
                     "und_status", "last_reliable_px", "last_reliable_ts", "trans"):
            setattr(d, name, list(getattr(self, name))[:k])
        d.opt = {key: list(v)[:k] for key, v in self.opt.items()}
        # a 1-min candle is known at its minute END
        d.candles = self.candles[self.candles["timestamp"] + timedelta(minutes=1) <= ts].copy()
        d.chain = [c for c in self.chain if c[0] <= ts]
        d.news = [n for n in self.news if n[0] <= ts]
        d.daily_close = None
        return d


def _f(x):
    return float(x) if x is not None else None


def hr_sessions(conn) -> list[tuple[date, str]]:
    return [(r[0], r[1]) for r in conn.execute(
        "SELECT trading_date, session_id FROM hr_capture_sessions WHERE status IN ('COMPLETED','COMPLETED_WITH_GAPS') "
        "ORDER BY trading_date").fetchall()]


def load_day(conn, session_id: str, d: date, symbol: str) -> DayData | None:
    cfg_row = conn.execute("SELECT config FROM hr_capture_sessions WHERE session_id=%s", (session_id,)).fetchone()
    uni = (cfg_row[0] or {}).get("universe", {}).get(symbol) if cfg_row else None
    hrc = (cfg_row[0] or {}).get("hr", {}) if cfg_row else {}
    if not uni:
        return None
    start = datetime.combine(d, time(14, 55), tzinfo=IST)
    times = [start + BAR * k for k in range(420)]
    pos = {t: k for k, t in enumerate(times)}
    n = len(times)
    fut_bid, fut_ask, fut_mid, fut_status = [None] * n, [None] * n, [None] * n, [None] * n
    und_status, lr_px, lr_ts = [None] * n, [None] * n, [None] * n
    trans = [None] * n
    for (ts, fb, fa, fs, us, lp, lt, pcr, pcrv, straddle, isp, iqr, isn, isq, ce_vd, pe_vd, ce_oid, pe_oid) in conn.execute(
            "SELECT bar_ts, futures_bid, futures_ask, futures_status, underlying_status, last_reliable_underlying_price, "
            "last_reliable_underlying_ts, pcr_oi, pcr_volume, straddle_mid, option_implied_spot_research_only, implied_spot_iqr, "
            "implied_spot_n, implied_spot_quality, ce_volume_delta_sum, pe_volume_delta_sum, ce_oi_delta_sum, pe_oi_delta_sum "
            "FROM hr_option_transition_state WHERE session_id=%s AND symbol=%s", (session_id, symbol)).fetchall():
        k = pos.get(ts.astimezone(IST))
        if k is None:
            continue
        fut_bid[k], fut_ask[k] = _f(fb), _f(fa)
        fut_mid[k] = (fut_bid[k] + fut_ask[k]) / 2 if fut_bid[k] and fut_ask[k] else None
        fut_status[k], und_status[k], lr_px[k], lr_ts[k] = fs, us, _f(lp), lt
        trans[k] = dict(pcr_oi=_f(pcr), pcr_volume=_f(pcrv), straddle=_f(straddle), implied_spot=_f(isp), implied_iqr=_f(iqr),
                        implied_n=isn, implied_quality=isq, ce_volume=_f(ce_vd), pe_volume=_f(pe_vd), ce_oi_delta=_f(ce_oid),
                        pe_oi_delta=_f(pe_oid))
    fut_last, fut_trades, idx_close = [None] * n, [None] * n, [None] * n
    for itype, ts, close, trades in conn.execute(
            "SELECT instrument_type, bar_ts, close, trade_count FROM hr_ohlc_5s WHERE session_id=%s AND symbol=%s "
            "AND instrument_type IN ('FUTIDX','INDEX')", (session_id, symbol)).fetchall():
        k = pos.get(ts.astimezone(IST))
        if k is None:
            continue
        if itype == "FUTIDX":
            fut_last[k], fut_trades[k] = _f(close), trades
        else:
            idx_close[k] = _f(close)
    legs = {}
    for ot, off, strike, sid in conn.execute(
            "SELECT option_type, atm_offset, strike, security_id FROM hr_instruments WHERE session_id=%s AND symbol=%s "
            "AND instrument_type='OPTIDX'", (session_id, symbol)).fetchall():
        legs[(ot, int(off))] = dict(strike=float(strike), security_id=sid)
    opt = {k: [None] * n for k in legs}
    for ot, off, ts, bid, ask, mid, sp, age, vd, cv, oi, oid, di, dq in conn.execute(
            "SELECT option_type, atm_offset, bar_ts, bid, ask, mid, spread_pct, quote_age_s, volume_delta, cumulative_volume, oi, "
            "oi_delta, depth_imbalance, data_quality FROM hr_option_5s WHERE session_id=%s AND symbol=%s", (session_id, symbol)).fetchall():
        k = pos.get(ts.astimezone(IST))
        key = (ot, int(off))
        if k is None or key not in opt:
            continue
        opt[key][k] = dict(bid=_f(bid), ask=_f(ask), mid=_f(mid), spread_pct=_f(sp), quote_age=_f(age), volume=_f(vd),
                           cum_volume=_f(cv), oi=_f(oi), oi_delta=_f(oid), depth_imb=_f(di), quality=dq)
    candles = load_candles(conn, symbol, d, d)
    chain = [(ts, _f(spot), (p or {}).get("oc", {})) for ts, spot, p in conn.execute(
        "SELECT fetched_at, spot, raw_payload FROM option_chain_raw WHERE symbol=%s AND fetched_at::date=%s "
        "AND fetched_at::time BETWEEN '14:15' AND '15:31' ORDER BY fetched_at", (symbol, d)).fetchall()]
    dc = conn.execute("SELECT close FROM raw_daily_candles WHERE symbol=%s AND date=%s", (symbol, d)).fetchone()
    feed = conn.execute("SELECT count(*) FROM classified_events WHERE classified_at::date=%s", (d,)).fetchone()[0]
    news = [(r[0], r[1]) for r in conn.execute(
        "SELECT classified_at, severity FROM classified_events WHERE classified_at::date=%s AND is_relevant", (d,)).fetchall()]
    return DayData(symbol=symbol, trade_date=d, expiry=date.fromisoformat(uni["expiry"]) if uni.get("expiry") else None,
                   strike_step=float(uni["strike_step"]), band_atm=float(uni["band_atm_strike"]),
                   universe_resolved_at=hrc.get("resolve_at"), times=times, fut_bid=fut_bid, fut_ask=fut_ask, fut_mid=fut_mid,
                   fut_last=fut_last, fut_trades=fut_trades, fut_status=fut_status, idx_close=idx_close, und_status=und_status,
                   last_reliable_px=lr_px, last_reliable_ts=lr_ts, legs=legs, opt=opt, trans=trans, candles=candles, chain=chain,
                   daily_close=_f(dc[0]) if dc else None, news=news, news_feed_active=feed > 0)


def load_candles(conn, symbol: str, d0: date, d1: date) -> pd.DataFrame:
    rows = conn.execute("SELECT timestamp, open, high, low, close, volume FROM raw_candles WHERE symbol=%s "
                        "AND timestamp::date BETWEEN %s AND %s ORDER BY timestamp", (symbol, d0, d1)).fetchall()
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_convert(IST)
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = df[c].astype(float)
    return df


def prior_trading_days(conn, symbol: str, d: date, n: int) -> list[date]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT timestamp::date FROM raw_candles WHERE symbol=%s AND timestamp::date < %s ORDER BY 1 DESC LIMIT %s",
        (symbol, d, n)).fetchall()][::-1]
