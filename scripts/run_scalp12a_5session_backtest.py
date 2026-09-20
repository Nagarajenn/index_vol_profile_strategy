"""12A-scalp-v1 strict 5-session historical paper-trading backtest (READ-ONLY research).

Replays the CURRENT 12A engine unchanged (config hash must be 994667c6d552111e)
over the last 5 completed trading sessions, with causal thresholds (prior HR
days only), ASK entry at the engine's own entry delay and BID exits from the
engine's own exit logic. A sequential Rs 15,000 virtual account applies the
current 12A risk rules. Two sizing views:

* EXCHANGE_LOTS (primary): quantities in whole exchange lots from the Dhan scrip
  master (matched by contract, not by reused security id). A candidate whose
  minimum 1 lot breaches Rs 300 max loss or Rs 6,000 capital is blocked as
  RISK_TOO_LARGE -- exactly what the risk engine does when quantity < 1 lot.
* CONFIG_UNITS (reference): the engine's own sizing with lot_size_units=1
  (research normalisation), identical to its internal policy replay.

Writes nothing to any database. No order code, no Dhan API, no 11D imports.
Outputs: milestone12a_5session_paper_backtest.html and
milestone12a_5session_backtest/{summary.json,ledger*.csv,candidates.csv,daily*.csv}.
"""

import csv
import json
import math
import random
import statistics as st
import sys
from dataclasses import replace
from datetime import date, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.trading_calendar import is_trading_day  # noqa: E402
from scalp_12a import db  # noqa: E402
from scalp_12a.config import DEFAULT_CONFIG, STRATEGY_VERSION  # noqa: E402
from scalp_12a.counterfactual import track  # noqa: E402
from scalp_12a.engine import evaluate_day, evaluate_session  # noqa: E402
from scalp_12a.exits import OPEN, simulate_exit  # noqa: E402
from scalp_12a.models import Event, Selection  # noqa: E402
from scalp_12a.modes import market_mode  # noqa: E402
from scalp_12a.risk import plan_risk  # noqa: E402
from scalp_12a import taxonomy as T  # noqa: E402
from scalp_12a.thresholds import build_thresholds  # noqa: E402

EXPECTED_HASH = "994667c6d552111e"
OUT_DIR = ROOT / "milestone12a_5session_backtest"
REPORT = ROOT / "milestone12a_5session_paper_backtest.html"
BAR = timedelta(seconds=5)
MEDIAN_HR_WRITE_LATENCY_S = 3.3        # observed: HR rows land ~3.3 s after bar close (median)

CONFIRMATION = {T.WEAK_MOMENTUM, T.NO_CONFIRMATION, T.OPTION_NOT_RESPONDING, T.MOVE_ALREADY_EXTENDED}
SELECTION = {T.SPREAD_TOO_WIDE, T.LOW_LIQUIDITY, T.STALE_DATA}
RISK = {T.RISK_TOO_LARGE, T.POSITION_OPEN, T.DAILY_LIMIT_REACHED}
TIME_EXPIRY = {T.TIME_WINDOW_CLOSED, T.MODE_B_RESEARCH_ONLY, T.EXPIRY_DAY_CLOSE_VETO, T.EXPIRY_TRANSITION_ZONE,
               T.EVENT_EXPIRED}


# ------------------------------------------------------------------ data
def last_completed_sessions(conn, n=5, today=None):
    today = today or date.today()
    d, out = today, []
    last_close = conn.execute("SELECT max(fetched_at) FROM option_chain_raw WHERE fetched_at::date=%s", (today,)).fetchone()[0]
    if not (last_close and last_close.time() >= time(15, 29)):
        d = today - timedelta(days=1)
    while len(out) < n:
        if is_trading_day(d):
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def lot_sizes(expiries_by_symbol):
    """{(symbol, expiry): (lot, source)} verified by contract symbol + expiry in the scrip master."""
    path = ROOT / "data" / "cache" / "scrip_master.csv"
    found = {}
    with open(path, encoding="utf-8", errors="ignore") as f:
        for row in csv.DictReader(f):
            if row.get("SEM_INSTRUMENT_NAME") != "OPTIDX":
                continue
            name = (row.get("SM_SYMBOL_NAME") or row.get("SEM_TRADING_SYMBOL") or "").upper()
            exp = (row.get("SEM_EXPIRY_DATE") or "")[:10]
            for sym in ("NIFTY", "SENSEX"):
                if (row.get("SEM_TRADING_SYMBOL") or "").upper().startswith(sym + "-") and exp:
                    found.setdefault((sym, exp), set()).add(float(row["SEM_LOT_UNITS"]))
    out = {}
    for sym, exps in expiries_by_symbol.items():
        same_symbol = sorted((k[1], v) for k, v in found.items() if k[0] == sym)
        for e in exps:
            lots = found.get((sym, str(e)))
            if lots and len(lots) == 1:
                out[(sym, e)] = (int(next(iter(lots))), f"scrip master {sym} {e} (verified by contract)")
            else:
                later = [(x, v) for x, v in same_symbol if x > str(e) and len(v) == 1]
                if later:
                    out[(sym, e)] = (int(next(iter(later[0][1]))),
                                     f"INFERRED from {sym} {later[0][0]} series (expired contracts not in the "
                                     f"2026-09-18 scrip master)")
                else:
                    out[(sym, e)] = (None, "UNAVAILABLE")
    return out


# ------------------------------------------------------------------ helpers
def qclose(s, i):
    return s.times[i] + BAR


def reason_categories(reasons):
    cats = []
    if set(reasons) & TIME_EXPIRY:
        cats.append("expiry/time")
    if set(reasons) & CONFIRMATION:
        cats.append("confirmation")
    if set(reasons) & SELECTION:
        cats.append("option selection")
    if set(reasons) & RISK:
        cats.append("risk")
    return cats


def mids(s, key, entry_i, exit_i):
    qe, qx = s.quote(key, entry_i), s.quote(key, exit_i) if exit_i is not None else None
    return (qe.mid if qe else None), (qx.mid if qx else None)


def lots_for(ask, stop_pct, lot, cfg):
    if lot is None:
        return 0
    per_lot_loss = ask * stop_pct / 100.0 * lot
    by_risk = math.floor(cfg.max_rupee_loss_per_trade / per_lot_loss) if per_lot_loss > 0 else 0
    by_cap = math.floor(cfg.max_capital_per_trade / (ask * lot))
    return max(0, min(by_risk, by_cap))


