"""Turns an EXISTING 12C decision stream into hypothetical (paper) positions.

The decision stream is consumed read-only: this module never computes, alters or second-guesses
a BUY CE / BUY PE / WAIT call, and it never places an order.

Lifecycle (documented, deliberately boring -- it introduces no trading rule of its own):

* BUY CE / BUY PE while flat        -> OPEN a position on the ATM contract of the signal minute.
                                       Entry = the ASK of the signal minute, or of the next minute
                                       when cfg.entry_at_next_minute is set.
* the same side continuing          -> the SAME position stays open. Repeated BUY minutes never
                                       create a second position and never re-price the entry.
* the opposite BUY                  -> CLOSE at that minute's BID (reason SIGNAL_FLIP) and OPEN
                                       the new side at that minute's ASK.
* WAIT                              -> CLOSE at that minute's BID (reason WAIT).
* stop breach                       -> always FLAGGED; it closes the simulation only when
                                       cfg.close_on_stop_breach is set (default: keep watching).
                                       After such a close the same side is not re-entered until the
                                       signal changes, so a stop cannot be undone on the next minute.
* end of the replay window          -> CLOSE at the last available BID (reason SESSION_END).
                                       In the live view the last position simply stays OPEN.
"""

from option_risk_12b.option_snapshot import shift
from position_sim_12c import VERSION
from position_sim_12c import metrics as M
from position_sim_12c import risk as R
from position_sim_12c.config import DEFAULT
from position_sim_12c.lots import lot_size

OPEN, CLOSED, UNAVAILABLE = "OPEN", "CLOSED", "UNAVAILABLE"


def _open_position(symbol, row, series, cfg):
    side = row["decision"][-2:]
    strike, signal_m = row["atm"], row["minute"]
    m = shift(signal_m, 1) if cfg.entry_at_next_minute else signal_m
    q = M.quote(series, m, side, strike)
    expiry = series[m]["expiry"] if m in series else (series[signal_m]["expiry"] if signal_m in series else None)
    qty, qty_src = lot_size(symbol, expiry) if expiry else (None, "UNKNOWN: no expiry on the snapshot")
    entry_ask = q["ask"] if q["status"] == M.OK else None
    return dict(version=VERSION, symbol=symbol, side=side, strike=strike, expiry=str(expiry) if expiry else None,
                contract=f"{symbol} {strike:g} {side}" if strike else f"{symbol} {side}",
                signal_minute=signal_m, entry_minute=m, confirmation=row.get("confirmation"),
                entry_price=entry_ask, entry_price_type="ASK",
                entry_price_status=M.OK if entry_ask is not None else M.UNAVAILABLE,
                entry_bid_at_signal=q["bid"], entry_ltp_at_signal=q["ltp"],
                quantity=qty, quantity_status="OK" if qty else "UNKNOWN", quantity_source=qty_src,
                status=OPEN if entry_ask is not None else UNAVAILABLE,
                stop_loss_price=M.stop_loss(entry_ask, cfg), stop_loss_pct=cfg.stop_loss_pct,
                stop_breach_minute=None, exit_minute=None, exit_bid=None, exit_reason=None,
                realised_pnl_per_unit=None, realised_pnl=None, realised_pnl_pct=None)


def _close_position(pos, series, minute, reason):
    q = M.quote(series, minute, pos["side"], pos["strike"])
    pos["exit_minute"] = minute
    pos["exit_reason"] = reason
    pos["status"] = CLOSED
    if q["status"] == M.OK and pos["entry_price"] is not None:
        pos["exit_bid"] = q["bid"]
        pos["realised_pnl_per_unit"] = M.r2(q["bid"] - pos["entry_price"])
        pos["realised_pnl"] = M.money(pos["realised_pnl_per_unit"], pos["quantity"])
        pos["realised_pnl_pct"] = round(pos["realised_pnl_per_unit"] / pos["entry_price"] * 100, 3)
    else:
        pos["exit_status"] = M.UNAVAILABLE       # no executable bid at the close minute
    return pos


