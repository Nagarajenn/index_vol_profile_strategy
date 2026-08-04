# Project Status — Sensex/Nifty Options Decision-Support Tool

_Last updated: 2026-07-31_

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

## 6. V2 "AI Trading Terminal" roadmap — progress

V1 (§1–5, tagged `v1.0.0`) is the working baseline. The V2 direction is an
explicit philosophy shift: every panel should answer one trading question
and present four layers — **Raw Values → AI Interpretation → Confidence →
Trading Implication** — rather than dumping numbers and leaving the trader
to interpret them. This is a 10-item priority-ordered roadmap, built
**one item at a time**, each followed by validate/test/commit/tag and a
stop-and-wait for review before the next.

| # | Item | Status |
|---|---|---|
| 1 | **AI Decision Card** | ✅ Shipped, tagged `v2.1.0` |
| 2 | Institutional Activity Card | Not started |
| 3 | 7-Strike Option Ladder (ATM ±3 ITM/OTM) | Not started (overlaps with §9 item 2 below) |
| 4 | AI Reasoning Panel | Not started |
| 5 | Volume Profile Interpretation | ✅ Shipped as "Volume Profile Intelligence" (see below) |
| 6 | Market Structure Card | Not started |
| 7 | Risk Assessment Card | Not started |
| 8 | Historical Replay | Not started |
| 9 | AI Watchlist | Not started |
| 10 | Trade Journal | Not started |

**Item 1 — AI Decision Card (done):** added a synthesized narrative sentence
(`backend/app/services/interpretation.py::build_interpretation`) that reads
price vs VWAP, price vs today's POC, trend label, and institutional bias
into one interpretive sentence — the one layer the existing card was
missing (Raw Values/Confidence/Action already existed, just unlabeled).
Wired into the existing `/api/v1/dashboard/{symbol}/latest` response as a
new `interpretation` field — no new endpoint, no migration. Frontend gained
a reusable `AnalysisCard` component implementing the generic 4-layer shell
(title, trading question, raw-values grid, interpretation text, confidence
gauge, highlighted implication block); `DecisionCardPanel` is now a thin
adapter onto it. 7 backend unit tests cover the interpretation logic
(normal case, missing VWAP/POC, neutral trend, excluded backfill-bias
label). This component is deliberately reusable — items 2, 5, 6, 7 above
will each plug into the same `AnalysisCard` shell rather than
re-implementing the 4-section layout.

**Item 5 — Volume Profile Intelligence (done, 2026-07-23):** delivered as a
dedicated panel rather than the 4-layer `AnalysisCard` shell, per its own
explicit spec ("reusable service", "keep the strategy engine unchanged") —
this is raw multi-metric analysis by design, not a single
interpretation/confidence/implication read.

New `analytics/volume_profile_intelligence.py` — pure functions, built on
the existing `compute_volume_profile()`, zero dependency on the DB/pipeline:
- **Developing POC/VAH/VAL**: the value area recomputed from only the
  candles available at each checkpoint through the session, showing how it
  has migrated so far (not just the final end-of-day figure).
- **HVN/LVN**: local-maxima/minima bins in the volume-by-price distribution
  (consolidation magnets vs. "air" the market moves through fast).
- **Value Migration**: today's POC/VAH/VAL vs. the prior session's, plus
  intraday drift since the first checkpoint.
- **Acceptance/Rejection**: for VAH/VAL/POC/prior-POC, whether price dwelt
  and closed inside a band around the level (accepted) or touched and
  moved away (rejected) or never reached it (untested).
- **Profile Shape (P/b/D/B)**: P/b when volume concentrates near the
  highs/lows with a thin opposite tail (fast markup/markdown); B when two
  separated high-volume clusters exist (double distribution); D otherwise
  (normal balanced auction).
- **Initial Balance**: high/low range of the first 60 minutes, flagged
  `is_complete` while the session hasn't reached that window yet.
- **Opening Type**: a heuristic approximation of Steidlmayer's taxonomy
  (Open-Drive / Open-Test-Drive / Open-Rejection-Reverse / Open-Auction)
  from the first 30 minutes' range and close-vs-open behavior.
- **Rotation Factor**: counts directional sign-flips between successive
  30-min high/low periods — frequent flips read "Rotational" (choppy,
  two-sided), few flips read "Trending" (one-sided).
- **Volume Pace**: today's cumulative volume vs. the average cumulative
  volume at the same elapsed session time over the last 10 calendar days —
  tells you if today is unusually busy or quiet, independent of direction.

Several of these (Profile Shape, Opening Type, Rotation Factor) are
inherently fuzzy/discretionary in classic Market Profile literature — the
implementations are reasonable, deterministic, clearly-documented
heuristics, not a claim of matching one canonical textbook definition.
22 unit tests cover each metric with hand-constructed synthetic candles.

Backend: `VolumeProfileIntelligenceService` fetches the last 10 days of
`raw_candles` via the existing `CandleRepository` (no new repository
method), groups by date, and calls the analytics module fresh on every
request — no new DB tables, no migration, no pipeline changes. New
endpoint `GET /api/v1/volume-profile/{symbol}/intelligence`, separate from
the hot-polled dashboard endpoint since it's meaningfully heavier (full
multi-day profile recomputation vs. one row lookup); the frontend polls it
every 60s instead of 20s. 5 backend unit tests (date-grouping, unknown
symbol, no data, populated result) using a fake in-memory candle repo.

Frontend: new `VolumeProfileIntelligencePanel`, added below the price
chart on `TerminalPage`. Verified end-to-end against real live data —
every metric renders coherently (e.g. a "down" Value Migration and
"Open-Drive lower" lined up with the existing Decision Card's independent
"Strong Bearish" read, two separate computations agreeing).

**Explicitly not done, by design**: nothing here feeds
`analytics/confidence_score.py`, `analytics/trend_classifier.py`, or
`decision/decision_card.py` — verified zero diff on all three files plus
`analytics/institutional_bias.py`. This is informational-only for now, per
the "keep the strategy engine unchanged" instruction; wiring any of it into
the actual trend/confidence/action logic would be a separate, explicit
future decision.

Items 2, 4, 6–10 are intentionally **not scoped yet** — each gets its own
design pass when its turn comes, per the stated one-at-a-time process.

## 7. What's running right now

- **Backend**: `uvicorn app.main:app --reload` on `:8000` — started manually,
  not yet scheduled to auto-start (see §9 for that as a flagged opportunity).
- **Frontend**: `vite` dev server on `:5173` → http://localhost:5173 —
  started manually, same caveat.
- **Live loop**: `pipeline/live_loop.py`, ticking every 1 minute for both
  symbols during market hours — **now starts itself automatically** via a
  Windows Task Scheduler task, `SensexNifty-LiveLoop` (see §8). No manual
  start needed on future trading days.

