"""Milestone 11C: option candidate universe, 14:59 features, and post-cutoff
realized outcomes. Pure functions (no DB access) reused by scripts/
run_milestone11c.py, mirroring the discipline of market_transition/
direction_dataset.py (which this module deliberately imports constants
from rather than redefining them).

RESEARCH ONLY. Candidate CONSTRUCTION/SELECTION never reads anything
timestamped after 14:59:00 -- see build_candidate_universe(). Post-cutoff
data is read only by the separately-named build_post_cutoff_option_trajectory
/ compute_underlying_outcome / compute_realized_option_outcome functions,
used exclusively to score what WOULD have happened to a candidate already
selected at 14:59, never to influence that selection.
"""

from dataclasses import dataclass
from datetime import date, time
from typing import Callable, Literal

from option_chain.snapshot_features import StrikeDetail, extract_atm_window
from market_transition.direction_dataset import DECISION_CUTOFF, MAX_SNAPSHOT_AGE_SEC

Leg = Literal["CE", "PE"]

ATM_WINDOW_STRIKES = 5  # ATM +/- 5, per this milestone's explicit spec --
# deliberately NOT config.instruments' option_chain_atm_window=10 default,
# which is a different, wider production convention for a different use.

# Post-cutoff outcome window: native 1-minute checkpoints 15:00-15:15
# inclusive (16 points) -- the exact same window Milestone 9/10's actual-
# outcome machinery already uses (transition_actual_outcome, horizon=15).
OUTCOME_MINUTES: list[time] = [time(15, m) for m in range(0, 15)] + [time(15, 15)]
EXIT_CHECKPOINTS: list[time] = [time(15, 0), time(15, 5), time(15, 10), time(15, 15)]

OptionLookupFn = Callable[[str], dict | None]
"""Same contract as direction_dataset.OptionLookupFn: given an 'HH:MM:SS'
string, returns {'fetched_at','expiry','spot','raw_payload'} for the
latest option_chain_raw row at/before that time, or None."""


@dataclass
class CandidateOption:
    symbol: str
    session_date: date
    expiry: date | None
    strike: float
    option_type: Leg
    atm_offset: int  # strikes away from ATM, signed (0 = ATM)
    moneyness: float  # CE: strike-spot (positive=OTM); PE: spot-strike (positive=OTM)
    underlying_price: float
    timestamp: object | None  # the option_chain_raw fetched_at this candidate was built from
    ltp: float | None
    bid: float | None
    ask: float | None
    spread: float | None
    spread_pct: float | None  # spread / ask * 100
    volume: float | None
    oi: float | None
    oi_change: float | None
    iv: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    data_quality: Literal["GOOD", "DEGENERATE_GREEKS", "MISSING_QUOTE"]


def _atm_offset(strike: float, atm_strike: float, step: float) -> int:
    return round((strike - atm_strike) / step) if step else 0


def _moneyness(strike: float, spot: float, option_type: Leg) -> float:
    return (strike - spot) if option_type == "CE" else (spot - strike)


def build_candidate_universe(
    symbol: str, session_date: date, option_at_1459: dict | None, strike_step: float,
    atm_window_strikes: int = ATM_WINDOW_STRIKES,
) -> tuple[list[CandidateOption], str | None]:
    """The ATM+/-`atm_window_strikes` x {CE,PE} universe as of 14:59, built
    ONLY from `option_at_1459` (the caller's already-<=14:59 lookup, same
    contract as direction_dataset.build_pre_cutoff_features). Returns
    (candidates, rejection_reason) -- rejection_reason is None on success,
    else one of "NO_SNAPSHOT" / "STALE_SNAPSHOT" / "EMPTY_CHAIN"."""
    if option_at_1459 is None or not option_at_1459.get("raw_payload"):
        return [], "NO_SNAPSHOT"

    fetched_at = option_at_1459.get("fetched_at")
    if fetched_at is not None:
        cp_dt_naive = None
        try:
            import pandas as pd
            cp_dt = pd.Timestamp.combine(pd.Timestamp(session_date), DECISION_CUTOFF).tz_localize(fetched_at.tzinfo or "Asia/Kolkata")
            age_sec = (cp_dt - fetched_at).total_seconds()
            if age_sec > MAX_SNAPSHOT_AGE_SEC:
                return [], "STALE_SNAPSHOT"
        except Exception:
            pass

    details = extract_atm_window(option_at_1459["raw_payload"], atm_window_strikes=atm_window_strikes)
    if not details:
        return [], "EMPTY_CHAIN"

    spot = option_at_1459["raw_payload"].get("last_price")
    strikes = sorted({d.strike for d in details})
    atm_strike = min(strikes, key=lambda s: abs(s - spot)) if spot is not None else None

    candidates = []
    for d in details:
        offset = _atm_offset(d.strike, atm_strike, strike_step) if atm_strike is not None else 0
        moneyness = _moneyness(d.strike, spot, d.leg) if spot is not None else None
        spread = (d.ask - d.bid) if (d.ask is not None and d.bid is not None) else None
        spread_pct = (spread / d.ask * 100) if (spread is not None and d.ask) else None
        degenerate_greeks = d.delta == 0 and d.gamma == 0 and d.theta == 0 and d.vega == 0
        missing_quote = d.bid is None or d.ask is None or not d.ask
        quality = "MISSING_QUOTE" if missing_quote else ("DEGENERATE_GREEKS" if degenerate_greeks else "GOOD")
        candidates.append(CandidateOption(
            symbol=symbol, session_date=session_date, expiry=option_at_1459.get("expiry"),
            strike=d.strike, option_type=d.leg, atm_offset=offset, moneyness=moneyness,
            underlying_price=spot, timestamp=fetched_at,
            ltp=d.ltp, bid=d.bid, ask=d.ask, spread=spread, spread_pct=spread_pct,
            volume=d.volume, oi=d.oi, oi_change=d.oi_change, iv=d.iv,
            delta=d.delta, gamma=d.gamma, theta=d.theta, vega=d.vega,
            data_quality=quality,
        ))
    return candidates, None


