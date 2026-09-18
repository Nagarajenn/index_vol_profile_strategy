"""Replay a recorded HR session through the same parser and aggregators.

Reads data/cache/hr_capture/<date>_<session>.bin plus its .meta.json sidecar
and re-derives the 5-second tables deterministically. By default it only
prints a summary and writes NOTHING (live rows for the same bars already
own the unique keys, so replaying into the database is never the default).

Usage:
    venv\\Scripts\\python.exe scripts\\run_hr_replay.py data\\cache\\hr_capture\\20260915_<session>.bin
"""

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hr_capture.config import DEFAULT_HR_CONFIG
from hr_capture.recorder import read_recording
from hr_capture.service import MODE_REPLAY, CaptureSession
from hr_capture.universe import HRInstrument, ResolvedUniverse


class CountingWriter:
    def __init__(self):
        self.rows = Counter()
        self.samples: dict[str, dict] = {}

    def put(self, table, row):
        self.rows[table] += 1
        self.samples.setdefault(table, row)

    def put_many(self, rows_by_table):
        for table, rows in rows_by_table.items():
            for row in rows:
                self.put(table, row)

    def summary(self):
        return {"rows": dict(self.rows)}


def load_universes(meta: dict) -> dict:
    universes = {}
    for symbol, u in meta["universes"].items():
        instruments = []
        for d in u["instruments"]:
            d = dict(d)
            d["expiry"] = date.fromisoformat(d["expiry"]) if d.get("expiry") else None
            instruments.append(HRInstrument(**d))
        universes[symbol] = ResolvedUniverse(symbol, instruments, u["band_atm_strike"], u["reference_spot"],
                                             date.fromisoformat(u["expiry"]) if u.get("expiry") else None,
                                             u["strike_step"], u.get("issues", []))
    return universes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("recording", type=Path)
    args = parser.parse_args()
    meta = json.loads(args.recording.with_suffix(".meta.json").read_text(encoding="utf-8"))
    universes = load_universes(meta)
    writer = CountingWriter()
    session = CaptureSession(DEFAULT_HR_CONFIG, date.fromisoformat(meta["trading_date"]), universes, writer,
                             mode=MODE_REPLAY, source="REPLAY")
    last_ns = None
    for receive_ns, data in read_recording(args.recording):
        session.handle_message(receive_ns, data)
        session.finalize_due(receive_ns)
        last_ns = receive_ns
    session.finalize_all()
    print(json.dumps({"replayed_from_session": meta["session_id"], "last_receive_ns": last_ns,
                      "derived_rows": dict(writer.rows), "quality": session.quality_summary("REPLAY")},
                     indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
