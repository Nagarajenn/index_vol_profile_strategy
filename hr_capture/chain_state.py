"""Per-symbol 5-second option-chain state.

OBSERVATIONS AND STATE ONLY. Nothing here recommends, scores or signals a
trade; there is no BUY / SELL / ENTER / EXIT output of any kind. Field names
are deliberately descriptive (e.g. ``ce_volume_delta_sum`` rather than
"call pressure").

``option_implied_spot_research_only`` is a RESEARCH ONLY observation
(put-call parity on two-sided mids). It must never be used as a trading
input, never override the underlying, and is not a prediction of the close.

IV and Greeks are not carried by the WebSocket feed, so no IV skew is
computed (nothing is fabricated in its place).
"""

import numpy as np

from hr_capture.config import IMPLIED_SPOT_METHOD
from hr_capture.market_state import VALID, classify_market_state
from hr_capture.option_state import has_valid_two_sided_quote

SPOT_OK = "OK"
SPOT_LOW_COVERAGE = "LOW_COVERAGE"
SPOT_UNAVAILABLE = "UNAVAILABLE"


def _sum_or_none(values):
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def _change(current, previous):
    return None if current is None or previous is None else round(current - previous, 6)


def _imbalance(bids, asks):
    pairs = [(b, a) for b, a in zip(bids, asks) if b is not None and a is not None]
    total = sum(b + a for b, a in pairs)
    return round(sum(b - a for b, a in pairs) / total, 6) if pairs and total > 0 else None


def implied_spot(option_rows: list[dict], stale_after_s: float, min_strikes: int) -> dict:
    """RESEARCH ONLY: median over strikes of K + CE_mid - PE_mid."""
    by_strike: dict[float, dict] = {}
    for row in option_rows:
        by_strike.setdefault(row["strike"], {})[row["option_type"]] = row
    estimates, used = [], []
    for strike in sorted(by_strike):
        legs = by_strike[strike]
        ce, pe = legs.get("CE"), legs.get("PE")
        if ce and pe and has_valid_two_sided_quote(ce, stale_after_s) and has_valid_two_sided_quote(pe, stale_after_s):
            estimates.append(strike + ce["mid"] - pe["mid"])
            used.append(strike)
    if not estimates:
        return {"value": None, "n": 0, "iqr": None, "strikes": [], "quality": SPOT_UNAVAILABLE}
    arr = np.array(estimates, dtype=float)
    iqr = float(np.percentile(arr, 75) - np.percentile(arr, 25)) if len(arr) > 1 else None
    return {
        "value": round(float(np.median(arr)), 4), "n": len(arr),
        "iqr": round(iqr, 4) if iqr is not None else None, "strikes": used,
        "quality": SPOT_OK if len(arr) >= min_strikes else SPOT_LOW_COVERAGE,
    }


def parity_atm_strike(option_rows: list[dict], stale_after_s: float) -> float | None:
    """Observational: the listed strike where CE and PE mids are closest."""
    by_strike: dict[float, dict] = {}
    for row in option_rows:
        by_strike.setdefault(row["strike"], {})[row["option_type"]] = row
    best = None
    for strike, legs in by_strike.items():
        ce, pe = legs.get("CE"), legs.get("PE")
        if ce and pe and has_valid_two_sided_quote(ce, stale_after_s) and has_valid_two_sided_quote(pe, stale_after_s):
            gap = abs(ce["mid"] - pe["mid"])
            if best is None or gap < best[0]:
                best = (gap, strike)
    return best[1] if best else None


