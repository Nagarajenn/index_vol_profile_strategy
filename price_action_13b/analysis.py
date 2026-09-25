"""13A vs 13B comparison metrics (spec 11).

The spec is explicit: a change in total P&L is NOT evidence that 13B helps. So this module
computes selectivity, excursion and drawdown measures separately from P&L, and the report is
written to let them disagree with the P&L line.
"""

import statistics as st
from collections import Counter


def _num(xs):
    return [x for x in xs if isinstance(x, (int, float))]


def drawdown(pnls: list) -> float:
    peak, worst, cum = 0.0, 0.0, 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        worst = min(worst, cum - peak)
    return round(worst, 2)


def max_consecutive_losses(pnls: list) -> int:
    run, worst = 0, 0
    for p in pnls:
        run = run + 1 if p <= 0 else 0
        worst = max(worst, run)
    return worst


def summarise(positions: list[dict], label: str, min_sample: int = 20) -> dict:
    pnl = _num([p.get("realised_pnl") for p in positions])
    mfe = _num([p.get("mfe_per_unit") for p in positions])
    mae = _num([p.get("mae_per_unit") for p in positions])
    holds = _num([p.get("hold_minutes") for p in positions])
    exits = Counter(p.get("exit_reason") for p in positions)
    return dict(
        label=label, trades=len(positions), priced=len(pnl),
        sufficient=len(positions) >= min_sample,
        note=None if len(positions) >= min_sample else "INSUFFICIENT SAMPLE",
        wins=sum(1 for x in pnl if x > 0), losses=sum(1 for x in pnl if x <= 0),
        win_rate=round(sum(1 for x in pnl if x > 0) / len(pnl) * 100, 1) if pnl else None,
        total_pnl=round(sum(pnl), 2) if pnl else 0.0,
        mean_pnl=round(st.fmean(pnl), 2) if pnl else None,
        median_pnl=round(st.median(pnl), 2) if pnl else None,
        max_drawdown=drawdown(pnl) if pnl else 0.0,
        max_consecutive_losses=max_consecutive_losses(pnl) if pnl else 0,
        mean_hold_minutes=round(st.fmean(holds), 1) if holds else None,
        mean_mfe_per_unit=round(st.fmean(mfe), 2) if mfe else None,
        mean_mae_per_unit=round(st.fmean(mae), 2) if mae else None,
        stop_loss=exits.get("STOP_LOSS", 0), signal_flip=exits.get("SIGNAL_FLIP", 0),
        session_end=exits.get("SESSION_END", 0),
        by_side=dict(Counter(p.get("side") for p in positions)),
    )


def blocked_outcomes(blocked: list[dict]) -> dict:
    """What happened to the candidates 13B refused.

    This is the measurement that decides whether the layer earns its place: a block that
    avoided an adverse move is useful; a block that gave up a favourable one is a cost."""
    ends = _num([b.get("end") for b in blocked])
    mfes = _num([b.get("mfe") for b in blocked])
    maes = _num([b.get("mae") for b in blocked])
    adverse = [b for b in blocked if isinstance(b.get("end"), (int, float)) and b["end"] < 0]
    favourable = [b for b in blocked if isinstance(b.get("end"), (int, float)) and b["end"] > 0]
    would_have_run = [b for b in blocked if isinstance(b.get("mfe"), (int, float)) and b["mfe"] > 0]
    return dict(
        blocked=len(blocked), measurable=len(ends),
        moved_adversely=len(adverse),
        pct_moved_adversely=round(len(adverse) / len(ends) * 100, 1) if ends else None,
        moved_favourably=len(favourable),
        pct_moved_favourably=round(len(favourable) / len(ends) * 100, 1) if ends else None,
        had_positive_mfe=len(would_have_run),
        pct_had_positive_mfe=round(len(would_have_run) / len(ends) * 100, 1) if ends else None,
        mean_end_per_unit=round(st.fmean(ends), 2) if ends else None,
        mean_mfe_per_unit=round(st.fmean(mfes), 2) if mfes else None,
        mean_mae_per_unit=round(st.fmean(maes), 2) if maes else None,
        by_verdict=dict(Counter(b.get("confirmation") for b in blocked)),
        by_structure=dict(Counter(b.get("structure") for b in blocked)),
        note=("Measured over the 10 minutes after the blocked signal, priced on the BID against "
              "the entry ASK -- the same discipline every other milestone uses."),
    )


def accepted_outcomes(positions: list[dict]) -> dict:
    pnl = _num([p.get("realised_pnl") for p in positions])
    mfe = _num([p.get("mfe_per_unit") for p in positions])
    fav = [x for x in mfe if x > 0]
    return dict(accepted=len(positions), measurable=len(pnl),
                moved_favourably=len(fav),
                pct_moved_favourably=round(len(fav) / len(mfe) * 100, 1) if mfe else None,
                mean_pnl=round(st.fmean(pnl), 2) if pnl else None)


