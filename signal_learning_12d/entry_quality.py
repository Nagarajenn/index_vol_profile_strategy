"""Momentum state, move exhaustion and entry timing -- measured at the signal minute only.

Every function here returns BOTH a label and the raw measurements behind it. The measurements
are the deliverable; the label exists so a UI has a word to print. Read the labels as
descriptions of WHERE IN A MOVE the signal landed, never as a quality score -- whether LATE is
actually worse than GOOD is exactly what the learning dataset is meant to answer, and until it
does, the word carries no verdict.
"""

from signal_learning_12d.config import (ACCELERATING, ACTIVE, DECELERATING, DEFAULT, EARLY, EXHAUSTED,
                                        EXHAUSTING, EXTENDING, FALLING, FLAT, GOOD, INSUFFICIENT, LATE,
                                        PERSISTENT, REV, REVERSING, RISING, SLOWING, UNKNOWN)


def _own(feats: dict, side: str, key: str):
    return feats.get(f"{side.lower()}_{key}")


def momentum_state(feats: dict, side: str, cfg=DEFAULT) -> dict:
    """Classify the held side's own premium momentum at the signal minute.

    ACCELERATING / RISING / PERSISTENT / DECELERATING / FALLING / FLAT / REVERSING.
    The distinction that matters for this milestone is RISING vs DECELERATING: a premium can be
    up over three minutes while the most recent minute is already slowing, and the entry engine
    currently expresses both as the same BUY."""
    c1, c3, c5 = (_own(feats, side, "chg_1m"), _own(feats, side, "chg_3m"), _own(feats, side, "chg_5m"))
    accel = _own(feats, side, "acceleration")
    m = dict(chg_1m=c1, chg_3m=c3, chg_5m=c5, acceleration=accel, ratio=None)
    if c3 is None or c1 is None:
        return dict(state=INSUFFICIENT, measurements=m,
                    note="Not enough premium history at the signal minute for a momentum reading.")
    if abs(c3) < cfg.flat_pct:
        return dict(state=FLAT, measurements=m,
                    note=f"3-minute premium change {c3:+.2f}% is inside the flat band (±{cfg.flat_pct}%).")
    # Sign disagreement between the latest minute and the 3-minute move is the clearest
    # observable form of a turn, so it is reported before any magnitude judgement.
    if c1 * c3 < 0:
        return dict(state=REVERSING, measurements=m,
                    note=f"The last minute ({c1:+.2f}%) moved against the 3-minute trend ({c3:+.2f}%).")
    if c3 < 0:
        return dict(state=FALLING, measurements=m,
                    note=f"{side} premium is falling: {c3:+.2f}% over 3 minutes.")
    # rising: is the newest minute carrying more or less than the recent average?
    avg_prior = (c3 - c1) / 2 if c3 is not None else None
    ratio = (c1 / avg_prior) if (avg_prior and abs(avg_prior) > 1e-9) else None
    m["ratio"] = round(ratio, 3) if ratio is not None else None
    if ratio is not None and ratio >= cfg.accel_ratio:
        return dict(state=ACCELERATING, measurements=m,
                    note=f"The latest minute ({c1:+.2f}%) is outpacing the prior average ({avg_prior:+.2f}%).")
    if ratio is not None and ratio <= 1 / cfg.accel_ratio:
        return dict(state=DECELERATING, measurements=m,
                    note=f"{side} is still up {c3:+.2f}% over 3 minutes but the latest minute "
                         f"({c1:+.2f}%) is slower than the prior average ({avg_prior:+.2f}%).")
    if c5 is not None and c5 > 0 and c3 > 0:
        return dict(state=PERSISTENT, measurements=m,
                    note=f"{side} premium up over both 3 ({c3:+.2f}%) and 5 ({c5:+.2f}%) minutes at a steady pace.")
    return dict(state=RISING, measurements=m, note=f"{side} premium up {c3:+.2f}% over 3 minutes.")


