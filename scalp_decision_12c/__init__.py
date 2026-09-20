"""12C-scalp-decision-v1 -- explainable scalping decision + risk brake (ADVISORY ONLY).

Consumes what the platform already computes (12B option state, 1-minute candles,
levels snapshots) and produces ONE decision with its evidence:

    no position : BUY CE / BUY PE / WAIT
    position    : HOLD / CAUTION / PREPARE_EXIT / EXIT

Rule-based, no ML, no score in a box. Nothing here places, modifies or cancels an
order, opens or closes a position, or changes 11D / 12A. The 11D exit engine and the
trader remain authoritative.
"""