def compare(a_pos, b_pos, blocked, a_dec, b_dec, min_sample: int = 20) -> dict:
    a = summarise(a_pos, "13A", min_sample)
    b = summarise(b_pos, "13B", min_sample)
    a_buys = sum(1 for d in a_dec if d["thirteen_a"] in ("BUY_CE", "BUY_PE"))
    b_buys = sum(1 for d in b_dec if d["final"] in ("BUY_CE", "BUY_PE"))
    verdicts = Counter(d["price_action"] for d in b_dec if d["price_action"])
    return dict(
        thirteen_a=a, thirteen_b=b,
        candidates=a_buys, buys_after_price_action=b_buys,
        pct_rejected_by_price_action=round((1 - b_buys / a_buys) * 100, 1) if a_buys else None,
        buy_ce_a=sum(1 for d in a_dec if d["thirteen_a"] == "BUY_CE"),
        buy_pe_a=sum(1 for d in a_dec if d["thirteen_a"] == "BUY_PE"),
        buy_ce_b=sum(1 for d in b_dec if d["final"] == "BUY_CE"),
        buy_pe_b=sum(1 for d in b_dec if d["final"] == "BUY_PE"),
        wait_a=sum(1 for d in a_dec if d["thirteen_a"] == "WAIT"),
        wait_b=sum(1 for d in b_dec if d["final"] == "WAIT"),
        price_action_verdicts=dict(verdicts),
        blocked=blocked_outcomes(blocked),
        accepted=accepted_outcomes(b_pos),
        structures=dict(Counter(d["structure"] for d in b_dec if d.get("structure"))),
        breaks=dict(Counter(d["break_state"] for d in b_dec if d.get("break_state"))),
        setups=dict(Counter(d["setup"] for d in b_dec if d.get("setup"))),
        vwap_states=dict(Counter(d["vwap_state"] for d in b_dec if d.get("vwap_state"))),
        volume_states=dict(Counter(d["volume_state"] for d in b_dec if d.get("volume_state"))),
        value_states=dict(Counter(d["value_state"] for d in b_dec if d.get("value_state"))),
    )


def verdict(cmp: dict, min_sample: int = 20) -> dict:
    """The seven questions spec 11 requires to be answered SEPARATELY from P&L."""
    a, b, bl = cmp["thirteen_a"], cmp["thirteen_b"], cmp["blocked"]
    enough = a["trades"] >= min_sample and b["trades"] >= min_sample
    dd = (b["max_drawdown"] > a["max_drawdown"]) if (a["max_drawdown"] and b["max_drawdown"]) else None
    return dict(
        sufficient_sample=enough,
        selectivity=dict(improved=cmp["pct_rejected_by_price_action"] not in (None, 0),
                         detail=f"{cmp['pct_rejected_by_price_action']}% of 13A buys removed "
                                f"({cmp['candidates']} -> {cmp['buys_after_price_action']})."),
        entry_timing=dict(improved=None,
                          detail="Not separable: blocking a trade removes it rather than moving "
                                 "its entry, so 13B cannot improve the timing of a trade it keeps."),
        adverse_excursion=dict(
            improved=(b["mean_mae_per_unit"] or 0) > (a["mean_mae_per_unit"] or 0) if
            (a["mean_mae_per_unit"] is not None and b["mean_mae_per_unit"] is not None) else None,
            detail=f"Mean MAE per unit {a['mean_mae_per_unit']} -> {b['mean_mae_per_unit']}."),
        favorable_excursion=dict(
            improved=(b["mean_mfe_per_unit"] or 0) > (a["mean_mfe_per_unit"] or 0) if
            (a["mean_mfe_per_unit"] is not None and b["mean_mfe_per_unit"] is not None) else None,
            detail=f"Mean MFE per unit {a['mean_mfe_per_unit']} -> {b['mean_mfe_per_unit']}."),
        drawdown=dict(improved=dd, detail=f"Max drawdown {a['max_drawdown']} -> {b['max_drawdown']}."),
        trade_quality=dict(
            improved=None if not enough else (b["win_rate"] or 0) > (a["win_rate"] or 0),
            detail=f"Win rate {a['win_rate']}% -> {b['win_rate']}%, median P&L "
                   f"{a['median_pnl']} -> {b['median_pnl']}."),
        low_quality_entries=dict(
            improved=bl["pct_moved_adversely"] is not None and bl["pct_moved_adversely"] > 50,
            detail=f"Of {bl['measurable']} blocked candidates, {bl['pct_moved_adversely']}% moved "
                   f"adversely in the next 10 minutes and {bl['pct_had_positive_mfe']}% had a "
                   f"positive excursion that was given up."),
    )