## 8. Live pipeline outage (2026-07-20) — root cause, fix, and automation

**What happened:** the live loop silently stopped writing new rows for both
symbols starting ~14:04 IST, though the process itself never crashed —
`Get-Process` showed it still running, still "trying" every minute.

**Root cause:** `pipeline/live_loop.py` is a single long-running process
that reuses one `requests.Session` (via the `dhanhq` client) for its entire
multi-hour lifetime. Around 14:04, this machine's antivirus (Norton, which
does real-time HTTPS interception — the same class of interference seen
earlier in this project with git object writes) reset the underlying TCP
connection. The session's connection pool kept trying to reuse that now-dead
connection on every subsequent tick, failing identically each time
(`PermissionError(13, 'Permission denied')` wrapped in `ConnectionAborted`),
and the loop's broad `except Exception: logger.exception(...)` just logged
and moved on — no retry-with-fresh-connection, no alerting. A brand-new
process reached Dhan instantly, confirming the fix was a fresh session, not
a Dhan-side outage.

**Fix applied:**
1. Killed the two stuck processes, started a clean `live_loop` process —
   confirmed writing again within one tick.
2. Backfilled the missed window with `pipeline/catch_up_today.py` — verified
   every minute from 14:04 through the restart is now present for both
   symbols in `levels_snapshots` (idempotent upsert, safe to re-run).

**Hardening — daily-scoped process instead of one long-lived process:**
`run_live_loop()` gained a `run_single_session: bool` param
(`scripts/run_live_loop.py --single-session`): it now exits cleanly once
today's session closes (or immediately on a non-trading day) instead of
sleeping through the night in the same process. A new Windows Task
Scheduler task, **`SensexNifty-LiveLoop`**, starts a fresh process every
weekday at **09:10 IST** (5-min buffer before the 09:15 open) and lets it
exit itself at close — no manual daily start, and a much smaller window for
a connection to go stale before the process naturally recycles. Configured
"run only when logged on" (no Windows password stored) and
`MultipleInstancesPolicy=IgnoreNew` (won't double-start if a prior run is
still alive). First automatic run: the next trading day after this was set
up.

**Not yet addressed — flagged for review, see §9:** the loop still has no
alerting if it fails repeatedly, and no automatic retry-with-fresh-session
mid-day if this exact failure mode recurs during market hours (that day's
recovery was a manual restart). The daily process recycle *reduces* the
odds (a fresh connection every morning vs. one connection surviving weeks)
but doesn't eliminate the possibility of it happening again mid-session.

**Follow-up (2026-07-21, next trading morning) — two more issues found and
fixed:**
1. The Task Scheduler task fired at 09:10 as scheduled but its process was
   killed almost immediately (exit code `0xC000013A`,
   `STATUS_CONTROL_C_EXIT`) before it ever reached the 09:15 open — a
   scheduled batch file launched under an interactive Windows session opens
   a visible console window, and anything that closes that window (a stray
   click, another process, session churn) sends a close signal to the whole
   process group, killing it. Fixed by adding a hidden-window VBScript
   launcher (`scripts/run_live_loop_daily.vbs`, using `WshShell.Run` with
   window style `0`) and pointing the Task Scheduler action at
   `wscript.exe //B run_live_loop_daily.vbs` instead of the `.bat` directly
   — there is now no visible window for anything to close. Verified live by
   manually re-triggering the task (`schtasks /Run`) and confirming it kept
   ticking normally.
