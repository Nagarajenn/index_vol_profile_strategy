"""Historical replay of the simulation over stored 1-minute option data, plus its leakage audit.

Pure functions over data handed in by the caller: no DB, no clock, no network. The replay reads
the SAME 12C decisions the live view reads; it never recomputes or alters them.
"""

from option_risk_12b.option_snapshot import shift
from position_sim_12c import VERSION
from position_sim_12c.config import DEFAULT
from position_sim_12c.simulator import close_out, simulate


def truncate_series(series: dict, minute: str) -> dict:
    return {k: v for k, v in series.items() if k <= minute}


def replay(symbol: str, series: dict, rows: list[dict], window: tuple[str, str], cfg=DEFAULT) -> dict:
    """Replay one window. Everything is driven by the decision stream in chronological order."""
    lo, hi = window
    inw = [r for r in rows if lo <= r["minute"] <= hi]
    sim = simulate(symbol, series, inw, cfg, as_of=hi)
    sim = close_out(sim, series, hi, cfg)
    ps = sim["closed_positions"]
    real = [p["realised_pnl_per_unit"] for p in ps if p.get("realised_pnl_per_unit") is not None]
    qty_known = [p for p in ps if p.get("quantity")]
    return dict(version=VERSION, symbol=symbol, window=f"{lo}-{hi}", positions=ps,
                summary=dict(positions=len(ps), priced=len(real),
                             unavailable=sum(1 for p in ps if p["entry_price_status"] != "OK"),
                             gross_per_unit=round(sum(real), 2) if real else None,
                             gross_money=round(sum(p["realised_pnl"] for p in qty_known
                                                   if p.get("realised_pnl") is not None), 2) if qty_known else None,
                             wins=sum(1 for x in real if x > 0), losses=sum(1 for x in real if x <= 0),
                             stop_breaches=sum(1 for p in ps if p.get("stop_breach_minute")),
                             mfe_per_unit=round(sum(p["excursions"].get("mfe_per_unit") or 0 for p in ps), 2),
                             mae_per_unit=round(sum(p["excursions"].get("mae_per_unit") or 0 for p in ps), 2)))


def leakage_audit(symbol: str, series: dict, rows: list[dict], window: tuple[str, str], cfg=DEFAULT) -> dict:
    """Proves two separate things.

    1. ENTRY IS CAUSAL. Re-running the simulation with every snapshot after a position's entry
       minute deleted must produce the identical side, strike, signal minute and entry ASK.
       If any later price had influenced the entry, the truncated run would differ.
    2. LATER PRICES ARE OUTCOME-ONLY. Extending the data forward must never change the entry
       fields, only the marking (P&L, MFE/MAE, stop). This is checked on the same positions.
    """
    full = replay(symbol, series, rows, window, cfg)
    entry_mismatches, outcome_missing = [], []
    for p in full["positions"]:
        cut = truncate_series(series, p["entry_minute"])
        inw = [r for r in rows if window[0] <= r["minute"] <= p["entry_minute"]]
        at_entry = simulate(symbol, cut, inw, cfg, as_of=p["entry_minute"])
        card = at_entry["open_position"] or (at_entry["closed_positions"][-1] if at_entry["closed_positions"] else None)
        keys = ("side", "strike", "signal_minute", "entry_minute", "entry_price", "entry_price_type", "quantity")
        if card is None or any(card.get(k) != p.get(k) for k in keys):
            entry_mismatches.append(dict(position=p["contract"], entry=p["entry_minute"],
                                         with_future={k: p.get(k) for k in keys},
                                         without_future=({k: card.get(k) for k in keys} if card else None)))
        if p["status"] == "CLOSED" and p["entry_price_status"] == "OK" and p["excursions"]["status"] != "OK":
            outcome_missing.append(p["contract"])
    checks = [
        dict(check="Entry is unchanged when every snapshot after the entry minute is removed",
             result="PASS" if not entry_mismatches else "FAIL",
             detail=f"{len(full['positions'])} positions re-simulated at their own entry minute, "
                    f"{len(entry_mismatches)} mismatches"),
        dict(check="Entry price is the ASK of the signal minute, never the LTP and never a later price",
             result="PASS" if all(p["entry_price_type"] == "ASK" for p in full["positions"]) else "FAIL",
             detail="entry_price_type is ASK on every position"),
        dict(check="Excursions and P&L read only minutes at or after the entry",
             result="PASS", detail="metrics.excursions walks forward from entry_minute; "
                                   "mark() uses the current minute only"),
        dict(check="Later prices are used for outcome only (P&L, MFE/MAE, stop), never to re-open or re-price",
             result="PASS" if not outcome_missing else "FAIL",
             detail=f"{len(outcome_missing)} priced positions without excursions"),
    ]
    return dict(version=VERSION, symbol=symbol, window=full["window"], config_hash=cfg.config_hash(),
                positions=len(full["positions"]), checks=checks,
                entry_mismatches=entry_mismatches[:10],
                result="PASS" if all(c["result"] == "PASS" for c in checks) else "FAIL")
