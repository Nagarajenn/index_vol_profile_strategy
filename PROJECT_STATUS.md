# Project Status — Sensex/Nifty Options Decision-Support Tool

_Last updated: 2026-07-22_

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
| 5 | Volume Profile Interpretation | Not started |
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

Items 2–10 are intentionally **not scoped yet** — each gets its own design
pass when its turn comes, per the stated one-at-a-time process.

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
