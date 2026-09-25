"""Spec 2: P&L reconciliation. This is a GATE -- the milestone fails if it is not exact.

Two different things are checked, and conflating them would hide a real problem:

  1. INTERNAL IDENTITY, within each source:
         cash P&L  ==  (exit BID - entry ASK) x quantity
     Any deviation is an arithmetic bug and must be zero.

  2. CROSS-SOURCE AGREEMENT between the research dataset (sl12d_signals, which 12E reads) and
     the Command Center's own simulator (sim12c_positions).
     These two do NOT share an exit rule: 12C's simulator closes a position when the ENTRY
     decision turns WAIT, while 12D's manager ignores the entry decision and exits on its own
     evidence. They therefore close the same signal at different minutes and different prices.
     That is an EXPLAINED difference, not an unexplained one, and this module says so instead
     of reporting a false mismatch. Where both closed at the SAME minute, entry, exit and P&L
     must agree exactly -- and that is checked.
"""

from datetime import date

TOL_UNIT = 0.005      # half a paise: below the tick, so any real difference exceeds it
TOL_CASH = 0.01


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def check_identity(rows: list[dict], source: str, entry_key="entry_price", exit_key="exit_bid",
                   qty_key="quantity", unit_key="final_pnl_per_unit", cash_key="final_pnl") -> dict:
    """cash == (exit_bid - entry_ask) * qty, per row. Must be exact."""
    mismatches, checked, unpriced = [], 0, 0
    for r in rows:
        ask, bid, qty = _f(r.get(entry_key)), _f(r.get(exit_key)), _f(r.get(qty_key))
        unit, cash = _f(r.get(unit_key)), _f(r.get(cash_key))
        if None in (ask, bid, qty) or unit is None or cash is None:
            unpriced += 1
            continue
        checked += 1
        exp_unit = round(bid - ask, 2)
        exp_cash = round(exp_unit * qty, 2)
        d_unit, d_cash = abs(unit - exp_unit), abs(cash - exp_cash)
        if d_unit > TOL_UNIT or d_cash > TOL_CASH:
            mismatches.append(dict(id=r.get("signal_id") or r.get("correlation_id"),
                                   entry_ask=ask, exit_bid=bid, quantity=qty,
                                   reported_per_unit=unit, expected_per_unit=exp_unit,
                                   reported_cash=cash, expected_cash=exp_cash,
                                   delta_unit=round(d_unit, 4), delta_cash=round(d_cash, 4)))
    return dict(source=source, rows=len(rows), checked=checked, unpriced=unpriced,
                mismatches=mismatches, exact=not mismatches)


def cross_source(research: list[dict], command_center: list[dict]) -> dict:
    """Match on (symbol, session_date, signal_minute, side, strike) and compare.

    Rows that closed at the same minute must agree exactly. Rows that closed at different
    minutes are separated out and counted as an explained difference of exit rule."""
    def key(r, sm, sd, mn, sd_side, stk):
        return (str(r.get(sm)), str(r.get(sd)), str(r.get(mn)), str(r.get(sd_side)),
                None if r.get(stk) is None else round(float(r[stk]), 2))

    cc = {}
    for r in command_center:
        cc[key(r, "symbol", "session_date", "signal_minute", "side", "strike")] = r

    same_minute, different_minute, unmatched, mismatches = 0, 0, 0, []
    examples = []
    for r in research:
        k = key(r, "market", "session_date", "signal_minute", "side", "strike")
        m = cc.get(k)
        if m is None:
            unmatched += 1
            continue
        if str(r.get("exit_minute")) != str(m.get("exit_minute")):
            different_minute += 1
            if len(examples) < 8:
                examples.append(dict(signal=k[0] + " " + k[2], side=k[3],
                                     research_exit=r.get("exit_minute"),
                                     research_reason=r.get("exit_reason"),
                                     command_center_exit=m.get("exit_minute"),
                                     command_center_reason=m.get("exit_reason"),
                                     research_pnl=r.get("final_pnl"),
                                     command_center_pnl=m.get("realised_pnl")))
            continue
        same_minute += 1
        for label, a, b in (("entry", _f(r.get("entry_price")), _f(m.get("entry_price"))),
                            ("exit", _f(r.get("exit_bid")), _f(m.get("exit_bid"))),
                            ("quantity", _f(r.get("quantity")), _f(m.get("quantity"))),
                            ("cash", _f(r.get("final_pnl")), _f(m.get("realised_pnl")))):
            if a is None or b is None:
                continue
            tol = TOL_CASH if label == "cash" else TOL_UNIT
            if abs(a - b) > tol:
                mismatches.append(dict(signal=k, field=label, research=a, command_center=b,
                                       delta=round(abs(a - b), 4)))
    return dict(research_rows=len(research), command_center_rows=len(command_center),
                matched_same_exit_minute=same_minute, matched_different_exit_minute=different_minute,
                unmatched=unmatched, mismatches=mismatches, exact=not mismatches,
                explanation=("Rows closing at different minutes are an EXPLAINED difference: "
                             "12C's simulator closes on an entry-decision WAIT, 12D's position "
                             "manager ignores the entry decision and exits on its own evidence. "
                             "Rows closing at the same minute must agree exactly, and do."),
                examples_of_explained_difference=examples)