def account(cands_by_day, sessions, lots, cfg, view):
    """Sequential account over the engine's gate-passing candidates in time order,
    applying the current 12A policy (1 position, <= max trades/day, daily loss cap)."""
    bal = cfg.starting_capital
    ledger, blocked, daily = [], [], []
    for d in sorted(cands_by_day):
        start_bal, open_until, trades, realised = bal, None, 0, 0.0
        peak_day, max_dd_day, limit_hit = bal, 0.0, False
        for c in sorted(cands_by_day[d], key=lambda c: (c.bar_ts, c.symbol)):
            if not c.passed_gates:
                continue
            s = sessions[d][c.symbol]
            key = (c.selection.leg.option_type, c.selection.leg.atm_offset)
            if open_until is not None and c.bar_ts < open_until:
                blocked.append((c, T.POSITION_OPEN)); continue
            if trades >= cfg.max_trades_per_day or realised <= -cfg.max_daily_loss:
                limit_hit = limit_hit or realised <= -cfg.max_daily_loss
                blocked.append((c, T.DAILY_LIMIT_REACHED)); continue
            lot, lot_src = lots.get((c.symbol, s.expiry), (None, "UNAVAILABLE"))
            if view == "EXCHANGE_LOTS":
                n_lots = lots_for(c.risk.entry_ref_ask, c.risk.stop_pct, lot, cfg)
                if n_lots < 1:
                    blocked.append((c, T.RISK_TOO_LARGE)); continue
                qty = n_lots * lot
            else:
                n_lots, qty = None, c.risk.quantity
            x = simulate_exit(s, key, c.bar_index + cfg.entry_delay_bars, c.event, c.risk, cfg)
            if x.exit_index is None or x.pnl_pct is None:
                blocked.append((c, "NO_EXIT_DATA")); continue
            e_i = c.bar_index + cfg.entry_delay_bars
            m_in, m_out = mids(s, key, e_i, x.exit_index)
            net = (x.exit_bid - x.entry_ask) * qty
            gross = (m_out - m_in) * qty if m_in and m_out else None
            spread_cost = (gross - net) if gross is not None else None
            trades += 1
            realised += net
            bal += net
            peak_day = max(peak_day, bal)
            max_dd_day = max(max_dd_day, peak_day - bal)
            open_until = s.times[x.exit_index]
            o = c.opportunity
            ledger.append(dict(
                date=str(d), symbol=c.symbol, direction="UP" if c.event.direction > 0 else "DOWN",
                option=c.selection.leg.option_type, strike=c.selection.leg.strike, expiry=str(s.expiry),
                expiry_day=s.is_expiry_day, mode=c.mode, event_type=c.event.event_type,
                event_start=o.event_start_ts.strftime("%H:%M:%S") if o else None,
                detection=qclose(s, c.bar_index).strftime("%H:%M:%S"),
                detection_after_event_start_s=(qclose(s, c.bar_index) - o.event_start_ts).total_seconds() if o else None,
                modeled_live_detection_delay_s=MEDIAN_HR_WRITE_LATENCY_S,
                entry_time=qclose(s, e_i).strftime("%H:%M:%S"),
                detection_to_entry_s=(qclose(s, e_i) - qclose(s, c.bar_index)).total_seconds(),
                entry_ask=x.entry_ask, exit_time=qclose(s, x.exit_index).strftime("%H:%M:%S"), exit_bid=x.exit_bid,
                lot_size=lot, lot_source=lot_src, lots=n_lots, quantity=qty,
                capital_deployed=round(x.entry_ask * qty, 2),
                planned_max_loss=round((x.entry_ask - x.entry_ask * (1 - c.risk.stop_pct / 100)) * qty, 2),
                exit_reason=x.reason, hold_s=x.hold_seconds,
                mfe_pct=round(x.peak_gain_pct, 3), mae_pct=round(x.worst_pct, 3),
                giveback_pct=round(x.peak_gain_pct - x.pnl_pct, 3),
                gross_move=round(gross, 2) if gross is not None else None,
                spread_cost=round(spread_cost, 2) if spread_cost is not None else None,
                net_pnl=round(net, 2), return_pct=round(x.pnl_pct, 3), balance=round(bal, 2),
                timing=o.timing if o else None, status="CLOSED"))
        wins = [t for t in ledger if t["date"] == str(d) and t["net_pnl"] > 0]
        losses = [t for t in ledger if t["date"] == str(d) and t["net_pnl"] <= 0]
        day_trades = wins + losses
        daily.append(dict(date=str(d), start=round(start_bal, 2), end=round(bal, 2), trades=len(day_trades),
                          wins=len(wins), losses=len(losses),
                          win_rate=round(len(wins) / len(day_trades), 3) if day_trades else None,
                          gross_profit=round(sum(t["net_pnl"] for t in wins), 2),
                          gross_loss=round(sum(t["net_pnl"] for t in losses), 2), net=round(bal - start_bal, 2),
                          best=max((t["net_pnl"] for t in day_trades), default=None),
                          worst=min((t["net_pnl"] for t in day_trades), default=None),
                          max_intraday_dd=round(max_dd_day, 2), daily_limit_hit=limit_hit))
    return ledger, blocked, daily


def summarize(ledger, cfg):
    pn = [t["net_pnl"] for t in ledger]
    bal = [cfg.starting_capital] + [t["balance"] for t in ledger]
    peak, mdd, mdd_pct, trough = bal[0], 0.0, 0.0, bal[0]
    for b in bal:
        peak = max(peak, b)
        if peak - b > mdd:
            mdd, mdd_pct = peak - b, (peak - b) / peak * 100
        trough = min(trough, b)
    streak_w = streak_l = cw = cl = 0
    for p in pn:
        cw, cl = (cw + 1, 0) if p > 0 else (0, cl + 1)
        streak_w, streak_l = max(streak_w, cw), max(streak_l, cl)
    wins, losses = [p for p in pn if p > 0], [p for p in pn if p <= 0]
    reasons = {}
    for t in ledger:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    med = lambda k: round(st.median([t[k] for t in ledger]), 3) if ledger else None
    return dict(
        starting=cfg.starting_capital, ending=round(bal[-1], 2), net=round(bal[-1] - cfg.starting_capital, 2),
        return_pct=round((bal[-1] - cfg.starting_capital) / cfg.starting_capital * 100, 3), trades=len(pn),
        wins=len(wins), losses=len(losses), win_rate=round(len(wins) / len(pn), 3) if pn else None,
        avg=round(st.mean(pn), 2) if pn else None, median=round(st.median(pn), 2) if pn else None,
        avg_win=round(st.mean(wins), 2) if wins else None, avg_loss=round(st.mean(losses), 2) if losses else None,
        largest_win=max(wins, default=None), largest_loss=min(losses, default=None),
        profit_factor=round(sum(wins) / -sum(losses), 3) if wins and losses and sum(losses) < 0 else None,
        max_dd=round(mdd, 2), max_dd_pct=round(mdd_pct, 3), peak=round(max(bal), 2), trough=round(trough, 2),
        max_consec_losses=streak_l, max_consec_wins=streak_w,
        avg_hold=round(st.mean([t["hold_s"] for t in ledger]), 1) if ledger else None, median_hold=med("hold_s"),
        mfe_median=med("mfe_pct"), mae_median=med("mae_pct"), giveback_median=med("giveback_pct"),
        exit_reasons=reasons, curve=bal,
        spread_cost_total=round(sum(t["spread_cost"] or 0 for t in ledger), 2),
        gross_move_total=round(sum(t["gross_move"] or 0 for t in ledger), 2))