2. Separately — and more importantly — the process manually restarted the
   previous afternoon (§8's fix) had been started **without**
   `--single-session` (it predated that flag being added), so it stayed
   alive overnight, went back to sleep at close, then woke up at today's
   open and **hit the exact same stuck-connection bug again**, silently
   writing zero rows all morning until this was caught and the stale
   process was killed. This is exactly the failure mode `--single-session` +
   Task Scheduler was built to prevent, and confirms the fix is worth
   having — the gap this time was ~09 minutes (09:15→09:24), backfilled the
   same way as before. Going forward, every process is either
   `--single-session` (Task Scheduler) or freshly started, so this
   particular "old process silently survives into the next day" path
   shouldn't recur.

**Follow-up (2026-07-22, third trading morning) — root cause found for a
third failure mode:** the pipeline hadn't started at all by 09:23 that
morning — no live_loop process running, zero rows for the day. This time
Task Scheduler's own history showed the 09:10 trigger simply never fired
(`Last Run Time` still showed the previous day's manual trigger). Root
cause: `schtasks /Create` silently defaults new tasks to
`DisallowStartIfOnBatteries=true` / `StopIfGoingOnBatteries=true` — this
machine is a laptop, and it was running on battery at 09:10, so Windows
refused to start the task at all (no error logged anywhere, it just quietly
doesn't fire). Fixed by clearing both settings on the existing task via
`Set-ScheduledTask` (`Get-ScheduledTask` → mutate `.Settings` → re-apply) so
it now runs regardless of AC/battery state. Manually triggered the task,
confirmed it started ticking, and backfilled the ~09:15→09:26 gap the same
way as before.

**Net effect of all three fixes**: the pipeline has now failed to
self-recover on its own three mornings in a row for three unrelated
reasons (stuck connection, console-window kill, battery restriction) —
none of them a bug in the trading logic itself, all operational/Windows
scheduling quirks. Worth treating §9 item 5 (health alerting) as higher
priority than originally framed, precisely because each of these was only
caught by manually checking rather than being surfaced automatically.

**Follow-up (2026-07-22, later that same day) — a fourth, genuinely
external outage:** an actual power shutdown broke the live loop after
09:59 (machine rebooted at 11:13, but nothing auto-restarted the pipeline
since the only Task Scheduler trigger was 09:10, already passed). By the
time this was reported the market had closed for the day, so no live
recovery was needed or possible -- `catch_up_today.py` was run once to
replay the full session from historical candle data; verified zero missing
minutes 09:15-15:29 in both `levels_snapshots` and `raw_candles` for both
symbols. Unlike the three above, this one has no code-level fix -- it's a
real power event, not a bug -- and reinforces the same §9 item 5 point:
every one of these four outages was caught by someone manually checking,
not by any automated signal.

**Follow-up (2026-07-24 → 2026-07-27) — expired Dhan token, plus a new
scheduler quirk, plus a genuine backfill-tooling gap:** the Dhan access
token expired again sometime after Wednesday 2026-07-23 (these tokens
appear to need regenerating every couple of days, not just once) — every
fetch failed with `DH-901 Invalid_Authentication` for the *entire* Friday
session (one stray SENSEX row, zero for NIFTY) and continued failing into
Monday morning. Separately, Monday's 09:10 scheduled trigger never fired at
all (Task Scheduler's own history still showed Friday's run) — the leading
theory is a Windows quirk in how `ScheduleByWeek`'s weekly recurrence
counts from an anchor date on a different weekday (the task was created on
a Tuesday; Monday 2026-07-27 was the first Monday encountered since);
recreating the task fresh with today as the anchor is the fix in place now,
unconfirmed until it's observed firing correctly on its own tomorrow.

This was also the first time a *fully missed past day* (Friday, not just a
same-day gap) needed recovering, and the existing `catch_up_today.py` only
knew how to replay "today." Generalized it: `pipeline/catch_up_today.py`
now exposes `catch_up_date(symbol, target_date, interval_min)`, with
`catch_up_today()` reduced to a thin wrapper calling it with today's date.
For a past date it skips the live option-chain fetch entirely (there's no
way to know a prior day's actual intraday OI from a live-only endpoint) and
leaves institutional bias "Unavailable (historical)", matching how the
original 60-day backfill already handles that. New CLI:
`scripts/run_catch_up_date.py YYYY-MM-DD [SYMBOLS...]`. Used it to replay
all of Friday (376 checkpoints/symbol) once the new token was in place,
then `catch_up_today.py` for Monday's gap, then restarted the live loop --
verified zero missing minutes across Wed/Fri/Mon (weekend correctly absent)
in `levels_snapshots` for both symbols.

## 9. Opportunities to consider for the next round

Existing backlog (unchanged from before, still not built):

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
   would expose it) plus a new frontend strike-ladder component. This is
   the same work as V2 roadmap item 3 (§6).
3. **Chart overlays (already scoped, not yet built)**: swings, trendlines,
   breakout boxes, and the volume-profile side panel — the backend detail
   endpoint (§5) already serves this data, it just isn't rendered yet.
4. **Historical/timeline browsing** — deferred from V1 scope by design (see
   original V1 plan); still not built.

New, surfaced by today's outage (§8) — operational/reliability gaps rather
than trading-analysis features, worth a look regardless of where V2 roadmap
attention goes next:

5. **Pipeline health alerting.** Today's gap was discovered by you noticing
   the dashboard, not by any automated signal. A cheap addition: a small
   watchdog (could live in the existing backend, or a separate scheduled
   check) that alerts (even just a Windows notification or a log written
   somewhere visible) if `now() - max(as_of)` exceeds a threshold during
   market hours.
6. **Mid-session self-healing.** The daily process-recycle (§8) shrinks the
   blast radius of the stuck-connection bug but doesn't prevent it
   happening again mid-day. A bounded fix: after N consecutive failures for
   a symbol, tear down and rebuild the `dhanhq` client's session before
   retrying, instead of retrying forever against the same broken one.
7. **Backend/frontend auto-start.** Only the data pipeline is scheduled now
   (§7/§8) — `uvicorn`/`vite` still need a manual start each session if you
   want the dashboard itself up automatically too.
8. **Dhan token freshness.** The access token has now expired twice in a
   week (§8), each time silently failing every fetch for hours before
   anyone noticed. Since regenerating it is a manual step only you can do
   (Dhan account access), the realistic fix isn't automation -- it's an
   early, specific warning: item 5's health check could distinguish "no
   data because the token expired" (the log already has the exact
   `DH-901 Invalid_Authentication` signature to match on) from other
   causes, so the alert says "go regenerate the token" instead of just
   "something's wrong."

## 10. Market Intelligence Engine (Phase 1, 2026-07-27)

**Origin:** a new, large requirement submitted 2026-07-27 — full text stored
verbatim in the `product_requirements` table (`db/writer.py::insert_product_requirement`,
CLI: `scripts/store_requirement.py`) for history/audit purposes, independent
of the trading data model. The full spec described an 8-service "AI-powered
Market Intelligence Engine" (News Collector, Event Classifier, AI
Correlation Engine, Historical Knowledge Base, Sentiment Engine, Market
Impact Engine, Alert Engine, Dashboard Service) that converts real-world
news (RBI policy, geopolitics, Fed/US data, earnings, etc.) into structured,
per-event trading intelligence — not a news feed, an inference layer.

**Scoping decisions made before building (all explicit, all mine to ask,
not mine to decide):**
- **News source**: free RSS feeds, not a paid news API.
- **AI provider**: Claude API, cheap model (`claude-haiku-4-5`) — the user
  adds `ANTHROPIC_API_KEY` to `.env` themselves; never handled by me.
- **Confidence integration**: **advisory only** — news risk is surfaced to
  the trader but never mutates the stored `confidence_score` or any other
  trading-engine field. The spec's literal ask ("automatically reduce trade
  confidence") was explicitly declined at this stage.
- **Build approach**: phased. Phase 1 = collect + classify + a "latest
  updates" dashboard panel. Correlation Engine, Historical Knowledge Base,
  Sentiment Engine (as a distinct service), Market Impact Engine (sector
  heat map beyond the lightweight client-side aggregate built below), Alert
  Engine, any wiring into the confidence score, scheduling/automation of
  the collector, and a full event-history page are all **explicitly
  deferred**, not forgotten.

**What Phase 1 actually built:**

New top-level `market_intelligence/` package (sibling to `analytics/`, same
"reusable, provider-independent" pattern):
- `models.py` — pure dataclasses `NewsItem`/`ClassifiedEvent` + enums
  (24-category `EventCategory`, `Sentiment`, `Duration`, `ImpactLevel`,
  `Direction`).
- `collectors/rss_collector.py` — `RSSCollector`, 5 verified-working free
  feeds (Economic Times Markets, Moneycontrol Markets, Moneycontrol
  Business, LiveMint Markets, CNBC-TV18 Markets). Business Standard (HTTP
  403) and Reuters India (DNS failure, feed likely discontinued) were
  tested and dropped from the original candidate list.
- `classifiers/claude_classifier.py` — `ClaudeEventClassifier`, Anthropic
  structured outputs (`output_config.format.json_schema`) against
  `claude-haiku-4-5`, inferring all 16 fields the spec asked for (category,
  severity 1-5, confidence, sentiment, duration, volatility impact,
  reversal probability, affected sectors/indices, expected direction for
  NIFTY/SENSEX/BANKNIFTY, recommended action, risk level, rationale) in one
  call per news item; sets `is_relevant=false` for routine non-market news.
- `pipeline.py::collect_and_classify()` — orchestrator: upserts every news
  item seen (cheap, makes reruns resumable), classifies only unclassified
  items, capped at `max_new_classifications` per run as an API-cost safety
  valve.
- `scripts/run_market_intelligence.py` — one-shot manual CLI (`--max-new`).
  **Not scheduled/automated yet**, matching the same "don't auto-schedule a
  new pipeline until reviewed" caution applied to Volume Profile
  Intelligence.

New DB tables (`db/schema.sql`): `news_items` (unique on
`source, guid`), `classified_events` (FK to `news_items`, one row per
classified item, all 16 inferred fields, `CHECK(severity BETWEEN 1 AND 5)`).

Backend (Repository → Service → Router, same pattern as every other
panel): `MarketIntelligenceRepository.list_recent()` (query-only, joined
load on the news item), `MarketIntelligenceService.get_latest()` computing
two **derived, advisory-only** aggregates —
`overall_sentiment` (severity × confidence-weighted majority vote) and
`news_risk_score` 0-100 (`mean(severity × confidence) / 5 × 100`) — neither
of which touches `confidence_score.py`, `trend_classifier.py`,
`decision_card.py`, or `institutional_bias.py` (verified zero diff on all
four). New endpoint `GET /api/v1/market-intelligence/latest`
(symbol-independent — news isn't per-index).

Frontend: new `MarketIntelligencePanel`, added to `TerminalPage` **below
the Option Chain panel**, per the spec's explicit placement instruction.
Polls every 60s (slower than the 15-20s dashboard/volume-profile polls,
since news changes slowly and doesn't depend on the selected symbol).
Shows, per the spec's panel-content list but scoped to "latest updates
only" (full history/timeline explicitly deferred to a later phase): overall
sentiment, news risk score, last-updated timestamp, a lightweight
client-side **sector heat map** (aggregated from each event's
`affected_sectors`, weighted by severity × confidence × sentiment-sign — no
new backend endpoint, computed from the same events list already
returned), and a card per high-impact event showing category, severity,
sentiment, the AI's rationale ("AI Interpretation"), duration/volatility/
reversal-probability ("Expected Market Impact"), per-index direction calls,
recommended action ("Trading Recommendation"), risk level, confidence, and
the event's own published timestamp ("Event Timeline" per-event, rather
than a separate aggregate timeline view).

**Tests**: 11 new pipeline-side tests (`tests/test_market_intelligence.py`
— RSS collector against monkeypatched `feedparser`, classifier response
parsing as a pure function independent of the live API, pipeline
skip/cap/empty-collection logic) + 3 new backend tests
(`backend/tests/test_market_intelligence_service.py` — empty state,
dominant-sentiment selection, risk-score scaling), all passing. All 65
existing pipeline tests and 19 existing backend tests unaffected.

**Verified live** (2026-07-27): RSS collection tested against real feeds
(304 items across 5 sources), DB round-trip tested, and
`GET /api/v1/market-intelligence/latest` curl-tested and browser-verified
end-to-end — correctly returns
`{"overall_sentiment": "Neutral", "news_risk_score": 0, "events": []}`
since `ANTHROPIC_API_KEY` is not yet in `.env`, so no classification has
run. **The `ANTHROPIC_API_KEY` env var must be added before real events
will appear** — collection/DB/service/panel are all wired and tested, only
the API key is outstanding, and that's the user's to add, not mine to
handle.

**Deferred, not forgotten** (do not start without a review/go-ahead):
Correlation Engine + Historical Knowledge Base (comparing new events
against historical reactions), a dedicated Sentiment/Market-Impact service
beyond the simple derived aggregates above, a real Sector Heat Map backed
by historical sector-reaction data (today's is a same-request client-side
aggregate, not a learned/historical one), Alert Engine, wiring news risk
into the actual `confidence_score`, scheduling `run_market_intelligence.py`
to run automatically, and a full event-history/timeline page.

## 11. Market Transition Intelligence (Phase 1, 2026-07-31)

**Origin:** a new research-engine requirement — discover, quantify, and
explain recurring intraday transition behaviour around 3pm (2:00-2:59pm
pre-window vs. the 3:00-3:01pm move vs. what happens 3:01pm-to-close),
using historical data to find genuine statistical predictors rather than
assuming any. Explicitly **not** a trading-signal engine and explicitly
independent of the decision engine, with an optional future path to
becoming an advisory confidence adjustment.

**Scoping decisions made before building:**
- **Tick data**: unavailable (Dhan only ever provides 1-min OHLCV, same
  constraint as the rest of this project) — built on 1-min candles.
- **OI/option-chain-based factors** (call/put writing, PCR trends) and
  news-risk amplification: **deferred**. `option_chain_raw`/`summary` only
  has 14 days of history (vs. 78 days of price history in `raw_candles`) —
  far too thin to claim anything statistically. Expiry-day effects
  (weekly/monthly) *were* included, since they're derivable purely from the
  calendar (see below), no option-chain dependency needed.
- **Methodology**: transparent statistical comparison (point-biserial /
  Pearson correlation, chi-square, Kruskal-Wallis via `scipy.stats`) plus a
  k-nearest-neighbor "historical analog" approach for per-day scoring —
  **not** a fitted ML model. With ~56-77 usable days, a fitted model would
  overfit and be far harder to explain; "here are the N most similar
  historical days and what actually happened" directly serves the stated
  goal of letting the user validate whether a pattern is genuine or
  anecdotal.
- **Explanations**: template-generated (deterministic, composed only from
  the computed numbers), not LLM-generated — an explicit decision so the
  tool can never narrate more certainty than the underlying stats support.
- **Expiry calendar verified live** (not from training-data memory, which
  would likely be stale — SEBI changed expiry-day rules multiple times
  through 2025): NIFTY weekly = Tuesday, monthly = last Tuesday of month;
  SENSEX weekly = Thursday, monthly = last Thursday; holiday-adjusted via
  the existing `pipeline/trading_calendar.py`. Effective since 2025-09-01,
  stable across this project's entire price-history window.

**What Phase 1 built** — new top-level `market_transition/` package
(sibling to `analytics/`, `market_intelligence/`), pure functions only, no
DB/network dependency in the analysis logic itself:
- `expiry_calendar.py` — weekly/monthly classification per date.
- `market_regime.py` — 3-category regime (Trending / Range-Bound /
  Volatile) from realized volatility vs. its own historical average (same
  pattern as Volume Pace) combined with `compute_rotation_factor`.
- `models.py` — pure dataclasses for features, outcomes, correlation
  results, and scores.
- `feature_extraction.py` — one day's pre-3pm features + 3pm transition +
  post-3pm outcome, reusing `analytics/vwap.py`, `volume_profile.py`, and
  `volume_profile_intelligence.py` directly (no duplicated logic). Skips
  (returns `None`) any day with a pipeline-outage gap spanning the window
  rather than fabricating a result from partial data.
- `statistics.py` — the correlation study: every factor tested against
  both **reversal** (does it predict which way the move breaks) and
  **magnitude** (does it predict how big the post-3pm move is).
  `confidence_label` requires both significance *and* n≥20 — a low p-value
  from a handful of days is labeled "Insufficient data", never "Strong".
- `scoring.py` — k-NN historical-analog scoring: finds the K most similar
  historical days (weighted by how significant each factor is, per the
  correlation study), reports the analogs' empirical outcome mix as
  Transition Risk Score / P(Reversal) / P(Continuation) / Expected
  Volatility / Expected Direction / Historical Similarity Score / top
  contributing factors / deterministic explanation.
- `research.py` + `scripts/run_market_transition_research.py` — one-shot,
  idempotent orchestrator: loads all `raw_candles` history, extracts every
  complete day, runs the correlation study, scores every day, upserts both
  results tables. Re-running as more days accumulate refreshes both the
  study and every day's score (expected/desired — a day's read can change
  as history grows).

New DB tables: `mti_daily_transitions` (one row per symbol/day — features,
outcome, and current score) and `mti_factor_correlations` (one row per
symbol/factor/target — the current study, overwritten each run, not a
history of past studies).

Backend: `MarketTransitionRepository` → `MarketTransitionService` → new
endpoint `GET /api/v1/market-transition/{symbol}/research`, same
Repository/Service/Router pattern as the rest of the app. Frontend: new
route `/market-transition-intelligence` — a two-table research dashboard
(factor correlation study; daily results with click-to-expand explanations)
— plus persistent nav links in `AppShell` (`Terminal` /
`Market Intelligence` / `Market Transition Intelligence`), the first real
navigation in the app beyond the single summary-bar link pattern.

**Real bug caught during verification, before shipping:** `scoring.py`'s
`expected_direction` initially only counted analogs where the *original*
3pm transition direction matched the *later* post-3pm direction (i.e., only
"continuation" analogs), silently excluding every "reversal" analog's real
post-3pm direction from the vote — the result was `expected_direction`
reading "Flat" for nearly every one of the 77 days, caught by eyeballing
the live table (25 Flat/33 Up out of 77 before the fix vs. a healthy
25-down/22-flat/30-up split after). Fixed to use the actual sign of
`post_transition_move` directly, re-ran the research script to refresh
persisted scores, re-verified live in the browser.

**Verified on real data (2026-07-31):** 77 complete trading days extracted
per symbol (out of 78 available `raw_candles` days — one excluded for an
incomplete window). Current finding, honestly reported: **no factor has
reached Strong/Moderate confidence yet** — the two closest (2-3pm volume
slope, VWAP distance at 2:59pm, both vs. reversal) sit at p≈0.07-0.09,
correctly labeled "Weak", not oversold. This is the expected, correct
behavior for a ~2.5-month-old dataset, not a bug — the engine is designed
to say "not enough evidence yet" rather than manufacture false confidence,
and real signals should sharpen as more trading days accumulate via the
same orchestrator script.

**Zero diff** verified on `confidence_score.py`, `trend_classifier.py`,
`decision_card.py`, `institutional_bias.py` — this module reads
`raw_candles` history and writes only its own two new tables.

**Deferred, not forgotten:** OI/option-chain-based factors and news-risk
amplification (both revisit-worthy once `option_chain_raw` has months of
history), any wiring of a transition score into the live confidence score
(explicitly optional/future per the original ask), scheduling
`run_market_transition_research.py` to run automatically (currently
manual-only, same caution applied to every new pipeline in this project
until reviewed), and a dedicated Historical Knowledge Base beyond the
per-run k-NN analog search.

## 12. Live Market Transition Advisor (2026-07-31)

**Origin:** a follow-on to §11's historical engine — consume today's
in-progress 2:00-3:01pm session and compare it against the stored
historical MTI database in real time, before the 3pm event happens, so the
trader can see whether today is starting to resemble a known pattern.
Explicitly not a trading signal: output is capped to
Observe/Low/Medium/High/Very High transition risk plus a confidence label,
no buy/sell language anywhere, and the module only *reads* the historical
database — it never writes to it and never touches the trading decision
engine. Placed at the top of the Market Transition Intelligence page per
explicit instruction.

**Two upstream fixes made before building this, both driven by direct
user questions/observations:**
- **`statistical_confidence` was reading "Weak" for all 77 historical
  days.** Root cause: the label only depended on the *global* count of
  statistically-significant factors from the correlation study (currently
  2, for the whole 77-day dataset) — applied identically to every single
  day regardless of how well that specific day's analogs actually matched.
  Fixed by blending the global factor count with each day's own
  `historical_similarity_score`, so confidence now genuinely varies
  per-day (re-running the research script shifted the real distribution
  from 77×"Weak" to 6×"Weak"/71×"Moderate" on SENSEX). Will keep
  improving further as more days accumulate and more factors cross
  significance, but no longer *only* depends on that.
- **`feature_extraction.py` refactored** to expose
  `compute_pre_window_features(..., pre_window_end=<any time>)` as its own
  function (defaulting to the historical engine's fixed 14:59, so
  `extract_daily_transition_record`'s behavior is byte-for-byte unchanged
  and all existing tests still pass unmodified) — this is what lets the
  live advisor compute the *same* kind of features from a partial,
  still-forming session at any point during 14:00-14:59, not just at the
  end of a complete day.

**What was built** — `market_transition/live_advisor.py`, reusing
`scoring.py`'s k-NN engine wholesale (`find_analogs`, `score_day`, newly
exported publicly) rather than re-implementing similarity/probability
logic. The only genuinely new pieces:
- **Transition stage** from the clock: Not Yet Active / Pre-Transition
  Monitoring / Transition Window / Post-Transition Follow-Through /
  Session Complete. The advisor only produces a scored read during
  Pre-Transition Monitoring through Transition Window (2:00-3:01pm);
  outside that it reports `is_active=false` with just the stage and
  secondary context.
