"""The virtual paper account: 15,000 rupees of entirely fictional capital.

Risk controls here are hard gates evaluated BEFORE a decision is allowed
to become a trade. They are deliberately blunt -- no scaling with
confidence, no averaging down, no martingale, no size increase after a
loss. Position size is a deterministic function of the configured
premium-at-risk cap and the option's own premium, and of nothing else.
"""

from dataclasses import dataclass, field
from datetime import date

from paper_trading.config import PaperConfig
from paper_trading.models import PaperAccountSnapshot


@dataclass
class ClosedTrade:
    session_date: date
    symbol: str
    net_pnl: float


@dataclass
class PaperAccount:
    config: PaperConfig
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    capital_in_trade: float = 0.0
    peak_capital: float | None = None

    def __post_init__(self) -> None:
        if self.peak_capital is None:
            self.peak_capital = self.config.starting_capital

    # ---- balances ----------------------------------------------------
    @property
    def realized_pnl(self) -> float:
        return round(sum(t.net_pnl for t in self.closed_trades), 2)

    @property
    def current_capital(self) -> float:
        return round(self.config.starting_capital + self.realized_pnl, 2)

    @property
    def available_capital(self) -> float:
        return round(self.current_capital - self.capital_in_trade, 2)

    @property
    def max_drawdown(self) -> float:
        """Peak-to-trough on realised equity, as a positive number."""
        equity = self.config.starting_capital
        peak, worst = equity, 0.0
        for t in self.closed_trades:
            equity += t.net_pnl
            peak = max(peak, equity)
            worst = max(worst, peak - equity)
        return round(worst, 2)

    def daily_pnl(self, session_date: date) -> float:
        return round(sum(t.net_pnl for t in self.closed_trades if t.session_date == session_date), 2)

    def trades_today(self, session_date: date) -> int:
        return sum(1 for t in self.closed_trades if t.session_date == session_date)

    def trades_today_for_symbol(self, session_date: date, symbol: str) -> int:
        return sum(1 for t in self.closed_trades if t.session_date == session_date and t.symbol == symbol)

    # ---- risk gates --------------------------------------------------
    def can_trade(self, session_date: date, symbol: str, open_positions: int) -> tuple[bool, str | None]:
        """Every gate that can block a trade before it is even sized.
        Returns (allowed, blocking_reason)."""
        if open_positions >= self.config.max_concurrent_positions:
            return False, "RISK_LIMIT"
        if self.trades_today(session_date) >= self.config.max_trades_per_day:
            return False, "RISK_LIMIT"
        if self.trades_today_for_symbol(session_date, symbol) >= self.config.max_trades_per_symbol_per_day:
            return False, "RISK_LIMIT"
        if self.daily_pnl(session_date) <= -self.config.max_daily_loss:
            return False, "RISK_LIMIT"
        if self.max_drawdown >= self.config.max_account_drawdown:
            return False, "RISK_LIMIT"
        if self.available_capital <= 0:
            return False, "RISK_LIMIT"
        return True, None

    # ---- sizing ------------------------------------------------------
    def position_size(self, premium: float, lot_size: int = 1) -> int:
        """Deterministic. Never scaled by confidence, never increased after
        a loss, never averaged into an existing position."""
        if premium is None or premium <= 0:
            return 0
        budget = min(self.config.max_capital_per_trade, self.available_capital)
        units = int(budget // (premium * lot_size))
        return max(0, units) * lot_size

    def record_close(self, session_date: date, symbol: str, net_pnl: float) -> None:
        self.closed_trades.append(ClosedTrade(session_date, symbol, net_pnl))
        self.capital_in_trade = 0.0

    # ---- reporting ---------------------------------------------------
    def snapshot(self, session_date: date, unrealized_pnl: float = 0.0) -> PaperAccountSnapshot:
        wins = [t.net_pnl for t in self.closed_trades if t.net_pnl > 0]
        losses = [t.net_pnl for t in self.closed_trades if t.net_pnl <= 0]
        streak_w = streak_l = 0
        for t in reversed(self.closed_trades):
            if t.net_pnl > 0 and streak_l == 0:
                streak_w += 1
            elif t.net_pnl <= 0 and streak_w == 0:
                streak_l += 1
            else:
                break
        gross_win, gross_loss = sum(wins), abs(sum(losses))
        return PaperAccountSnapshot(
            session_date=session_date,
            starting_capital=self.config.starting_capital,
            current_capital=self.current_capital,
            available_capital=self.available_capital,
            capital_in_trade=self.capital_in_trade,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=round(unrealized_pnl, 2),
            daily_pnl=self.daily_pnl(session_date),
            total_pnl=self.realized_pnl,
            daily_drawdown=round(min(0.0, self.daily_pnl(session_date)), 2),
            max_drawdown=self.max_drawdown,
            trade_count=len(self.closed_trades),
            win_count=len(wins), loss_count=len(losses),
            consecutive_wins=streak_w, consecutive_losses=streak_l,
            average_win=round(sum(wins) / len(wins), 2) if wins else None,
            average_loss=round(sum(losses) / len(losses), 2) if losses else None,
            largest_win=round(max(wins), 2) if wins else None,
            largest_loss=round(min(losses), 2) if losses else None,
            profit_factor=round(gross_win / gross_loss, 2) if gross_loss else None,
        )
