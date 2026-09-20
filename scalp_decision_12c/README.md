# 12C — Scalping Decision + Risk Brake (`12C-scalp-decision-v1`)

One explainable, **advisory** call per minute, built from data the platform already collects:

* **no position** → `BUY CE` / `BUY PE` / `WAIT`
* **position open** → `HOLD` / `CAUTION` / `PREPARE_EXIT` / `EXIT`

Rule-based. No ML, no fitted model, no probability, no single mystery score. Every decision
names the evidence that produced it. **Nothing here can place, modify or cancel an order, or
open or close a position.** The 11D exit engine and the trader remain authoritative.

## What it reads (nothing new is captured)

| Input | Source |
|---|---|
| ATM CE/PE quotes, premium trajectories, OI, volume, IV/Greeks, straddle, option activity, underlying state | `option_risk_12b` minute view over existing `option_chain_raw` snapshots |
| 1-minute index candles, VWAP, POC, VAH/VAL, support/resistance, trend label | `raw_candles`, `levels_snapshots` |
| Open paper position | `paper_positions` (read-only), or a position the trader types into the panel |

## Evidence categories

Each is an independent observation with a state, its numbers and a sentence.

| Category | States |
|---|---|
| `UNDERLYING` | `UNDERLYING_BULLISH` / `UNDERLYING_BEARISH` / `UNDERLYING_NEUTRAL` / `UNDERLYING_STALE` / `UNDERLYING_MISSING` |
| `OPTION_RELATIVE` | `CALL_RELATIVE_STRENGTH` / `PUT_RELATIVE_STRENGTH` / `MOVEMENT_EXPANSION` / `PREMIUM_CONTRACTION` / `BALANCED` |
| `CE_MOMENTUM`, `PE_MOMENTUM` | `RISING` / `FALLING` / `ACCELERATING` / `DECELERATING` / `FLAT` / `INSUFFICIENT_DATA`, plus `persistent` and `spike` |
| `PARTICIPATION` | `CE_STRONG` / `PE_STRONG` / `MIXED` / `WEAK` |
| `OI_RELATIONSHIP` | per side: `LONG_BUILDUP` / `SHORT_COVERING` / `SHORT_BUILDUP` / `LONG_UNWINDING` / `NO_CLEAR_OI_PRICE_RELATION` |
| `LIQUIDITY` (per side) | `GOOD` / `ACCEPTABLE` / `POOR` |
| `STRADDLE` | `EXPANDING` / `CONTRACTING` / `FLAT` (+ `severe_contraction`) |
| `DATA_QUALITY` | `OK` / `DEGRADED` / `INSUFFICIENT`, with the underlying state, option activity and flags |

Interpretation rules that are deliberately **not** shortcuts:

* Direction is never read from one metric. "PE rising" is reported as `PUT_RELATIVE_STRENGTH`, not "the market will fall".
* OI is only read **together with** the premium move of the same side. Rising OI is not bullish or bearish by itself.
* Volume is **participation**, not direction; it is signed by the premium move it accompanies.
* The straddle is a **movement / premium-expansion** reading, never a direction on its own.
* IV and Greeks are secondary. Missing or degenerate values (e.g. deep-ITM puts published with zero IV) are marked
  unavailable and never replaced with zero.
* Intraday OI change is `oi(T) − oi(T−1 snapshot)`. Dhan's `previous_oi` (prior day) is never used for it.

## Entry rules

The candidate side comes from `OPTION_RELATIVE`. Ten checks then run for that side; each result is
**supporting**, **contradicting** or **blocking**. Any blocking item forces `WAIT`:

1. underlying agrees (opposite direction **blocks**; stale/missing contradicts)
2. one side clearly outperforms (`MOVEMENT_EXPANSION`, `PREMIUM_CONTRACTION`, `BALANCED` all **block**)
3. own 3-minute premium move ≥ `premium_move_pct`
4. that move is **persistent** (≥2 of the last 3 minutes agree); a one-minute spike **blocks**
5. participation confirms
6. the OI/premium relationship does not contradict
7. execution quality (`POOR` spread or no two-sided quote **blocks**)
8. the straddle is not in severe contraction (**blocks**)
9. the opposite side is not rising strongly at the same time (**blocks**)
10. option data for the minute exists (**blocks** otherwise)

**Confirmation** = `STRONG` (≥5 supporting, 0 contradicting, live underlying) / `MODERATE` (≥4, ≤1) /
`WEAK` (≥3, ≤1) / `NONE`. A `BUY` needs at least `MODERATE`; `WEAK` never becomes a trade.

