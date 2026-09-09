"""Paper-agent option selection from the frozen 14:59 chain.

Reuses market_transition.option_features_11c.build_candidate_universe
(ATM+/-5 x CE/PE extraction, staleness rejection) so the candidate data
path is identical to the 11C research. It does NOT reuse 11C's
opportunity SCORE: that score was explicitly not validated, and 11C
itself found it structurally biased toward the extremes of the chain
(max-delta deep ITM or minimum-absolute-cost deep OTM) because it worked
in raw points.

The correction here is deliberate and twofold:
  1. Hard qualification band -- a minimum delta (so the option actually
     tracks the underlying, which excludes deep-OTM lottery tickets) and
     a maximum premium (which bounds capital at risk and excludes deep
     ITM). The band does the structural work.
  2. Ranking inside the band is done in PERCENTAGE terms, not raw
     points, so a large premium cannot win merely by being large.

No symbol-specific strike preference is hard-coded anywhere. Whatever
moneyness gets chosen, the reason is recorded on the candidate.
"""

from market_transition.option_features_11c import build_candidate_universe
from paper_trading.config import PaperConfig
from paper_trading.models import PaperOptionCandidate


def _to_paper_candidate(c) -> PaperOptionCandidate:
    return PaperOptionCandidate(
        symbol=c.symbol, option_type=c.option_type, strike=c.strike, expiry=c.expiry,
        atm_offset=c.atm_offset, moneyness=c.moneyness, ltp=c.ltp, bid=c.bid, ask=c.ask,
        spread=c.spread, spread_pct=c.spread_pct, volume=c.volume, oi=c.oi,
        oi_change=c.oi_change, iv=c.iv, delta=c.delta, gamma=c.gamma, theta=c.theta,
        vega=c.vega,
    )


def build_paper_candidates(symbol, session_date, option_at_1459, strike_step, config: PaperConfig):
    """(candidates, rejection_reason). rejection_reason is None on success,
    else NO_SNAPSHOT / STALE_SNAPSHOT / EMPTY_CHAIN straight from the 11C
    extractor -- never patched over."""
    raw, rejection = build_candidate_universe(
        symbol, session_date, option_at_1459,
        strike_step=strike_step, atm_window_strikes=config.atm_window_strikes,
    )
    return [_to_paper_candidate(c) for c in raw], rejection


def qualify(candidate: PaperOptionCandidate, config: PaperConfig) -> PaperOptionCandidate:
    """Marks eligibility in a fixed order so the rejection reason is always
    the FIRST thing that disqualified the candidate, not an arbitrary one."""
    if candidate.bid is None or candidate.ask is None or not candidate.ask:
        candidate.eligible, candidate.rejection_reason = False, "MISSING_QUOTE"
    elif candidate.spread_pct is not None and candidate.spread_pct > config.max_spread_pct:
        candidate.eligible, candidate.rejection_reason = False, "SPREAD_TOO_WIDE"
    elif candidate.delta is None or candidate.delta == 0:
        candidate.eligible, candidate.rejection_reason = False, "MISSING_OR_DEGENERATE_DELTA"
    elif abs(candidate.delta) < config.min_option_delta:
        candidate.eligible, candidate.rejection_reason = False, "DELTA_TOO_LOW"
    elif candidate.ask > config.max_option_premium:
        candidate.eligible, candidate.rejection_reason = False, "PREMIUM_TOO_HIGH"
    else:
        candidate.eligible, candidate.rejection_reason = True, None
    return candidate


def expression_score(candidate: PaperOptionCandidate, expected_move_points: float) -> float | None:
    """Expected percentage gain on the premium actually paid, net of the
    round-trip spread -- both expressed as a % of the ask. Percentage
    terms are the point: it makes a cheap and an expensive option
    directly comparable, which raw points did not."""
    if candidate.delta is None or not candidate.ask or expected_move_points is None:
        return None
    expected_pct_gain = (abs(candidate.delta) * expected_move_points) / candidate.ask * 100
    spread_cost_pct = candidate.spread_pct or 0.0
    return expected_pct_gain - spread_cost_pct


def select_option(candidates, direction, expected_move_points, config: PaperConfig):
    """(selected_or_None, reason). `direction` is 'up' or 'down'; only the
    matching leg is ever considered -- the agent never buys the option
    that profits from being wrong."""
    if not candidates:
        return None, "INSUFFICIENT_OPTION_DATA"

    leg = "CE" if direction == "up" else "PE"
    same_leg = [qualify(c, config) for c in candidates if c.option_type == leg]
    eligible = [c for c in same_leg if c.eligible]
    if not eligible:
        blocked = {c.rejection_reason for c in same_leg}
        if blocked == {"SPREAD_TOO_WIDE"}:
            return None, "OPTION_SPREAD_TOO_WIDE"
        if "MISSING_QUOTE" in blocked and len(blocked) == 1:
            return None, "OPTION_LIQUIDITY_TOO_LOW"
        return None, "NO_VALID_OPTION"

    scored = [(expression_score(c, expected_move_points), c) for c in eligible]
    scored = [(s, c) for s, c in scored if s is not None]
    if not scored:
        return None, "NO_VALID_OPTION"

    # Deterministic ordering: best expression first, then the tighter
    # spread, then the lower strike -- no ties can resolve randomly.
    scored.sort(key=lambda sc: (-sc[0], sc[1].spread_pct or 0.0, sc[1].strike))
    best_score, best = scored[0]

    moneyness_label = "ATM" if best.atm_offset == 0 else (
        f"{'OTM' if (best.atm_offset > 0) == (leg == 'CE') else 'ITM'} {abs(best.atm_offset)}"
    )
    best.selection_rationale = (
        f"{moneyness_label} {leg} chosen from {len(eligible)} eligible {leg} candidates: "
        f"delta {best.delta:.2f} tracks the expected {expected_move_points:.0f}-pt move for a "
        f"{best.ask:.2f} premium, spread {best.spread_pct:.2f}% -- best net expected return "
        f"({best_score:.1f}%) inside the delta>={config.min_option_delta} / "
        f"premium<={config.max_option_premium:.0f} qualification band."
    )
    return best, "SELECTED"
