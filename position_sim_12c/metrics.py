"""Prices, values, P&L, stop loss and excursions for one hypothetical long-option position.

Price discipline, applied everywhere:
* a long option is ENTERED by paying the ASK  -> entry_price = ask, entry_price_type = "ASK"
* it is EXITED by selling at the BID          -> every P&L figure is BID-based
* the LTP is shown for reference only and never used for entry or P&L
Missing prices are reported as unavailable; nothing is substituted or filled.
"""

from option_risk_12b.option_snapshot import shift

OK, UNAVAILABLE, STALE, MISSING = "OK", "UNAVAILABLE", "STALE", "MISSING"


def quote(series: dict, minute: str, side: str, strike) -> dict:
    """The validated CE/PE quote at a minute: bid, ask, ltp and a status. No fill, no guessing."""
    s = series.get(minute)
    if not s or strike is None:
        return dict(status=MISSING, minute=minute, bid=None, ask=None, ltp=None, spread_pct=None)
    q = s["legs"].get((side, strike))
    if not q:
        return dict(status=MISSING, minute=minute, bid=None, ask=None, ltp=None, spread_pct=None)
    two_sided = q.get("bid") is not None and q.get("ask") is not None and q["ask"] >= q["bid"]
    return dict(status=OK if two_sided else UNAVAILABLE, minute=minute, bid=q.get("bid"), ask=q.get("ask"),
                ltp=q.get("ltp"), spread_pct=q.get("spread_pct"))


def stop_loss(entry_price: float | None, cfg) -> float | None:
    return None if entry_price is None else round(entry_price * (1 - cfg.stop_loss_pct / 100), 2)


def r2(x):
    """Option ticks are 2 dp; rounding here keeps binary-float noise out of every displayed figure."""
    return None if x is None else round(x, 2)


def money(price_move: float | None, qty: int | None) -> float | None:
    return None if (price_move is None or qty is None) else r2(price_move * qty)


def mark(entry_price: float | None, q: dict, qty: int | None, cfg) -> dict:
    """Mark-to-market against the BID. Returns per-unit and monetary figures; monetary ones are
    None when the lot size is unknown, rather than a made-up number."""
    bid = q.get("bid")
    sl = stop_loss(entry_price, cfg)
    if entry_price is None or bid is None:
        return dict(pnl_status=UNAVAILABLE, price_change=None, pnl=None, pnl_pct=None, pnl_per_unit=None,
                    entry_value=money(entry_price, qty), current_value=None, stop_loss_price=sl,
                    distance_to_stop=None, distance_to_stop_pct=None, stop_buffer_left=None, stop_breached=None)
    move = r2(bid - entry_price)
    return dict(pnl_status=OK, price_change=move, pnl_per_unit=move, pnl=money(move, qty),
                pnl_pct=round(move / entry_price * 100, 3), entry_value=money(entry_price, qty),
                current_value=money(bid, qty), stop_loss_price=r2(sl), distance_to_stop=r2(bid - sl),
                distance_to_stop_pct=round((bid - sl) / bid * 100, 2) if bid else None,
                # how much of the entry->stop buffer is left: 1.0 at entry, 0.0 at the stop
                stop_buffer_left=round((bid - sl) / (entry_price - sl), 4) if entry_price > sl else None,
                stop_breached=bid <= sl)


def excursions(series: dict, side: str, strike, entry_minute: str, entry_price: float | None,
               until_minute: str, qty: int | None) -> dict:
    """MFE / MAE over the BID path. Only minutes at or after the entry are read, so no observation
    from before the signal -- and none from after `until_minute` -- can enter these figures."""
    if entry_price is None:
        return dict(status=UNAVAILABLE, mfe=None, mae=None, mfe_pct=None, mae_pct=None, points=0)
    best = worst = None
    m, n = entry_minute, 0
    while m <= until_minute:
        q = quote(series, m, side, strike)
        if q["status"] == OK:
            d = q["bid"] - entry_price
            best = d if best is None else max(best, d)
            worst = d if worst is None else min(worst, d)
            n += 1
        m = shift(m, 1)
    if best is None:
        return dict(status=UNAVAILABLE, mfe=None, mae=None, mfe_pct=None, mae_pct=None, points=0)
    return dict(status=OK, mfe_per_unit=r2(best), mae_per_unit=r2(worst), mfe=money(best, qty), mae=money(worst, qty),
                mfe_pct=round(best / entry_price * 100, 3), mae_pct=round(worst / entry_price * 100, 3), points=n)


def hold(entry_minute: str, now_minute: str) -> dict:
    a = int(entry_minute[:2]) * 60 + int(entry_minute[3:])
    b = int(now_minute[:2]) * 60 + int(now_minute[3:])
    mins = max(0, b - a)
    return dict(hold_minutes=mins, hold_text=f"{mins:02d}m", now_minute=now_minute)


def data_state(series: dict, minute: str, latest_available: str | None, cfg) -> str:
    """OK / STALE / MISSING for the option feed behind the position view."""
    if latest_available is None:
        return MISSING
    gap = (int(minute[:2]) * 60 + int(minute[3:])) - (int(latest_available[:2]) * 60 + int(latest_available[3:]))
    if latest_available not in series:
        return MISSING
    return STALE if gap > cfg.stale_after_minutes else OK
