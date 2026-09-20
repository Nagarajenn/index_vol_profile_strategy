# 12C — Scalping Decision + Risk Brake: validation

`12C-scalp-decision-v1` · config hash `d0b1847f5180d11b` · run `12c-20260920T135722` · generated 2026-09-20T13:58:48

This is a **sanity check, not research**. It replays the rules over sessions
2026-09-11, 2026-09-15, 2026-09-16, 2026-09-17, 2026-09-18 (3023 minutes, both symbols) and asks only whether they behave as
written. No threshold was tuned, no outcome was scored, and no profitability claim is made or implied.

## Checks

| Check | Result | Detail |
|---|---|---|
| Rules behave as written (no invariant broken) | **PASS** | 0 violations |
| No-lookahead: truncating the inputs at T changes nothing | **PASS** | 0 mismatches |
| WAIT is a normal outcome, not an exception | **PASS** | WAIT 55.9% of 3023 minutes |
| Entries are not concentrated in one minute-level spike rule | **PASS** | BUY_CE 669, BUY_PE 665 |
| EXIT is never reached from a single evidence family | **PASS** | 1608 EXIT calls over 6046 reference assessments |
| A position on the side the options favour is rarely told to EXIT | **PASS** | 0.0% of aligned assessments vs 46.7% of opposed ones |

## Entry decisions

| Decision | Minutes | Share |
|---|---|---|
| BUY_CE | 669 | 22.1% |
| BUY_PE | 665 | 22.0% |
| WAIT | 1689 | 55.9% |

Confirmation levels: MODERATE 619, NONE 1675, STRONG 725, WEAK 4

### Why WAIT was returned (first blocking condition)

| Blocking category | Minutes |
|---|---|
| UNDERLYING | 575 |
| OPTION_RELATIVE | 417 |
| CE_MOMENTUM | 230 |
| PE_MOMENTUM | 220 |
| STRADDLE | 100 |

## Risk brake on reference positions

Every minute is also evaluated as if an ATM CE and an ATM PE were held — these are reference
positions for exercising the ladder, not trades and not 11D.

| Position / action | Minutes |
|---|---|
| CE|CAUTION | 1074 |
| CE|EXIT | 837 |
| CE|HOLD | 635 |
| CE|PREPARE_EXIT | 477 |
| PE|CAUTION | 1222 |
| PE|EXIT | 771 |
| PE|HOLD | 579 |
| PE|PREPARE_EXIT | 451 |

## What a BUY state actually is

A decision is recomputed every minute, so consecutive BUY minutes are **one continuing condition**,
not many separate signals: 611 BUY episodes in total (61.1 per symbol-day), median 2 minutes long, longest 13.

## Interpretation

The rules fire the way they are written: entries need several independent categories to agree,
WAIT dominates, and EXIT needs both a broken premium trend and at least
four independent families against the position. What this check does **not** show is whether
acting on the decisions makes money — that question is deliberately left alone here, and the
12B research already found that option-chain warnings were not selective.

An ATM CE and an ATM PE are both assessed every minute, so roughly half of those reference positions
are deliberately on the wrong side of the market. EXIT was reached in 0.0% of assessments where
the position matched the side the options favoured, against 46.7% where it did not.

Artefacts: `data/cache/scalp_decision_12c/12c-20260920T135722/12c_validation.json` and
`12c_decision_trace.jsonl` (one decision trace per line; the format is documented in README.md).
