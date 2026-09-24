"""Orchestration and aggregation: build the diagnostic rows, then summarise them.

Every grouped statistic carries its N, and groups below `cfg.min_sample` are marked
INSUFFICIENT SAMPLE. Today and history are kept in separate result sets and never merged
without a label (spec 23).
"""

import statistics as st
from collections import Counter, defaultdict

from option_risk_12b.engine import prepare
from option_audit_12e import VERSION, density
from option_audit_12e import loss_attribution as LA
from option_audit_12e import market_state as MS
from option_audit_12e import trade_diagnostic as TD
from option_audit_12e.config import DEFAULT
from scalp_decision_12c import loader
from signal_learning_12d.historical_replay import replay_session

LEVELS_COLS = ("as_of", "close", "vwap_now", "today_poc", "today_vah", "today_val", "support_low",
               "support_high", "resistance_low", "resistance_high", "trend_label")


def _num(xs):
    return [x for x in xs if isinstance(x, (int, float))]


def _levels(conn, symbol, d):
    rows = conn.execute(
        f"""select to_char(as_of at time zone 'Asia/Kolkata','HH24:MI'), {', '.join(LEVELS_COLS[1:])}
            from levels_snapshots where symbol=%s and (as_of at time zone 'Asia/Kolkata')::date=%s
            order by as_of""", (symbol, d)).fetchall()
    return {r[0]: dict(zip(LEVELS_COLS, r)) for r in rows}


def diagnose_session(conn, symbol: str, d, cfg=DEFAULT) -> list[dict]:
    """One symbol-day -> diagnostic rows, one per 12D signal episode."""
    snaps = loader.load_snapshots(conn, symbol, d, start="09:00")
    if not snaps:
        return []
    series, cmap = prepare(snaps, loader.load_candles(conn, symbol, d, start="09:00"))
    signals = replay_session(symbol, d, series, cmap, _levels(conn, symbol, d))
    out = []
    for s in signals:
        row = TD.build(series, s, cfg)
        ms = MS.classify(series, s["signal_minute"], cfg)
        row["market_state"] = ms["state"]
        row["market_state_note"] = ms["note"]
        row["market_lookback_pct"] = ms["lookback_pct"]
        ext = MS.premium_extension(series, s["signal_minute"], s["side"], s.get("strike"))
        row["premium_position_in_range"] = ext["position_in_range"]
        for h in cfg.horizons:
            row[f"quadrant_{h}m"] = LA.quadrant(row, h, cfg)
        if row.get("final_pnl_per_unit") is not None and row["final_pnl_per_unit"] <= 0:
            row.update(LA.classify(row, cfg))
        else:
            row.update(loss_reason=None, loss_note=None, evidence={})
        row["version"] = VERSION
        row["config_hash"] = cfg.config_hash()
        out.append(row)
    return out


# ---------------------------------------------------------------- aggregation
def group(rows, key, cfg=DEFAULT) -> dict:
    g = defaultdict(list)
    for r in rows:
        g[r.get(key) if r.get(key) is not None else "UNKNOWN"].append(r)
    return {k: summarise(v, cfg) for k, v in sorted(g.items(), key=lambda x: -len(x[1]))}