def snapshot(pos: dict, series: dict, evidence: dict | None, now_minute: str, cfg=DEFAULT) -> dict:
    """The live card for one position as of `now_minute`. Prices after the entry are used only
    for marking, excursions and the stop -- never to revisit the entry or the signal."""
    side, strike = pos["side"], pos["strike"]
    latest = max((m for m in series if m <= now_minute), default=None)
    q = M.quote(series, latest, side, strike) if latest else dict(status=M.MISSING, bid=None, ask=None, ltp=None,
                                                                  minute=None, spread_pct=None)
    data_status = M.data_state(series, now_minute, latest, cfg)
    m = M.mark(pos["entry_price"], q, pos["quantity"], cfg)
    ex = M.excursions(series, side, strike, pos["entry_minute"], pos["entry_price"],
                      pos.get("exit_minute") or (latest or now_minute), pos["quantity"])
    rk = R.assess(side, strike, evidence, m, data_status, cfg)
    return dict(**{k: pos[k] for k in ("version", "symbol", "side", "strike", "expiry", "contract", "signal_minute",
                                       "entry_minute", "confirmation", "entry_price", "entry_price_type",
                                       "entry_price_status", "quantity", "quantity_status", "quantity_source",
                                       "status", "stop_loss_pct", "exit_minute", "exit_bid", "exit_reason",
                                       "entry_bid_at_signal", "entry_ltp_at_signal",
                                       "realised_pnl", "realised_pnl_per_unit", "realised_pnl_pct",
                                       "stop_breach_minute")},
                current=dict(minute=q["minute"], ltp=q["ltp"], bid=q["bid"], ask=q["ask"],
                             spread_pct=q["spread_pct"], data_status=data_status),
                since_signal=dict(entry_ask=pos["entry_price"], current_bid=q["bid"], price_change=m["price_change"],
                                  pnl=m["pnl"], pnl_pct=m["pnl_pct"], pnl_status=m["pnl_status"]),
                **{k: m[k] for k in ("pnl", "pnl_per_unit", "pnl_pct", "pnl_status", "entry_value", "current_value",
                                     "stop_loss_price", "distance_to_stop", "distance_to_stop_pct",
                                     "stop_buffer_left", "stop_breached")},
                excursions=ex, **M.hold(pos["entry_minute"], now_minute), risk=rk, advisory_only=True,
                notice="Hypothetical position for observability. No order is placed and no account is touched.")


def simulate(symbol: str, series: dict, rows: list[dict], cfg=DEFAULT, as_of: str | None = None) -> dict:
    """rows: the existing 12C per-minute decisions ({minute, decision, atm, confirmation, evidence}),
    in chronological order. Returns closed positions, the open one (if any) and its live card."""
    rows = [r for r in rows if as_of is None or r["minute"] <= as_of]
    positions, pos, stopped_side = [], None, None
    for r in rows:
        d, m = r["decision"], r["minute"]
        # after a stop-breach close, the same continuing signal must not instantly re-enter the
        # position it was just stopped out of; a new one needs a genuinely new episode
        if stopped_side and not (d.startswith("BUY") and d[-2:] == stopped_side):
            stopped_side = None
        if pos is not None and pos["status"] == OPEN:
            q = M.quote(series, m, pos["side"], pos["strike"])
            mk = M.mark(pos["entry_price"], q, pos["quantity"], cfg)
            if mk.get("stop_breached") and pos["stop_breach_minute"] is None:
                pos["stop_breach_minute"] = m          # always flagged; closing is configurable
                if cfg.close_on_stop_breach:
                    positions.append(_close_position(pos, series, m, "STOP_BREACH"))
                    stopped_side, pos = pos["side"], None
        if pos is not None and pos["status"] == OPEN:
            if d == "WAIT":
                positions.append(_close_position(pos, series, m, "WAIT"))
                pos = None
            elif d.startswith("BUY") and d[-2:] != pos["side"]:
                positions.append(_close_position(pos, series, m, "SIGNAL_FLIP"))
                pos = None
        if pos is None and d.startswith("BUY") and d[-2:] != stopped_side:
            pos = _open_position(symbol, r, series, cfg)
            if pos["status"] == UNAVAILABLE:          # no ASK: recorded, never priced from the LTP
                positions.append(pos)
                pos = None
    now = as_of or (rows[-1]["minute"] if rows else None)
    ev = rows[-1].get("evidence") if rows else None
    open_card = snapshot(pos, series, ev, now, cfg) if (pos and now) else None
    closed = []
    for p in positions:
        ev_at = next((r.get("evidence") for r in reversed(rows) if r["minute"] == (p.get("exit_minute") or p["entry_minute"])), None)
        closed.append(snapshot(p, series, ev_at, p.get("exit_minute") or now or p["entry_minute"], cfg))
    return dict(version=VERSION, config_hash=cfg.config_hash(), symbol=symbol, as_of=now,
                open_position=open_card, closed_positions=closed,
                counts=dict(opened=len(positions) + (1 if pos else 0), closed=len(positions),
                            unavailable=sum(1 for p in positions if p["status"] == UNAVAILABLE)),
                advisory_only=True)


def close_out(sim: dict, series: dict, minute: str, cfg=DEFAULT) -> dict:
    """Historical replay only: close a still-open position at the last available bid."""
    if not sim.get("open_position"):
        return sim
    p = sim["open_position"]
    raw = dict(p, status=OPEN, stop_breach_minute=p.get("stop_breach_minute"))
    closed = _close_position(raw, series, minute, "SESSION_END")
    sim["closed_positions"].append(snapshot(closed, series, None, minute, cfg))
    sim["open_position"] = None
    sim["counts"]["closed"] += 1
    return sim