# ---------------------------------------------------------------- the PARTIAL experiment
def forward_by_verdict(blocked: list[dict], allowed: list[dict]) -> dict:
    """Forward movement split by price-action verdict (the experiment's core question).

    `blocked` rows carry their own 10-minute forward path. `allowed` rows are realised trades,
    so their MFE/MAE come from the position itself -- the two are reported separately and never
    averaged together, because one is a hypothetical path and the other an actual holding."""
    out = {}
    by_v = {}
    for b in blocked:
        by_v.setdefault(b.get("confirmation"), []).append(b)
    for v, rows in by_v.items():
        ends = _num([r.get("end") for r in rows])
        mfes = _num([r.get("mfe") for r in rows])
        maes = _num([r.get("mae") for r in rows])
        out[f"{v} (blocked)"] = dict(
            n=len(rows), measurable=len(ends),
            adverse=sum(1 for e in ends if e < 0),
            favourable=sum(1 for e in ends if e > 0),
            pct_adverse=round(sum(1 for e in ends if e < 0) / len(ends) * 100, 1) if ends else None,
            pct_favourable=round(sum(1 for e in ends if e > 0) / len(ends) * 100, 1) if ends else None,
            mean_end=round(st.fmean(ends), 2) if ends else None,
            mean_cash=None,          # a blocked candidate was never sized, so it has no cash result
            mean_mfe=round(st.fmean(mfes), 2) if mfes else None,
            mean_mae=round(st.fmean(maes), 2) if maes else None)
    by_a = {}
    for p in allowed:
        by_a.setdefault(p.get("price_action"), []).append(p)
    for v, rows in by_a.items():
        # PER UNIT, to match the blocked rows. Cash P&L is reported in its own column --
        # averaging a per-unit forward path against a cash result would be meaningless.
        per_unit = _num([r.get("realised_pnl_per_unit") for r in rows])
        cash = _num([r.get("realised_pnl") for r in rows])
        mfes = _num([r.get("mfe_per_unit") for r in rows])
        maes = _num([r.get("mae_per_unit") for r in rows])
        out[f"{v} (allowed, realised)"] = dict(
            n=len(rows), measurable=len(per_unit),
            adverse=sum(1 for e in per_unit if e <= 0),
            favourable=sum(1 for e in per_unit if e > 0),
            pct_adverse=round(sum(1 for e in per_unit if e <= 0) / len(per_unit) * 100, 1) if per_unit else None,
            pct_favourable=round(sum(1 for e in per_unit if e > 0) / len(per_unit) * 100, 1) if per_unit else None,
            mean_end=round(st.fmean(per_unit), 2) if per_unit else None,
            mean_cash=round(st.fmean(cash), 2) if cash else None,
            mean_mfe=round(st.fmean(mfes), 2) if mfes else None,
            mean_mae=round(st.fmean(maes), 2) if maes else None)
    return out


def three_way(a_pos, b_pos, c_pos, a_dec, b_dec, c_dec, b_blocked, c_blocked,
              min_sample: int = 20) -> dict:
    """13A baseline vs 13B default vs 13B experiment, on identical inputs."""
    def cands(dec, key):
        return sum(1 for d in dec if d[key] in ("BUY_CE", "BUY_PE"))
    return dict(
        baseline=summarise(a_pos, "13A", min_sample),
        default=summarise(b_pos, "13B default", min_sample),
        experiment=summarise(c_pos, "13B allow-PARTIAL", min_sample),
        candidate_minutes=dict(
            path_a=cands(a_dec, "thirteen_a"),
            path_b=sum(1 for d in b_dec if d.get("price_action")),
            path_c=sum(1 for d in c_dec if d.get("price_action"))),
        verdicts_default=dict(Counter(d["price_action"] for d in b_dec if d.get("price_action"))),
        verdicts_experiment=dict(Counter(d["price_action"] for d in c_dec if d.get("price_action"))),
        blocked_default=len(b_blocked), blocked_experiment=len(c_blocked),
        filtering_default=round(len(b_blocked) / max(sum(1 for d in b_dec if d.get("price_action")), 1) * 100, 1),
        filtering_experiment=round(len(c_blocked) / max(sum(1 for d in c_dec if d.get("price_action")), 1) * 100, 1),
        partial_allowed=sum(1 for p in c_pos if p.get("price_action") == "PARTIAL"),
        forward_default=forward_by_verdict(b_blocked, b_pos),
        forward_experiment=forward_by_verdict(c_blocked, c_pos),
        note=("PATH A, B and C are replayed from identical inputs, but blocking a trade frees "
              "capacity for later ones, so the three paths do NOT see the same number of "
              "candidate minutes. That is why candidate counts differ between paths and why a "
              "simple 'X% filtered' ratio must be read within a path, never across paths."),
    )
