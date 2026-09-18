"""Append-only raw packet recording (crash-safe forensic copy + replay input).

File format: repeated records of struct "<QI" (receive_ns, length) followed
by the exact WebSocket message bytes. A JSON sidecar holds the session's
instrument universe and configuration so a recording is self-describing.
Only messages received inside the capture window are recorded.
"""

import json
import struct
from pathlib import Path

RECORD_HEADER = struct.Struct("<QI")


class PacketRecorder:
    def __init__(self, path: Path, flush_every: int = 500):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh = open(path, "ab")
        self._flush_every = flush_every
        self.records = 0
        self.bytes_written = 0
        self.errors = 0

    def append(self, receive_ns: int, data: bytes) -> None:
        try:
            blob = RECORD_HEADER.pack(int(receive_ns), len(data)) + bytes(data)
            self._fh.write(blob)
            self.records += 1
            self.bytes_written += len(blob)
            if self.records % self._flush_every == 0:
                self._fh.flush()
        except Exception:
            self.errors += 1

    def close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:
            self.errors += 1


def write_sidecar(path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")


def read_recording(path: Path):
    """Yields (receive_ns, bytes). Stops cleanly at a truncated tail record."""
    with open(path, "rb") as fh:
        while True:
            header = fh.read(RECORD_HEADER.size)
            if len(header) < RECORD_HEADER.size:
                return
            receive_ns, length = RECORD_HEADER.unpack(header)
            data = fh.read(length)
            if len(data) < length:
                return
            yield receive_ns, data
