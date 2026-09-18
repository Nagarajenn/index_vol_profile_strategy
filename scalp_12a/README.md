# 12A-scalp-v1 — Controlled Scalp Strategy (EXPERIMENT)

`11d-paper-v1` is the frozen **CONTROL**. `12A-scalp-v1` is a separate, independently
versioned **EXPERIMENT**: short-duration, event-driven option buying (BUY CE / BUY PE only)
with pre-defined risk and proactive exits.

**Status: research + live shadow only.** 12A is not connected to paper trading and
contains no order code. Paper integration is gated on the 10 criteria in the research report
(`milestone12a_research_report.html`).

## Boundaries (enforced by `tests/test_scalp12a_isolation.py`)

- 11D files, strategy version, config version and hash `9c7c362d7e0c6a14` are pinned; unchanged.
- The HR capture package (`hr_capture/`) is pinned by content hash; 12A only reads `hr_*` tables.
- 12A imports nothing from `paper_trading`, the live loop, Dhan clients or HR internals, and
  nothing in the platform imports 12A.
- 12A SQL writes only `scalp12a_*` tables. No order endpoints (`place/modify/cancel_order`, `/orders`) anywhere.
- Own DB connection (`application_name=scalp12a`), own process, own scheduled task.

## Pipeline (one symbol-session, bar by bar, causal)

```
HR 5-second bars (futures, index, ATM±5 CE/PE quotes)   1-minute levels + 11D decision
        │                                                  │ (CONTEXT only, never a veto)
        ▼                                                  ▼
thresholds.py  percentiles of |30 s| / |180 s| futures moves on PRIOR HR days only
events.py      MOMENTUM / REVERSAL / CONTINUATION / (WEAK near-miss) / NO_EVENT — futures-led
option_selector.py  CE for up, PE for down; ITM≤2 / OTM≤1; spread, age, premium, volume; never "cheapest"
confirmation.py     displacement + option response + persistence + not already extended
risk.py        before entry: stop %, target %, rupee risk → quantity, underlying invalidation, max hold
modes.py       PRE / MODE_A (15:00–15:15) / MODE_B (15:15–15:30, index frozen, research only)
               expiry day: no entries and forced flat from 15:10; HARD NO TRADE from 15:15
engine.py      decision at bar i → hypothetical fill at ASK of bar i+2 (live-realistic delay)
exits.py       BID path: stop (tighten-only trail), target, momentum failure, fade, underlying
               invalidation, event retrace, futures/option divergence, spread expansion, stale data,
               max hold, expiry-zone / session end
counterfactual.py  for EVERY candidate (traded or rejected): MFE, MAE, time-to-each, fixed-horizon
               exits 15–300 s, underlying move, plus what the active exit would have done
```

`opportunity.py` (research measurement, not a decision input, not in the hash): for every candidate,
event start, detection bar end / live detection time and latency, detection price, realistic entry,
futures MFE/MAE after detection with times, points remaining after entry, and a timing class
`DETECTED_EARLY` (≥50% of the event's move still ahead at the realistic entry) / `DETECTED_LATE` /
`NO_FOLLOW_THROUGH` / `UNKNOWN`. The report also counts missed opportunities (rejected, yet early and
positive after the active exit) and false positives (confirmed, but the active exit lost).

NO-TRADE reasons (all applicable ones recorded): `NO_EVENT, WEAK_MOMENTUM, NO_CONFIRMATION,
SPREAD_TOO_WIDE, LOW_LIQUIDITY, OPTION_NOT_RESPONDING, MOVE_ALREADY_EXTENDED, RISK_TOO_LARGE,
STALE_DATA, EVENT_EXPIRED, TIME_WINDOW_CLOSED`, plus `EXPIRY_DAY_CLOSE_VETO, EXPIRY_TRANSITION_ZONE,
MODE_B_RESEARCH_ONLY, INSUFFICIENT_HISTORY, POSITION_OPEN, DAILY_LIMIT_REACHED`.

## Research & shadow

| Piece | File | Runs |
|---|---|---|
| 1-minute chronological research (Step 2) | `research_1min.py` | `scripts/run_scalp12a_research.py` |
| HR 5-second research vs random (Step 4) | `research_hr.py` | same, after each session |
| Live shadow recorder (Step 3) | `scripts/run_scalp12a_shadow.py` | task `SensexNifty-Scalp12AShadow`, weekdays 14:53 |
| Validation report (J) | `report.py` → `milestone12a_research_report.html` | regenerated after each shadow session |
| Tables | `schema.sql` (`scalp12a_shadow_sessions`, `scalp12a_candidates`) | `scripts/scalp12a_setup_db.py` |

Every candidate row carries `strategy_version`, `config_hash`, event type, reasons, risk,
expected opportunity (selection/response), the actual counterfactual result and data quality.
Live rows also record `detected_wall_ts` / `detection_latency_s` (first sighting, never overwritten),
which is the evidence for real-time detectability.

## Parameter evidence

Every value in `config.py` is labelled `RESEARCH_1MIN`, `PROVISIONAL_5S`, `POLICY` or
`EVIDENCE_VETO`. 5-second thresholds are **not locked**: with 4 HR days (2 evaluable after the
causal threshold seed) nothing about 5-second behaviour is validated. Any change to a value
must bump `CONFIG_VERSION`, which changes the hash stamped on every row.
