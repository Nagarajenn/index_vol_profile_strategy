"""Why did this losing trade lose? One evidence-based label per trade.

Rules, in order of how directly the evidence implicates each cause. The order matters: a trade
where the underlying reversed is explained by the reversal, not by the spread it also paid.
Where two causes are genuinely comparable the label is MIXED rather than an arbitrary pick, and
where the data cannot support any of them it is UNKNOWN.

Nothing here claims causality beyond what is measured. "IV_HEADWIND" means IV fell while the
underlying went the right way and the premium did not follow -- it does not assert that the IV
fall is what caused the loss.
"""

from option_audit_12e.config import DEFAULT, IV_HEADWIND


def _first_ok(row: dict, horizons) -> tuple:
    """The earliest horizon with a usable underlying reading, and its value."""
    for h in horizons:
        v = row.get(f"und_{h}m_pct")
        if v is not None:
            return h, v
    return None, None


def classify(row: dict, cfg=DEFAULT) -> dict:
    """(label, note, evidence). Only called for trades that actually lost."""
    side = row.get("side")
    want_down = side == "PE"
    pnl = row.get("final_pnl_per_unit")
    ev = {}

    if pnl is None:
        return dict(loss_reason="DATA_ISSUE", loss_note="No executable exit price; the result is unknown.",
                    evidence=ev)
    if row.get("exit_reason") == "STOP_LOSS":
        return dict(loss_reason="STOP_LOSS", loss_note="Closed by the hard stop.", evidence=ev)

    # --- did the underlying do what the signal expected, at any measured horizon? ------------
    dirs = {h: row.get(f"und_direction_ok_{h}m") for h in cfg.horizons}
    known = {h: v for h, v in dirs.items() if v is not None}
    und_move = row.get("und_move_to_exit_pct")
    ev["und_direction_by_horizon"] = known
    ev["und_move_to_exit_pct"] = und_move

    went_wrong = bool(known) and not any(known.values())
    if went_wrong:
        # it never went the expected way at any horizon we can measure
        if row.get("exit_reason") == "SIGNAL_FLIP":
            return dict(loss_reason="SIGNAL_FLIP",
                        loss_note="The underlying never moved the expected way and 12C flipped to the other side.",
                        evidence=ev)
        return dict(loss_reason="UNDERLYING_DID_NOT_CONTINUE",
                    loss_note=f"The underlying did not move {'down' if want_down else 'up'} at any measured "
                              f"horizon (move to exit {und_move:+.2f}%)." if und_move is not None
                              else "The underlying did not move the expected way at any measured horizon.",
                    evidence=ev)

    started_right_then_turned = bool(known) and any(known.values()) and (
        und_move is not None and ((und_move > cfg.und_flat_pct) if want_down else (und_move < -cfg.und_flat_pct)))
    if started_right_then_turned:
        return dict(loss_reason="MOMENTUM_REVERSAL",
                    loss_note=f"The underlying moved the right way first, then reversed "
                              f"({und_move:+.2f}% by the exit).", evidence=ev)

    # --- the underlying DID go the right way. So why did the option lose? ----------------------
    friction = row.get("execution_friction_per_unit")
    mid = row.get("mid_to_mid_per_unit")
    ev["mid_to_mid_per_unit"] = mid
    ev["execution_friction_per_unit"] = friction

    # execution friction alone turned a flat-or-positive mid result into a loss
    if friction is not None and mid is not None and mid >= 0 > pnl:
        return dict(loss_reason="SPREAD_FRICTION",
                    loss_note=f"Mid-to-mid the trade was {mid:+.2f}/unit; the ASK-to-BID round trip "
                              f"cost {abs(friction):.2f}/unit and turned it negative.", evidence=ev)
    if friction is not None and pnl < 0 and abs(friction) >= cfg.spread_dominant_share * abs(pnl):
        return dict(loss_reason="SPREAD_FRICTION",
                    loss_note=f"Execution friction of {abs(friction):.2f}/unit accounts for most of a "
                              f"{abs(pnl):.2f}/unit loss.", evidence=ev)

    # IV fell while the underlying went the right way
    if row.get("iv_state") == IV_HEADWIND:
        ev["iv_change_to_exit_pct"] = row.get("iv_change_to_exit_pct")
        return dict(loss_reason="IV_HEADWIND",
                    loss_note=f"The underlying moved as expected but IV fell "
                              f"{row['iv_change_to_exit_pct']:+.2f}% over the hold.", evidence=ev)

    # the premium simply did not move enough per unit of spot
    h, _ = _first_ok(row, cfg.horizons)
    eff = row.get(f"response_efficiency_{h}m") if h else None
    ev["response_efficiency"] = eff
    ev["response_ratio"] = row.get(f"response_ratio_{h}m") if h else None
    ev["strike_band"] = row.get("strike_band")
    ev["entry_delta"] = row.get("entry_delta")
    if eff is not None and eff < cfg.weak_response_efficiency:
        if row.get("strike_band") in ("MODERATELY_OTM", "FAR_OTM"):
            return dict(loss_reason="STRIKE_DISTANCE",
                        loss_note=f"The contract is {row['strike_band'].replace('_', ' ').lower()} "
                                  f"({row.get('strike_distance_pct')}% from spot) and delivered only "
                                  f"{eff:.2f}x the response delta implied.", evidence=ev)
        return dict(loss_reason="WEAK_OPTION_RESPONSE",
                    loss_note=f"The premium delivered only {eff:.2f}x the move delta implied for this "
                              f"underlying change.", evidence=ev)

    # the move was largely finished before the signal arrived
    pre5, post = row.get("und_pre_5m_pct"), row.get("und_move_to_exit_pct")
    if pre5 is not None and post is not None and abs(pre5) + abs(post) > 0:
        share = abs(pre5) / (abs(pre5) + abs(post))
        ev["pre_move_share"] = round(share, 3)
        if share >= cfg.late_entry_pre_move_share and ((pre5 < 0) if want_down else (pre5 > 0)):
            return dict(loss_reason="LATE_ENTRY",
                        loss_note=f"{share*100:.0f}% of the move around this signal happened in the "
                                  f"5 minutes BEFORE it ({pre5:+.2f}% before vs {post:+.2f}% after).",
                        evidence=ev)
    return dict(loss_reason="MIXED",
                loss_note="The underlying moved as expected and no single measured factor dominates.",
                evidence=ev)


def quadrant(row: dict, horizon: int, cfg=DEFAULT) -> str | None:
    """Spec 14's four categories at one horizon. None when either side is unmeasurable."""
    from option_audit_12e.config import (A_UND_OK_OPT_OK, B_UND_OK_OPT_BAD, C_UND_BAD_OPT_OK,
                                         D_UND_BAD_OPT_BAD)
    u, o = row.get(f"und_direction_ok_{horizon}m"), row.get(f"opt_profitable_{horizon}m")
    if u is None or o is None:
        return None
    if u and o:
        return A_UND_OK_OPT_OK
    if u and not o:
        return B_UND_OK_OPT_BAD
    if not u and o:
        return C_UND_BAD_OPT_OK
    return D_UND_BAD_OPT_BAD