def summarise(rows, cfg=DEFAULT) -> dict:
    pnl = _num([r.get("final_pnl_per_unit") for r in rows])
    und = _num([r.get("und_move_to_exit_pct") for r in rows])
    ratios = _num([r.get("response_ratio_5m") for r in rows])
    effs = _num([r.get("response_efficiency_5m") for r in rows])
    spreads = _num([r.get("entry_spread_pct") for r in rows])
    ivs = _num([r.get("iv_change_to_exit_pct") for r in rows])
    deltas = _num([abs(r["entry_delta"]) for r in rows if r.get("entry_delta") is not None])
    fric = _num([r.get("execution_friction_per_unit") for r in rows])
    mid = _num([r.get("mid_to_mid_per_unit") for r in rows])
    return dict(
        n=len(rows), sufficient=len(rows) >= cfg.min_sample,
        note=None if len(rows) >= cfg.min_sample else "INSUFFICIENT SAMPLE",
        wins=sum(1 for v in pnl if v > 0), losses=sum(1 for v in pnl if v <= 0),
        win_rate=round(sum(1 for v in pnl if v > 0) / len(pnl) * 100, 1) if pnl else None,
        mean_pnl_per_unit=round(st.fmean(pnl), 2) if pnl else None,
        median_pnl_per_unit=round(st.median(pnl), 2) if pnl else None,
        mean_mid_to_mid=round(st.fmean(mid), 2) if mid else None,
        mean_execution_friction=round(st.fmean(fric), 2) if fric else None,
        mean_underlying_move_pct=round(st.fmean(und), 3) if und else None,
        mean_response_ratio_5m=round(st.fmean(ratios), 3) if ratios else None,
        median_response_ratio_5m=round(st.median(ratios), 3) if ratios else None,
        mean_response_efficiency_5m=round(st.fmean(effs), 3) if effs else None,
        median_response_efficiency_5m=round(st.median(effs), 3) if effs else None,
        mean_entry_spread_pct=round(st.fmean(spreads), 3) if spreads else None,
        mean_iv_change_pct=round(st.fmean(ivs), 3) if ivs else None,
        mean_abs_delta=round(st.fmean(deltas), 3) if deltas else None,
    )


def delta_buckets(rows, cfg=DEFAULT) -> dict:
    out = {}
    for lo, hi in cfg.delta_buckets:
        sub = [r for r in rows if r.get("entry_delta") is not None and lo <= abs(r["entry_delta"]) < hi]
        out[f"{lo:.1f}-{hi:.1f}"] = summarise(sub, cfg)
    missing = [r for r in rows if r.get("entry_delta") is None]
    if missing:
        out["delta unavailable"] = summarise(missing, cfg)
    return out


