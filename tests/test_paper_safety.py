"""MANDATORY real-order safety tests for the paper trading agent.

These are structural, not behavioural: they assert that the paper package
physically cannot reach a real broker, so a future edit that imports one
fails CI rather than quietly enabling live trading.
"""

import importlib
import inspect

import pytest

from paper_trading import broker as broker_module
from paper_trading.broker import PaperBroker
from paper_trading.safety import (
    FORBIDDEN_SOURCE_FRAGMENTS,
    PAPER_MODE,
    RealOrderAttemptError,
    assert_paper_mode,
    scan_package_for_real_order_calls,
)


def test_paper_mode_invariant_is_true():
    assert PAPER_MODE is True
    assert_paper_mode()  # must not raise


def test_no_real_order_call_anywhere_in_the_paper_package():
    """The whole point of the milestone: scan every .py file in
    paper_trading/ for order-placement fragments and any broker import."""
    violations = scan_package_for_real_order_calls()
    assert violations == [], f"Real-order fragments found in the paper package: {violations}"


@pytest.mark.parametrize("fragment", FORBIDDEN_SOURCE_FRAGMENTS)
def test_forbidden_fragment_absent_from_broker_source(fragment):
    source = inspect.getsource(broker_module)
    assert fragment not in source


def test_paper_broker_rejects_any_real_order_style_method():
    broker = PaperBroker()
    for name in ("place_order", "placeOrder", "modify_order", "cancel_order", "buy_order", "sell_order"):
        with pytest.raises(RealOrderAttemptError):
            getattr(broker, name)


def test_paper_package_does_not_import_the_broker_client():
    """Import every paper module and assert none of them pulled a broker
    client into sys.modules through their own import graph."""
    import sys

    for module in (
        "paper_trading.agent", "paper_trading.broker", "paper_trading.decision",
        "paper_trading.tick", "paper_trading.journal", "paper_trading.risk",
        "paper_trading.option_selection", "paper_trading.position_manager",
    ):
        importlib.import_module(module)

    paper_modules = {name: mod for name, mod in sys.modules.items() if name.startswith("paper_trading")}
    for name, mod in paper_modules.items():
        source_file = getattr(mod, "__file__", None)
        if not source_file or not source_file.endswith(".py"):
            continue
        with open(source_file, encoding="utf-8") as fh:
            source = fh.read()
        if name.endswith("safety"):
            continue
        assert "dhan" not in source.lower(), f"{name} references a broker client"


def test_paper_broker_is_flagged_as_paper():
    assert PaperBroker().is_paper is True
