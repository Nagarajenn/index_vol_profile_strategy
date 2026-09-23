"""The hard caps. Every one is checked immediately before an order is built, in one place,
against freshly read state -- never against a value cached earlier in the tick.

Design rules for this module:
  * Pure function of an explicit context. No DB access, no clock, no network.
  * It returns REFUSALS, never raises: a refusal is a normal outcome that must be journalled.
  * Default-deny. An unknown or missing input refuses; it never falls through to allow.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from live_trading.config import (DEFAULT, HALT_AFTER_FIRST_LOSS, LOTS_PER_ENTRY, MAX_ENTRIES_PER_DAY,
                                 MAX_ENTRY_COST_RS, STARTING_CAPITAL_RS, SYMBOL_BY_WEEKDAY)

CONFIRMATION_RANK = {"NONE": 0, "WEAK": 1, "MODERATE": 2, "STRONG": 3}


@dataclass
class EntryContext:
    """Everything the guards are allowed to look at."""
    symbol: str
    session_date: date
    now: datetime
    minute: str                      # 'HH:MM' of the signal
    decision: str                    # BUY_CE / BUY_PE / WAIT
    confirmation: str | None
    episode_minutes: int             # consecutive minutes this BUY side has held
    armed: bool
    halted: bool
    halt_reason: str | None
    kill_switch: bool
    entries_used: int
    open_position: bool
    realised_pnl: float              # today, so far
    correlation_id: str
    already_seen: bool               # this correlation id is already in live_orders
    last_entry_minute: str | None    # signal minute of the most recent entry today, if any
    contract_ok: bool
    contract_reason: str
    lot_size: int | None
    ask: float | None
    spread_pct: float | None
    snapshot_age_min: float | None
    cfg: object = field(default=DEFAULT)

    @property
    def episode_start(self) -> str:
        """The minute this unbroken run of the same decision began."""
        h, m = (int(x) for x in self.minute.split(":"))
        total = h * 60 + m - max(self.episode_minutes - 1, 0)
        return f"{total // 60:02d}:{total % 60:02d}"

    @property
    def entry_cost(self) -> float | None:
        if self.ask is None or not self.lot_size:
            return None
        return self.ask * self.lot_size * LOTS_PER_ENTRY


def check(ctx: EntryContext) -> tuple[list[str], list[str]]:
    """(refusals, passed). An empty refusal list means an order may be built.

    Order matters only for readability -- every guard is evaluated, so the journal records
    every reason the trade did not happen, not just the first."""
    cfg = ctx.cfg
    refuse, passed = [], []

    def g(name: str, ok: bool, why: str):
        (passed if ok else refuse).append(name if ok else f"{name}: {why}")

    # -- 0. is this even an entry signal
    g("SIGNAL", ctx.decision in ("BUY_CE", "BUY_PE"), f"decision is {ctx.decision}, not a BUY")

    # -- 1..3 the trader's stated caps
    g("MAX_ENTRIES", ctx.entries_used < MAX_ENTRIES_PER_DAY,
      f"{ctx.entries_used} of {MAX_ENTRIES_PER_DAY} entries already used today")
    g("LOSS_HALT", not (HALT_AFTER_FIRST_LOSS and ctx.realised_pnl < 0),
      f"the day is halted after a realised loss of Rs {ctx.realised_pnl:,.2f}")
    g("HALTED", not ctx.halted, ctx.halt_reason or "session halted")

    # -- 4..6 operator control
    g("ONE_AT_A_TIME", not ctx.open_position, "a live position is already open")
    g("ARMED", ctx.armed, "the session is not armed")
    g("KILL_SWITCH", not ctx.kill_switch, "the kill switch is on")

    # -- 7 which symbol may trade today
    allowed = SYMBOL_BY_WEEKDAY.get(ctx.session_date.weekday(), ())
    g("SYMBOL_OF_THE_DAY", ctx.symbol in allowed,
      f"{ctx.symbol} is not scheduled for {ctx.session_date.strftime('%A')} (allowed: {', '.join(allowed) or 'none'})")

    # -- 8 entry qualifiers
    g("CONFIRMATION",
      CONFIRMATION_RANK.get(ctx.confirmation or "NONE", 0) >= CONFIRMATION_RANK[cfg.min_confirmation],
      f"confirmation is {ctx.confirmation or 'NONE'}, not {cfg.min_confirmation}")
    g("EPISODE", ctx.episode_minutes >= cfg.min_episode_minutes,
      f"the BUY has held {ctx.episode_minutes} minute(s), needs {cfg.min_episode_minutes}")
    g("TIME_WINDOW", cfg.entry_window_start <= ctx.minute <= cfg.entry_window_end,
      f"{ctx.minute} is outside the entry window {cfg.entry_window_start}-{cfg.entry_window_end}")
    # One entry per episode. Without this, a BUY that keeps running qualifies on EVERY
    # subsequent minute (episode length only grows), so both of the day's slots can be spent
    # on one continuous opinion a minute apart -- observed in the 2026-09-23 dry run at
    # 09:51 and 09:52. The episode that produced the last entry must END before another.
    g("NEW_EPISODE", ctx.last_entry_minute is None or ctx.last_entry_minute < ctx.episode_start,
      f"already entered at {ctx.last_entry_minute} inside this same episode (started {ctx.episode_start})")

    # -- 9 data quality
    g("DATA_FRESH", ctx.snapshot_age_min is not None and ctx.snapshot_age_min <= cfg.max_snapshot_age_min,
      f"latest option snapshot is {ctx.snapshot_age_min} min old (max {cfg.max_snapshot_age_min})"
      if ctx.snapshot_age_min is not None else "snapshot age is unknown")
    g("SPREAD", ctx.spread_pct is not None and ctx.spread_pct <= cfg.max_spread_pct,
      f"spread {ctx.spread_pct:.2f}% exceeds {cfg.max_spread_pct:.2f}%" if ctx.spread_pct is not None
      else "spread is unknown")

    # -- 10 the contract and its cost
    g("CONTRACT", ctx.contract_ok, ctx.contract_reason)
    cost = ctx.entry_cost
    g("ENTRY_COST", cost is not None and cost <= MAX_ENTRY_COST_RS,
      f"1 lot would cost Rs {cost:,.0f}, over the Rs {MAX_ENTRY_COST_RS:,.0f} cap "
      f"(quantity is quantised to the lot and cannot be reduced)" if cost is not None
      else "entry cost cannot be computed")
    g("CAPITAL", cost is not None and cost <= STARTING_CAPITAL_RS + min(ctx.realised_pnl, 0.0),
      f"Rs {cost:,.0f} exceeds the capital available" if cost is not None else "capital check needs a cost")

    # -- 11 idempotency
    g("NOT_DUPLICATE", not ctx.already_seen, f"{ctx.correlation_id} has already been acted on")

    return refuse, passed


def correlation_id(symbol: str, session_date: date, minute: str) -> str:
    """Stable per (symbol, day, signal minute): a retry of the same minute can never double-fire."""
    return f"{symbol}:{session_date}:{minute}"
