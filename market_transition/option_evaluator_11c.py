"""Milestone 11C: aggregation/statistics over a list of symbol-day
decision records (one per evaluated symbol-day, already carrying the
selection result and realized post-14:59 outcome for the opportunity
engine's pick plus every comparison baseline). Pure functions -- no DB
access, no formula changes; this module only summarizes what
option_opportunity_11c.select_candidate() and option_features_11c's
outcome functions already computed.
"""

from statistics import mean, median


def _pct_stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "median": None, "max": None, "min": None}
    return {"n": len(values), "mean": mean(values), "median": median(values), "max": max(values), "min": min(values)}


def evaluate_engine(records: list[dict], pnl_field: str = "final_pct_return") -> dict:
    """`records`: one dict per symbol-day with at minimum: symbol,
    session_date, direction_state, selection_reason ("SELECTED" or a
    NO_TRADE_* reason), selected_option_type, selected_moneyness_bucket,
    expiry_type, confidence_tier, underlying_direction, and (only when
    traded) an `outcome` dict from compute_realized_option_outcome."""
    n_days = len(records)
    traded = [r for r in records if r["selection_reason"] == "SELECTED"]
    no_trade = [r for r in records if r["selection_reason"] != "SELECTED"]

    no_trade_reasons: dict[str, int] = {}
    for r in no_trade:
        no_trade_reasons[r["selection_reason"]] = no_trade_reasons.get(r["selection_reason"], 0) + 1

    pnls = [r["outcome"][pnl_field] for r in traded if r.get("outcome", {}).get(pnl_field) is not None]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p <= 0]
    mfes = [r["outcome"]["mfe_pct"] for r in traded if r.get("outcome", {}).get("mfe_pct") is not None]
    maes = [r["outcome"]["mae_pct"] for r in traded if r.get("outcome", {}).get("mae_pct") is not None]
    spreads = [r["selected_spread_pct"] for r in traded if r.get("selected_spread_pct") is not None]

    direction_correct_traded = [
        r for r in traded if r.get("underlying_direction") is not None and r["direction_state"] == r["underlying_direction"]
    ]
    direction_correct_all = [
        r for r in records if r.get("underlying_direction") is not None and r.get("direction_state") is not None
        and r["direction_state"] == r["underlying_direction"]
    ]
    direction_scoreable_all = [r for r in records if r.get("underlying_direction") is not None and r.get("direction_state") is not None]

    return {
        "n_days": n_days,
        "n_trades": len(traded),
        "n_no_trade": len(no_trade),
        "trade_frequency": (len(traded) / n_days) if n_days else None,
        "no_trade_reasons": no_trade_reasons,
        "direction_accuracy_all_days": (len(direction_correct_all) / len(direction_scoreable_all)) if direction_scoreable_all else None,
        "direction_accuracy_traded_days": (len(direction_correct_traded) / len(traded)) if traded else None,
        "pnl": _pct_stats(pnls),
        "win_rate": (len(winners) / len(pnls)) if pnls else None,
        "avg_winner": mean(winners) if winners else None,
        "avg_loser": mean(losers) if losers else None,
        "max_loss": min(pnls) if pnls else None,
        "mfe": _pct_stats(mfes),
        "mae": _pct_stats(maes),
        "avg_spread_pct": mean(spreads) if spreads else None,
        "by_option_type": _breakdown(traded, "selected_option_type", pnl_field),
        "by_moneyness_bucket": _breakdown(traded, "selected_moneyness_bucket", pnl_field),
        "by_symbol": _breakdown(traded, "symbol", pnl_field),
        "by_expiry_type": _breakdown(traded, "expiry_type", pnl_field),
        "by_confidence_tier": _breakdown(traded, "confidence_tier", pnl_field),
    }


MIN_N_FOR_SEGMENT = 3  # below this, a segment's stats are reported as n only -- not interpreted


def _breakdown(traded: list[dict], key: str, pnl_field: str) -> dict:
    groups: dict = {}
    for r in traded:
        k = r.get(key)
        groups.setdefault(k, []).append(r)
    out = {}
    for k, rows in groups.items():
        pnls = [r["outcome"][pnl_field] for r in rows if r.get("outcome", {}).get(pnl_field) is not None]
        stats = _pct_stats(pnls)
        stats["insufficient_n"] = stats["n"] < MIN_N_FOR_SEGMENT
        out[str(k)] = stats
    return out


def evaluate_baseline(records: list[dict], baseline_key: str, pnl_field: str = "final_pct_return") -> dict:
    """`records[i][baseline_key]` is either None (no candidate existed on
    that side, e.g. no ITM neighbor at the edge of the chain) or a dict
    with at least `final_pct_return`/`mfe_pct`/`mae_pct` -- baselines
    ALWAYS trade when a candidate exists (never NO TRADE by choice), so
    "no candidate" is a data-availability gap, not a decision."""
    outcomes = [r[baseline_key] for r in records if r.get(baseline_key) is not None]
    pnls = [o[pnl_field] for o in outcomes if o.get(pnl_field) is not None]
    winners = [p for p in pnls if p > 0]
    return {
        "n": len(outcomes),
        "pnl": _pct_stats(pnls),
        "win_rate": (len(winners) / len(pnls)) if pnls else None,
    }
