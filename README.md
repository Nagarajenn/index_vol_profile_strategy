# Sensex/Nifty Intraday Decision-Support Tool

Pulls Sensex/Nifty market data from the Dhan v2 API, computes intraday technical
levels (VWAP, developing Volume Profile/POC/Value Area, Support/Resistance,
Swing Highs/Lows, Trendlines, Breakout boxes), folds in Option Chain OI/PCR
context, and renders an annotated 5-minute chart plus a structured decision
card (Trend / Institutional Bias / Confidence / Support / Resistance / POC /
Action).

**This is a decision-support / technical-analysis tool for your own
discretionary trading. It does not place or modify any orders, and nothing
in it talks to Dhan's order-placement endpoints. It is not licensed
investment advice.**

## Setup

```
python -m venv venv
venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and fill in `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` (never commit
this file). Dhan access tokens typically expire daily — regenerate and update
`.env` if you see a `DH-901 Invalid_Authentication` error.

**Database**: create a Postgres database (and optionally a dedicated schema)
yourself first (pgAdmin/DBeaver/psql), then add to `.env`:
```
DATABASE_URL=postgresql://user:password@host:port/dbname
DB_SCHEMA=public   # or your schema name, if not using the default
```
If your password contains special characters (`@`, `:`, `/`), percent-encode
them (`@` -> `%40`) or the connection string won't parse. Then create the
tables:
```
venv\Scripts\python.exe db\setup_db.py
```

## Usage

**One-shot live snapshot** (current market state, both symbols by default):
```
venv\Scripts\python.exe scripts\run_live_snapshot.py [SENSEX] [NIFTY]
```
Prints the decision card and writes raw candles/option chain + computed
levels to Postgres, plus a chart PNG under
`vol_pro_snapshot_training\{SYMBOL}\{YYYY-MM-DD}\{HHMM}\chart.png` if the
event-driven trigger fires (see below).

**Auto-repeating live loop** (fires a snapshot every 1 min during market
hours, 09:15-15:30 IST, sleeps through nights/weekends/holidays):
```
venv\Scripts\python.exe scripts\run_live_loop.py [SENSEX] [NIFTY]
```
Runs until you Ctrl+C. This does not auto-start itself — run it manually
each trading day, or wire it into Windows Task Scheduler yourself.

**60-day historical backfill** (dense, every 5-min bar, for training/backtesting):
```
venv\Scripts\python.exe scripts\run_backfill.py --days 3     REM small test first
venv\Scripts\python.exe scripts\run_backfill.py               REM full 60-day run
```
Writes directly to Postgres. Option-chain-derived Institutional Bias is only
available for live snapshots (Dhan's option chain is live-data-only) —
backfilled snapshots mark this `"unavailable_backfill"` and the confidence
score renormalizes around the remaining components.

**One-time migration** of an existing JSON snapshot archive into Postgres
(only needed if you have old `vol_pro_snapshot_training/` data from before
the DB migration):
```
venv\Scripts\python.exe db\migrate_json_to_db.py
```
Safe to re-run — every insert is `ON CONFLICT DO NOTHING`/idempotent.

**Backtest / tune scoring weights** against saved snapshots:
```
venv\Scripts\python.exe scripts\run_tune_weights.py SENSEX
```
This is a scaffold: with only backfilled data (no live OI signal, a single
realized price path) treat its output as a starting point, not a final
answer. It never overwrites `config/scoring_weights.json` automatically.

## Data storage

Raw input data (1-min/daily candles, option chain) and computed output
(levels, decision cards) live in Postgres (`db/schema.sql`):
- `raw_candles` / `raw_daily_candles` — OHLCV, upserted incrementally (only
  new rows since the last known timestamp are written on each live poll).
- `option_chain_raw` / `option_chain_summary` — full payload + PCR/OI/IV
  summary, live snapshots only.
- `levels_snapshots` — one row per (symbol, as_of): VWAP, POC/Value Area,
  support/resistance, trend, institutional bias, confidence score + its
  sub-scores as real columns (for easy aggregation), and the full
  swings/trendlines/breakout-boxes/volume-profile-bins detail as JSONB.

**Chart PNGs are event-driven in live mode** — rendered only on the first
snapshot of the session, a trend-label change, a POC move of at least one
volume-profile bin since the last chart, or if 15 minutes pass with no
trigger (`pipeline/run_snapshot.py::should_render_chart`). They're only
needed for visual review / model training, not every 1-min computation
tick. Backfill mode still renders at a fixed checkpoint list
(`config/settings.py::BACKFILL_CHART_CHECKPOINTS`) instead.

## Key assumptions worth knowing about

- **Volume Profile is an approximation.** Dhan provides 1-min OHLCV candles,
  not tick-by-tick trade prints, so volume-at-price is estimated by
  distributing each candle's volume across the price bins it spans (see
  `analytics/volume_profile.py` for the exact method). This is standard
  practice for candle-based profiles but isn't identical to a true
  tick-level profile.
- Bin sizes, round-number steps, and the confidence-score weights in
  `config/instruments.py` / `config/scoring_weights.json` are reasonable
  starting defaults, meant to be tuned via `scripts/run_tune_weights.py` as
  more data accumulates.
- This machine's antivirus does TLS interception on outbound HTTPS; the
  `truststore` package (bootstrapped in `config/__init__.py`) makes Python
  trust the OS certificate store so API calls verify correctly. If you move
  this project to a machine without that interception, `truststore` is
  harmless to leave in place.

## Running tests

```
venv\Scripts\python.exe -m pytest tests\ -v
```
