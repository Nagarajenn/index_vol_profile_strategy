# Milestone 13 — Live Trading (Dhan) for NIFTY / SENSEX options

**Status: PLAN ONLY. Nothing in this document is built. No order code exists in the repo today.**

Written 2026-09-23 during market hours, for implementation after the close, at the trader's
request: *"a UI that will do direct trading from dhan for nifty and sensex... from tomorrow we
will start take 1 or 2 trading per day live."*

---

## 0. What the evidence says, recorded here so it is not lost later

This project's own research is the reason the caps in §4 are hard-coded rather than configurable:

| Milestone | Finding |
|---|---|
| 11A–11C | No validated directional edge; no validated option-expression rule. |
| 12A | Shadow-only; the research gate has not been passed. |
| 12B | Option-chain closing-state warnings are **not selective** — they do not beat a majority-direction base rate. |
| 12C | WAIT 55.9%; a BUY is a *state* (~61 episodes/symbol-day, median 2 min), not a trade list. |
| 12C sim (2026-09-23) | 27 hypothetical positions: SENSEX +₹375, NIFTY −₹341, single trades from −₹479 to +₹390. Pre-cost. |

**This layer is therefore built to survive being wrong, not to scale a proven signal.** The live
result should be treated as a further experiment with real money, and the daily loss-stop is the
feature that matters most.

---

## 1. Decisions taken (trader, 2026-09-23)

| Question | Decision |
|---|---|
| Who confirms each order | **Agent places automatically on a 12C signal** — no click in the loop |
| What the agent decides | **Entry only.** The exit stays with the trader |
| Hard caps | **2 entries/day, exactly 1 lot, day halts after the first realised loss** |

Two consequences of that combination are called out in §7 and need an explicit answer before the
first live session.

---

## 2. Impact on the existing pipeline

The honest answer to *"will this impact the current pipeline"*: **it does not have to, and the plan
is built so that it does not.** Four existing guarantees must survive untouched.

| Existing guarantee | How it is preserved |
|---|---|
| `paper_trading/` physically cannot reach a broker (`safety.py` + `tests/test_paper_safety.py` scan the package source for `place_order`, `dhan_client`, `dhanhq`) | The live package is **separate**. Not one line of `paper_trading/` changes. Its scan keeps passing. |
| 12A / 12C / HR / Opportunity-Matrix tests assert no order API is reachable | Those tests keep passing unchanged. A **new** allowlist test asserts `live_trading/` is the *only* package where order fragments may appear. |
| The FastAPI backend is read-only (`allow_methods=["GET"]`, "never writes to the DB") | The read-only backend is **not modified**. Control actions go to a **separate** local-only service on its own port. |
| The 1-minute live loop must never be blocked or crashed by anything downstream | The trader runs as a **separate process**. It never imports the live loop and the live loop never imports it. They coordinate only through Postgres. |

Net pipeline impact: **one new table group (`live_*`), one new process, one new local service, one
new frontend page.** Zero edits to data capture, analytics, 12A/12B/12C decision logic, or the
existing backend.

---

## 3. Architecture

```
  pipeline/live_loop.py  ──writes──>  option_chain_raw / raw_candles / levels_snapshots
        (unchanged)                            │
                                               │ reads (SELECT only)
                                               ▼
                              scripts/run_live_trader.py        ← NEW process
                                   live_trading/
                                     ├─ guards.py      hard caps, checked per order
                                     ├─ contracts.py   strike -> security_id (scrip master)
                                     ├─ broker.py      the ONLY file that calls dhanhq orders
                                     ├─ trigger.py     12C signal -> entry candidate
                                     ├─ state.py       arm / halt / position, in live_* tables
                                     └─ journal.py     every intent + every response, append-only
                                               │
                              ┌────────────────┴────────────────┐
                              ▼                                 ▼
                    Dhan order API                    live_orders / live_positions
                                                                │
                                        backend_control/ (NEW, 127.0.0.1 only, POST allowed)
                                                                │
                                                     frontend  /live-trading
```

### Why a separate process, not a thread in the live loop
A blocked HTTP call to a broker must never stall the 1-minute data capture that every other
milestone depends on. Separate processes make that structural rather than careful.

### Why a separate control service, not the existing backend
The existing backend's read-only guarantee is documented, tested and relied on. Adding POST to it
would quietly convert it into a write path for the whole dashboard. The control service is a
~150-line FastAPI app bound to `127.0.0.1`, serving only: arm, disarm, kill, exit-now, and status.

