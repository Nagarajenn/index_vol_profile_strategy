"""Outcome and lifecycle labels.

Two separate questions, deliberately not collapsed into WIN/LOSS:

    OUTCOME    how much money the episode made or lost.
    LIFECYCLE  what SHAPE the episode had -- whether the direction was right, whether the entry
               arrived late, whether it went the right way first and was given back.

A trade that reached +₹747 MFE with -₹11 MAE and a trade that reached +₹54 MFE with -₹157 MAE
can both end negative. Calling both of them LOSS discards the only information that could tell
you which part of the system to look at.

Every label is derived from measurements that are present. Where the data cannot support a
label the answer is INCONCLUSIVE -- never a guess.
"""

from signal_learning_12d.config import (DEFAULT, EXHAUSTED, EXHAUSTING, FLAT_OUT, LATE, LOSS, REV,
                                        SMALL_LOSS, SMALL_WIN, STRONG_LOSS, STRONG_WIN, WIN)


def outcome_label(pnl_pct: float | None, cfg=DEFAULT) -> str | None:
    """Size of the result as a percentage of the entry price. None stays None."""
    if pnl_pct is None:
        return None
    if pnl_pct >= cfg.strong_pct:
        return STRONG_WIN
    if pnl_pct >= cfg.win_pct:
        return WIN
    if pnl_pct >= cfg.small_pct:
        return SMALL_WIN
    if pnl_pct > -cfg.small_pct:
        return FLAT_OUT
    if pnl_pct > -cfg.win_pct:
        return SMALL_LOSS
    if pnl_pct > -cfg.strong_pct:
        return LOSS
    return STRONG_LOSS


def direction_correct(mfe_pct: float | None, cfg=DEFAULT) -> bool | None:
    """Did the position EVER go the right way by a meaningful amount?

    This is the cleanest separation of 'was the direction right' from 'did I keep the money'.
    A signal whose premium never rose by even the small threshold was directionally wrong,
    regardless of how it was managed afterwards."""
    if mfe_pct is None:
        return None
    return mfe_pct >= cfg.small_pct


def lifecycle_label(row: dict, cfg=DEFAULT) -> str:
    """The SHAPE of the episode, from measurements only.

    Order matters: the most specific diagnosis that the data actually supports wins."""
    mfe, mae = row.get("mfe_pct"), row.get("mae_pct")
    final = row.get("final_pnl_pct")
    o1 = row.get("outcome_1m_pct")
    timing = row.get("entry_timing")
    exhaustion = row.get("exhaustion_state")
    if final is None or mfe is None or mae is None:
        return "INCONCLUSIVE"

    went_right = mfe >= cfg.small_pct
    went_wrong_first = o1 is not None and o1 <= -cfg.small_pct
    gave_it_back = went_right and final <= -cfg.small_pct
    never_worked = mfe < cfg.small_pct

    # A signal that never went the right way at all, and was immediately against, is a false
    # signal -- an entry-timing or exit question does not arise.
    if never_worked and went_wrong_first:
        return "IMMEDIATE_FALSE_SIGNAL"
    # Entered into a move that was already exhausting, and it did not work.
    if never_worked and (timing == EXHAUSTED or exhaustion in (EXHAUSTING, REV)):
        return "MOMENTUM_EXHAUSTION_ENTRY"
    if never_worked:
        return "CHOPPY_SIGNAL" if abs(final) < cfg.win_pct else "IMMEDIATE_FALSE_SIGNAL"
    # It went the right way and was given back: direction was right, the exit was not.
    if gave_it_back:
        return "GOOD_DIRECTION_LATE_ENTRY" if timing in (LATE, EXHAUSTED) else "GOOD_DIRECTION_BAD_EXIT"
    # Went against first, then recovered into profit.
    if went_wrong_first and final >= cfg.small_pct:
        return "INITIAL_ADVERSE_THEN_RECOVERED"
    if final >= cfg.small_pct:
        return "GOOD_ENTRY_GOOD_FOLLOW_THROUGH"
    return "CHOPPY_SIGNAL" if abs(final) < cfg.win_pct else "INCONCLUSIVE"


def diagnose(row: dict, cfg=DEFAULT) -> dict:
    """Spec 20: three SEPARATE questions, so a correct call with a bad entry is never confused
    with a false signal."""
    mfe, final = row.get("mfe_pct"), row.get("final_pnl_pct")
    dir_ok = direction_correct(mfe, cfg)
    # Entry timing quality is judged by what happened immediately after the entry, not by the
    # eventual result: an entry is 'good' if it did not have to be endured.
    mae1 = row.get("mae_1m")
    entry_ok = None if (mae1 is None or row.get("entry_price") in (None, 0)) else \
        (mae1 / row["entry_price"] * 100) > -cfg.win_pct
    # Exit quality: how much of the best available result was actually kept.
    exit_ok = None
    if mfe is not None and final is not None:
        exit_ok = final >= 0 if mfe < cfg.win_pct else (final >= mfe * 0.4)
    return dict(direction_correct=dir_ok, entry_timing_ok=entry_ok, exit_ok=exit_ok,
                capture_ratio=round(final / mfe, 3) if (mfe and mfe > 0 and final is not None) else None)
