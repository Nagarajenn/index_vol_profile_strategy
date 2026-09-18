"""12A engine: evaluate one symbol-session bar by bar, causally.

At bar i only bars 0..i are read to DECIDE; the hypothetical fill is the ASK
of bar i + entry_delay_bars (2: the first bar that closes after a live observer
can have seen bar i). Counterfactual and exit tracking then read later bars, which is
outcome measurement, never decision input (pinned by the truncation test).

Deterministic and stateless: re-running on a longer prefix of the same
session reproduces every earlier candidate exactly, which is what lets the
live shadow recorder recompute each tick and upsert idempotently.
"""

from dataclasses import dataclass, field

from scalp_12a.config import ScalpConfig
from scalp_12a.confirmation import confirm
from scalp_12a.counterfactual import track
from scalp_12a.events import detect_event, futures_stale
from scalp_12a.exits import OPEN, simulate_exit
from scalp_12a.models import Candidate, Selection, SessionBars, Thresholds
from scalp_12a.modes import market_mode, window_vetoes
from scalp_12a.opportunity import measure as measure_opportunity
from scalp_12a.option_selector import select_option
from scalp_12a.risk import plan_risk
from scalp_12a.taxonomy import DAILY_LIMIT_REACHED, EVENT_EXPIRED, INSUFFICIENT_HISTORY, POSITION_OPEN, WEAK


@dataclass
class SessionResult:
    candidates: list[Candidate]
    bars_evaluated: int
    stale_bars: int
    session_reasons: list[str] = field(default_factory=list)


@dataclass
class PolicyState:
    """Shared across both symbols of one trading day (12A account rules)."""
    open_until: object = None           # datetime the open position exits, or None
    trades: int = 0
    realised_rupees: float = 0.0


def _dedupe(items):
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def evaluate_session(session: SessionBars, thr: Thresholds, config: ScalpConfig, context_fn=None,
                     session_complete: bool = True, policy: PolicyState | None = None,
                     start_index: int = 0, apply_policy: bool = True) -> SessionResult:
    policy = policy or PolicyState()
    cooldown = config.cooldown_seconds // config.bar_seconds
    candidates: list[Candidate] = []
    if not thr.sufficient:
        return SessionResult([], 0, 0, [INSUFFICIENT_HISTORY])
    last_strong_i = -10**9      # cooldown applies after STRONG candidates ...
    last_any_i = -10**9         # ... while a WEAK near-miss never blocks the STRONG event behind it
    stale = 0
    evaluated = 0
    for i in range(start_index, len(session)):
        evaluated += 1
        if futures_stale(session, i, config):
            stale += 1
            continue
        if i - last_strong_i < cooldown:
            continue
        event = detect_event(session, i, thr, config)
        if event is None:
            continue
        if event.strength == WEAK and i - last_any_i < cooldown:
            continue
        last_any_i = i
        if event.strength != WEAK:
            last_strong_i = i
        ts = session.times[i]
        mode = market_mode(ts, config)
        reasons = window_vetoes(ts, session.is_expiry_day, config)
        selection = select_option(session, event, i, config)
        reasons += selection.reasons
        conf_reasons, conf_detail = confirm(session, event, selection, i, thr, config)
        reasons += conf_reasons
        plan = plan_risk(event, selection, config) if selection.leg else None
        if plan:
            reasons += plan.reasons

        # Counterfactual leg: the selected leg, else the direction's ATM leg.
        key = (selection.leg.option_type, selection.leg.atm_offset) if selection.leg else \
            ("CE" if event.direction > 0 else "PE", 0)
        entry_index = i + config.entry_delay_bars
        if entry_index >= len(session):
            if session_complete:
                reasons.append(EVENT_EXPIRED)
            cf = None
        else:
            eq = session.quote(key, entry_index)
            if eq is None or not eq.valid:
                reasons.append(EVENT_EXPIRED)
            cf = track(session, key, entry_index, event.direction, config, session_complete)
        opportunity = measure_opportunity(session, event, i, entry_index, key, config, session_complete)

        cf_plan = plan
        leg_source = "SELECTED" if selection.leg else "NONE"
        if cf_plan is None and key in session.legs and session.quote(key, i) and session.quote(key, i).valid:
            cf_plan = plan_risk(event, Selection(session.legs[key], session.quote(key, i), None, None, 0), config)
            leg_source = "ATM_FALLBACK"
        cf_exit = None
        if cf is not None and cf_plan is not None:
            cf_exit = simulate_exit(session, key, entry_index, event, cf_plan, config, session_complete)

        reasons = _dedupe(reasons)
        passed = not reasons and entry_index < len(session)
        would_trade = False
        policy_exit = None
        if passed and apply_policy:
            if policy.open_until is not None and ts < policy.open_until:
                reasons.append(POSITION_OPEN)
            elif policy.trades >= config.max_trades_per_day or \
                    policy.realised_rupees <= -config.max_daily_loss:
                reasons.append(DAILY_LIMIT_REACHED)
            else:
                would_trade = True
                policy_exit = simulate_exit(session, key, entry_index, event, plan, config, session_complete)
                policy.trades += 1
                if policy_exit.reason == OPEN or policy_exit.exit_index is None:
                    policy.open_until = session.times[-1]
                else:
                    policy.open_until = session.times[policy_exit.exit_index]
                    if policy_exit.pnl_pct is not None:
                        policy.realised_rupees += policy_exit.pnl_pct / 100.0 * plan.entry_ref_ask * plan.quantity
        dq = "GOOD"
        if selection.rejections.get("stale_quote") or (cf is not None and not cf.complete):
            dq = "DEGRADED" if selection.rejections.get("stale_quote") else "PARTIAL"
        candidates.append(Candidate(
            symbol=session.symbol, trading_date=session.trading_date, bar_index=i, bar_ts=ts, mode=mode,
            event=event, selection=selection, risk=plan, no_trade_reasons=reasons, passed_gates=passed,
            would_trade=would_trade, confirmation=conf_detail,
            context=context_fn(ts) if context_fn else {}, counterfactual=cf, policy_exit=policy_exit,
            counterfactual_exit=cf_exit, counterfactual_leg_source=leg_source if cf else "NONE",
            opportunity=opportunity,
            data_quality=dq))
    return SessionResult(candidates, evaluated, stale, [])


