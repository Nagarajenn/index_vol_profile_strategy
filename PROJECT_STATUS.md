# Project Status — Sensex/Nifty Options Decision-Support Tool

_Last updated: 2026-07-20_

## 1. Intent of this strategy

The goal is **not** an automated trading bot — it's an AI "chart analyst" that reads
the market the way a discretionary intraday trader would, and hands back a
structured read the trader uses to decide whether to buy Sensex/Nifty **CE
(call) or PE (put) options**, or stay out.

Concretely, the system:
1. Watches price action the way a volume-profile/VWAP trader does — where is
   price relative to today's Point of Control (POC), VWAP, and the
   developing Value Area; is the market trending or rotating; is it
   breaking out of a range.
2. Cross-checks that read against **institutional positioning** in the
   options chain (Call/Put OI buildup, PCR) — the idea being that heavy
   Call-OI buildup above spot acts as writer resistance, heavy Put-OI
   buildup below spot acts as writer support.
3. Combines both into a single **0–100 confidence score** and a plain-English
   **Trend / Bias / Action** card, so the trader isn't reading six indicators
   separately and mentally averaging them under time pressure.
4. Logs every read to a database, building a growing history so the scoring
   weights can later be **backtested and tuned** against what actually
   happened next — turning "the model's opinion" into something empirically
   calibrated over time rather than a fixed set of guessed weights.

**What it deliberately does not do**: place or modify any order, size a
position, set a stop-loss/target, or give personalized investment advice. It
is decision support for the trader's own judgment, not an execution system.

## 2. Data pipelines

Everything ultimately comes from Dhan's v2 REST API (`dhan_client/client.py`)
and lands in Postgres (database `ai_lab_claude`, schema `ai_poc_strategy`).
There are two ingestion pipelines and two on-demand/analysis jobs:

| Pipeline | File | Cadence | Symbols | Source data | Writes to |
|---|---|---|---|---|---|
| **Live loop** | `pipeline/live_loop.py` | Every **1 minute**, 09:15–15:30 IST, Mon–Fri, skipping the 2026 NSE/BSE holiday list | SENSEX, NIFTY | 1-min candles (~8-day rolling lookback), daily candles, live option chain (nearest expiry) | `raw_candles`, `raw_daily_candles`, `option_chain_raw`, `option_chain_summary`, `levels_snapshots` (mode=`live`), `chart.png` (event-driven, see §3) |
| **60-day backfill** | `pipeline/backfill.py` | One-time/on-demand batch job (not scheduled) | SENSEX, NIFTY | 1-min + daily candles only — **no option chain** (Dhan's option chain is live-data-only, so institutional bias can't be reconstructed retroactively) | Same tables, mode=`backfill`, checkpointed every **5 minutes** (76 checkpoints/trading day) |
| Backtest / tune-weights | `backtest/*.py` | On-demand analysis, not an ingestion pipeline | either | Reads `levels_snapshots` back from Postgres; re-fetches candles only to compute forward returns for labeling | Nothing persisted — prints a candidate weight set for `config/scoring_weights.json` |
| One-time JSON→DB migration | `db/migrate_json_to_db.py` | Already run once | SENSEX, NIFTY | The original 60-day JSON snapshot archive + a matching raw-candle fetch | Same tables (idempotent, safe to re-run) |

**Instrument metadata** (`config/instruments.py`):