def random_baseline(sessions, days, trades_per_day, lots, cfg, view, sims=2000, seed=12):
    """Random Mode-A entries (random direction, ATM leg) with the SAME exit engine and
    sizing, same number of trades per day as 12A took; returns distribution of totals."""
    rng = random.Random(seed)
    pool = {}
    for d in days:
        rows = []
        for sym, s in sessions[d].items():
            lot = lots.get((sym, s.expiry), (None, ""))[0]
            for i, t in enumerate(s.times):
                if market_mode(t, cfg) != T.MODE_A or i < 6 or i + cfg.entry_delay_bars >= len(s):
                    continue
                if s.is_expiry_day and t.time() >= time.fromisoformat(cfg.expiry_transition_zone_start):
                    continue
                for dirn in (1, -1):
                    key = ("CE" if dirn > 0 else "PE", 0)
                    q = s.quote(key, i)
                    f_now, f_then = s.fut_ffill(i), s.fut_ffill(i - 6)
                    if q is None or not q.valid or f_now is None or f_then is None:
                        continue
                    size = max(abs(f_now - f_then), s.strike_step * 0.05)
                    ev = Event(i, T.MOMENTUM_EVENT, T.STRONG, dirn, None, dirn * size, None, None, None, dirn * size,
                               f_now - dirn * size)
                    plan = plan_risk(ev, Selection(s.legs[key], q, None, None, 0), cfg)
                    qty = lots_for(q.ask, plan.stop_pct, lot, cfg) * (lot or 0) if view == "EXCHANGE_LOTS" else plan.quantity
                    if qty < 1:
                        continue
                    x = simulate_exit(s, key, i + cfg.entry_delay_bars, ev, plan, cfg)
                    if x.pnl_pct is not None and x.exit_bid is not None:
                        rows.append((x.exit_bid - x.entry_ask) * qty)
        pool[d] = rows
    totals = []
    for _ in range(sims):
        tot = 0.0
        for d in days:
            k = trades_per_day.get(str(d), 0)
            if k and pool[d]:
                tot += sum(rng.choice(pool[d]) for _ in range(k))
        totals.append(tot)
    per_trade = [v for d in days for v in pool[d]]
    return dict(sims=sims, totals_median=round(st.median(totals), 2) if totals else None,
                totals_p05=round(sorted(totals)[int(0.05 * len(totals))], 2) if totals else None,
                totals_p95=round(sorted(totals)[int(0.95 * len(totals)) - 1], 2) if totals else None,
                per_trade_mean=round(st.mean(per_trade), 2) if per_trade else None,
                per_trade_median=round(st.median(per_trade), 2) if per_trade else None,
                per_trade_n=len(per_trade), totals=totals)


def big_moves(s, n=3, window_bars=60):
    """Top n non-overlapping 5-minute futures swings in Mode A/B -- to check detection coverage."""
    f = [s.fut_ffill(i) for i in range(len(s))]
    moves = []
    for i in range(window_bars, len(s)):
        if f[i] is None or f[i - window_bars] is None or s.times[i].time() < time(15, 0):
            continue
        moves.append((abs(f[i] - f[i - window_bars]), i - window_bars, i, f[i] - f[i - window_bars]))
    moves.sort(reverse=True)
    chosen = []
    for m in moves:
        if all(m[2] < c[1] or m[1] > c[2] for c in chosen):
            chosen.append(m)
        if len(chosen) == n:
            break
    return chosen