def move_exhaustion(feats: dict, side: str, cfg=DEFAULT) -> dict:
    """How far the move has already travelled by the signal minute.

    ACTIVE / EXTENDING / SLOWING / EXHAUSTING / REVERSING / UNKNOWN. Deliberately not a single
    formula: the measurements are exposed so the dataset can test which of them matters."""
    c1, c3, c5 = (_own(feats, side, "chg_1m"), _own(feats, side, "chg_3m"), _own(feats, side, "chg_5m"))
    mom = momentum_state(feats, side, cfg)["state"]
    straddle = feats.get("straddle_chg_3m")
    m = dict(chg_1m=c1, chg_3m=c3, chg_5m=c5, momentum=mom, straddle_chg_3m=straddle,
             extension_pct=c5 if c5 is not None else c3)
    if c3 is None:
        return dict(state=UNKNOWN, measurements=m, note="No premium history for an extension reading.")
    ext = c5 if c5 is not None else c3
    if mom == REVERSING:
        return dict(state=REV, measurements=m, note=f"The move is turning: last minute {c1:+.2f}% against {c3:+.2f}%.")
    if ext is not None and ext >= cfg.strong_extension_pct and mom in (DECELERATING, FLAT):
        return dict(state=EXHAUSTING, measurements=m,
                    note=f"Premium already extended {ext:+.2f}% over 5 minutes and no longer accelerating.")
    if mom == DECELERATING:
        return dict(state=SLOWING, measurements=m, note=f"Move intact ({c3:+.2f}% over 3m) but decelerating.")
    if ext is not None and ext >= cfg.extension_pct:
        return dict(state=EXTENDING, measurements=m, note=f"Premium extended {ext:+.2f}% over 5 minutes and still going.")
    return dict(state=ACTIVE, measurements=m, note=f"Move in progress: {c3:+.2f}% over 3 minutes.")


def entry_timing(feats: dict, side: str, cfg=DEFAULT) -> dict:
    """WHERE in the move the signal arrived: EARLY / GOOD / LATE / EXHAUSTED.

    PROVISIONAL and configurable, and not a quality judgement. EARLY means the premium has
    barely moved yet; LATE means a lot of the move is already behind the entry. Whether either
    is actually worse than GOOD is the open question this milestone exists to answer."""
    mom = momentum_state(feats, side, cfg)
    exh = move_exhaustion(feats, side, cfg)
    c3, c5 = _own(feats, side, "chg_3m"), _own(feats, side, "chg_5m")
    m = dict(chg_3m=c3, chg_5m=c5, momentum=mom["state"], exhaustion=exh["state"],
             extension_pct=exh["measurements"]["extension_pct"])
    if mom["state"] == INSUFFICIENT:
        return dict(state=INSUFFICIENT, measurements=m, provisional=True,
                    note="Not enough history at the signal minute to place the entry within the move.")
    if exh["state"] in (EXHAUSTING, REV):
        return dict(state=EXHAUSTED, measurements=m, provisional=True,
                    note=f"Entry arrives on an exhausting move ({exh['note']})")
    ext = m["extension_pct"]
    if ext is None:
        return dict(state=UNKNOWN, measurements=m, provisional=True, note="No extension measurement available.")
    if ext >= cfg.late_move_pct or exh["state"] == SLOWING:
        return dict(state=LATE, measurements=m, provisional=True,
                    note=f"{ext:+.2f}% of the move is already behind this entry"
                         + (" and momentum is slowing." if exh["state"] == SLOWING else "."))
    if abs(ext) < cfg.early_move_pct:
        return dict(state=EARLY, measurements=m, provisional=True,
                    note=f"Premium has moved only {ext:+.2f}% so far -- the signal is ahead of the move.")
    return dict(state=GOOD, measurements=m, provisional=True,
                note=f"Entry lands {ext:+.2f}% into the move with momentum {mom['state'].lower()}.")


def assess(feats: dict, side: str, cfg=DEFAULT) -> dict:
    """All three readings for one signal, with their measurements kept alongside the labels."""
    mom, exh, tim = momentum_state(feats, side, cfg), move_exhaustion(feats, side, cfg), entry_timing(feats, side, cfg)
    return dict(momentum_state=mom["state"], momentum_note=mom["note"], momentum_measurements=mom["measurements"],
                exhaustion_state=exh["state"], exhaustion_note=exh["note"],
                entry_timing=tim["state"], entry_timing_note=tim["note"],
                entry_timing_provisional=tim.get("provisional", True))