| | SENSEX | NIFTY |
|---|---|---|
| Exchange | BSE | NSE |
| Security ID (resolved from Dhan's scrip master, not hardcoded) | 51 | 13 |
| Volume-profile bin size | 25 pts | 5 pts |
| Round-number step (for support/resistance) | 100 pts | 50 pts |

**Current database volumes** (live as of 2026-07-20 mid-session):

| Table | Rows | Contents |
|---|---|---|
| `raw_candles` | 51,346 | 1-min OHLCV, both symbols |
| `raw_daily_candles` | 136 | Daily OHLCV |
| `levels_snapshots` | 9,407 (9,118 backfill + 289 live) | Every computed level, per checkpoint |
| `option_chain_raw` / `option_chain_summary` | 74 each | Live-mode only — grows by ~1 row/minute per symbol while the live loop runs during market hours |

**Today's session (2026-07-20) is live-tracked end to end**: the morning
(09:15 → live-loop-start) was caught up in one pass
(`pipeline/catch_up_today.py`, `scripts/run_catch_up_today.py`) — replayed as
`mode="live"` rows at 1-min granularity using a single shared option-chain
fetch (Dhan has no historical intraday OI, so every catch-up checkpoint reads
against the same "current" OI snapshot rather than truly contemporaneous
data — an accepted, documented approximation, exact for the most recent
checkpoint and weakest for the earliest one). `pipeline/live_loop.py` then
took over for the rest of the session with a fresh option-chain fetch every
minute. Verified: distinct-timestamp row counts matched real market minutes
(no duplicate rows from the catch-up's necessarily-redundant tail
iterations), and exactly one option-chain row was written per symbol for the
catch-up (not once per replayed checkpoint).

## 3. What comes out of it

Two outputs per checkpoint:

**A. The decision card** — the primary output, e.g.:
```
Trend: Strong Bullish intraday
Institutional Bias: Mildly Bullish
Confidence: 88/100
Support: 78,092
Resistance: 78,400–78,500
POC: 77,962
Trend can move above or below the POC
Action: Favor calls while price holds above VWAP (77,937) and POC (77,962);
above 78,400–78,500, momentum can extend further; invalidate the bullish
view below 78,092.
```
Backed by a `levels_snapshots` row holding every underlying number: VWAP,
today's/yesterday's POC + Value Area High/Low, the full volume-profile
histogram, swing highs/lows, trendlines, breakout boxes, support/resistance
zones, and each confidence sub-score individually (so they can be
aggregated/analyzed later without recomputing anything).

**B. The annotated chart** — a 5-minute candlestick PNG with VWAP, today's
POC + Value Area shading, yesterday's POC, swing markers, trendlines,
support/resistance zones, breakout boxes, and a volume-profile side panel.
This is **event-driven in live mode**, not generated every minute — it only
renders on the first snapshot of the session, a trend-label change, a POC
move of at least one volume-profile bin since the last chart, or a 15-minute
backstop if nothing else has triggered. Backfill mode renders at a fixed
checkpoint list (10:00/12:00/14:00/15:25) instead, since it's for visual
review/training rather than live monitoring.

## 4. How the CE/PE buy/sell read is decided

Everything rolls up from three independent reads, then a weighted score:

**Trend** (`analytics/trend_classifier.py`) — a vote of three signals, each
scored -1/0/+1: price vs VWAP (0.05% deadband), EMA(20) slope over the last
5 bars (0.05% deadband), and swing structure (higher-highs+higher-lows =
bullish, lower-highs+lower-lows = bearish). The sum (-3..+3) maps to Strong
Bearish / Bearish / Neutral / Bullish / Strong Bullish.

**Institutional Bias** (`analytics/institutional_bias.py`, live only) —
near-ATM Call-OI buildup above spot = bearish signal; Put-OI buildup below
spot = bullish signal; PCR > 1.2 = bullish tilt, PCR < 0.8 = bearish tilt.
Combined score -2..+2 maps to Bearish / Mildly Bearish / Neutral / Mildly
Bullish / Bullish. Always "Unavailable (historical)" for backfilled rows.

**Confidence score** (`analytics/confidence_score.py`, 0–100) — a weighted
sum of seven 0–1 sub-scores, current weights (`config/scoring_weights.json`,
tunable via the backtest scaffold, never auto-applied):

| Component | Weight | What it measures |
|---|---|---|
| Trend alignment | 25 | How unanimous the 3 trend signals are |
| VWAP position | 15 | Distance of price from VWAP (capped at 0.5% move) |
| Structure (HH/HL) | 15 | Whether swing structure agrees with the trend direction |
| Trendline confluence | 10 | A validated trendline in the trend's direction, weighted by touch count |
| Support/resistance proximity | 10 | How close price is to an actionable S/R zone (within 1%) |
| Breakout confirmation | 10 | A confirmed breakout box matching the trend direction |
| Institutional bias | 15 | Magnitude of the OI/PCR-derived bias (excluded + renormalized when unavailable, e.g. backfill) |

**The Action text** (`decision/decision_card.py`) then follows simple rules
off the trend direction:
- **Bullish** (trend score ≥ 1): favor calls while price holds above
  VWAP/POC; momentum can extend on a break above resistance; invalidate the
  bullish view (i.e. stop favoring calls) below the support zone.
- **Bearish** (trend score ≤ -1): wait for a reclaim of VWAP/POC before
  considering calls; below support, favor bearish setups / puts.
- **Neutral** (trend score = 0): no clear edge — wait for a decisive break
  of the support–resistance range with volume confirmation before choosing
  CE/PE either way.

**The actual buy/sell call is the trader's, not the system's** — this output
is the read the trader combines with their own risk management, position
sizing, and stop-loss/target discipline, none of which this tool currently
does. There is also no backtested proof yet that following this Action text
is profitable — the confidence-score weights above are starting defaults;
`scripts/run_tune_weights.py` exists specifically to calibrate them against
realized outcomes as more live data (with real institutional-bias signal)
accumulates, and a first pass on the 60-day backfill already shows the
current weights have roughly zero calibration (baseline score -0.72,
essentially no separation between confident-and-right vs confident-and-wrong
calls) — reinforcing that these are unvalidated defaults, not a proven edge.

## 5. The Dashboard (V1) — architecture and tech stack

Phases 1–2 (above) are the data/analytics engine. Phase 3 adds a **read-only
presentation layer** on top — a web dashboard so the decision card, chart,
and option chain don't have to be read from raw database rows. It is purely
a viewer: nothing in this layer writes to the database, places an order, or
changes how any level is computed. Built to a "professional trading
terminal" bar (dark mode, information-dense, Bloomberg/TradingView-style),
using clean-architecture conventions (Repository pattern, Service layer,
dependency injection, strongly-typed request/response contracts) since the
intent is for this to keep growing rather than stay a throwaway prototype.

### Backend — `backend/`

| | |
|---|---|
| Language/runtime | Python 3.14, own virtual environment (`backend/venv`) — kept fully separate from the ingestion pipeline's Python 3.13 environment so neither can destabilize the other |
| Framework | FastAPI + Uvicorn |
| Database access | SQLAlchemy 2.0 (async ORM, `asyncpg` driver), read-only models mapped 1:1 onto the existing pipeline-owned tables — this layer never creates/alters/drops schema |
| Migrations | Alembic, baselined against the live schema (an intentionally **empty** first migration — proof the ORM models exactly match reality, not just a generated-and-trusted one); owns only *future* schema deltas, `db/setup_db.py` remains authoritative for initial table creation |
| Validation/contracts | Pydantic v2 DTOs for every request/response — nothing untyped crosses the API boundary |
| Config | `pydantic-settings`, reading the **same** root `.env` the pipeline uses (`DATABASE_URL`, `DB_SCHEMA`) — one source of truth for connection config, no duplication |
| Code reuse | The pipeline's `analytics` and `config` packages are installed into the backend's venv as an editable dependency (new root `pyproject.toml`) specifically so `analytics/resample.py`'s 1-min→5-min candle resampling logic is reused verbatim, not reimplemented |
| Architecture | Repository (query-only, no business logic) → Service (owns staleness/no-data/market-hours decisions, resampling) → Router (thin HTTP↔DTO translation) → a single centralized exception→HTTP status mapping, rather than scattered try/except per endpoint |

**Endpoints (V1):**
- `GET /api/v1/symbols` — static instrument list
- `GET /api/v1/dashboard/{symbol}/latest` — the one endpoint the UI polls every ~20s: latest decision-card fields, 5-min resampled candles for today's session, and an option-chain summary, wrapped in a `status: "live" | "stale" | "no_data"` envelope so the frontend never has to special-case "market's closed" as an error
- `GET /api/v1/levels/{symbol}/latest/detail` — swings/trendlines/breakout-boxes/volume-profile-bins, built and verified now but **not yet wired into any screen** — reserved so the v1.1 chart-overlay work (see §7) is a frontend-only change

### Frontend — `frontend/`

| | |
|---|---|
| Language/tooling | TypeScript, Vite |
| UI framework | React 19 |
| Component library | Material UI (MUI) v9, custom dark theme (near-black background, blue accents) |
| Routing | React Router (single route today — `TerminalPage` — wired for more screens later) |
| Server state / polling | TanStack Query — polls `/dashboard/{symbol}/latest` every ~20s, no WebSocket in V1 |
| Client state | Zustand — currently just the selected symbol |
| Charting | Recharts — a hand-built candlestick renderer (Recharts has no built-in candlestick type), using its v3 hook-based scale API (`useXAxisScale`/`useYAxisScale`) to draw OHLC bars, with VWAP/POC as reference lines and Value-Area/Support/Resistance as shaded reference areas |
| HTTP client | Axios |

**What's on screen today**: a symbol switcher (SENSEX/NIFTY), the decision
card (Trend badge, Institutional Bias, Confidence gauge, Support/Resistance/
POC/VWAP, Action text), a 5-minute candlestick chart with VWAP/POC/Value-Area/
Support/Resistance overlays, and an option-chain summary panel (PCR, ATM
strike, ATM IV call/put). All three panels are stacked vertically and proven
working end-to-end against real live and historical data — the current
layout is functional but not yet the target information-density layout (see
§7, first item).

## 6. What's running right now

- **Backend**: `uvicorn app.main:app --reload` on `:8000`
- **Frontend**: `vite` dev server on `:5173` → http://localhost:5173
- **Live loop**: `pipeline/live_loop.py` running in the background, ticking
  every 1 minute for both symbols through today's session (started after the
  one-time catch-up described in §2)