---

## 4. Hard caps — code, not configuration

`live_trading/guards.py`. Every one of these is checked **immediately before** the order call, in
one function, against freshly read state. Failing any check returns a refusal that is journalled.

| # | Guard | Rule |
|---|---|---|
| 1 | Trade count | Max **2 entries per session date**. Counted from `live_orders`, not memory. |
| 2 | Size | Exactly **1 lot**, quantity from the scrip master. If lot size is UNKNOWN → refuse. |
| 3 | Loss halt | After the **first realised loss** of the day, the session is halted. No further entries. |
| 4 | One at a time | Refuse any entry while a live position is open. |
| 5 | Arm token | Disarmed on process start. The trader arms the day in the UI; caps hit → auto-disarm. |
| 6 | Kill switch | A DB flag checked before every order. Set from the UI, takes effect immediately. |
| 7 | Time window | No entry before **09:45** or after **14:45** (§7.2). Never inside the 15:15 freeze. |
| 8 | Data freshness | Refuse if the latest option snapshot is older than **2 minutes**. |
| 9 | Spread | Refuse if the leg's bid-ask spread exceeds the configured ceiling. |
| 10 | Capital | Refuse if entry value exceeds the configured per-trade rupee cap. |
| 11 | Idempotency | Every order carries a correlation id derived from `(symbol, date, signal_minute)`. A repeat is refused, not re-sent. |

Guards 1, 2 and 3 are the trader's stated decision and are **not** read from a config file — changing
them is a code change that must fail a test, the same pattern `paper_trading/safety.py` already uses.

---

## 5. The order itself

Verified against the installed SDK and the cached scrip master today:

```
place_order(security_id, exchange_segment, transaction_type, quantity, order_type,
            product_type, price, trigger_price=0, ..., tag=None)
```

| Field | Value | Source |
|---|---|---|
| `security_id` | e.g. `839161` | `SEM_SMST_SECURITY_ID`, resolved from the scrip master by (symbol, expiry, strike, CE/PE). Verified unambiguous: SENSEX 24-Sep 74700 CE → 839161, lot 20, tick 0.05. |
| `exchange_segment` | `BSE_FNO` / `NSE_FNO` | `config/instruments.py`, already present |
| `transaction_type` | `BUY` | entry only |
| `quantity` | 1 lot | `SEM_LOT_UNITS`, never hard-coded |
| `order_type` | **LIMIT**, priced at ask + 2 ticks | see below |
| `product_type` | `INTRADAY` | |
| `tag` | correlation id | links the order back to the 12C decision minute |

**LIMIT, not MARKET.** A market order on an index option during a spread blowout is the single
cheapest way to lose money for no reason. A marketable limit at ask + 2 ticks fills in normal
conditions and simply *fails* in abnormal ones — which is the correct behaviour. An unfilled order
is cancelled after a configured number of seconds and journalled as `NOT_FILLED`.

---

## 6. Database (`live_*`, package-owned schema file; `db/schema.sql` stays frozen)

- **`live_orders`** — append-only. One row per *intent*, whether or not it reached Dhan: correlation
  id, symbol, contract, security id, side, qty, limit price, the 12C decision + evidence snapshot
  that triggered it, every guard's verdict, the broker request, the broker response, status.
  Nothing is ever updated except the status/fill fields.
- **`live_positions`** — open/closed live positions, entry and exit, realised P&L, the exit route
  (trader-initiated / cancelled / rejected).
- **`live_session_state`** — one row per (symbol, date): armed, halted, halt reason, entries used.
- **`live_journal`** — every refusal with its reason, so a day with no trades is as explainable as a
  day with two.

`live_positions` is what feeds the daily loss-halt in guard #3, so it must be written before the
next signal can be evaluated.

---

## 7. Two risks in the chosen combination that need an answer before going live

### 7.1 Auto-entry + manual exit leaves a position with no automatic protection
The agent will open a position by itself, but nothing closes it. If attention lapses — a meeting, a
dropped connection, a phone call — a long weekly option can decay hard, and on expiry day it can go
to zero. The stated design has no automated floor under that.

**Recommendation (needs your yes/no):** add **one** agent-initiated exit — a hard force-flat at
**15:10** — and nothing else. It does not second-guess your exit; it only guarantees no live position
survives the session. It is the smallest possible violation of "I manage the exit" and it removes
the worst tail.

A second option, if you would rather the broker hold the floor: place a **broker-side stop-loss
order** with the entry (`place_super_order`). That protects against disconnects too, but it is a
materially larger build and adds order-modification paths, so I would not do it for day one.

