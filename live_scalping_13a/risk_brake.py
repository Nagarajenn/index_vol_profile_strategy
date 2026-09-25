"""The risk brake (spec 15-19, 22).

ACTIVE or LOCKED. When LOCKED, BUY CE and BUY PE are both disabled and only WAIT is produced;
an already-open position continues to be MANAGED, because refusing to manage a live position is
not risk control, it is abandonment.

Allocated capital and the daily loss limit are separate quantities and are never conflated.
The lockout is driven by REALISED losses (spec 17): unrealised P&L moves minute to minute and
locking on it would halt the day over a position that has not been closed.
"""

from dataclasses import dataclass, field

from live_scalping_13a.config import ACTIVE, DEFAULT, LOCKED


@dataclass
class RiskState:
    realised_pnl: float = 0.0
    unrealised_pnl: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    open_position_value: float = 0.0
    lock_reasons: list = field(default_factory=list)

    def record_close(self, pnl: float) -> None:
        self.realised_pnl += pnl
        self.trades_today += 1
        self.consecutive_losses = self.consecutive_losses + 1 if pnl <= 0 else 0

    @property
    def total_pnl(self) -> float:
        return self.realised_pnl + self.unrealised_pnl


def evaluate(state: RiskState, cfg=DEFAULT) -> dict:
    """The brake's verdict plus every number the UI must show."""
    r = cfg.risk
    reasons = []
    if state.realised_pnl <= -r.max_daily_loss:
        reasons.append(f"DAILY_LOSS: realised {state.realised_pnl:,.2f} has reached the "
                       f"{-r.max_daily_loss:,.2f} limit")
    if state.consecutive_losses >= r.max_consecutive_losses:
        reasons.append(f"CONSECUTIVE_LOSSES: {state.consecutive_losses} of {r.max_consecutive_losses}")
    if state.trades_today >= r.max_trades_per_day:
        reasons.append(f"TRADE_COUNT: {state.trades_today} of {r.max_trades_per_day}")

    locked = bool(reasons)
    remaining = max(r.max_daily_loss + state.realised_pnl, 0.0)
    return dict(
        state=LOCKED if locked else ACTIVE,
        lock_reasons=reasons,
        # the four quantities the UI must keep distinct (spec 16/22)
        allocated_capital=r.experiment_capital,
        max_daily_loss=r.max_daily_loss,
        daily_realised_pnl=round(state.realised_pnl, 2),
        daily_unrealised_pnl=round(state.unrealised_pnl, 2),
        daily_total_pnl=round(state.total_pnl, 2),
        remaining_daily_risk=round(remaining, 2),
        consecutive_losses=state.consecutive_losses,
        max_consecutive_losses=r.max_consecutive_losses,
        trades_today=state.trades_today,
        max_trades_per_day=r.max_trades_per_day,
        open_position_value=round(state.open_position_value, 2),
        max_position_value=r.max_position_value,
        note=("Trading is LOCKED: " + "; ".join(reasons) + ". An open position is still managed."
              if locked else
              f"Active. {remaining:,.2f} of the {r.max_daily_loss:,.2f} daily loss limit remains. "
              f"Allocated capital ({r.experiment_capital:,.2f}) is NOT the loss limit."),
    )


def position_allowed(state: RiskState, entry_value: float | None, cfg=DEFAULT) -> tuple:
    """(allowed, reason) for a specific candidate's size."""
    r = cfg.risk
    v = evaluate(state, cfg)
    if v["state"] == LOCKED:
        return False, "RISK_LOCKED"
    if entry_value is None:
        return False, "CRITICAL_DATA_MISSING"
    if entry_value > r.max_position_value:
        return False, "RISK_LOCKED"
    return True, None
