"""Post-entry management of an already-approved paper position.

This is the ONE place the agent is allowed to use information later than
14:59 -- and only to manage a position the frozen decision already
approved. It can never change that decision: it appends PositionEvents
and may exit, nothing more.

Hard rules, enforced in code rather than by convention:
  * a stop may tighten or stay, NEVER widen (tighten_stop asserts this)
  * a position is force-exited at max_holding_minutes, no exceptions
  * exits price at the BID; a missing BID is a recorded data exception
"""

from datetime import datetime

from paper_trading.config import PaperConfig
from paper_trading.models import MomentumState, PaperPosition, PositionEvent


def tighten_stop(position: PaperPosition, new_stop: float, note: str) -> bool:
    """A stop may only move toward protecting capital. Widening is
    rejected outright -- this is what stops 'give it more room' from ever
    entering the agent's behaviour."""
    if new_stop <= position.current_stop:
        return False
    position.current_stop = round(new_stop, 2)
    return True


def classify_momentum(
    position: PaperPosition, underlying_price: float | None, adverse_minutes: int, config: PaperConfig,
) -> MomentumState:
    """Momentum of the UNDERLYING relative to the direction the position
    was taken in -- not of the option premium, which also moves with IV
    and theta."""
    if underlying_price is None or position.spot_at_entry is None:
        return "MODERATE"
    move = underlying_price - position.spot_at_entry
    favourable = move if position.option_type == "CE" else -move
    if adverse_minutes >= config.momentum_failure_minutes:
        return "FAILED"
    if favourable <= 0:
        return "WEAKENING"
    return "STRONG" if adverse_minutes == 0 else "MODERATE"


def evaluate_minute(
    position: PaperPosition, now: datetime, underlying_price: float | None,
    bid: float | None, ask: float | None, atr_14: float | None,
    adverse_minutes: int, config: PaperConfig,
) -> tuple[str | None, PositionEvent]:
    """One minute of management. Returns (exit_reason_or_None, event).

    Checked in a fixed order so the recorded exit reason is deterministic
    when two conditions become true in the same minute."""
    minutes_in = int((now - position.entry_timestamp).total_seconds() // 60)
    momentum = classify_momentum(position, underlying_price, adverse_minutes, config)
    unrealized = ((bid - position.entry_price) * position.quantity) if bid is not None else None
    exit_reason: str | None = None
    note = ""

    spread_pct = ((ask - bid) / ask * 100) if (ask and bid is not None) else None

    if minutes_in >= config.max_holding_minutes:
        exit_reason, note = "TIME_EXIT", f"Forced exit at the {config.max_holding_minutes}-minute hard limit"
    elif minutes_in < config.min_holding_minutes:
        note = "Below the minimum holding time -- holding regardless of quote"
    elif bid is not None and bid >= position.current_target:
        exit_reason, note = "TARGET_HIT", f"Bid {bid:.2f} reached target {position.current_target:.2f}"
    elif bid is not None and bid <= position.current_stop:
        exit_reason, note = "STOP_HIT", f"Bid {bid:.2f} hit stop {position.current_stop:.2f}"
    elif momentum == "FAILED":
        exit_reason, note = "MOMENTUM_FAILURE", (
            f"Underlying moved against the position for {adverse_minutes} consecutive minutes")
    elif (underlying_price is not None and position.spot_at_entry is not None and atr_14
          and _adverse_move(position, underlying_price) >= config.reversal_atr_multiple * atr_14):
        exit_reason, note = "DIRECTION_REVERSAL", (
            f"Underlying reversed {_adverse_move(position, underlying_price):.0f} pts against entry "
            f"(>= {config.reversal_atr_multiple} x ATR)")
    elif spread_pct is not None and spread_pct > config.exit_spread_pct_limit:
        exit_reason, note = "OPTION_LIQUIDITY_FAILURE", (
            f"Quote deteriorated to a {spread_pct:.1f}% spread (limit {config.exit_spread_pct_limit}%)")
    else:
        note = _maybe_trail(position, bid, momentum, config)

    event = PositionEvent(
        event_timestamp=now, minutes_in_trade=minutes_in,
        event_type=exit_reason or ("TRAIL" if "Tightened" in note else "HOLD"),
        underlying_price=underlying_price, option_bid=bid, option_ask=ask,
        unrealized_pnl=round(unrealized, 2) if unrealized is not None else None,
        momentum=momentum, current_stop=position.current_stop,
        current_target=position.current_target, note=note,
    )
    position.events.append(event)
    return exit_reason, event


def _adverse_move(position: PaperPosition, underlying_price: float) -> float:
    move = underlying_price - position.spot_at_entry
    return abs(min(move, 0.0)) if position.option_type == "CE" else abs(max(move, 0.0))


def _maybe_trail(position: PaperPosition, bid: float | None, momentum: MomentumState, config: PaperConfig) -> str:
    """Deterministic, one-directional protection. It is NOT a P&L-maximising
    trailing stop: it only engages once most of the target is already
    captured, and only ever locks in part of that gain."""
    if bid is None:
        return "No bid this minute -- stop and target unchanged"
    captured = bid - position.entry_price
    required = (position.initial_target - position.entry_price) * config.trail_activate_reward_ratio
    if captured > 0 and required > 0 and captured >= required:
        locked = position.entry_price + captured * config.trail_lock_fraction
        if tighten_stop(position, locked, "trail"):
            return (f"Tightened stop to {position.current_stop:.2f} -- "
                    f"{config.trail_lock_fraction:.0%} of a {captured:.2f} gain locked in")
    if momentum == "WEAKENING":
        return "Momentum weakening -- holding, stop unchanged (a stop is never widened)"
    return "No change -- momentum intact, stop and target unchanged"