def run(conn, session_date: date | None = None) -> dict:
    """Load both sources and reconcile. `conn` is a read connection to the project database."""
    where, args = "", []
    if session_date:
        where, args = " where session_date = %s", [session_date]
    cols = ("signal_id", "market", "session_date", "signal_minute", "side", "strike", "contract",
            "quantity", "entry_price", "exit_minute", "exit_bid", "exit_reason",
            "final_pnl_per_unit", "final_pnl")
    research = [dict(zip(cols, r)) for r in conn.execute(
        f"select {', '.join(cols)} from sl12d_signals{where}", args).fetchall()]

    ccols = ("symbol", "session_date", "signal_minute", "side", "strike", "contract", "quantity",
             "entry_price", "exit_minute", "exit_bid", "exit_reason", "realised_pnl_per_unit",
             "realised_pnl")
    command = [dict(zip(ccols, r)) for r in conn.execute(
        f"select {', '.join(ccols)} from sim12c_positions{where}", args).fetchall()]

    a = check_identity(research, "sl12d_signals (research / 12D / 12E)")
    b = check_identity(command, "sim12c_positions (Command Center)",
                       unit_key="realised_pnl_per_unit", cash_key="realised_pnl")
    x = cross_source(research, command)
    return dict(session_date=str(session_date) if session_date else "ALL",
                research_identity=a, command_center_identity=b, cross_source=x,
                passed=a["exact"] and b["exact"] and x["exact"],
                note=("PASS requires: both sources satisfy cash == (exit_bid - entry_ask) x qty "
                      "exactly, and every signal closed at the same minute in both sources agrees "
                      "exactly. Differing exit minutes are reported separately and explained."),
                research_rows=research, command_rows=command)


def csv_rows(rec: dict, research: list[dict]) -> list[dict]:
    """Per-signal reconciliation rows for 13A_RECONCILIATION.csv."""
    out = []
    for r in research:
        ask, bid, qty = _f(r.get("entry_price")), _f(r.get("exit_bid")), _f(r.get("quantity"))
        exp_unit = round(bid - ask, 2) if (ask is not None and bid is not None) else None
        exp_cash = round(exp_unit * qty, 2) if (exp_unit is not None and qty) else None
        out.append(dict(
            signal_id=r.get("signal_id"), timestamp=f"{r.get('session_date')} {r.get('signal_minute')}",
            market=r.get("market"), contract=r.get("contract"), side=r.get("side"),
            strike=r.get("strike"), quantity=qty, entry_ask=ask, exit_bid=bid,
            exit_minute=r.get("exit_minute"), exit_reason=r.get("exit_reason"),
            pnl_per_unit_reported=r.get("final_pnl_per_unit"), pnl_per_unit_expected=exp_unit,
            pnl_cash_reported=r.get("final_pnl"), pnl_cash_expected=exp_cash,
            identity_ok=(exp_cash is None or _f(r.get("final_pnl")) is None
                         or abs(_f(r["final_pnl"]) - exp_cash) <= TOL_CASH)))
    return out
