import pytest

from option_chain.snapshot_features import (
    classify_option_positioning,
    compute_snapshot_features,
    extract_atm_window,
)


def _strike_entry(oi=1000.0, previous_oi=800.0, volume=5000.0, last_price=100.0, iv=15.0) -> dict:
    return {
        "oi": oi, "previous_oi": previous_oi, "volume": volume, "previous_volume": volume * 0.9,
        "last_price": last_price, "average_price": last_price, "top_bid_price": last_price - 0.5,
        "top_ask_price": last_price + 0.5, "top_bid_quantity": 100, "top_ask_quantity": 100,
        "implied_volatility": iv, "previous_close_price": last_price,
        "greeks": {"delta": 0.5, "gamma": 0.001, "theta": -10.0, "vega": 5.0},
    }


def _flat_chain(spot: float = 100.0, step: float = 1.0, n_strikes: int = 15, overrides: dict | None = None) -> dict:
    """A chain of `n_strikes` strikes centered near `spot`, every strike
    identical except where `overrides` (dict keyed by (strike, "ce"/"pe"))
    supplies a different entry."""
    overrides = overrides or {}
    base_strike = round(spot / step) * step
    oc = {}
    for i in range(-(n_strikes // 2), n_strikes // 2 + 1):
        strike = base_strike + i * step
        ce = dict(overrides.get((strike, "ce"), _strike_entry()))
        pe = dict(overrides.get((strike, "pe"), _strike_entry()))
        oc[str(strike)] = {"ce": ce, "pe": pe}
    return {"expiry": "2026-08-27", "last_price": spot, "oc": oc}


def test_compute_snapshot_features_returns_none_for_empty_chain():
    assert compute_snapshot_features({"last_price": 100.0, "oc": {}}) is None


def test_pcr_by_oi_and_volume_reflect_actual_totals():
    payload = _flat_chain(
        spot=100.0,
        overrides={
            (100.0, "ce"): _strike_entry(oi=1000.0, volume=2000.0),
            (100.0, "pe"): _strike_entry(oi=2000.0, volume=1000.0),
        },
    )
    features = compute_snapshot_features(payload, atm_window_strikes=1)
    assert features is not None
    assert features.pcr_oi is not None
    assert features.pcr_volume is not None


def test_atm_straddle_value_is_call_plus_put_ltp_at_atm():
    payload = _flat_chain(
        spot=100.0,
        overrides={(100.0, "ce"): _strike_entry(last_price=50.0), (100.0, "pe"): _strike_entry(last_price=40.0)},
    )
    features = compute_snapshot_features(payload)
    assert features.atm_straddle_value == pytest.approx(90.0)


def test_max_oi_strikes_identify_the_actual_walls():
    payload = _flat_chain(
        spot=100.0,
        overrides={
            (105.0, "ce"): _strike_entry(oi=50_000.0),
            (95.0, "pe"): _strike_entry(oi=60_000.0),
        },
    )
    features = compute_snapshot_features(payload)
    assert features.max_call_oi_strike == pytest.approx(105.0)
    assert features.max_put_oi_strike == pytest.approx(95.0)
    assert features.spot_distance_from_max_call_oi == pytest.approx(100.0 - 105.0)
    assert features.spot_distance_from_max_put_oi == pytest.approx(100.0 - 95.0)


def test_call_oi_buildup_detected_between_two_snapshots():
    prior_payload = _flat_chain(spot=100.0)
    prior = compute_snapshot_features(prior_payload, atm_window_strikes=2)

    # Call OI within the ATM window grows substantially on the later snapshot.
    later_payload = _flat_chain(
        spot=100.0,
        overrides={
            (100.0, "ce"): _strike_entry(oi=50_000.0),
            (101.0, "ce"): _strike_entry(oi=40_000.0),
        },
    )
    later = compute_snapshot_features(later_payload, atm_window_strikes=2, prior=prior)

    assert later.call_oi_buildup is not None and later.call_oi_buildup > 0
    assert later.call_unwinding == 0.0


def test_put_unwinding_detected_when_put_concentration_shrinks():
    prior_payload = _flat_chain(spot=100.0, overrides={(100.0, "pe"): _strike_entry(oi=80_000.0)})
    prior = compute_snapshot_features(prior_payload, atm_window_strikes=2)

    later_payload = _flat_chain(spot=100.0)  # back to the flat baseline -- put OI concentration shrank
    later = compute_snapshot_features(later_payload, atm_window_strikes=2, prior=prior)

    assert later.put_unwinding is not None and later.put_unwinding > 0
    assert later.put_oi_buildup == 0.0


def test_oi_migration_note_populated_when_the_max_oi_strike_moves():
    # Both override strikes must fall within _flat_chain's default 15-strike
    # range (spot +/- 7, i.e. 93-107) or the override is silently a no-op.
    prior_payload = _flat_chain(spot=100.0, overrides={(105.0, "ce"): _strike_entry(oi=50_000.0)})
    prior = compute_snapshot_features(prior_payload)

    later_payload = _flat_chain(spot=100.0, overrides={(98.0, "ce"): _strike_entry(oi=60_000.0)})
    later = compute_snapshot_features(later_payload, prior=prior)

    assert later.oi_migration_note is not None
    assert "105" in later.oi_migration_note and "98" in later.oi_migration_note


def test_first_snapshot_of_the_day_has_no_change_fields():
    payload = _flat_chain(spot=100.0)
    features = compute_snapshot_features(payload)  # no prior supplied
    assert features.pcr_change is None
    assert features.call_oi_buildup is None
    assert features.atm_iv_change is None
    assert features.oi_migration_note is None


def test_extract_atm_window_returns_both_legs_for_every_strike_in_range():
    payload = _flat_chain(spot=100.0, n_strikes=15)
    details = extract_atm_window(payload, atm_window_strikes=5)
    # 11 strikes (ATM +/- 5) x 2 legs
    assert len(details) == 22
    strikes_seen = {d.strike for d in details}
    assert min(strikes_seen) == pytest.approx(95.0)
    assert max(strikes_seen) == pytest.approx(105.0)


def test_extract_atm_window_parses_greeks_and_bid_ask():
    payload = _flat_chain(spot=100.0)
    details = extract_atm_window(payload, atm_window_strikes=1)
    atm_ce = next(d for d in details if d.strike == 100.0 and d.leg == "CE")
    assert atm_ce.delta == pytest.approx(0.5)
    assert atm_ce.bid == pytest.approx(99.5)
    assert atm_ce.ask == pytest.approx(100.5)
    assert atm_ce.oi_change == pytest.approx(1000.0 - 800.0)


def test_classify_neutral_when_no_strong_signal():
    payload = _flat_chain(spot=100.0)  # symmetric chain -> PCR ~1, no imbalance
    features = compute_snapshot_features(payload)
    assert classify_option_positioning(features) in ("NEUTRAL", "MIXED")


def test_classify_bullish_when_multiple_signals_agree():
    payload = _flat_chain(
        spot=100.0,
        overrides={(k, "pe"): _strike_entry(oi=200_000.0, volume=200_000.0) for k in (99.0, 100.0, 101.0)},
    )
    features = compute_snapshot_features(payload, atm_window_strikes=2)
    assert classify_option_positioning(features) == "BULLISH"


def test_classify_bearish_when_multiple_signals_agree():
    payload = _flat_chain(
        spot=100.0,
        overrides={(k, "ce"): _strike_entry(oi=200_000.0, volume=200_000.0) for k in (99.0, 100.0, 101.0)},
    )
    features = compute_snapshot_features(payload, atm_window_strikes=2)
    assert classify_option_positioning(features) == "BEARISH"


def test_classify_rapidly_changing_when_signals_strongly_disagree():
    # Deep put-writing (bullish PCR) but heavy call volume dominance and
    # call OI building faster than put OI -- multiple signals pulling
    # opposite ways at once.
    payload = _flat_chain(
        spot=100.0,
        overrides={
            **{(k, "pe"): _strike_entry(oi=300_000.0, volume=1_000.0) for k in (99.0, 100.0, 101.0)},
            **{(k, "ce"): _strike_entry(oi=50_000.0, volume=500_000.0) for k in (99.0, 100.0, 101.0)},
        },
    )
    features = compute_snapshot_features(payload, atm_window_strikes=2)
    label = classify_option_positioning(features)
    assert label in ("RAPIDLY_CHANGING", "MIXED")