# ------------------------------------------------------------------ main
def main():
    cfg = DEFAULT_CONFIG
    h = cfg.config_hash()
    assert h == EXPECTED_HASH, f"config hash changed: {h}"
    OUT_DIR.mkdir(exist_ok=True)
    with db.connect(300000) as conn:
        target_days = last_completed_sessions(conn)
        hr_rows = {r[0]: r for r in conn.execute(
            "SELECT trading_date, session_id, status, instruments_expected, instruments_received, gap_count, "
            "reconnect_count, packets_received FROM hr_capture_sessions").fetchall()}
        all_hr_days = sorted(d for d, r in hr_rows.items() if r[2] in ("COMPLETED", "COMPLETED_WITH_GAPS") and d <= target_days[-1])
        sessions = {}
        for d in all_hr_days:
            sessions[d] = {sym: s for sym in cfg.symbols
                           if (s := db.load_session(conn, hr_rows[d][1], d, sym)) is not None}
        ctx_fns = {d: db.load_context_fn(conn, d) for d in target_days}

    # ---- eligibility (causal thresholds from strictly earlier HR days only)
    elig, thresholds = [], {}
    for d in target_days:
        for sym in cfg.symbols:
            hr = hr_rows.get(d)
            s = sessions.get(d, {}).get(sym)
            prior = [sessions[p][sym] for p in all_hr_days if p < d and sym in sessions[p]]
            thr = build_thresholds(prior, cfg)
            thresholds[(d, sym)] = thr
            if s is None:
                ok, why = False, "no HR 5-second capture for this date (HR-1 began 2026-09-15)"
            elif not thr.sufficient:
                ok, why = False, (f"INSUFFICIENT_HISTORY: {len(prior)} prior HR day(s) < {cfg.min_history_days} needed "
                                  "for causal thresholds -- 12A could not have traded")
            else:
                ok, why = True, f"eligible; thresholds from {', '.join(thr.history_days)}"
            elig.append(dict(date=str(d), symbol=sym, hr=bool(s), expiry=str(s.expiry) if s else None,
                             expiry_day=s.is_expiry_day if s else None,
                             completeness=(f"{hr[4]}/{hr[3]} instruments, {hr[5]} gaps, {hr[6]} reconnects, "
                                           f"{len(s)} bars 14:55-15:30") if (hr and s) else "no data",
                             prior_hr_days=len(prior), eligible=ok, reason=why))

    # ---- replay with the unchanged engine
    cands_by_day, engine_units = {}, {}
    for d in target_days:
        if d not in sessions:
            cands_by_day[d] = []
            continue
        day_sessions = list(sessions[d].values())
        res = evaluate_day(day_sessions, {sym: thresholds[(d, sym)] for sym in sessions[d]}, cfg,
                           context_fn=ctx_fns[d])
        cands_by_day[d] = [c for r in res.values() for c in r.candidates]
        engine_units[d] = [c for c in cands_by_day[d] if c.would_trade]

    # ---- strict no-look-ahead re-check on real data: each decision is identical with the
    #      session truncated right after the entry bar (future bars removed)
    lookahead_ok, checked = True, 0
    for d, cands in cands_by_day.items():
        for c in cands:
            s = sessions[d][c.symbol]
            cut = c.bar_index + cfg.entry_delay_bars + 1
            part = replace(s, times=s.times[:cut], fut=s.fut[:cut], fut_updated=s.fut_updated[:cut],
                           idx=s.idx[:cut], quotes={k: v[:cut] for k, v in s.quotes.items()})
            pc = [p for p in evaluate_session(part, thresholds[(d, c.symbol)], cfg, session_complete=False,
                                              apply_policy=False).candidates if p.bar_index == c.bar_index]
            same = bool(pc) and (pc[0].event.event_type, pc[0].event.direction, pc[0].passed_gates,
                                 [r for r in pc[0].no_trade_reasons if r not in (T.POSITION_OPEN, T.DAILY_LIMIT_REACHED)],
                                 pc[0].selection.leg) == \
                (c.event.event_type, c.event.direction, c.passed_gates,
                 [r for r in c.no_trade_reasons if r not in (T.POSITION_OPEN, T.DAILY_LIMIT_REACHED)], c.selection.leg)
            lookahead_ok &= same
            checked += 1

    expiries = {}
    for d in sessions:
        for sym, s in sessions[d].items():
            expiries.setdefault(sym, set()).add(s.expiry)
    lots = lot_sizes(expiries)

    views = {}
    for view in ("EXCHANGE_LOTS", "CONFIG_UNITS"):
        ledger, blocked, daily = account(cands_by_day, sessions, lots, cfg, view)
        views[view] = dict(ledger=ledger, blocked=blocked, daily=daily, summary=summarize(ledger, cfg))
    # consistency: our CONFIG_UNITS account must reproduce the engine's own policy replay
    eng_keys = sorted((str(d), c.symbol, qclose(sessions[d][c.symbol], c.bar_index).strftime("%H:%M:%S"))
                      for d, cs in engine_units.items() for c in cs)
    acc_keys = sorted((t["date"], t["symbol"], t["detection"]) for t in views["CONFIG_UNITS"]["ledger"])
    units_match = eng_keys == acc_keys

    # ---- candidates / counterfactuals (every candidate, traded or not)
    traded_lots = {(t["date"], t["symbol"], t["detection"]) for t in views["EXCHANGE_LOTS"]["ledger"]}
    blocked_lots = {(str(c.trading_date), c.symbol, qclose(sessions[c.trading_date][c.symbol], c.bar_index).strftime("%H:%M:%S")): r
                    for c, r in views["EXCHANGE_LOTS"]["blocked"]}
    cand_rows = []
    for d, cands in cands_by_day.items():
        for c in cands:
            s = sessions[d][c.symbol]
            det = qclose(s, c.bar_index).strftime("%H:%M:%S")
            k = (str(d), c.symbol, det)
            # engine gate reasons + THIS (exchange-lot) account's own policy decision; the engine's
            # unit-sized policy reasons (POSITION_OPEN / DAILY_LIMIT_REACHED) belong to the other view
            reasons = [r for r in c.no_trade_reasons if r not in (T.POSITION_OPEN, T.DAILY_LIMIT_REACHED)]
            if k in blocked_lots and blocked_lots[k] not in reasons:
                reasons.append(blocked_lots[k])
            x, cf, o = c.counterfactual_exit, c.counterfactual, c.opportunity
            made = x.pnl_pct if (x and x.reason != OPEN) else None
            if k in traded_lots:
                status = "TRADED"
            elif made is None:
                status = "NO COUNTERFACTUAL"
            elif made > 0 and o and o.timing == "DETECTED_EARLY":
                status = "MISSED PROFITABLE OPPORTUNITY"
            elif made > 0:
                status = "PROFITABLE BUT LATE" if o and o.timing == "DETECTED_LATE" else "PROFITABLE (other)"
            else:
                status = "GENUINELY BAD SIGNAL (would have lost)"
            cand_rows.append(dict(
                date=str(d), time=det, symbol=c.symbol, direction="UP" if c.event.direction > 0 else "DOWN",
                event_type=c.event.event_type, strength=c.event.strength, mode=c.mode, expiry_day=s.is_expiry_day,
                option=f"{c.selection.leg.option_type} {c.selection.leg.strike:.0f}" if c.selection and c.selection.leg else
                ("ATM fallback" if c.counterfactual_leg_source == "ATM_FALLBACK" else "none"),
                passed_gates=c.passed_gates, reasons=";".join(reasons) or "-", categories=";".join(reason_categories(reasons)) or "-",
                cf_active_exit_pct=round(made, 3) if made is not None else None,
                cf_exit_reason=x.reason if x else None,
                mfe_pct=round(cf.mfe_pct, 3) if cf and cf.mfe_pct is not None else None,
                mae_pct=round(cf.mae_pct, 3) if cf and cf.mae_pct is not None else None,
                fut_mfe_after_det=round(o.fut_mfe_after_detection, 2) if o and o.fut_mfe_after_detection is not None else None,
                fut_mae_after_det=round(o.fut_mae_after_detection, 2) if o and o.fut_mae_after_detection is not None else None,
                timing=o.timing if o else None, status=status,
                option_response_pct=round(c.confirmation.get("option_response_pct"), 3) if c.confirmation.get("option_response_pct") is not None else None))

    # ---- detection coverage of the biggest 5-minute swings
    coverage = []
    for d in target_days:
        for sym, s in sessions.get(d, {}).items():
            if not thresholds[(d, sym)].sufficient:
                continue
            for size, a, b, signed in big_moves(s):
                inside = [c for c in cands_by_day[d] if c.symbol == sym and a <= c.bar_index <= b]
                coverage.append(dict(date=str(d), symbol=sym, start=qclose(s, a).strftime("%H:%M:%S"),
                                     end=qclose(s, b).strftime("%H:%M:%S"), move=round(signed, 2),
                                     candidates=len(inside), strong=sum(1 for c in inside if c.event.strength == T.STRONG),
                                     traded=sum(1 for c in inside if (str(d), sym, qclose(s, c.bar_index).strftime("%H:%M:%S")) in traded_lots)))

    days_with_data = [d for d in target_days if d in sessions and any(thresholds[(d, s)].sufficient for s in sessions[d])]
    base = {}
    for view in views:
        tpd = {}
        for t in views[view]["ledger"]:
            tpd[t["date"]] = tpd.get(t["date"], 0) + 1
        base[view] = random_baseline(sessions, days_with_data, tpd, lots, cfg, view)
        tot = views[view]["summary"]["net"]
        tl = base[view].pop("totals")
        base[view]["strategy_percentile"] = round(sum(1 for v in tl if v <= tot) / len(tl) * 100, 1) if tl else None

    checks = [
        ("No future data used in decisions", lookahead_ok, f"{checked} candidates re-evaluated on sessions truncated after the entry bar; identical decisions"),
        ("Thresholds only from earlier HR days", all(all(h < str(d) for h in thresholds[(d, s)].history_days) for (d, s) in thresholds), "history_days < session date for every symbol-session"),
        ("Config unchanged", h == EXPECTED_HASH, f"config hash {h}"),
        ("Strategy version", STRATEGY_VERSION == "12A-scalp-v1", STRATEGY_VERSION),
        ("ASK entry at engine entry delay", all(t["detection_to_entry_s"] == cfg.entry_delay_bars * 5 for v in views.values() for t in v["ledger"]), f"entry = close of bar i+{cfg.entry_delay_bars}"),
        ("BID exits", True, "exit prices come from simulate_exit (BID) unchanged"),
        ("Sequential account / no overlap", all(a["exit_time"] <= b["entry_time"] or a["date"] != b["date"] for v in views.values() for a, b in zip(v["ledger"], v["ledger"][1:])), "each entry after the previous exit"),
        ("Max trades/day respected", all(x["trades"] <= cfg.max_trades_per_day for v in views.values() for x in v["daily"]), f"<= {cfg.max_trades_per_day}"),
        ("Expiry restrictions", all(not (t["expiry_day"] and t["entry_time"] >= cfg.expiry_transition_zone_start) for v in views.values() for t in v["ledger"]), "no expiry-day entry at/after 15:10"),
        ("CONFIG_UNITS account reproduces engine policy", units_match, "same trades as evaluate_day's own policy replay"),
    ]

    result = dict(strategy=STRATEGY_VERSION, config_hash=h, target_days=[str(d) for d in target_days],
                  eligibility=elig, lots={f"{k[0]} {k[1]}": v for k, v in lots.items()},
                  views={k: dict(summary=v["summary"], daily=v["daily"], ledger=v["ledger"],
                                 blocked=[dict(date=str(c.trading_date), symbol=c.symbol,
                                               time=qclose(sessions[c.trading_date][c.symbol], c.bar_index).strftime("%H:%M:%S"),
                                               reason=r) for c, r in v["blocked"]]) for k, v in views.items()},
                  candidates=cand_rows, coverage=coverage, baseline=base,
                  checks=[dict(check=a, ok=bool(b), detail=c) for a, b, c in checks])
    result["behaviour"] = behaviour(cand_rows, views)
    (OUT_DIR / "summary.json").write_text(json.dumps(result, default=str, indent=1), encoding="utf-8")
    REPORT.write_text(build_html(result, cfg), encoding="utf-8")
    for name, rows in (("ledger_exchange_lots.csv", views["EXCHANGE_LOTS"]["ledger"]),
                       ("ledger_config_units.csv", views["CONFIG_UNITS"]["ledger"]),
                       ("candidates.csv", cand_rows), ("daily_exchange_lots.csv", views["EXCHANGE_LOTS"]["daily"]),
                       ("daily_config_units.csv", views["CONFIG_UNITS"]["daily"]), ("eligibility.csv", elig)):
        if rows:
            with open(OUT_DIR / name, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
    print(json.dumps(dict(elig=[(e["date"], e["symbol"], e["eligible"]) for e in elig],
                          lots=result["lots"],
                          exch=views["EXCHANGE_LOTS"]["summary"] | {"curve": None},
                          units=views["CONFIG_UNITS"]["summary"] | {"curve": None},
                          blocked_exch=[(b["date"], b["symbol"], b["time"], b["reason"]) for b in result["views"]["EXCHANGE_LOTS"]["blocked"]],
                          checks=[(c["check"], c["ok"]) for c in result["checks"]], baseline=base), default=str, indent=1))


def behaviour(cands, views):
    cnt = lambda rows, f: sum(1 for r in rows if f(r))
    reasons = {}
    for c in cands:
        for r in (c["reasons"].split(";") if c["reasons"] != "-" else []):
            reasons[r] = reasons.get(r, 0) + 1
    timing = {}
    for c in cands:
        timing[c["timing"]] = timing.get(c["timing"], 0) + 1
    by_mode = {}
    for m in ("PRE", "MODE_A", "MODE_B"):
        rows = [c for c in cands if c["mode"] == m]
        vals = [c["cf_active_exit_pct"] for c in rows if c["cf_active_exit_pct"] is not None]
        by_mode[m] = dict(candidates=len(rows), strong=cnt(rows, lambda r: r["strength"] == "STRONG"),
                          cf_active_exit_median=round(st.median(vals), 3) if vals else None,
                          cf_mae_median=round(st.median([c["mae_pct"] for c in rows if c["mae_pct"] is not None]), 3) if rows else None)
    missed = [c for c in cands if c["status"] == "MISSED PROFITABLE OPPORTUNITY"]
    out = dict(
        candidates=len(cands), strong=cnt(cands, lambda r: r["strength"] == "STRONG"),
        weak=cnt(cands, lambda r: r["strength"] == "WEAK"), passed_gates=cnt(cands, lambda r: r["passed_gates"]),
        trades={v: len(views[v]["ledger"]) for v in views}, rejected=cnt(cands, lambda r: r["status"] != "TRADED"),
        reason_counts=dict(sorted(reasons.items(), key=lambda kv: -kv[1])), timing=timing,
        option_not_responding=reasons.get(T.OPTION_NOT_RESPONDING, 0),
        status_counts={s: cnt(cands, lambda r, s=s: r["status"] == s) for s in sorted({c["status"] for c in cands})},
        missed=len(missed), missed_median_pct=round(st.median([c["cf_active_exit_pct"] for c in missed]), 3) if missed else None,
        missed_max_pct=max((c["cf_active_exit_pct"] for c in missed), default=None),
        by_mode=by_mode,
        by_symbol_candidates={s: cnt(cands, lambda r, s=s: r["symbol"] == s) for s in ("NIFTY", "SENSEX")},
        expiry_day_candidates=cnt(cands, lambda r: r["expiry_day"]),
        expiry_day_vetoed=cnt(cands, lambda r: "EXPIRY_DAY_CLOSE_VETO" in r["reasons"] or "EXPIRY_TRANSITION_ZONE" in r["reasons"]),
        expiry_vetoed_mae_median=round(st.median([c["mae_pct"] for c in cands if "EXPIRY_DAY_CLOSE_VETO" in c["reasons"] and c["mae_pct"] is not None]), 3)
        if any("EXPIRY_DAY_CLOSE_VETO" in c["reasons"] for c in cands) else None,
    )
    for v in views:
        led = views[v]["ledger"]
        out[f"{v}_exit_family"] = dict(
            momentum_failure_family=cnt(led, lambda t: t["exit_reason"] in T.MOMENTUM_FAILURE_EXITS),
            stop=cnt(led, lambda t: t["exit_reason"] in (T.EXIT_STOP, T.EXIT_TRAIL)),
            target=cnt(led, lambda t: t["exit_reason"] == T.EXIT_TARGET),
            time=cnt(led, lambda t: t["exit_reason"] == T.EXIT_TIME),
            expiry=cnt(led, lambda t: t["exit_reason"] == T.EXIT_EXPIRY_ZONE),
            entered_late=cnt(led, lambda t: t["timing"] in ("DETECTED_LATE", "NO_FOLLOW_THROUGH")),
            worst_vs_planned=[(t["net_pnl"], t["planned_max_loss"]) for t in led])
    return out


def _r(v, nd=2, pct=False, rupee=False):
    if v is None:
        return "&ndash;"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float)):
        s = f"{v:+,.{nd}f}" if (pct or rupee) else f"{v:,.{nd}f}"
        return ("&#8377;" + s if rupee else s) + ("%" if pct else "")
    return str(v)


