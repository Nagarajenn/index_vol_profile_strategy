"""PaperBroker -- the ONLY execution path the paper agent has.

There is no real-broker implementation behind this and no adapter that
could be swapped in: the class simulates fills arithmetically from quotes
that were read out of the database. It imports nothing that can reach a
network.

Execution realism (carried over from Milestone 11C):
    BUY  fills at ASK
    SELL fills at BID
Never LTP, never the midpoint. A missing ASK means no entry; a missing
BID at exit is a recorded data exception, never an invented price.

Costs: no validated brokerage/tax model exists in this project, so none
is invented. net_pnl == gross_pnl and every P&L figure this broker
produces is PRE-COST, flagged as such on the fill.
"""

from dataclasses import dataclass
from datetime import datetime

from paper_trading.safety import RealOrderAttemptError, assert_paper_mode

PNL_BASIS = "PRE_COST"


@dataclass
class PaperFill:
    timestamp: datetime
    side: str            # "BUY" or "SELL"
    price: float         # the executable price actually used
    bid: float | None
    ask: float | None
    ltp: float | None
    spread: float | None
    spread_pct: float | None
    quantity: int
    basis: str = PNL_BASIS
    data_exception: str | None = None


class PaperBroker:
    """Simulated execution. Every method asserts PAPER_MODE first, so even
    a caller that somehow bypassed the agent still cannot execute if the
    invariant were ever flipped."""

    def __init__(self) -> None:
        assert_paper_mode()
        self.is_paper = True
        self.fills: list[PaperFill] = []

    # -- entry ---------------------------------------------------------
    def buy(self, timestamp, bid, ask, ltp, quantity) -> PaperFill:
        assert_paper_mode()
        if ask is None or ask <= 0:
            raise ValueError("Cannot simulate a BUY without a valid ASK -- caller must return NO TRADE")
        spread = (ask - bid) if bid is not None else None
        fill = PaperFill(
            timestamp=timestamp, side="BUY", price=float(ask), bid=bid, ask=ask, ltp=ltp,
            spread=spread, spread_pct=(spread / ask * 100) if spread is not None else None,
            quantity=quantity,
        )
        self.fills.append(fill)
        return fill

    # -- exit ----------------------------------------------------------
    def sell(self, timestamp, bid, ask, ltp, quantity, fallback_price=None) -> PaperFill:
        """Exits at BID. If no BID exists (a genuine data gap at the forced
        19-minute exit, for example) the fill is marked with a data
        exception and uses the caller's explicit fallback -- this broker
        never fabricates a price of its own."""
        assert_paper_mode()
        exception = None
        if bid is not None and bid > 0:
            price = float(bid)
        elif fallback_price is not None:
            price = float(fallback_price)
            exception = "NO_BID_AT_EXIT_USED_CALLER_FALLBACK"
        else:
            raise ValueError("No BID and no fallback price supplied for the paper exit")
        spread = (ask - bid) if (ask is not None and bid is not None) else None
        fill = PaperFill(
            timestamp=timestamp, side="SELL", price=price, bid=bid, ask=ask, ltp=ltp,
            spread=spread, spread_pct=(spread / ask * 100) if (spread is not None and ask) else None,
            quantity=quantity, data_exception=exception,
        )
        self.fills.append(fill)
        return fill

    # -- the door that is nailed shut -----------------------------------
    def __getattr__(self, name: str):
        """Any attempt to call a real-broker style method on the paper
        broker raises rather than silently doing nothing, so a future
        refactor that assumes a broker interface fails loudly."""
        raise RealOrderAttemptError(
            f"PaperBroker has no '{name}'. This is a simulator: real order routing "
            f"does not exist in the paper trading package."
        )


def compute_pnl(entry_price: float, exit_price: float, quantity: int) -> dict:
    """Long-option P&L only (the agent buys CE or PE and never writes).
    PRE-COST by construction -- see the module docstring."""
    gross = (exit_price - entry_price) * quantity
    return {
        "gross_pnl": round(gross, 2),
        "costs": None,
        "net_pnl": round(gross, 2),
        "return_pct": round((exit_price - entry_price) / entry_price * 100, 3) if entry_price else None,
        "basis": PNL_BASIS,
    }