- **Expected Timing of Transition** — genuinely new analysis, not derived
  from anything already stored: for each of the K historical analogs,
  fetches a padded ~14:50-15:10 candle window and finds the first minute
  price moved at least 40% of that day's eventual post-transition move in
  the matching direction (the "onset"), then reports the earliest-latest
  range across analogs with a detectable onset (falls back to "expect it
  around the 3:00 PM window" if fewer than 3 analogs have one).
- **Estimated Move** — signed mean of the analogs' `post_transition_move`,
  distinct from the historical engine's `expected_volatility` (which is
  the unsigned average magnitude); this is the point estimate, that's the
  dispersion.
- **Transition Risk Level** — a documented heuristic (same "reasonable,
  explained heuristic" spirit as Profile Shape/Opening Type elsewhere in
  this codebase): `0.6 × decisiveness + 0.4 × historical_similarity`,
  where decisiveness is how far the reversal probability sits from 50/50.
  Always "Observe" outside the active window or below the minimum analog
  count.
- **Trader-language explanation** — deterministic template (not LLM, same
  decision as the historical engine), composed to match the user's
  example style: "*Today's market currently resembles N previous sessions
  where X; in Y of those the market reversed around Z; current reversal
  probability is estimated at P%; news risk remains ...*"

**Contextual, not scored:** institutional bias (`levels_snapshots.institutional_bias_label`,
already computed live) and news risk/sentiment (existing Market
Intelligence engine) are surfaced in the explanation and as separate
fields, but are **not** weighted into the k-NN similarity or probability
computation — consistent with the historical engine's own deferral of
OI-based factors (still only ~2-3 weeks of `option_chain_raw` history,
nowhere near enough to weight anything statistically). If confidence in
those factors builds over months, revisit; for now they're informational
context only, matching this whole module's "advisory only" design.

