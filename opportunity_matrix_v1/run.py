"""Orchestrates one Opportunity Matrix v1 research run (read-only) and writes all artifacts to
data/cache/opportunity_matrix_v1/<run_id>/."""

import csv
import json
import subprocess
from datetime import datetime
from pathlib import Path

from config.settings import IST
from opportunity_matrix_v1 import loader
from opportunity_matrix_v1.config import DATASET_VERSION, DEFAULT, VERSION
from opportunity_matrix_v1.pipeline import build
from opportunity_matrix_v1.thresholds import minute_thresholds

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache" / "opportunity_matrix_v1"


def load_all(cfg):
    with loader.connect() as conn:
        sess = loader.hr_sessions(conn)
        days = {}
        for d, sid in sess:
            days[d] = {}
            for sym in cfg.symbols:
                x = loader.load_day(conn, sid, d, sym)
                if x is not None:
                    days[d][sym] = x
        minute_th = {}
        for d in days:
            for sym in cfg.symbols:
                prior_days = loader.prior_trading_days(conn, sym, d, cfg.prior_1min_days)
                c = loader.load_candles(conn, sym, prior_days[0], prior_days[-1]) if prior_days else None
                pc = {pd_: c[c["timestamp"].dt.date == pd_].reset_index(drop=True) for pd_ in prior_days} if c is not None else {}
                minute_th[(d, sym)] = minute_thresholds(d, pc, cfg.vp_bin_size[sym], cfg)
                if sym in days[d]:
                    days[d][sym].candles = loader.load_candles(conn, sym, d, d)
    return days, minute_th


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except Exception:
        return None


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v, default=str) if isinstance(v, (list, dict)) else v) for k, v in r.items()})


def main(cfg=DEFAULT):
    from opportunity_matrix_v1 import experiments, leakage, report
    run_id = datetime.now(IST).strftime("om1-%Y%m%dT%H%M%S")
    out = CACHE / run_id
    out.mkdir(parents=True, exist_ok=True)
    days, minute_th = load_all(cfg)
    ds = build(days, minute_th, cfg)
    audit = leakage.audit(days, minute_th, ds, cfg)
    res = experiments.run_all(ds, days, cfg)
    meta = dict(run_id=run_id, git_commit=git_commit(), version=VERSION, dataset_version=DATASET_VERSION, config_hash=cfg.config_hash())
    report.write_all(out, ds, res, audit, meta, days, cfg)
    return out, ds, res, audit


if __name__ == "__main__":
    o, ds, res, audit = main()
    print("artifacts:", o)
    print("leakage:", audit["overall"])