def build_chain_row(*, option_rows: list[dict], band_atm_strike: float | None, underlying: dict, futures: dict,
                    prev: dict | None, symbol_packets: int, is_gap: bool, closing_phase_reached: bool,
                    after_window_end: bool, bucket_end_ts, stale_after_s: float, min_strikes: int) -> dict:
    ce = [r for r in option_rows if r["option_type"] == "CE"]
    pe = [r for r in option_rows if r["option_type"] == "PE"]
    valid = [r for r in option_rows if has_valid_two_sided_quote(r, stale_after_s)]
    updated = sum(1 for r in option_rows if r["updated_in_bucket"])

    ce_vol = _sum_or_none(r["volume_delta"] for r in ce)
    pe_vol = _sum_or_none(r["volume_delta"] for r in pe)
    ce_oi = [r["oi_delta"] for r in ce if r["oi_delta"] is not None]
    pe_oi = [r["oi_delta"] for r in pe if r["oi_delta"] is not None]

    straddle = None
    atm_legs = {r["option_type"]: r for r in option_rows if r.get("atm_offset") == 0}
    if all(leg in atm_legs and has_valid_two_sided_quote(atm_legs[leg], stale_after_s) for leg in ("CE", "PE")):
        straddle = round(atm_legs["CE"]["mid"] + atm_legs["PE"]["mid"], 4)
    straddle_change = _change(straddle, prev.get("straddle_mid") if prev else None)

    ce_oi_total = _sum_or_none(r["oi"] for r in ce)
    pe_oi_total = _sum_or_none(r["oi"] for r in pe)
    pcr_oi = round(pe_oi_total / ce_oi_total, 6) if ce_oi_total and pe_oi_total is not None else None
    pcr_volume = round(pe_vol / ce_vol, 6) if ce_vol and pe_vol is not None else None

    spot = implied_spot(option_rows, stale_after_s, min_strikes)
    state = classify_market_state(
        after_window_end=after_window_end, disconnected=is_gap, symbol_packets=symbol_packets,
        underlying_status=underlying["status"], options_updated=updated, futures_status=futures["status"],
        closing_phase_reached=closing_phase_reached,
    )

    flags = []
    if is_gap:
        flags.append("GAP")
    if underlying["status"] != VALID:
        flags.append(f"UNDERLYING_{underlying['status']}")
    if futures["status"] != VALID:
        flags.append(f"FUTURES_{futures['status']}")
    if option_rows and len(valid) < len(option_rows) / 2:
        flags.append("LOW_OPTION_QUOTE_COVERAGE")

    return {
        "band_atm_strike": band_atm_strike,
        "parity_atm_strike": parity_atm_strike(option_rows, stale_after_s),
        "underlying_last_price": underlying["last_price"],
        "underlying_status": underlying["status"],
        "underlying_seconds_since_packet": underlying["seconds_since_packet"],
        "underlying_seconds_since_change": underlying["seconds_since_change"],
        "last_reliable_underlying_price": underlying["last_reliable_price"],
        "last_reliable_underlying_ts": underlying["last_reliable_ts"],
        "futures_last_price": futures["last_price"],
        "futures_status": futures["status"],
        "futures_bid": futures["bid"],
        "futures_ask": futures["ask"],
        "futures_volume_delta": futures["volume_delta"],
        "options_expected": len(option_rows),
        "options_updated": updated,
        "options_with_valid_quotes": len(valid),
        "ce_volume_delta_sum": ce_vol,
        "pe_volume_delta_sum": pe_vol,
        "ce_volume_delta_change": _change(ce_vol, prev.get("ce_volume_delta_sum") if prev else None),
        "pe_volume_delta_change": _change(pe_vol, prev.get("pe_volume_delta_sum") if prev else None),
        "ce_oi_delta_sum": sum(ce_oi) if ce_oi else None,
        "pe_oi_delta_sum": sum(pe_oi) if pe_oi else None,
        "ce_oi_delta_n": len(ce_oi),
        "pe_oi_delta_n": len(pe_oi),
        "ce_l1_imbalance": _imbalance([r["bid_qty_l1"] for r in ce], [r["ask_qty_l1"] for r in ce]),
        "pe_l1_imbalance": _imbalance([r["bid_qty_l1"] for r in pe], [r["ask_qty_l1"] for r in pe]),
        "ce_depth_imbalance": _imbalance([r["bid_qty_total5"] for r in ce], [r["ask_qty_total5"] for r in ce]),
        "pe_depth_imbalance": _imbalance([r["bid_qty_total5"] for r in pe], [r["ask_qty_total5"] for r in pe]),
        "straddle_mid": straddle,
        "straddle_change": straddle_change,
        "straddle_change_delta": _change(straddle_change, prev.get("straddle_change") if prev else None),
        "pcr_oi": pcr_oi,
        "pcr_oi_change": _change(pcr_oi, prev.get("pcr_oi") if prev else None),
        "pcr_volume": pcr_volume,
        "option_implied_spot_research_only": spot["value"],
        "implied_spot_method": IMPLIED_SPOT_METHOD,
        "implied_spot_n": spot["n"],
        "implied_spot_iqr": spot["iqr"],
        "implied_spot_strikes": spot["strikes"],
        "implied_spot_quality": spot["quality"],
        "implied_spot_calc_ts": bucket_end_ts,
        "market_state": state,
        "data_quality": ",".join(flags) if flags else "OK",
    }
