# HR-1 — High-Resolution Option Intelligence Capture

**Data capture, data quality and market-state foundation only.** Nothing in this
package produces, scores or executes a trade. It is independent of the existing
1-minute pipeline and of the frozen `11d-paper-v1` experiment.

## Boundary

| | Existing platform | HR-1 |
|---|---|---|
| Process | `scripts/run_live_loop.py` (09:10 task) | `scripts/run_hr_capture.py` (14:50 task) |
| Dhan transport | REST (candles, option chain) | WebSocket market feed only — **no REST calls** |
| DB connection | `db/connection.py` shared connection | own connection, `application_name=hr_capture`, 5 s statement / 2 s lock timeout |
| Tables | existing tables | `hr_*` only (writes); read-only SELECTs of `option_chain_raw`, `raw_candles` |
| Imports | never imports `hr_capture` | imports only `config.settings`, `config.instruments`, `pipeline.trading_calendar` |
| Orders | none in HR | none — no order code, no order endpoints |

Enforced by `tests/test_hr_isolation.py` (frozen-file hashes, strategy hash `9c7c362d7e0c6a14`,
import graph both ways, hr_-only writes, broken-HR import test, order-fragment scan).

## Session timeline (IST, trading days only)

| Time | Action |
|---|---|
| 14:50 | Task Scheduler starts the process (exits at once on non-trading days) |
| 14:54 | Universe resolved from the latest `option_chain_raw` row (fallback: cached scrip master); WebSocket connects and subscribes |
| 14:54–14:55 | Pre-window packets set baselines (quotes, cumulative volume, OI) — **not persisted** |
| 14:55:00 ≤ receive_ts < 15:30:00 | Raw ticks, recording, 5 s bars, option state, chain state persisted |
| ~15:30:03 | Final buckets flushed, exchange timestamps back-filled, session closed with quality summary |
| 15:35 | Wall-clock hard stop (independent watchdog thread) |

## Universe (48 instruments)

Per symbol: index (`QUOTE`) + nearest-expiry index future (`FULL`) + ATM ± 5 CE/PE (`FULL`).
ATM = listed strike nearest the reference spot at 14:54; the band is positional over the
actual strike list. **No strikes or security IDs are hard-coded.** The band stays fixed for
the session; a `BAND_EDGE` event is recorded if the observed parity ATM reaches the edge.

## Tables

| Table | Purpose |
|---|---|
| `hr_capture_sessions` | one row per run: versions, window, counts, status, quality summary |
| `hr_instruments` | resolved universe and ID source per session |
| `hr_raw_ticks` | **forensic source of truth**: every de-duplicated packet, raw bytes, exchange + receive time |
| `hr_ohlc_5s` | 5 s bars from raw events (receive-time buckets); `trade_count` is a lower bound |
| `hr_option_5s` | per-contract quote/volume/OI/depth state per 5 s, with quote age |
| `hr_option_transition_state` | per-symbol chain observations per 5 s; underlying/futures status; market state; **option_implied_spot_research_only** |
| `hr_capture_events` | connect/subscribe/disconnect/gap/state-change/band-edge audit trail |

## Time semantics

* `receive_ts` / `receive_ns` — local arrival time; used for bucketing and arrival order.
* `ltt_epoch` — raw exchange last-trade-time integer, **1-second resolution**.
* `exchange_ts` — `ltt_epoch` interpreted with the per-session detected convention
  (`UTC_EPOCH` or `IST_WALLCLOCK_EPOCH`); NULL when undetermined. **No sub-second exchange
  ordering is claimed.**

## Data-quality vocabulary

* Feed status (underlying, futures): `VALID` / `STALE` (no packets) / `FROZEN` (packets, price unchanged) / `MISSING`.
* Market state: `CONTINUOUS`, `AUCTION_OR_CLOSING_STATE` (underlying stale/frozen after 15:15 while
  options/futures keep updating — an observation, not a confirmed exchange phase), `UNDERLYING_STALE`,
  `DATA_GAP`, `RECONNECT`, `CLOSED`, `UNKNOWN`.
* Row flags: `GAP`, `NO_UPDATE`, `NO_DATA_YET`, `STALE_QUOTE`, `MISSING_BID_ASK`, `CROSSED`,
  `VOLUME_RESET`, `BASELINE_IN_BUCKET`.
* Duplicates: consecutive identical payloads per instrument and packet type are dropped and counted
  (they still prove the feed is alive). Changes that later revert (A→B→A) are kept.

## Failure policy

* Initial connect failure / drop → bounded backoff 1, 2, 4, 8, 16, 30 s; the backoff resets only after
  data arrives or the connection stays up 30 s.
* HTTP 429 → rate-limit cool-down 60, 120, 300 s.
* 806 / 807 / 808 / 809 or HTTP 401/403 → stop immediately (`FAILED_AUTH`), no retry loop.
* 805 (connection limit) → one retry after 30 s, then stop.
* DB errors → rows spilled to `data/cache/hr_capture/<session>_spill_<table>.jsonl`; capture continues.
* The raw recording `data/cache/hr_capture/<date>_<session>.bin` (+ `.meta.json`) is written regardless of the DB.

## Operations

```bat
REM validate DDL (no changes)            REM apply DDL (hr_* only, before/after structure check)
venv\Scripts\python.exe scripts\hr_setup_db.py          venv\Scripts\python.exe scripts\hr_setup_db.py --apply

REM offline connectivity test — connects, subscribes, counts packets, writes NOTHING
venv\Scripts\python.exe scripts\run_hr_capture.py --connectivity-test 30 --universe-date 2026-09-11 --as-of 15:29

REM live session (what the scheduled task runs) / dry run without DB or recording
venv\Scripts\python.exe scripts\run_hr_capture.py
venv\Scripts\python.exe scripts\run_hr_capture.py --dry-run

REM deterministic replay of a recording (prints summary, writes nothing)
venv\Scripts\python.exe scripts\run_hr_replay.py data\cache\hr_capture\<date>_<session>.bin
```

Logs: `logs/hr/hr_capture_YYYYMMDD.log` and `logs/hr/hr_capture_daily.log`.

## Not available from this feed (not fabricated)

IV and Greeks (so no IV skew), the auction indicative price, true trade counts, 20-level depth for
BSE (SENSEX) contracts, and any historical 5-second data before the first captured session.
