"""Append-only narrative of the session: every refusal, arm, disarm, kill and force-flat.

A day with no trades must be as explainable as a day with two -- that is this table's job.
"""

import json


def log(conn, session_date, event: str, detail: str = "", symbol: str | None = None,
        minute: str | None = None, payload: dict | None = None) -> None:
    conn.execute("""INSERT INTO live_journal (symbol, session_date, minute, event, detail, payload)
                    VALUES (%s, %s, %s, %s, %s, %s)""",
                 (symbol, session_date, minute, event, detail[:2000],
                  json.dumps(payload, default=str) if payload else None))


def recent(conn, session_date, limit: int = 200) -> list[dict]:
    cols = ("at", "symbol", "minute", "event", "detail")
    rows = conn.execute(f"""SELECT {', '.join(cols)} FROM live_journal WHERE session_date=%s
                            ORDER BY at DESC LIMIT %s""", (session_date, limit)).fetchall()
    return [dict(zip(cols, r)) for r in rows]