### 7.2 A 2-trade cap plus an always-on trigger takes the *earliest* signals, not the best
12C produces ~61 BUY episodes a symbol-day. With auto-entry, the first two episodes consume both
slots — today that would have been **09:20 and 09:22**, inside the opening noise, purely because
they happened first. The cap does not select good trades; it selects early ones.

**Recommendation (needs your yes/no):** three qualifiers before an auto-entry, which allocate the two
scarce slots rather than change any threshold:
1. Confirmation must be **STRONG** (not MODERATE/WEAK).
2. The BUY state must have **persisted ≥2 consecutive minutes** (an episode, not a flicker).
3. **No entry before 09:45** — the opening 30 minutes are where the simulation's worst single loss
   (−₹479 at 09:54) and most churn sit.

These are risk-allocation rules, not signal tuning — no 12C threshold changes. But they *will* change
which trades happen, so they need your explicit sign-off, and I will report their effect against the
stored simulation history before the first live session rather than after.

---

## 8. UI — `/live-trading` (new page)

Built in the same idiom as the Scalping Decision panel, because that is the reading order you have
been using all session.

1. **State bar** — ARMED / DISARMED / HALTED, entries used (0 of 2), the halt reason in words, the
   kill switch, and an unmissable **LIVE — REAL MONEY** marker in a colour used nowhere else.
2. **The decision** — the same 12C card: BUY CE / BUY PE / WAIT, confirmation, WHY?, supporting /
   contradicting / blocking, evidence chips.
3. **Why no order** — when the decision says BUY but no order was placed, the guard that refused it,
   named. This is the panel's most important job on a normal day.
4. **Live position** — contract, entry fill, quantity, live bid, unrealised P&L, MFE/MAE, and the
   risk brake's HOLD / CAUTION / PREPARE EXIT / EXIT as **advice**, plus a large **EXIT NOW** button
   (your exit, one confirm step).
5. **Today's live orders** — every intent including the refused ones, with its correlation id.
6. **Closed live positions** — the same table shape as the simulation history, so live and simulated
   results are read side by side in the same format.

The arm control requires an explicit confirm; the page renders DISARMED on every load.

---

## 9. Build order (after market close; nothing here runs during a session)

| Step | Work | Gate |
|---|---|---|
| 1 | `live_trading/` skeleton, `live_*` schema, the allowlist test | Existing suites still green |
| 2 | `contracts.py` — strike → security id, with tests against the real scrip master | Resolves both symbols, current + next expiry |
| 3 | `guards.py` — all 11 caps + tests, including "refuses everything when disarmed" | Every guard has a failing-case test |
| 4 | `broker.py` — `place_order` behind a `DRY_RUN` flag that is **True by default** | Dry run produces a complete journalled order that is never sent |
| 5 | `trigger.py` + `run_live_trader.py`, still DRY_RUN | A full replayed session produces ≤2 intents, correctly timed |
| 6 | Control service + `/live-trading` page, still DRY_RUN | You can arm/disarm/kill and see refusals |
| 7 | **One** live order, smallest possible, placed by you from the UI with DRY_RUN off | Fill, journal row and P&L all reconcile against the Dhan order book |
| 8 | Auto-entry enabled for one symbol only, one trade cap, for one session | Reviewed before widening |

Step 7 is deliberately a manual single order even though the design is auto-entry: the first real
order should be one a human pressed, so that a fill, a tag and a journal row are proven to reconcile
before anything is automated.

---

## 10. Boundaries I will hold

- I will write this code. **I will not place an order, run the live trader with DRY_RUN off, or arm a
  session.** Those are yours.
- I will not touch your Dhan credentials. `.env` stays yours; the code reads what is already there.
- `DRY_RUN` defaults to True in source. Turning it off is a deliberate act by you, not a default.
- If something in the live path looks wrong mid-build, I will stop and say so rather than ship it
  because it was scheduled.

---

## 11. Open questions for your sign-off

1. **§7.1** — force-flat at 15:10: yes or no?
2. **§7.2** — the three entry qualifiers (STRONG only, ≥2-minute episode, nothing before 09:45): yes
   or no?
3. **Per-trade rupee cap** for guard #10 — 1 lot of SENSEX at ₹250 is ₹5,000; at ₹400 it is ₹8,000.
   What is the maximum you want a single entry to be allowed to cost?
4. **Which symbol first** — NIFTY, SENSEX, or both from day one?
