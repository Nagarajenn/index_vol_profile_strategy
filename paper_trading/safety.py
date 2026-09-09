"""Real-order safety invariants for the paper trading agent.

The guarantee this module provides is structural, not configurational:
the paper execution layer physically cannot reach a real broker because
(a) nothing in `paper_trading/` imports `dhan_client`, and (b) every
execution call routes through PaperBroker, which raises rather than
delegating anywhere else.

tests/test_paper_safety.py asserts both properties against the real
package source, so a future edit that imports a broker breaks the build.
"""

from pathlib import Path

PAPER_MODE = True
"""Hard invariant. This is never read from configuration or the
environment -- flipping it is a code change that must fail the safety
tests, which assert it is True."""

PACKAGE_ROOT = Path(__file__).resolve().parent

# Substrings that must never appear in this package's source. Kept as
# fragments (not full call expressions) so a near-miss like
# `client.place_order_v2(...)` is caught too.
FORBIDDEN_SOURCE_FRAGMENTS = (
    "place_order",
    "modify_order",
    "cancel_order",
    "buy_order",
    "sell_order",
    "dhan_client",
    "dhanhq",
)

# The one file allowed to contain those fragments: this one, which names
# them in order to forbid them.
SAFETY_SELF_FILENAME = "safety.py"


class RealOrderAttemptError(RuntimeError):
    """Raised if anything tries to route a paper order to a real broker.

    Reaching this exception means a programming error, not a runtime
    condition -- there is no code path that is supposed to raise it."""


def assert_paper_mode() -> None:
    if PAPER_MODE is not True:
        raise RealOrderAttemptError(
            "PAPER_MODE is not True -- the paper agent refuses to run. "
            "Live trading is a separate milestone requiring explicit human approval."
        )


def scan_package_for_real_order_calls() -> list[str]:
    """Returns a list of 'file:fragment' violations. Empty list == safe.

    Used by the mandatory safety test rather than kept as a runtime check,
    because the point is to fail CI when someone edits the package, not to
    pay a filesystem scan on every decision."""
    violations = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path.name == SAFETY_SELF_FILENAME:
            continue
        source = path.read_text(encoding="utf-8")
        for fragment in FORBIDDEN_SOURCE_FRAGMENTS:
            if fragment in source:
                violations.append(f"{path.relative_to(PACKAGE_ROOT)}:{fragment}")
    return violations
