"""Fail-closed batched writer.

Rows are queued from the capture loop and flushed on a background thread.
Every failure is contained here: a database error drops the connection,
counts the rows, spills them to a local JSONL file and carries on. Nothing
from this module can raise into the capture loop, and nothing it does can
touch a non-hr table (see db.insert_sql).
"""

import json
import logging
import queue
import threading
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from hr_capture import db as hr_db
from hr_capture.config import HRConfig

logger = logging.getLogger(__name__)


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return str(value)


class HRWriter:
    def __init__(self, config: HRConfig, spill_dir: Path, session_id: str, enabled: bool = True,
                 connection_factory=None):
        self.config = config
        self.enabled = enabled
        self.session_id = str(session_id)
        self.spill_dir = spill_dir
        self._connection_factory = connection_factory or (lambda: hr_db.connect(config))
        self._conn = None
        self._queue: queue.Queue = queue.Queue(maxsize=config.max_queue_rows)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._next_connect_attempt = 0.0
        self.stats = {"queued": defaultdict(int), "written": defaultdict(int), "failed": defaultdict(int),
                      "spilled": defaultdict(int), "dropped_queue_full": 0, "db_errors": 0, "flushes": 0,
                      "last_error": None, "dry_run_rows": defaultdict(int)}

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self.enabled and self._thread is None:
            self._thread = threading.Thread(target=self._run, name="hr-writer", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        self._drain_and_flush()
        self._close()

    # ---------------------------------------------------------------- API

    def put(self, table: str, row: dict) -> None:
        if not self.enabled:
            self.stats["dry_run_rows"][table] += 1
            return
        try:
            self._queue.put_nowait((table, row))
            self.stats["queued"][table] += 1
        except queue.Full:
            self.stats["dropped_queue_full"] += 1

    def put_many(self, rows_by_table: dict[str, list[dict]]) -> None:
        for table, rows in rows_by_table.items():
            for row in rows:
                self.put(table, row)

    def execute_now(self, sql: str, params) -> bool:
        """Synchronous statement (session create/finalize). Never raises."""
        if not self.enabled:
            return True
        try:
            with self._lock:
                conn = self._connection()
                if conn is None:
                    return False
                with conn.cursor() as cur:
                    cur.execute(sql, params)
            return True
        except Exception as exc:
            self._record_error(exc)
            return False

    def insert_now(self, table: str, row: dict) -> bool:
        return self.execute_now(hr_db.insert_sql(table), hr_db.adapt_row(table, row))

    # ---------------------------------------------------------------- internals

    def _connection(self):
        if self._conn is not None and not self._conn.closed:
            return self._conn
        if time.monotonic() < self._next_connect_attempt:
            return None
        try:
            self._conn = self._connection_factory()
            return self._conn
        except Exception as exc:
            self._next_connect_attempt = time.monotonic() + 10.0
            self._record_error(exc)
            return None

    def _close(self) -> None:
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

    def _record_error(self, exc: Exception) -> None:
        self.stats["db_errors"] += 1
        self.stats["last_error"] = f"{type(exc).__name__}: {exc}"[:500]
        logger.warning("HR writer error (contained): %s", self.stats["last_error"])
        self._close()

    def _run(self) -> None:
        while not self._stop.wait(self.config.flush_interval_s):
            self._drain_and_flush()

    def _drain_and_flush(self) -> None:
        batches: dict[str, list[dict]] = defaultdict(list)
        while True:
            try:
                table, row = self._queue.get_nowait()
            except queue.Empty:
                break
            batches[table].append(row)
        if batches:
            self._flush(batches)

    def _flush(self, batches: dict[str, list[dict]]) -> None:
        self.stats["flushes"] += 1
        for table, rows in batches.items():
            for start in range(0, len(rows), self.config.max_rows_per_insert):
                chunk = rows[start: start + self.config.max_rows_per_insert]
                try:
                    with self._lock:
                        conn = self._connection()
                        if conn is None:
                            raise ConnectionError("HR database unavailable")
                        with conn.cursor() as cur:
                            cur.executemany(hr_db.insert_sql(table), [hr_db.adapt_row(table, r) for r in chunk])
                    self.stats["written"][table] += len(chunk)
                except Exception as exc:
                    self._record_error(exc)
                    self.stats["failed"][table] += len(chunk)
                    self._spill(table, chunk)

    def _spill(self, table: str, rows: list[dict]) -> None:
        try:
            self.spill_dir.mkdir(parents=True, exist_ok=True)
            path = self.spill_dir / f"{self.session_id}_spill_{table}.jsonl"
            with open(path, "a", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, default=_json_default) + "\n")
            self.stats["spilled"][table] += len(rows)
        except Exception as exc:
            self.stats["last_error"] = f"spill failed: {type(exc).__name__}: {exc}"[:500]

    def summary(self) -> dict:
        return {key: (dict(value) if isinstance(value, defaultdict) else value) for key, value in self.stats.items()}