None of these auto-start on their own — they were started manually this
session and would need to be started again (or scheduled) on a future day.

## 7. Planned enhancements (next round — not yet built)

Captured from review feedback on the V1 dashboard, to be scoped/built next:

1. **Layout rework.** Reposition the decision-card summary and the
   option-chain summary side by side (roughly half-width each) instead of
   stacked, with the price chart moved below both — a more information-dense,
   terminal-style layout. Purely a frontend/UI change (MUI Grid/flex
   rework in `TerminalPage.tsx`), no backend or data changes needed.
2. **Option chain depth.** Currently only the ATM strike's IV (call/put) is
   shown. Extend to show 3 strikes in-the-money and 3 out-of-the-money on
   each side (7 strikes total centered on ATM) — likely OI, LTP, and IV per
   strike, not just IV. This needs a small backend addition (the raw
   option-chain payload already has every strike's data in
   `option_chain_raw`/`option_chain/summary.py`'s near-ATM window logic; a
   new DTO + endpoint or an extension of the existing option-chain summary
   would expose it) plus a new frontend strike-ladder component.
3. **Chart overlays (already scoped, not yet built)**: swings, trendlines,
   breakout boxes, and the volume-profile side panel — the backend detail
   endpoint (§5) already serves this data, it just isn't rendered yet.
4. **Historical/timeline browsing** — deferred from V1 scope by design (see
   original V1 plan); still not built.
