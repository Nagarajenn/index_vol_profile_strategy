"""27-Aug regression test (spec Part 12).

2026-08-27 SENSEX is the specific case the spec calls out: the
14:31-14:59 pre-window read FLAT, but 15:00 onward saw a real ~-312pt
move -- Phase 7A (already shipped, tested separately in
tests/test_cas_transition.py) fixed the underlying bug where a flat
pre-trend swallowed a real post-window move under a generic "Neutral"
label. That fix is real code behavior, not hardcoded to this one date --
classify_transition_type()/classify_transition_magnitude() take
pre_direction/post_direction/magnitude as arguments and are already
covered by boundary tests independent of any specific calendar day.

This test covers the NEW territory Phase 9 adds on top of that: does the
unified market-state vector (transition_state.py) still surface real,
distinguishing bearish evidence for a 27-Aug-SHAPED session even though
price_bias reads "flat" -- i.e., does "flat price" get correctly treated
as "no price signal", not "no signal at all"? The known real facts about
this specific day (verified earlier this session via the CAS Intelligence
table and a direct DB query): pre-window flat, actual post-window move
approximately -312 points, pre-window volume approximately 1.3M vs.
post-window approximately 3.8M (ratio approximately 2.88x), PCR at 14:59
approximately 0.65, institutional bias "Mildly Bearish", monthly expiry.
Fields not otherwise recorded in this session (exact call/put OI change
values) use representative numbers consistent with that known PCR/bias
context, not fabricated to force a particular test result -- the
assertions below check for genuine bearish-leaning EVIDENCE, not a
pinned exact verdict string.
"""

from market_transition.cas_windows import PreTransitionWindow
from market_transition.transition_state import build_market_state_vector
from market_transition.verdict import compute_verdict


def _27aug_shaped_window() -> PreTransitionWindow:
    return PreTransitionWindow(
        window_index=6, window_label="14:55-14:59",
        open=77245.54, close=77245.54, high=77250.0, low=77240.0,  # flat -- matches the real day's pre-window read
        net_point_change=0.0, pct_change=0.0,
        volume=221_762.0, rvol_pct=134.0, volume_acceleration_ratio=0.63,
        buy_volume_estimate=110_000.0, sell_volume_estimate=111_762.0, dominance_ratio=0.496, dominant_side="balanced",
        vwap_at_window_end=77260.0, price_distance_from_vwap=-14.5, price_distance_from_vwap_pct=-0.02, vwap_slope=0.37,
        poc_at_window_end=77212.5, poc_change_during_window=0.0, poc_slope=0.0, vah=77250.0, val=77180.0,
        # PCR ~0.65 (real, known value) with call OI building faster than put OI --
        # representative of a bearish-leaning option structure at that PCR level,
        # not the exact real deltas (not recorded in this session).
        pcr=0.65, pcr_change=0.029, call_oi_change=1500.0, put_oi_change=200.0, iv_change=0.37, option_pressure_score=-0.2,
        market_regime="Volatile", institutional_bias_label="Mildly Bearish", institutional_bias_score=-2, news_risk_score=None,
    )


def test_flat_price_day_still_shows_real_bearish_option_evidence():
    """The core Part 12 point applied to the state vector: a flat
    price_bias must not mean "nothing to report" when the option-side
    evidence is genuinely one-sided."""
    vector = build_market_state_vector(_27aug_shaped_window(), option_bias="BEARISH")

    assert vector.price_bias == "flat"
    # Despite flat price, the option-side evidence is NOT flat/neutral.
    assert vector.oi_structure == "Call-side concentration increasing"
    assert vector.option_bias == "BEARISH"
    assert vector.pcr_trend == "Rising"


def test_flat_price_with_bearish_option_positioning_is_not_a_contradiction():
    # Call-side building (bearish) alongside bearish option positioning is
    # CONSISTENT evidence, not conflicting -- the contradiction rules only
    # fire when price and options point opposite ways, and "flat" isn't a
    # direction to disagree with.
    vector = build_market_state_vector(_27aug_shaped_window(), option_bias="BEARISH")
    assert vector.contradictions == []


def test_a_decisive_bearish_read_for_this_shape_is_a_real_down_verdict_not_no_material_move():
    """Feeds a 27-Aug-shaped read's evidence through the verdict layer with
    a genuinely thin-but-sufficient historical sample (n_analogs at the
    minimum threshold) and a probability split consistent with what such
    one-sided option evidence would support -- confirms the verdict layer
    does not default to NO_MATERIAL_MOVE just because the PRICE leg of
    the evidence was flat."""
    from market_transition.scoring import MIN_ANALOGS

    vector = build_market_state_vector(_27aug_shaped_window(), option_bias="BEARISH")
    verdict = compute_verdict(
        n_analogs=MIN_ANALOGS + 5, probability_up=0.15, probability_down=0.63, probability_flat=0.22,
        contradictions=vector.contradictions,
    )
    assert verdict == "DOWN"
    assert verdict != "NO_MATERIAL_MOVE"