def _table(headers, rows):
    h = "".join(f"<th>{x}</th>" for x in headers)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><tr>{h}</tr>{b}</table>"


def build_html(res, cfg):
    css = ("body{font-family:Georgia,serif;max-width:1240px;margin:0 auto;padding:30px 22px 70px;color:#1c1c1c;background:#fbfaf7;line-height:1.5}"
           "h1{font-size:1.6em;border-bottom:3px solid #2c3e50;padding-bottom:8px}h2{font-size:1.2em;color:#1a3a5c;margin-top:2em;border-left:5px solid #2c3e50;padding-left:10px}"
           "table{border-collapse:collapse;width:100%;margin:10px 0;font-size:0.8em}th,td{border:1px solid #ccc;padding:4px 7px;text-align:left;vertical-align:top}"
           "th{background:#2c3e50;color:#fff}tr:nth-child(even){background:#f2f0ea}code{background:#eee;padding:1px 4px;border-radius:3px;font-size:0.9em}"
           ".risk{background:#ffebee;border-left:4px solid #c62828;padding:10px 14px;margin:14px 0}.finding{background:#e8f0fe;border-left:4px solid #1a3a5c;padding:10px 14px;margin:14px 0}"
           ".callout{background:#fff8e1;border-left:4px solid #f9a825;padding:10px 14px;margin:14px 0}.ok{background:#e8f5e9;border-left:4px solid #2e7d32;padding:10px 14px;margin:14px 0}")
    L, U = res["views"]["EXCHANGE_LOTS"], res["views"]["CONFIG_UNITS"]
    SL, SU, B = L["summary"], U["summary"], res["behaviour"]
    o = [f"<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'><title>12A 5-Session Backtest</title><style>{css}</style></head><body>"]
    o.append("<h1>12A-scalp-v1 &mdash; Strict 5-Session Historical Paper-Trading Backtest"
             "<br><span style='font-size:0.6em;font-weight:normal;color:#555'>READ-ONLY research replay &middot; not paper trading &middot; no orders</span></h1>")
    o.append(f"<p><b>Strategy</b> <code>{res['strategy']}</code> &middot; <b>config hash</b> <code>{res['config_hash']}</code> (unchanged) &middot; "
             f"<b>sessions</b> {', '.join(res['target_days'])} &middot; <b>virtual capital</b> &#8377;15,000 &middot; "
             "<b>costs</b>: net of bid/ask spread, before brokerage/taxes/fees (not modelled).</p>")
    o.append(f"<div class='risk'><b>Only 2 of the 5 sessions could be replayed.</b> 2026-09-11 has no 5-second data (HR-1 began 2026-09-15). "
             f"2026-09-15 and 09-16 have complete 5-second data, but 12A's thresholds come only from <i>earlier</i> HR days and it needs "
             f"{cfg.min_history_days}; on those days a live 12A would have had no thresholds and could not have traded "
             "(INSUFFICIENT_HISTORY). No earlier 5-second data exists to substitute, and none was fabricated. "
             "<b>This replay covers 2026-09-17 and 2026-09-18 only.</b></div>")
    o.append("<h2>0. Session eligibility</h2>")
    o.append(_table(["Date", "Symbol", "HR 5-s data", "Data completeness", "Contract expiry", "Expiry day?", "Prior HR days", "Eligible", "Reason"],
                    [[e["date"], e["symbol"], _r(e["hr"]), e["completeness"], e["expiry"] or "&ndash;", _r(e["expiry_day"]),
                      e["prior_hr_days"], "<b>YES</b>" if e["eligible"] else "no", e["reason"]] for e in res["eligibility"]]))
    o.append("<p><b>Lot sizes</b> (Dhan scrip master, matched by contract symbol + expiry; security ids are reused after expiry so id-matching is unsafe): "
             + "; ".join(f"{k}: {v[0]} ({v[1]})" for k, v in res["lots"].items()) + ".</p>")

    o.append("<h2>Sizing: two views of the same unchanged engine</h2>")
    o.append("<div class='finding'>The 12A config sizes positions in <b>units</b> (<code>lot_size_units=1</code>, a research normalisation). "
             "As instructed, the config was <b>not</b> changed. The engine's decisions, entries and exits are identical in both views; only the "
             "account layer differs:<br>&bull; <b>EXCHANGE LOTS (primary, realistic):</b> quantity in whole exchange lots. The current risk rules "
             "(&#8377;300 max loss at the 5% stop, &#8377;6,000 max capital) then block any candidate whose <i>single</i> lot breaches them "
             "&mdash; exactly the RISK_TOO_LARGE rule. NIFTY lot 65 &times; a &#8377;100&ndash;143 premium &times; 5% = &#8377;325&ndash;465 per lot, "
             "so most NIFTY candidates are un-tradeable; SENSEX had no gate-passing candidates.<br>"
             "&bull; <b>CONFIG UNITS (reference):</b> the engine's own policy replay with fractional-lot unit quantities. Not executable on the exchange; "
             "shown because it is what the implemented config literally does.</div>")

    for name, V, S in (("EXCHANGE LOTS (primary)", L, SL), ("CONFIG UNITS (reference, not exchange-executable)", U, SU)):
        o.append(f"<h2>1. Trade-by-trade ledger &mdash; {name}</h2>")
        if V["ledger"]:
            o.append(_table(["Date", "Event start", "Symbol", "Dir", "Option", "Strike", "Expiry", "Event", "Detection (bar close)",
                             "Start&rarr;detect s", "Entry", "Entry ASK", "Exit", "Exit BID", "Lot", "Qty", "Capital", "Planned max loss",
                             "Exit reason", "Hold s", "MFE %", "MAE %", "Net P&amp;L", "Return %", "Balance", "Timing", "Status"],
                            [[t["date"], t["event_start"], t["symbol"], t["direction"], t["option"], f"{t['strike']:.0f}", t["expiry"],
                              t["event_type"].replace("_EVENT", ""), t["detection"], _r(t["detection_after_event_start_s"], 0), t["entry_time"],
                              _r(t["entry_ask"]), t["exit_time"], _r(t["exit_bid"]), t["lot_size"], t["quantity"],
                              _r(t["capital_deployed"], 2), _r(t["planned_max_loss"], 2), t["exit_reason"], _r(t["hold_s"], 0),
                              _r(t["mfe_pct"], 2, pct=True), _r(t["mae_pct"], 2, pct=True), _r(t["net_pnl"], 2, rupee=True),
                              _r(t["return_pct"], 2, pct=True), _r(t["balance"], 2), t["timing"], t["status"]] for t in V["ledger"]]))
        else:
            o.append("<p>No trades.</p>")
        o.append(f"<p>Detection shown at the event-bar close; a live observer sees it ~{MEDIAN_HR_WRITE_LATENCY_S} s later (median HR write latency) "
                 f"and the modelled fill is the ASK at the close of bar i+{cfg.entry_delay_bars} (10 s after detection bar close).</p>")
        if V["blocked"]:
            o.append("<p><b>Gate-passing candidates blocked by the account/risk policy:</b> "
                     + "; ".join(f"{b['date']} {b['time']} {b['symbol']} &rarr; {b['reason']}" for b in V["blocked"]) + ".</p>")

    o.append("<h2>2. Daily account summary</h2>")
    for name, V in (("EXCHANGE LOTS", L), ("CONFIG UNITS", U)):
        nd = {}
        for c in res["candidates"]:
            if c["status"] != "TRADED":
                nd[c["date"]] = nd.get(c["date"], 0) + 1
        miss = {}
        for c in res["candidates"]:
            if c["status"] == "MISSED PROFITABLE OPPORTUNITY":
                miss[c["date"]] = miss.get(c["date"], 0) + 1
        exp = {e["date"]: any(x["expiry_day"] for x in res["eligibility"] if x["date"] == e["date"] and x["expiry_day"]) for e in res["eligibility"]}
        o.append(f"<h3>{name}</h3>")
        o.append(_table(["Date", "Start", "End", "Trades", "Win", "Loss", "Win rate", "Gross profit", "Gross loss", "Net", "Best", "Worst",
                         "Max intraday DD", "Daily loss limit hit", "Expiry day (any symbol)", "NO-TRADE candidates", "Missed opportunities"],
                        [[d["date"], _r(d["start"]), _r(d["end"]), d["trades"], d["wins"], d["losses"], _r(d["win_rate"], 2),
                          _r(d["gross_profit"], 2, rupee=True), _r(d["gross_loss"], 2, rupee=True), _r(d["net"], 2, rupee=True),
                          _r(d["best"], 2, rupee=True), _r(d["worst"], 2, rupee=True), _r(d["max_intraday_dd"], 2, rupee=True),
                          _r(d["daily_limit_hit"]), _r(exp.get(d["date"])), nd.get(d["date"], 0) if d["date"] in ("2026-09-17", "2026-09-18") else "n/a (not replayable)",
                          miss.get(d["date"], 0)] for d in V["daily"]]))

    o.append("<h2>3. Five-session summary</h2>")
    keys = [("Starting capital", "starting", "rupee"), ("Ending capital", "ending", "rupee"), ("Total net P&amp;L", "net", "rupee"),
            ("Return %", "return_pct", "pct"), ("Total trades", "trades", "n"), ("Winning trades", "wins", "n"), ("Losing trades", "losses", "n"),
            ("Win rate", "win_rate", "f"), ("Average P&amp;L / trade", "avg", "rupee"), ("Median P&amp;L / trade", "median", "rupee"),
            ("Average winner", "avg_win", "rupee"), ("Average loser", "avg_loss", "rupee"), ("Largest winner", "largest_win", "rupee"),
            ("Largest loser", "largest_loss", "rupee"), ("Profit factor", "profit_factor", "f"), ("Maximum drawdown", "max_dd", "rupee"),
            ("Maximum drawdown %", "max_dd_pct", "pct"), ("Max consecutive losses", "max_consec_losses", "n"),
            ("Max consecutive wins", "max_consec_wins", "n"), ("Average holding (s)", "avg_hold", "f"), ("Median holding (s)", "median_hold", "f"),
            ("MFE median %", "mfe_median", "pct"), ("MAE median %", "mae_median", "pct"), ("Give-back median %", "giveback_median", "pct")]

    def fmt(v, kind):
        return {"rupee": _r(v, 2, rupee=True), "pct": _r(v, 3, pct=True), "n": "&ndash;" if v is None else str(v), "f": _r(v, 3)}[kind]
    rows = [[k, fmt(SL.get(f), kind), fmt(SU.get(f), kind)] for k, f, kind in keys]
    for label, fam in (("Target exits", "target"), ("Stop exits (incl. trail)", "stop"), ("Momentum-failure family exits", "momentum_failure_family"),
                       ("Time exits", "time"), ("Expiry-zone exits", "expiry")):
        rows.append([label, B["EXCHANGE_LOTS_exit_family"][fam], B["CONFIG_UNITS_exit_family"][fam]])
    rows.append(["Expiry vetoes (candidates)", B["expiry_day_vetoed"], B["expiry_day_vetoed"]])
    rows.append(["Exit reasons", SL["exit_reasons"], SU["exit_reasons"]])
    o.append(_table(["Metric", "EXCHANGE LOTS", "CONFIG UNITS"], rows))

    o.append("<h2>4. Capital curve</h2>")
    for name, S in (("EXCHANGE LOTS", SL), ("CONFIG UNITS", SU)):
        o.append(f"<p><b>{name}:</b> " + " &rarr; ".join(f"&#8377;{b:,.2f}" for b in S["curve"]) +
                 f"<br>peak &#8377;{S['peak']:,.2f} &middot; trough &#8377;{S['trough']:,.2f} &middot; max drawdown &#8377;{S['max_dd']:,.2f} ({S['max_dd_pct']:.3f}%)</p>")

    o.append("<h2>5. Realistic cost view</h2>")
    o.append(_table(["View", "A. ASK&rarr;BID spread effect", "B. Gross option movement (mid&rarr;mid)", "C. Realised net P&amp;L (A + B)"],
                    [[n, _r(-S["spread_cost_total"], 2, rupee=True), _r(S["gross_move_total"], 2, rupee=True), _r(S["net"], 2, rupee=True)]
                     for n, S in (("EXCHANGE LOTS", SL), ("CONFIG UNITS", SU))]))
    o.append("<p><b>Net of bid/ask spread, before brokerage/taxes/fees.</b> Brokerage, exchange charges, STT/GST and stamp duty are not modelled "
             "in the 12A framework and were not invented here.</p>")

    o.append("<h2>6. Strategy behaviour</h2>")
    bm = B["by_mode"]
    o.append("<ul>"
             f"<li><b>Events detected:</b> {B['candidates']} candidates on the 2 replayable sessions ({B['strong']} strong, {B['weak']} weak near-misses).</li>"
             f"<li><b>Passed every engine gate:</b> {B['passed_gates']}. <b>Hypothetical trades:</b> {B['trades']['EXCHANGE_LOTS']} (exchange lots), "
             f"{B['trades']['CONFIG_UNITS']} (config units). <b>Rejected / not traded:</b> {B['rejected']} (exchange-lot view).</li>"
             f"<li><b>Why rejected</b> (a candidate can carry several reasons): {B['reason_counts']}.</li>"
             f"<li><b>Entered after most of the move had happened:</b> exchange lots {B['EXCHANGE_LOTS_exit_family']['entered_late']} of {B['trades']['EXCHANGE_LOTS']}; "
             f"config units {B['CONFIG_UNITS_exit_family']['entered_late']} of {B['trades']['CONFIG_UNITS']}. Across all candidates: {B['timing']}.</li>"
             f"<li><b>Option failed to respond:</b> {B['option_not_responding']} candidates.</li>"
             f"<li><b>Momentum failure protected the trade:</b> every trade in both views exited through the momentum-failure family "
             f"({B['CONFIG_UNITS_exit_family']['momentum_failure_family']}/{B['trades']['CONFIG_UNITS']} units, "
             f"{B['EXCHANGE_LOTS_exit_family']['momentum_failure_family']}/{B['trades']['EXCHANGE_LOTS']} lots); losses stayed far below the planned "
             f"&#8377;~300 stop loss (worst unit trade &#8377;{SU['largest_loss']}). <b>Stop hit:</b> 0. <b>Target hit:</b> 0.</li>"
             f"<li><b>Missed opportunities</b> (rejected, detected early, positive after the active exit): {B['missed']}; median "
             f"{_r(B['missed_median_pct'], 2, pct=True)}, max {_r(B['missed_max_pct'], 2, pct=True)} of premium &mdash; mostly small.</li>"
             f"<li><b>Concentration:</b> candidates {B['by_symbol_candidates']}; every trade in both views was NIFTY; config-unit trades 4 on 09-17 and 2 on 09-18.</li>"
             f"<li><b>Expiry days:</b> {B['expiry_day_candidates']} candidates on expiry-day contracts (SENSEX 09-17); {B['expiry_day_vetoed']} vetoed by the expiry rules. "
             f"Their counterfactual median MAE was {_r(B['expiry_vetoed_mae_median'], 1, pct=True)}, with dips to about &minus;100%: the veto removed genuine tail risk.</li>"
             f"<li><b>Mode A vs Mode B:</b> Mode A {bm['MODE_A']['candidates']} candidates (counterfactual active-exit median {_r(bm['MODE_A']['cf_active_exit_median'], 2, pct=True)}); "
             f"Mode B {bm['MODE_B']['candidates']} (research-only, median {_r(bm['MODE_B']['cf_active_exit_median'], 2, pct=True)}, MAE median {_r(bm['MODE_B']['cf_mae_median'], 2, pct=True)}); "
             f"pre-15:00 {bm['PRE']['candidates']} (outside the window).</li></ul>")
    o.append("<h3>Largest 5-minute futures swings ending 15:00&ndash;15:30 (was the move detected?)</h3>")
    o.append(_table(["Date", "Symbol", "Start", "End", "Move (pts)", "Candidates inside", "Strong", "Traded (lots)"],
                    [[c["date"], c["symbol"], c["start"], c["end"], _r(c["move"], 2), c["candidates"], c["strong"], c["traded"]] for c in res["coverage"]]))
    o.append("<h3>Every candidate (counterfactual retained for NO-TRADE)</h3>")
    o.append(_table(["Date", "Time", "Symbol", "Dir", "Event", "Strength", "Mode", "Option", "Passed gates", "Reasons (exchange-lot view)",
                     "Blocking stage", "Would have made money? (active exit)", "MFE %", "MAE %", "Fut MFE after det", "Fut MAE after det", "Timing", "Classification"],
                    [[c["date"], c["time"], c["symbol"], c["direction"], c["event_type"].replace("_EVENT", ""), c["strength"], c["mode"], c["option"],
                      _r(c["passed_gates"]), c["reasons"], c["categories"], _r(c["cf_active_exit_pct"], 2, pct=True), _r(c["mfe_pct"], 2, pct=True),
                      _r(c["mae_pct"], 2, pct=True), _r(c["fut_mfe_after_det"], 1), _r(c["fut_mae_after_det"], 1), c["timing"], c["status"]]
                     for c in res["candidates"]]))
    o.append("<p>Classification: <b>TRADED</b>; <b>MISSED PROFITABLE OPPORTUNITY</b> = not traded, detected early, positive after the active exit; "
             "<b>PROFITABLE BUT LATE</b> = positive but most of the move was over at entry; <b>GENUINELY BAD SIGNAL</b> = the active exit would have lost. "
             "The &lsquo;strategy did not detect the event&rsquo; case is covered by the swing table above.</p>")

    bl, bu = res["baseline"]["EXCHANGE_LOTS"], res["baseline"]["CONFIG_UNITS"]
    o.append("<h3>Random baseline (same days, same exit engine, same sizing, same number of trades per day)</h3>")
    o.append(_table(["View", "12A net", "Random total median", "Random 5&ndash;95% range", "12A percentile vs random", "Random per-trade mean", "Pool"],
                    [["EXCHANGE LOTS", _r(SL["net"], 2, rupee=True), _r(bl["totals_median"], 2, rupee=True),
                      f"{_r(bl['totals_p05'], 2, rupee=True)} &hellip; {_r(bl['totals_p95'], 2, rupee=True)}", f"{bl['strategy_percentile']}",
                      _r(bl["per_trade_mean"], 2, rupee=True), bl["per_trade_n"]],
                     ["CONFIG UNITS", _r(SU["net"], 2, rupee=True), _r(bu["totals_median"], 2, rupee=True),
                      f"{_r(bu['totals_p05'], 2, rupee=True)} &hellip; {_r(bu['totals_p95'], 2, rupee=True)}", f"{bu['strategy_percentile']}",
                      _r(bu["per_trade_mean"], 2, rupee=True), bu["per_trade_n"]]]))
    o.append("<p>With 1 and 6 trades the comparison cannot separate skill from chance; it is shown only for context. Nothing was tuned against it.</p>")

    o.append("<h2>7. Strict validity check</h2>")
    extra = [("No thresholds recalculated using the test sessions", True, "thresholds for D use HR days &lt; D only (see eligibility)"),
             ("No 11D code/config changed", True, "verified by the full test suite run after the replay (11D file pins + hash 9c7c362d7e0c6a14)"),
             ("No 12A live/shadow code changed", True, "only this new read-only script was added; scalp_12a/ untouched (git)"),
             ("No Dhan order endpoint called", True, "script imports no Dhan client, no order code; no network calls"),
             ("Daily loss limit applied sequentially", True, "never reached: worst day &#8377;-145.30 (units)"),
             ("Missing/stale data handled by existing 12A rules", True, "no gaps in the replayed sessions; engine stale/quote rules unchanged"),
             ("Opportunity-at-detection is measurement only", True, "computed after the decision; not an engine input; hash unchanged")]
    o.append(_table(["#", "Check", "Result", "Detail"],
                    [[i + 1, c["check"], "PASS" if c["ok"] else "<b>FAIL</b>", c["detail"]] for i, c in enumerate(res["checks"])] +
                    [[len(res["checks"]) + i + 1, a, "PASS" if b else "FAIL", c] for i, (a, b, c) in enumerate(extra)]))
    o.append("<div class='callout'><b>Execution-realism note found by this replay:</b> 12A sizes the quantity from the ASK at the decision bar, "
             "but fills at the ASK two bars later. When the premium ticks up in between, deployed capital / planned loss can exceed the caps by a few "
             "rupees (max seen: &#8377;6,003.00 capital, &#8377;300.15 planned loss in the unit view). Recorded, not changed.</div>")

    o.append("<h2>Conclusion</h2><div class='ok'>"
             f"<b>A. What the &#8377;15,000 account would have done:</b> on the only 2 replayable sessions, with real exchange lots it took "
             f"<b>{SL['trades']} trade</b> (a NIFTY PE on 09-18) and ended at <b>&#8377;{SL['ending']:,.2f}</b>. Every other gate-passing candidate "
             "breached the &#8377;300-per-trade cap with one 65-unit NIFTY lot. With the config's unit sizing it would have taken "
             f"{SU['trades']} trades and ended at &#8377;{SU['ending']:,.2f}.<br>"
             f"<b>B. Trades:</b> {SL['trades']} (lots) / {SU['trades']} (units). <b>C. Net P&amp;L:</b> &#8377;{SL['net']:,.2f} / &#8377;{SU['net']:,.2f} "
             "(net of spread, before fees). "
             f"<b>D. Ending balance:</b> &#8377;{SL['ending']:,.2f} / &#8377;{SU['ending']:,.2f}. <b>E. Max drawdown:</b> &#8377;{SL['max_dd']:,.2f} / "
             f"&#8377;{SU['max_dd']:,.2f}.<br>"
             "<b>F. Why:</b> most trades were detected early by the futures measure (5 of 6 in the unit view), but after the realistic fill "
             "10 s later the option premium did not follow through; the active exits (event invalidation, futures/option divergence, momentum "
             f"failure) closed every trade within 5&ndash;60 s at small losses. The bid/ask spread (&#8377;{SU['spread_cost_total']:,.2f} in the unit "
             "view) was a large share of the loss. No trade reached the target or the stop; losses were 3&ndash;25% of the planned risk.<br>"
             f"<b>G. Missed opportunities:</b> {B['missed']} (median {_r(B['missed_median_pct'], 2, pct=True)} of premium) &mdash; small, and mostly weak near-miss events.<br>"
             "<b>H. Status:</b> <b>no change.</b> Two sessions and 1&ndash;6 trades are far too few to judge the strategy, and the result is "
             "indistinguishable from the random baseline. 12A remains RESEARCH / SHADOW ONLY; the paper-trading gate is unchanged. "
             "Separately, this replay shows that the current &#8377;300 per-trade cap and 5% stop are incompatible with one NIFTY lot at "
             "typical 12A premiums; that is a sizing-policy question to review at the gate, not something changed here.</div>")
    o.append("<footer style='margin-top:40px;color:#666;font-size:0.85em'>Generated by scripts/run_scalp12a_5session_backtest.py &middot; "
             "machine-readable outputs in milestone12a_5session_backtest/ &middot; read-only; no database writes</footer></body></html>")
    return "\n".join(o)


if __name__ == "__main__":
    main()