def evaluate_day(sessions: list[SessionBars], thresholds: dict, config: ScalpConfig, context_fn=None,
                 session_complete: bool = True) -> dict[str, SessionResult]:
    """Both symbols of one day, interleaved in time so the shared account policy
    (one position, daily trade/loss caps) is applied in chronological order."""
    policy = PolicyState()
    raw = {}
    for s in sessions:
        ctx = (lambda ts, sym=s.symbol: context_fn(sym, ts)) if context_fn else None
        raw[s.symbol] = evaluate_session(s, thresholds[s.symbol], config, ctx, session_complete, apply_policy=False)
    by_symbol = {s.symbol: s for s in sessions}
    ordered = sorted((c for r in raw.values() for c in r.candidates), key=lambda c: (c.bar_ts, c.symbol))
    for c in ordered:
        if not c.passed_gates:
            continue
        if policy.open_until is not None and c.bar_ts < policy.open_until:
            c.no_trade_reasons.append(POSITION_OPEN)
            continue
        if policy.trades >= config.max_trades_per_day or policy.realised_rupees <= -config.max_daily_loss:
            c.no_trade_reasons.append(DAILY_LIMIT_REACHED)
            continue
        s = by_symbol[c.symbol]
        key = (c.selection.leg.option_type, c.selection.leg.atm_offset)
        c.policy_exit = simulate_exit(s, key, c.bar_index + config.entry_delay_bars, c.event, c.risk, config,
                                      session_complete)
        c.would_trade = True
        policy.trades += 1
        if c.policy_exit.exit_index is None:
            policy.open_until = s.times[-1]
        else:
            policy.open_until = s.times[c.policy_exit.exit_index]
            if c.policy_exit.pnl_pct is not None:
                policy.realised_rupees += c.policy_exit.pnl_pct / 100.0 * c.policy_exit.entry_ask * c.risk.quantity
    return raw
