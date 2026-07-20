import logging

import psycopg
from psycopg import sql

from config.settings import DB_SCHEMA, require_database_url

logger = logging.getLogger(__name__)

_conn: psycopg.Connection | None = None


def _connect() -> psycopg.Connection:
    conn = psycopg.connect(
        require_database_url(),
        autocommit=True,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3,
    )
    if DB_SCHEMA != "public":
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(DB_SCHEMA)))
    return conn


def get_connection() -> psycopg.Connection:
    """Single lazily-created connection, no pool -- this is one sequential
    writer process (the live loop / backfill / migration script), not a
    concurrent web service, so pooling would solve a problem we don't have.
    """
    global _conn
    if _conn is None or _conn.closed:
        _conn = _connect()
    return _conn


def _drop_connection() -> None:
    global _conn
    _conn = None


def execute(sql: str, params=None) -> None:
    """Run one statement, reconnecting and retrying once on a dropped
    connection -- a 6+ hour live session with one write/minute needs to
    survive a transient network blip without the whole loop dying.
    """
    for attempt in (1, 2):
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute(sql, params)
            return
        except psycopg.OperationalError:
            logger.warning("DB connection lost, reconnecting (attempt %d)", attempt)
            _drop_connection()
            if attempt == 2:
                raise


def executemany(sql: str, params_seq) -> None:
    for attempt in (1, 2):
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.executemany(sql, params_seq)
            return
        except psycopg.OperationalError:
            logger.warning("DB connection lost, reconnecting (attempt %d)", attempt)
            _drop_connection()
            if attempt == 2:
                raise


def fetch_one(sql: str, params=None):
    for attempt in (1, 2):
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()
        except psycopg.OperationalError:
            logger.warning("DB connection lost, reconnecting (attempt %d)", attempt)
            _drop_connection()
            if attempt == 2:
                raise


def fetch_all(sql: str, params=None):
    for attempt in (1, 2):
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        except psycopg.OperationalError:
            logger.warning("DB connection lost, reconnecting (attempt %d)", attempt)
            _drop_connection()
            if attempt == 2:
                raise