# ---------------------------------------------------------------------
# Post-14:59 realized outcomes -- these functions are the ONLY ones in
# this module permitted to read a time later than 14:59:00.
# ---------------------------------------------------------------------

def build_post_cutoff_option_trajectory(
    strike: float, option_type: Leg, option_lookup_fn: OptionLookupFn, atm_window_strikes: int = ATM_WINDOW_STRIKES,
) -> list[tuple[time, StrikeDetail | None]]:
    """(minute, StrikeDetail-or-None) for every native minute 15:00-15:15
    inclusive. Reuses extract_atm_window (unmodified) at each minute and
    filters to the one (strike, option_type) pair -- never constructs a
    new candidate universe from this data, only measures the ALREADY-
    selected candidate's realized path."""
    out = []
    for minute in OUTCOME_MINUTES:
        row = option_lookup_fn(minute.strftime("%H:%M:%S"))
        detail = None
        if row is not None and row.get("raw_payload"):
            for d in extract_atm_window(row["raw_payload"], atm_window_strikes=atm_window_strikes):
                if d.strike == strike and d.leg == option_type:
                    detail = d
                    break
        out.append((minute, detail))
    return out


def compute_realized_option_outcome(entry_ask: float, trajectory: list[tuple[time, StrikeDetail | None]]) -> dict:
    """Realistic bid-based exit economics: BUY at `entry_ask` (frozen at
    14:59), SELL at BID at each checkpoint. MFE/MAE are diagnostic (best/
    worst bid seen along the path), never the assumed executed return."""
    exits = {}
    for cp in EXIT_CHECKPOINTS:
        detail = next((d for t, d in trajectory if t == cp), None)
        bid = detail.bid if detail else None
        exits[cp.strftime("%H:%M")] = {
            "exit_bid": bid,
            "pnl": (bid - entry_ask) if (bid is not None and entry_ask) else None,
            "pct_return": ((bid - entry_ask) / entry_ask * 100) if (bid is not None and entry_ask) else None,
        }

    bids_with_time = [(t, d.bid) for t, d in trajectory if d is not None and d.bid is not None]
    mfe = mae = None
    time_to_mfe = time_to_mae = None
    if bids_with_time and entry_ask:
        best_t, best_bid = max(bids_with_time, key=lambda x: x[1])
        worst_t, worst_bid = min(bids_with_time, key=lambda x: x[1])
        mfe = (best_bid - entry_ask) / entry_ask * 100
        mae = (worst_bid - entry_ask) / entry_ask * 100
        time_to_mfe = best_t.strftime("%H:%M")
        time_to_mae = worst_t.strftime("%H:%M")

    return {
        "entry_ask": entry_ask,
        "exits": exits,
        "final_pnl": exits.get("15:15", {}).get("pnl"),
        "final_pct_return": exits.get("15:15", {}).get("pct_return"),
        "mfe_pct": mfe, "mae_pct": mae,
        "time_to_mfe": time_to_mfe, "time_to_mae": time_to_mae,
    }


UNDERLYING_CHECKPOINTS: list[time] = [DECISION_CUTOFF, time(15, 0), time(15, 5), time(15, 10), time(15, 15)]


def compute_underlying_outcome(day_candles) -> dict:
    """Close price at 14:59/15:00/15:05/15:10/15:15 plus max favorable/
    adverse move and final move, all measured from the 14:59 baseline.
    `day_candles` must already carry a `time` column (matches direction_
    dataset's own convention)."""
    import pandas as pd
    closes = {}
    for cp in UNDERLYING_CHECKPOINTS:
        sub = day_candles[day_candles["time"] <= cp]
        closes[cp.strftime("%H:%M")] = float(sub["close"].iloc[-1]) if not sub.empty else None

    baseline = closes.get("14:59")
    post_closes = [v for k, v in closes.items() if k != "14:59" and v is not None]
    max_favorable_up = (max(post_closes) - baseline) if (baseline and post_closes) else None
    max_adverse_up = (min(post_closes) - baseline) if (baseline and post_closes) else None
    final_move = (closes.get("15:15") - baseline) if (baseline and closes.get("15:15") is not None) else None
    direction = None
    if final_move is not None:
        direction = "up" if final_move > 0 else ("down" if final_move < 0 else "flat")

    return {
        "closes": closes,
        "baseline_1459": baseline,
        "max_favorable_up_move": max_favorable_up,
        "max_adverse_up_move": max_adverse_up,
        "final_move": final_move,
        "direction": direction,
    }