def iv_quantile_buckets(rows, cfg=DEFAULT) -> dict:
    """Empirical terciles of ENTRY IV, per spec 10 -- not a fixed threshold."""
    ivs = sorted(_num([r.get("entry_iv") for r in rows]))
    if len(ivs) < 3:
        return {"note": "INSUFFICIENT SAMPLE for IV quantiles"}
    q1, q2 = ivs[len(ivs) // 3], ivs[2 * len(ivs) // 3]
    out = {f"low (<{q1:.2f})": summarise([r for r in rows if (r.get("entry_iv") or 0) < q1], cfg),
           f"mid ({q1:.2f}-{q2:.2f})": summarise(
               [r for r in rows if q1 <= (r.get("entry_iv") or -1) < q2], cfg),
           f"high (>={q2:.2f})": summarise([r for r in rows if (r.get("entry_iv") or -1) >= q2], cfg)}
    return out


def hour_buckets(rows, cfg=DEFAULT) -> dict:
    bands = [("09:15-10:00", "09:15", "10:00"), ("10:00-11:00", "10:00", "11:00"),
             ("11:00-12:00", "11:00", "12:00"), ("12:00-13:00", "12:00", "13:00"),
             ("13:00-14:00", "13:00", "14:00"), ("14:00-15:00", "14:00", "15:00"),
             ("15:00+", "15:00", "23:59")]
    return {name: summarise([r for r in rows if lo <= r["signal_minute"] < hi], cfg)
            for name, lo, hi in bands}


def quadrants(rows, cfg=DEFAULT) -> dict:
    out = {}
    for h in cfg.horizons:
        c = Counter(r.get(f"quadrant_{h}m") or "UNMEASURABLE" for r in rows)
        total = sum(v for k, v in c.items() if k != "UNMEASURABLE")
        out[f"{h}m"] = dict(counts=dict(c), measurable=total,
                            pct={k: round(v / total * 100, 1) for k, v in c.items()
                                 if k != "UNMEASURABLE" and total})
    return out


def direction_accuracy(rows, cfg=DEFAULT) -> dict:
    """Spec 15: direction from the UNDERLYING, per horizon. Never called 'accuracy' loosely."""
    out = {}
    for h in cfg.horizons:
        vals = [r.get(f"und_direction_ok_{h}m") for r in rows]
        known = [v for v in vals if v is not None]
        out[f"{h}m"] = dict(measurable=len(known), correct=sum(1 for v in known if v),
                            pct=round(sum(1 for v in known if v) / len(known) * 100, 1) if known else None,
                            unmeasurable=len(vals) - len(known))
    return out


def response(rows, cfg=DEFAULT) -> dict:
    out = {}
    for h in cfg.horizons:
        r5 = _num([r.get(f"response_ratio_{h}m") for r in rows])
        ef = _num([r.get(f"response_efficiency_{h}m") for r in rows])
        gap = _num([r.get(f"response_gap_{h}m") for r in rows])
        out[f"{h}m"] = dict(n=len(r5), measurable_efficiency=len(ef),
                            mean_elasticity=round(st.fmean(r5), 2) if r5 else None,
                            median_elasticity=round(st.median(r5), 2) if r5 else None,
                            mean_efficiency=round(st.fmean(ef), 3) if ef else None,
                            median_efficiency=round(st.median(ef), 3) if ef else None,
                            weak_pct=round(sum(1 for x in ef if x < cfg.weak_response_efficiency) / len(ef) * 100, 1)
                            if ef else None,
                            mean_response_gap=round(st.fmean(gap), 3) if gap else None,
                            note="RESPONSE_GAP compares the measured mid move against a FIRST-ORDER "
                                 "THEORETICAL ESTIMATE (delta x spot change). Benchmark only.")
    return out


def spread_economics(rows, cfg=DEFAULT) -> dict:
    ask_bid = _num([r.get("ask_to_bid_per_unit") for r in rows])
    mid = _num([r.get("mid_to_mid_per_unit") for r in rows])
    fric = _num([r.get("execution_friction_per_unit") for r in rows])
    ent = _num([r.get("entry_spread") for r in rows])
    ext = _num([r.get("exit_spread") for r in rows])
    losers = [r for r in rows if isinstance(r.get("ask_to_bid_per_unit"), (int, float))
              and r["ask_to_bid_per_unit"] <= 0]
    saved = [r for r in losers if isinstance(r.get("mid_to_mid_per_unit"), (int, float))
             and r["mid_to_mid_per_unit"] > 0]
    return dict(
        n=len(rows),
        mean_executable_per_unit=round(st.fmean(ask_bid), 3) if ask_bid else None,
        mean_mid_to_mid_per_unit=round(st.fmean(mid), 3) if mid else None,
        mean_execution_friction_per_unit=round(st.fmean(fric), 3) if fric else None,
        friction_share_of_result=round(abs(st.fmean(fric)) / abs(st.fmean(ask_bid)) * 100, 1)
        if (fric and ask_bid and st.fmean(ask_bid)) else None,
        mean_entry_spread=round(st.fmean(ent), 3) if ent else None,
        mean_exit_spread=round(st.fmean(ext), 3) if ext else None,
        losers=len(losers), losers_that_were_positive_mid_to_mid=len(saved),
        pct_of_losers_caused_by_friction=round(len(saved) / len(losers) * 100, 1) if losers else None,
    )


def theta_context(rows, cfg=DEFAULT) -> dict:
    th = _num([r.get("theta_estimate_per_unit") for r in rows])
    fric = _num([r.get("execution_friction_per_unit") for r in rows])
    pnl = _num([r.get("final_pnl_per_unit") for r in rows])
    return dict(n_with_theta=len(th),
                mean_theta_estimate_per_unit=round(st.fmean(th), 3) if th else None,
                mean_execution_friction_per_unit=round(st.fmean(fric), 3) if fric else None,
                mean_result_per_unit=round(st.fmean(pnl), 3) if pnl else None,
                note="Theta is published per day; the estimate scales it by hold minutes / 375. "
                     "Compare its size against friction before attributing anything to decay.")


def report(rows, label: str, cfg=DEFAULT) -> dict:
    pe = [r for r in rows if r["side"] == "PE"]
    ce = [r for r in rows if r["side"] == "CE"]
    return dict(
        label=label, version=VERSION, config_hash=cfg.config_hash(),
        signals=len(rows), buy_ce=len(ce), buy_pe=len(pe),
        sessions=len({(r["market"], r["session_date"]) for r in rows}),
        overall=summarise(rows, cfg), by_side=dict(PE=summarise(pe, cfg), CE=summarise(ce, cfg)),
        direction_accuracy=direction_accuracy(rows, cfg),
        direction_accuracy_pe=direction_accuracy(pe, cfg),
        direction_accuracy_ce=direction_accuracy(ce, cfg),
        quadrants=quadrants(rows, cfg), quadrants_pe=quadrants(pe, cfg), quadrants_ce=quadrants(ce, cfg),
        response=response(rows, cfg), response_pe=response(pe, cfg), response_ce=response(ce, cfg),
        spread_economics=spread_economics(rows, cfg),
        spread_economics_pe=spread_economics(pe, cfg),
        theta_context=theta_context(rows, cfg),
        by_market_state=group(rows, "market_state", cfg),
        pe_by_market_state=group(pe, "market_state", cfg),
        ce_by_market_state=group(ce, "market_state", cfg),
        by_strike_band=group(rows, "strike_band", cfg),
        by_iv_state=group(rows, "iv_state", cfg),
        by_exit_reason=group(rows, "exit_reason", cfg),
        by_loss_reason=group([r for r in rows if r.get("loss_reason")], "loss_reason", cfg),
        loss_reason_counts=dict(Counter(r["loss_reason"] for r in rows if r.get("loss_reason"))),
        pe_loss_reason_counts=dict(Counter(r["loss_reason"] for r in pe if r.get("loss_reason"))),
        delta_buckets=delta_buckets(rows, cfg), iv_buckets=iv_quantile_buckets(rows, cfg),
        by_hour=hour_buckets(rows, cfg),
        pre_signal=dict(
            mean_und_pre_1m=round(st.fmean(_num([r.get("und_pre_1m_pct") for r in rows])), 4)
            if _num([r.get("und_pre_1m_pct") for r in rows]) else None,
            mean_und_pre_3m=round(st.fmean(_num([r.get("und_pre_3m_pct") for r in rows])), 4)
            if _num([r.get("und_pre_3m_pct") for r in rows]) else None,
            mean_und_pre_5m=round(st.fmean(_num([r.get("und_pre_5m_pct") for r in rows])), 4)
            if _num([r.get("und_pre_5m_pct") for r in rows]) else None,
            mean_opt_pre_5m=round(st.fmean(_num([r.get("opt_pre_5m_pct") for r in rows])), 4)
            if _num([r.get("opt_pre_5m_pct") for r in rows]) else None,
            mean_premium_position_in_range=round(
                st.fmean(_num([r.get("premium_position_in_range") for r in rows])), 1)
            if _num([r.get("premium_position_in_range") for r in rows]) else None,
        ),
        density=density.density(rows), runs=density.runs(rows), flips=density.flips(rows),
        data_quality=dict(
            missing_greeks=sum(1 for r in rows if r.get("entry_delta") is None),
            missing_iv=sum(1 for r in rows if r.get("entry_iv") is None),
            missing_entry_quote=sum(1 for r in rows if r.get("entry_ask") is None),
            missing_exit_quote=sum(1 for r in rows if r.get("exit_bid") is None),
            greeks_status=dict(Counter(r.get("greeks_status") for r in rows)),
        ),
        min_sample=cfg.min_sample,
        caveat=("Diagnosis only, on paper simulation. No strategy rule was read for anything but its "
                "output and none was changed. Groups below the minimum sample are not interpretable."),
    )
