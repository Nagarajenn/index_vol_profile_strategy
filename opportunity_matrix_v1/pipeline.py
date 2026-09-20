"""Assembles the Opportunity Matrix dataset for all HR days, day by day, in chronological order."""

from datetime import datetime, time

from config.settings import IST
from opportunity_matrix_v1 import counterfactual as CF
from opportunity_matrix_v1.baseline import baseline_rows
from opportunity_matrix_v1.closing_state import closing_rows, persistence_movements
from opportunity_matrix_v1.events import detect_events, lead_lag
from opportunity_matrix_v1.response import option_response_rows, strike_universe
from opportunity_matrix_v1.setup import setup_state, snapshots
from opportunity_matrix_v1.thresholds import day_roles, hr_thresholds


def build(days: dict, minute_th: dict, cfg) -> dict:
    """days: {date: {symbol: DayData}} for every HR day; minute_th: {(date, symbol): Thresholds}."""
    dates = sorted(days)
    roles = day_roles(dates, cfg)
    out = {k: [] for k in ("market_states", "setup", "events", "option_response", "strike_universe", "counterfactuals",
                           "closing_state", "persistence", "baseline", "thresholds", "skipped")}
    hth_by = {}
    for d in dates:
        for sym in cfg.symbols:
            day = days[d].get(sym)
            if day is None:
                out["skipped"].append(dict(date=str(d), symbol=sym, reason="NO_HR_DATA"))
                continue
            prior = [days[p][sym] for p in dates if p < d and sym in days[p]]
            hth = hr_thresholds(d, prior, cfg)
            mth = minute_th[(d, sym)]
            hth_by[(d, sym)] = hth
            out["thresholds"].append(dict(date=str(d), symbol=sym, role=roles[d], hr_source_days=[str(x) for x in (hth.source_days if hth else ())],
                                          minute_source_days=[str(x) for x in mth.source_days]))
            snaps = snapshots(day, mth, cfg)
            for s in snaps:
                s["role"] = roles[d]
            out["market_states"] += snaps
            st = setup_state(snaps, mth, cfg)
            st.update(symbol=sym, trade_date=str(d), expiry_flag=day.is_expiry, role=roles[d])
            out["setup"].append(st)
            pre = {s["snapshot"]: s["market_state"] for s in snaps}
            if hth is None:
                out["skipped"].append(dict(date=str(d), symbol=sym, reason=f"SEED_DAY: {len(prior)} prior HR day(s) < {cfg.min_prior_hr_days}"))
                continue
            evs = detect_events(day, hth, cfg)
            for e in evs:
                ll = lead_lag(day, e["i"], e["dir"], hth, cfg)
                e.update(ll)
                g = CF.gates(e, ll, day, hth, cfg)
                e.update({k: v for k, v in g.items() if k != "stage_results"}, stage_results=g["stage_results"])
                e.update(role=roles[d], expiry=str(day.expiry), state_14_30=pre.get("14:30"), state_14_50=pre.get("14:50"),
                         state_14_55=pre.get("14:55"), state_14_59=pre.get("14:59"), setup_state=st["setup_state"],
                         setup_direction=st["setup_direction"],
                         setup_agreement=("AGREE" if st["setup_direction"] == e["dir"] else "DISAGREE" if st["setup_direction"] == -e["dir"] else "NEUTRAL"))
                oc, fav = CF.outcomes(e, g, day, cfg)
                e.update(oc)
                cfs = {lbl: CF.counterfactual(e, g, day, cfg, lbl) for lbl in cfg.entry_offsets}
                for lbl, c in cfs.items():
                    if c:
                        c.update(research_approved=g["research_approved"], window=e["window"], expiry_flag=day.is_expiry,
                                 lead_lag_class=ll["lead_lag_class"], event_type=e["event_type"], role=roles[d], cluster_first=e["cluster_first"])
                        out["counterfactuals"].append(c)
                prim = cfs.get(cfg.primary_entry)
                e["outcome_label"] = CF.outcome_label(prim, fav, cfg)
                for k in ("entry_bid", "entry_ask", "entry_spread_pct", "mfe", "mae", "time_to_mfe", "time_to_mae", "time_to_1", "giveback",
                          "net_return", "hit1_before_minus1", "move_remaining"):
                    e[f"cf_{k}"] = prim.get(k) if prim else None
                out["option_response"] += option_response_rows(e, day, hth, cfg)
                e_idx = e["i"] + cfg.entry_offsets[cfg.primary_entry]
                if e_idx < len(day):
                    for r in strike_universe(day, e_idx, e["dir"], cfg):
                        r.update(event_id=e["event_id"], symbol=sym, entry=cfg.primary_entry)
                        out["strike_universe"].append(r)
            out["events"] += evs
            cr = closing_rows(day, hth, cfg)
            out["closing_state"] += cr
            out["persistence"] += persistence_movements(day, cr, hth, cfg)
            b = baseline_rows(day, evs, cfg)
            for r in b:
                r["role"] = roles[d]
            out["baseline"] += b
    out["roles"] = {str(k): v for k, v in roles.items()}
    out["_hth"] = hth_by
    return out
