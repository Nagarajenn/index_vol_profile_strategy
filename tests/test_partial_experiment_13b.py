"""13B-EXP-1: the PARTIAL experiment is exactly one flag, and it changes exactly one behaviour."""

from dataclasses import asdict
from pathlib import Path

from price_action_13b import analysis as AN
from price_action_13b import decide as D
from price_action_13b.config import (CONFIRMED, CONTRADICTED, DEFAULT, EXPERIMENT_ALLOW_PARTIAL,
                                     EXPERIMENT_VERSION, NO_SETUP, PARTIAL, UNKNOWN)

ROOT = Path(__file__).resolve().parent.parent


# ================================================================ the experiment is isolated
def test_exactly_one_field_differs_from_the_committed_default():
    a, b = asdict(DEFAULT), asdict(EXPERIMENT_ALLOW_PARTIAL)
    diff = {k for k in a if a[k] != b[k]}
    assert diff == {"block_on_partial"}, diff
    assert DEFAULT.block_on_partial is True
    assert EXPERIMENT_ALLOW_PARTIAL.block_on_partial is False


def test_the_two_configs_hash_differently_so_results_cannot_be_confused():
    assert DEFAULT.config_hash() != EXPERIMENT_ALLOW_PARTIAL.config_hash()
    assert EXPERIMENT_VERSION.endswith("exp-allow-partial")


def test_the_committed_default_still_blocks_partial():
    """The baseline this is measured against must not drift underneath it."""
    out = D.apply("BUY_PE", dict(confirmation=PARTIAL, reason="x"), DEFAULT)
    assert out["final_decision"] == "WAIT" and out["price_action_block"] is True


# ================================================================ the changed behaviour
def test_partial_now_preserves_the_13a_buy():
    for side in ("BUY_CE", "BUY_PE"):
        out = D.apply(side, dict(confirmation=PARTIAL, reason="x"), EXPERIMENT_ALLOW_PARTIAL)
        assert out["final_decision"] == side
        assert out["price_action_block"] is False
        assert out["final_price_action_state"] == PARTIAL


def test_contradicted_and_no_setup_still_block_under_the_experiment():
    """The protection the experiment must preserve."""
    for verdict in (CONTRADICTED, NO_SETUP):
        out = D.apply("BUY_PE", dict(confirmation=verdict, reason="x"), EXPERIMENT_ALLOW_PARTIAL)
        assert out["final_decision"] == "WAIT", verdict
        assert out["price_action_block"] is True
        assert out["block_reason"] == f"PRICE_ACTION_{verdict}"


def test_confirmed_and_unknown_are_unaffected_by_the_experiment():
    for verdict in (CONFIRMED, UNKNOWN):
        a = D.apply("BUY_CE", dict(confirmation=verdict, reason="x"), DEFAULT)
        b = D.apply("BUY_CE", dict(confirmation=verdict, reason="x"), EXPERIMENT_ALLOW_PARTIAL)
        assert a["final_decision"] == b["final_decision"] == "BUY_CE", verdict


def test_the_experiment_still_cannot_create_a_buy():
    for verdict in (CONFIRMED, PARTIAL, CONTRADICTED, NO_SETUP, UNKNOWN):
        out = D.apply("WAIT", dict(confirmation=verdict, reason="x"), EXPERIMENT_ALLOW_PARTIAL)
        assert out["final_decision"] == "WAIT"
        assert out["price_action_block"] is False


# ================================================================ the analysis keeps units straight
def test_blocked_and_allowed_outcomes_are_both_reported_per_unit():
    """A per-unit forward path and a cash result must never be averaged together."""
    blocked = [dict(confirmation=PARTIAL, end=-2.0, mfe=3.0, mae=-4.0)]
    allowed = [dict(price_action=PARTIAL, realised_pnl_per_unit=5.0, realised_pnl=325.0,
                    mfe_per_unit=8.0, mae_per_unit=-1.0)]
    out = AN.forward_by_verdict(blocked, allowed)
    assert out[f"{PARTIAL} (blocked)"]["mean_end"] == -2.0
    assert out[f"{PARTIAL} (allowed, realised)"]["mean_end"] == 5.0      # per unit, not 325
    assert out[f"{PARTIAL} (allowed, realised)"]["mean_cash"] == 325.0   # cash kept separate


def test_a_blocked_candidate_has_no_cash_result():
    out = AN.forward_by_verdict([dict(confirmation=NO_SETUP, end=-1.0, mfe=0.0, mae=-2.0)], [])
    assert out[f"{NO_SETUP} (blocked)"]["mean_cash"] is None


def test_the_three_way_comparison_counts_each_path_separately():
    """Blocking frees capacity, so the paths do not see the same candidate minutes."""
    a_dec = [dict(thirteen_a="BUY_CE", final="BUY_CE", price_action=None)]
    b_dec = [dict(thirteen_a="BUY_CE", final="WAIT", price_action=PARTIAL),
             dict(thirteen_a="BUY_PE", final="WAIT", price_action=CONTRADICTED)]
    c_dec = [dict(thirteen_a="BUY_CE", final="BUY_CE", price_action=PARTIAL)]
    out = AN.three_way([], [], [], a_dec, b_dec, c_dec, [], [])
    assert out["candidate_minutes"] == dict(path_a=1, path_b=2, path_c=1)
    assert "never across paths" in out["note"]


# ================================================================ nothing else moved
def test_no_other_13b_threshold_was_touched():
    """Every gate the spec listed as off-limits must be identical in both configs."""
    a, b = asdict(DEFAULT), asdict(EXPERIMENT_ALLOW_PARTIAL)
    for field in ("swing_k", "structure_window", "min_swing_pct", "break_buffer_pct",
                  "follow_through_bars", "wick_body_ratio", "extension_atr_mult", "atr_period",
                  "vwap_near_pct", "vwap_distant_pct", "volume_window", "volume_expanding_ratio",
                  "volume_spike_ratio", "volume_declining_ratio", "value_edge_pct",
                  "block_on_contradicted", "block_on_no_setup", "preserve_on_unknown", "enabled"):
        assert a[field] == b[field], field


def test_no_broker_path_in_the_experiment_runner():
    frags = ["place" + "_order", "modify" + "_order", "cancel" + "_order", "dhanhq", "dhan_client"]
    for name in ("experiment.py", "exp_report.py"):
        src = (ROOT / "price_action_13b" / name).read_text(encoding="utf-8")
        for f in frags:
            assert f not in src, f"{name} mentions {f}"