**Packaging fix required:** `market_transition` (and, transitively via
`expiry_calendar.py`'s holiday-adjustment logic, `pipeline.trading_calendar`)
had to be added to the root `pyproject.toml`'s installable packages list
and reinstalled (`pip install -e .`) into *both* venvs — the historical
engine never needed this since its only consumer was pipeline-side
scripts, but the live advisor's backend service reuses `market_transition`'s
pure functions directly (same pattern as `VolumeProfileIntelligenceService`
reusing `analytics/`), so the backend's separate Python 3.14 venv needed
it too. `scipy` was missing from `backend/requirements.txt` for the same
reason and has been added.

**Backend:** `LiveTransitionAdvisorService` composes four repositories
(candles, the historical MTI database, levels snapshots for institutional
bias, market intelligence for news) — same multi-repo composition pattern
as `DashboardService`. New `CandleRepository.list_between(symbol, start, end)`
added (existing `list_since` is open-ended, unsuitable for fetching a
single analog day's narrow candle window without pulling in every day
since). New endpoint `GET /api/v1/market-transition/{symbol}/live-advisor`.

**Verified:** 26 new `market_transition` unit tests (transition stage
boundaries, live query building/clamping, timing-onset detection,
risk-level thresholds, end-to-end k-NN scoring on synthetic known-correlation
data) + 3 new backend service tests (unknown symbol, inactive-outside-window,
active-scored-result — the latter two via monkeypatching `datetime.now()`
in the service module, since real wall-clock time can't be relied on to
land inside the 2:00-3:01pm window during a test run). All 132 pipeline +
27 backend tests pass. Live-curl-verified against the running backend at
13:38 (before 2pm): correctly returned `is_active: false`, `stage: "Not
Yet Active"`, `risk_level: "Observe"`, while still surfacing institutional
bias ("Bullish") and news risk (39/100, Neutral) as background context —
confirming those secondary signals work independent of the core advisory's
active state. The "active, scored" path was verified via an ad-hoc
real-data simulation (today's real 2026-07-30 candles sliced to 14:20,
compared against the real 77-day historical database) rather than live at
market time, since building landed before 2:00pm; results were coherent
(similarity 84%, confidence "Moderate" matching the new blended formula,
5 nearest analogs all plausible dates) and the same code path is exercised
by the monkeypatched backend test.

**Zero diff** verified on `confidence_score.py`, `trend_classifier.py`,
`decision_card.py`, `institutional_bias.py`.

**Follow-up (2026-07-31, later same day) — active window extended through
market close.** User reported the advisor's output reverted to "not enough
data" right after 3:01pm and asked whether that was expected, requesting it
stay visible through the end of the session instead. Root cause: `determine_transition_stage()`
already had a "Post-Transition Follow-Through" concept, but `is_advisor_active()`
gated on the stricter `PRE_WINDOW_START..TRANSITION_END` (14:00-15:01), so
that stage never actually produced a scored result. Fixed by extending
`FOLLOW_THROUGH_END` from 15:20 to `time(15, 30)` (session close) and
aligning `is_advisor_active()` to match; the score itself stays frozen at
the 14:59 pre-window read (unchanged), just visible longer, with an added
explanation note during follow-through: *"This reflects the pre-transition
read (frozen at 2:59 PM) -- compare it against how price actually moved."*
Updated `tests/test_live_advisor.py`'s stage/active-window parametrize
tables and added `test_build_live_advisory_stays_active_through_follow_through`.
All 162 tests (135 pipeline + 27 backend) passed at the time.

**Follow-up (2026-07-31, later same day) — forecast-vs-actual tracking +
chart arrow.** User asked for two things: (1) a way to see, per day,
whether the pre-3pm forecast matched what actually happened, and (2) a
simple directional arrow on the price chart reflecting the live forecast.

*Forecast vs actual* turned out to need no new persistence: every
historical day in `mti_daily_transitions` already carries both a forecast
(`probability_reversal`/`probability_continuation`, computed via the same
leave-one-day-out k-NN scoring as the live advisor) and the actual
`outcome` — the historical engine effectively re-forecasts every day
against the others when it scores it. `MarketTransitionService._to_daily_dto`
now derives `predicted_outcome` (whichever probability is higher; `None`
on a dead-even split) and `forecast_correct` (matches `outcome`, but
`None` when `outcome == "neutral"` — grading a directional call against a
no-significant-move day isn't a fair test). `get_research()` aggregates
these into `forecast_evaluable_days`/`forecast_hit_count`/`forecast_accuracy_pct`
on the response. Frontend: "Predicted" + "Match" columns added to the
Daily Transition Results table, plus an accuracy summary line. Live on
SENSEX at build time: 59.6% (28/47 directional days).

*Chart arrow*: `TerminalPage` now also polls `useLiveTransitionAdvisor`
(already built for the MTI page) and passes it into `CandlestickChart` →
`useCandlestickChart`, which draws one additional marker at the latest
candle — up/down arrow colored by `expected_direction` (already the
correct signal: it's the actual sign of analogs' post-transition moves,
so a reversal against an uptrend already resolves to a down arrow with no
separate trend-vs-lean combination needed) with the risk level and
reversal-vs-continuation lean in the marker text; a neutral circle when
`expected_direction == "flat"`. Only drawn while the advisor is active
with a non-"Observe" read, so the chart stays clean the rest of the day —
verified negatively today, since the session crossed 15:30 (market close)
during testing and the marker correctly stayed absent (`is_active: false`,
`risk_level: "Observe"`).

Both pieces are additive/derived-only — no schema changes, no new writes,
`CandlestickChart`'s existing callers unaffected (`liveAdvisory` defaults
to `null`). 10 new backend tests for the forecast-grading logic (tie/null
probabilities, neutral-outcome exclusion, multi-day aggregation) — all 33
backend + 135 pipeline tests pass; `npx tsc -b` clean.

**Deferred, not forgotten:** OI/call-writing/put-writing as *scored*
(not just contextual) factors once `option_chain_raw` has enough history;
allowing this advisor to adjust the live trading confidence score
(explicitly future/optional per the original ask, never done here);
scheduling anything automatic (this is entirely on-demand/read-time, no
new scheduled task was added).

**Follow-up (2026-07-31, same day, ~14:38 IST):** the user reported the
panel stuck showing "only produces a read between 2:00 PM and 3:01 PM"
*while it actually was 2:38 PM* — a real bug, not the expected pre-2pm
state. Root cause: **`asyncpg` (the backend's async driver) returns
`TIMESTAMPTZ` columns tagged as UTC regardless of the column's actual
value, unlike `psycopg` (the sync pipeline's driver), which correctly
tags them IST.** The underlying instant was always correct, but
`market_transition`'s pure functions compare `.dt.time` against clock
constants (`time(14, 0)`, etc.) — with candles mislabeled as UTC, a real
14:38 IST reading showed as 09:08, permanently below every window
threshold. This is a new class of bug specific to the live advisor: no
earlier backend service ever compared `.dt.time` against a clock
threshold (only date-level grouping, which coincidentally still works
under the mislabeling since IST's +5:30 offset never crosses a date
boundary during market hours) — so it was never surfaced before. Fixed
by converting to IST once, at the ORM-row-to-DataFrame boundary, in
`live_transition_advisor_service.py::_candles_to_df`
(`r.timestamp.astimezone(settings.ist)`), rather than touching the shared
DB engine config (narrower blast radius, only affects this service).

Caught in the same pass: `ContributingFactor.today_value` was an
unrounded `str(float)` (e.g. `"-0.024586044683282456"`), landing directly
in the trader-language explanation text — not the clean read the whole
point of this feature was to produce. Fixed to format continuous values
to 2 decimal places at the source (`scoring.py::_top_contributing_factors`),
so both this page and the historical daily-results panel benefit.

Also hit an operational snag applying the fix: `uvicorn --reload`
auto-picked up the `_candles_to_df` change (inside `backend/`) but not
the `scoring.py` change (in the external `market_transition/` package,
imported via the editable install) — reload only watches the directory
it's run from. Had to manually kill and restart the backend process, and
in doing so discovered the very first `Stop-Process` had silently failed
to kill the old process (leaving two servers bound to :8000
simultaneously, with curl nondeterministically hitting whichever). Fully
verified only after confirming exactly one PID owned the port. Live-verified
end-to-end afterward: correct `is_active: true`, real analog matches,
onset-based timing estimate ("between 2:50 PM and 3:04 PM"), and clean
`0.10`/`0.04`-formatted explanation text, both via curl and in the browser.
All 132 pipeline + 27 backend tests still pass.

## 13. Trend alarm sound (2-candle Bullish/Bearish streak) (2026-07-31)

User asked for an audible alert when `trend_label` (from `analytics/trend_classifier.py`'s
5-level scale: Strong Bearish/Bearish/Neutral/Bullish/Strong Bullish) reads
Bullish or Bearish for 2 candles in a row, with a distinct sound for the
Strong variants. Frontend-only — no backend or schema change; `trend_label`
was already served on every `/api/v1/dashboard/{symbol}/latest` poll.

**"2 candles" interpretation**: tracked across consecutive dashboard polls
(20s cadence against the live pipeline's 1-min snapshot cadence) rather
than the chart's 5-min resampled bars, since there's no existing way to
read back a short history of `trend_label` at chart-candle granularity
without new backend work — this is the same signal already reaching the
frontend today, just watched for two-in-a-row persistence in the same
Bullish/Bearish family.

**New files:**
- `frontend/src/utils/trendAlertSounds.ts` — two beeps synthesized via
  Web Audio API (`AudioContext`/`OscillatorNode`), not sampled audio
  files: a single 660Hz tone for plain Bullish/Bearish, a louder
  880Hz double-beep for Strong Bullish/Strong Bearish so the two are
  distinguishable by ear. `unlockTrendAlertAudio()` resumes a suspended
  context (browsers block audio until a user gesture has occurred
  somewhere on the page) — called opportunistically on every play attempt
  and from the mute-toggle click.
- `frontend/src/hooks/useTrendAlert.ts` — the streak logic. Depends on
  both `trendLabel` **and** `dataUpdatedAt` (TanStack Query's per-fetch
  timestamp) — depending on `trendLabel` alone would never re-fire the
  effect while the label stays unchanged across several polls in a row,
  which is exactly the common case this needs to detect. Fires once when
  a Bullish/Bearish family streak reaches 2, and again only on
  *escalation* to Strong within the same streak (tracked via an
  `alertedRank` 0/1/2 so a de-escalation back to plain Bullish/Bearish, or
  the streak just continuing at the same strength, never re-fires or
  nags). Resets on Neutral or a family flip, and on the selected symbol
  changing.
- `frontend/src/store/useAlertSoundStore.ts` — tiny Zustand store, one
  `enabled` boolean + `toggle()`, no persistence (defaults on each
  session load, matching "don't add what wasn't asked for").

**Wired into `AppShell.tsx`** (not `TerminalPage`) so the alarm fires
regardless of which page the trader currently has open — polls
`useDashboardData(selectedSymbol)` at the shell level, sharing the same
TanStack Query cache entry `TerminalPage` already uses (same `queryKey`,
so no extra network requests). A small speaker icon button next to the
nav links mutes/unmutes and doubles as the audio-unlock gesture.

**Verified:** `npx tsc -b` clean; browser check confirmed no console
errors, the mute toggle flips state correctly (label swaps "Mute trend
alarm..." <-> "Unmute trend alarm") with no `AudioContext` errors. Since
the market was closed at build time (`trend_label` static for the rest of
the session, can't observe a real live streak), the streak/escalation
logic itself was verified by running the exact algorithm in the live page
context via 8 scenarios (2-candle fire, no-fire-on-1-reading,
escalate-to-strong-fires-again, no-repeat-at-same-strength,
no-refire-on-de-escalation, reset-then-rearm-after-neutral,
family-switch-resets, direct-2-candle-strong) — all 8 matched the
intended behavior exactly. No frontend test runner exists in this repo
yet (`npm run build`/`tsc -b` + manual browser checks is the established
verification pattern here), so this was the most direct feasible check
short of adding one. Backend/pipeline test suites (33 + 135) untouched
and still pass, as expected for a frontend-only change.

## 14. SEBI/NSE market-close time change (2026-08-03) — SESSION_CLOSE 15:30 -> 15:40

User asked (1) whether the pipeline had stopped -- it hadn't, `raw_candles`
was current to the same minute as wall-clock time for both symbols -- and
(2) to check whether a same-day regulatory timing change affected the
tool's closing-time assumptions. It does: effective 2026-08-03, NSE
extended the F&O session close from 3:30 PM to 3:40 PM (10-minute
extension, applies to both index and stock derivatives -- covers
SENSEX/NIFTY options, this tool's actual instruments), introduced alongside
a new cash-market Closing Auction Session (continuous trading to 3:15 PM,
auction 3:15-3:35 PM for F&O-eligible stocks) and a widened derivative
VWAP window (3:10 PM-3:40 PM, was 3:00 PM-3:30 PM). Sources: [Groww](https://groww.in/blog/nse-extends-f-and-o-trading-hours-by-10-minutes-new-timings-effective-from-august-3-2026),
[Flattrade Kosh](https://flattrade.in/kosh/nse-extends-fo-trading-hours-till-340-pm-from-august-3-2026-what-it-means-for-traders/),
[Outlook Business](https://www.outlookbusiness.com/markets/sebi-closing-auction-session-new-stock-market-timings-from-august-3).

**Fixed (mechanical, low-risk):** `config/settings.py::SESSION_CLOSE`
"15:30" -> "15:40" -- governs `pipeline/live_loop.py`'s daily exit time
and the backend's `is_market_hours` computation (`backend/app/core/config.py`
re-exports the same constant; `dashboard_service.py` derives
`is_market_hours` from it, no separate edit needed there). Also bumped
`market_transition/live_advisor.py::FOLLOW_THROUGH_END` (15:30 -> 15:40)
so the Live Advisor's follow-through display stays visible through the
new close instead of reverting to dormant 10 minutes early. Updated the
matching boundary tests in `tests/test_live_advisor.py`
(`test_determine_transition_stage`, `test_is_advisor_active`). All 135
pipeline + 33 backend tests pass.

Today's already-running `live_loop` process (started 09:10, `--single-session`)
had the old 15:30 baked in at import time -- a file edit alone wouldn't
have applied to it today, only tomorrow's fresh Task-Scheduler-launched
process. Restarted it cleanly today (precisely identified PIDs 38460/3020
by `CreationDate`+`CommandLine` before killing, replicated the exact
invocation `run_live_loop_daily.bat` uses: `python.exe scripts/run_live_loop.py
SENSEX NIFTY --single-session >> logs/live_loop_daily.log 2>&1`) so
today's session also collects through 15:40 instead of stopping at 15:30
and needing a manual catch-up backfill afterward. Confirmed zero data gap
(last snapshot under the old process at 15:16, first under the new one at
15:17) and confirmed the new process holds `SESSION_CLOSE == "15:40"` in
memory. Also cleaned up an unrelated dangling backend process tree left
over from the 2026-07-31 session (PIDs 26348/34332/25820, 3 days stale,
not the one actually bound to :8000) while investigating.

**Deliberately NOT changed:** the Market Transition Intelligence engine's
`PRE_WINDOW_START`/`PRE_WINDOW_END`/`TRANSITION_START`/`TRANSITION_END`
(14:00/14:59/15:00/15:01 in `market_transition/feature_extraction.py`).
These anchor the entire "2:00-3:01pm transition" research thesis across
77+ days of existing historical data (originally chosen as roughly
30-minutes-before-the-old-3:30-close). Whether to shift this window (e.g.
to preserve "~30 min before F&O close" under the new 3:40 close) is a
methodology decision, not a mechanical constant fix, and changes the
meaning of every historical day already scored -- flagged for the user to
decide rather than changed silently.

## 15. Dhan access-token expiry + a real catch-up-loop bug (2026-08-04)

User asked to check the pipeline. It was down for the entire session so
far (`live_loop` running since 09:10 but every fetch failing since
09:15:08 with `DH-901 Invalid_Authentication` -- confirmed via
`raw_candles` still stuck at yesterday's 15:39 close). This is expected,
recoverable Dhan behavior (access tokens expire and must be regenerated
through their portal, not a code bug) -- reported it and asked the user to
regenerate. They did; verified the new token directly with a standalone
`fetch_intraday_candles` call (got real candles through 09:24) before
touching anything, then restarted `live_loop` (the already-running
process had the expired token baked in at import time, same class of
issue as the SESSION_CLOSE fix in §14 -- a `.env` edit alone doesn't reach
an already-running process).

**Real bug found and fixed while backfilling the ~9-minute gap this left
in `levels_snapshots`** (raw candles had no gap -- Dhan's intraday
endpoint returns the whole day per request, so the first successful fetch
retroactively filled `raw_candles` for free): `scripts/run_catch_up_today.py`
produced 807 log lines and took ~35s for what should've been a ~10-checkpoint
job. `pipeline/catch_up_today.py::catch_up_date()` loops
`generate_checkpoint_times()` (strictly ascending, session-open to
session-close) and filters `day_df_full` to `<= cutoff` each time. Once
`cutoff` passes the latest actually-fetched candle, that filter does
**not** become empty like the old docstring claimed -- it just returns
every candle up to the real latest one again, identical to the previous
iteration, so `run_snapshot()` recomputed and rewrote the exact same "now"
snapshot for every remaining checkpoint through session close (376 repeats
of `09:25:00` alone for SENSEX). Harmless to final DB state (idempotent
upsert on `(symbol, as_of)`, confirmed `COUNT(*) == COUNT(DISTINCT as_of)`
after the fix), but pure wasted computation and log noise every time this
script has ever been run mid-session -- predates today's SESSION_CLOSE
change, which only made the checkpoint list 10 minutes longer.

**Fixed**: compute `latest_available = day_df_full["timestamp"].max()`
once before the loop; `break` (checkpoints are strictly ascending, so
nothing later can differ) once `cutoff > latest_available`, instead of
relying on a truncation-emptiness check that never actually fires for
today's in-progress-session case. Re-ran live to verify: SENSEX went from
386 checkpoints/~35s (old, buggy) to 14 checkpoints/~10s (fixed, matching
the 14 real minutes elapsed since open); NIFTY similarly to 15. No
existing test coverage exists for this class of orchestration script in
this repo (only pure-function analytics/market_transition/backend layers
are unit-tested; `run_snapshot`/`backfill`/`catch_up_today` aren't, and
adding a full external-API/DB mock harness for one loop-boundary fix
wasn't judged worth the new precedent) -- verified via the live re-run
instead. All 135 pipeline tests (untouched by this change) still pass.
