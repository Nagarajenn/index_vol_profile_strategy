"""One hypothetical position at a time (spec 13/14/21/28).

Price discipline, unchanged from 12C: buy at the ASK, mark and exit on the BID, never LTP and
never the midpoint. P&L = (current BID - entry ASK) x quantity, which is exactly the identity
the reconciliation gate checks.

The stop is fixed at entry and never moves. Widening a stop, moving it away or averaging down
are prohibited (spec 28) and there is no code path that can do any of them: `stop_price` is
written once in `open_position` and read-only thereafter.
"""

from dataclasses import dataclass, field

from option_risk_12b.option_snapshot import shift
from live_scalping_13a import features as FE
from live_scalping_13a.config import DEFAULT

OPEN, CLOSED = "OPEN", "CLOSED"


@dataclass
class Position:
    symbol: str
    session_date: str
    side: str
    strike: float
    expiry: str | None
    contract: str
    signal_minute: str
    entry_minute: str
    entry_ask: float
    quantity: int
    stop_price: float          # set once at entry; never modified
    quality: str
    entry_value: float
    status: str = OPEN
    exit_minute: str | None = None
    exit_bid: float | None = None
    exit_reason: str | None = None
    realised_pnl_per_unit: float | None = None
    realised_pnl: float | None = None
    mfe_per_unit: float | None = None
    mae_per_unit: float | None = None
    marks: list = field(default_factory=list)

    def mark(self, series: dict, minute: str) -> dict:
        """The live card (spec 21). Marking never changes the stop or the entry."""
        q = FE.quote(series, minute, self.side, self.strike)
        bid = q["bid"]
        if bid is None:
            return dict(minute=minute, priced=False, note="No executable bid this minute.")
        per_unit = round(bid - self.entry_ask, 2)
        self.marks.append((minute, bid))
        diffs = [round(b - self.entry_ask, 2) for _, b in self.marks]
        self.mfe_per_unit, self.mae_per_unit = max(diffs), min(diffs)
        return dict(
            minute=minute, priced=True, contract=self.contract, strike=self.strike,
            entry_ask=self.entry_ask, current_bid=bid, current_ask=q["ask"], current_ltp=q["ltp"],
            quantity=self.quantity, entry_value=self.entry_value,
            current_value=round(bid * self.quantity, 2),
            pnl_per_unit=per_unit, pnl=round(per_unit * self.quantity, 2),
            pnl_pct=round(per_unit / self.entry_ask * 100, 3) if self.entry_ask else None,
            stop_loss=self.stop_price,
            distance_to_stop=round(bid - self.stop_price, 2),
            distance_to_stop_pct=round((bid - self.stop_price) / self.entry_ask * 100, 3)
            if self.entry_ask else None,
            mfe_per_unit=self.mfe_per_unit, mae_per_unit=self.mae_per_unit,
            mfe=round(self.mfe_per_unit * self.quantity, 2),
            mae=round(self.mae_per_unit * self.quantity, 2),
            hold_minutes=_mins(self.entry_minute, minute),
            stop_breached=bid <= self.stop_price,
        )

    def close(self, series: dict, minute: str, reason: str) -> dict:
        q = FE.quote(series, minute, self.side, self.strike)
        self.status, self.exit_minute, self.exit_reason = CLOSED, minute, reason
        if q["bid"] is not None:
            self.exit_bid = q["bid"]
            self.realised_pnl_per_unit = round(q["bid"] - self.entry_ask, 2)
            self.realised_pnl = round(self.realised_pnl_per_unit * self.quantity, 2)
        return self.to_dict()

    def to_dict(self) -> dict:
        return dict(symbol=self.symbol, session_date=self.session_date, side=self.side,
                    strike=self.strike, expiry=self.expiry, contract=self.contract,
                    signal_minute=self.signal_minute, entry_minute=self.entry_minute,
                    entry_ask=self.entry_ask, quantity=self.quantity, entry_value=self.entry_value,
                    stop_price=self.stop_price, quality=self.quality, status=self.status,
                    exit_minute=self.exit_minute, exit_bid=self.exit_bid,
                    exit_reason=self.exit_reason,
                    realised_pnl_per_unit=self.realised_pnl_per_unit, realised_pnl=self.realised_pnl,
                    mfe_per_unit=self.mfe_per_unit, mae_per_unit=self.mae_per_unit,
                    hold_minutes=_mins(self.entry_minute, self.exit_minute) if self.exit_minute else None)


def _mins(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None
    def idx(x):
        h, m = (int(v) for v in x.split(":"))
        return h * 60 + m
    return idx(b) - idx(a)


def open_position(series: dict, minute: str, symbol: str, session_date, side: str, strike: float,
                  quantity: int, quality: str, cfg=DEFAULT) -> Position | None:
    """Entry at the ASK. Returns None when there is no executable ask -- never a guessed fill."""
    q = FE.quote(series, minute, side, strike)
    if q["ask"] is None or not quantity:
        return None
    ask = q["ask"]
    return Position(symbol=symbol, session_date=str(session_date), side=side, strike=strike,
                    expiry=str(series[minute].get("expiry")) if minute in series else None,
                    contract=f"{symbol} {strike:g} {side}", signal_minute=minute, entry_minute=minute,
                    entry_ask=ask, quantity=quantity,
                    stop_price=round(ask * (1 - cfg.gates.stop_loss_pct / 100), 2),
                    quality=quality, entry_value=round(ask * quantity, 2))
