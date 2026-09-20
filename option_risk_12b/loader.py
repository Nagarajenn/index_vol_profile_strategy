"""Read-only data access for 12B research. SELECT-only on a connection opened with
default_transaction_read_only=on, so the database itself rejects any write."""

from datetime import date

import psycopg

from config.settings import DB_SCHEMA, IST, require_database_url


def connect() -> psycopg.Connection:
    opts = f"-c search_path={DB_SCHEMA},public -c statement_timeout=300000 -c default_transaction_read_only=on"
    return psycopg.connect(require_database_url(), autocommit=True, application_name="12b_option_risk_research", options=opts)


def session_dates(conn) -> list[tuple[str, date]]:
    q = """select distinct symbol, (fetched_at at time zone 'Asia/Kolkata')::date from option_chain_raw order by 2, 1"""
    return conn.execute(q).fetchall()


def load_snapshots(conn, symbol: str, d: date, start="14:55", end="15:40") -> list[dict]:
    q = """select fetched_at, spot, expiry, raw_payload from option_chain_raw
           where symbol=%s and (fetched_at at time zone 'Asia/Kolkata')::date=%s
             and (fetched_at at time zone 'Asia/Kolkata')::time >= %s and (fetched_at at time zone 'Asia/Kolkata')::time < %s
           order by fetched_at"""
    rows = conn.execute(q, (symbol, d, start, f"{end}:59")).fetchall()
    return [dict(fetched_at=r[0].astimezone(IST), spot=r[1], expiry=r[2], payload=r[3]) for r in rows]


def load_candles(conn, symbol: str, d: date, start="14:50", end="15:40") -> list[dict]:
    q = """select timestamp, open, high, low, close, volume from raw_candles
           where symbol=%s and (timestamp at time zone 'Asia/Kolkata')::date=%s
             and (timestamp at time zone 'Asia/Kolkata')::time between %s and %s order by timestamp"""
    rows = conn.execute(q, (symbol, d, start, end)).fetchall()
    return [dict(timestamp=r[0].astimezone(IST), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in rows]


def load_daily_close(conn, symbol: str, d: date):
    r = conn.execute("select close from raw_daily_candles where symbol=%s and date=%s", (symbol, d)).fetchone()
    return r[0] if r else None


def load_paper_positions(conn) -> list[dict]:
    q = """select id, symbol, session_date, option_type, strike, entry_timestamp, exit_timestamp, entry_spread_pct, is_open
           from paper_positions order by entry_timestamp"""
    return [dict(id=r[0], symbol=r[1], session_date=r[2], option_type=r[3], strike=r[4],
                 entry_minute=r[5].astimezone(IST).strftime("%H:%M"),
                 exit_minute=r[6].astimezone(IST).strftime("%H:%M") if r[6] else None,
                 entry_spread_pct=r[7], is_open=r[8], label=f"PAPER #{r[0]} BUY {r[1]} {r[3]} {r[4]:g}")
            for r in conn.execute(q).fetchall()]