**Stale underlying:** a new entry is allowed only on exceptional option-only evidence — ≥5 supporting
categories, no non-underlying contradiction, `GOOD` liquidity and a persistent move — and is then capped
at `MODERATE`, never `STRONG`, because the underlying cannot confirm it.

`held_minutes` reports how many consecutive earlier minutes produced the same decision, so a steady
state is distinguishable from a flicker.

## Risk brake rules

Evidence against an open position is grouped into **independent families** — `MOMENTUM`, `RELATIVE`,
`PARTICIPATION`, `POSITIONING`, `LIQUIDITY`, `UNDERLYING` — so correlated signals inside one family count
once and one noisy minute can never reach `EXIT`. Core families are `MOMENTUM`, `RELATIVE`, `UNDERLYING`.

| Action | Condition |
|---|---|
| `HOLD` | no family against, or one non-core family |
| `CAUTION` | one core family, or any two families |
| `PREPARE_EXIT` | ≥3 families including a core one |
| `EXIT` | ≥4 families including a core one **and** the position's own premium is persistently falling (thesis broken) |

If the thesis is not broken, `EXIT` is downgraded to `PREPARE_EXIT`. Risk level (`LOW` … `EXTREME`) is
informational and never triggers an action by itself.

## No lookahead

At minute T the option series and candles are truncated at T before anything is computed, so no later
snapshot, later candle or end-of-day value can enter a decision. This is enforced by
`tests/test_scalp_decision_12c.py::test_no_future_data_can_enter_the_decision` (every minute recomputed
from truncated inputs must be identical) and re-checked on real sessions by `validate.py`.

## Decision trace format

`out["trace"]` is one flat JSON object per decision; `validate.py` writes them as JSON Lines
(`data/cache/scalp_decision_12c/<run>/12c_decision_trace.jsonl`).

| Field | Meaning |
|---|---|
| `timestamp`, `session_date`, `symbol` | the minute the decision belongs to |
| `version`, `config_hash` | rule version and the hash of every threshold used |
| `underlying_state`, `position_state` | `LIVE`/`STALE`/`MISSING`; `NONE`/`BUY_CE`/`BUY_PE` |
| `decision`, `confirmation`, `held_minutes` | `BUY_CE`/`BUY_PE`/`WAIT`, its confirmation, minutes held |
| `risk_level`, `risk_action` | only when a position exists |
| `underlying_signal` | the underlying category state |
| `ce_relative_strength`, `pe_relative_strength`, `option_relative_state` | 3-minute CE and PE premium moves and the resulting state |
| `ce_momentum`, `pe_momentum`, `ce_momentum_3m`, `pe_momentum_3m`, `ce_persistent`, `pe_persistent` | momentum labels, sizes and persistence |
| `ce_volume_signal`, `pe_volume_signal`, `participation_state` | volume vs each side's own 5-minute average |
| `ce_oi_signal`, `pe_oi_signal` | the OI/premium relationship per side |
| `liquidity_signal`, `ce_spread_pct`, `pe_spread_pct` | execution quality |
| `straddle_signal`, `straddle_3m` | premium expansion / contraction |
| `supporting`, `contradicting`, `blocking` | category names behind the entry decision |
| `families_against`, `n_against` | the brake's independent families |
| `data_quality_flags` | e.g. `STALE_UNDERLYING`, `INVALID_GREEKS`, `MISSING_OPTION_DATA` |
| `reason` | the plain-English sentence shown in the panel |

Same inputs always produce the same trace, so any decision can be reproduced later.

## Where it runs

* Offline / replay: `scalp_decision_12c.engine.decide_at` (or `decide_prepared` for a minute-by-minute replay).
* Live: `GET /api/v1/scalp-decision-12c/{symbol}` (read-only) → the **SCALPING DECISION + RISK BRAKE** panel at
  the top of the Terminal and Paper Trading pages. `?position=CE|PE&strike=…` shows the brake for a position
  the trader holds themselves; an open paper position always takes precedence.
* Sanity check: `python -m scalp_decision_12c.validate [sessions]` → `VALIDATION.md`.

## What this is not

It is not a prediction, not a probability, and not evidence that acting on it makes money. The 12B research
found that option-chain warnings were not selective and that option pressure did not beat a simple base rate
for the next index print. 12C makes the existing evidence **legible and position-aware**; it does not claim an edge.
