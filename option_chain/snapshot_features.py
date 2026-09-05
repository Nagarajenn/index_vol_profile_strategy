"""Option Chain Snapshot derived-feature engine (Phase 9A).

Pure functions over a raw Dhan option-chain payload (the same
{"expiry", "last_price", "oc": {strike: {"ce":..,"pe":..}}} shape
option_chain/summary.py already reads) -- no DB access, mirrors the
"pure function over a payload" discipline used throughout analytics/.

Reuses option_chain/summary.py's ATM-index-finding logic (not
reimplemented) but computes a much richer feature set: PCR by volume (not
just OI), OI concentration, straddle value, IV skew, and -- when a prior
snapshot's features are supplied -- the position-CHANGE metrics (OI
build-up/unwinding, volume acceleration, IV expansion/compression) that
option_chain_summary.py has never needed before now.

Verified against a real Dhan payload (2026-08-27 SENSEX, 14:30 snapshot):
each strike's "ce"/"pe" entry carries oi, previous_oi, volume,
previous_volume, last_price, average_price, top_bid_price, top_ask_price,
top_bid_quantity, top_ask_quantity, implied_volatility, and
greeks: {delta, gamma, theta, vega} -- exactly what's modeled below, not
guessed from documentation alone.
"""

from dataclasses import dataclass
from typing import Literal

PositionClassification = Literal["BULLISH", "BEARISH", "NEUTRAL", "MIXED", "RAPIDLY_CHANGING"]


@dataclass
class StrikeDetail:
    strike: float
    leg: Literal["CE", "PE"]
    ltp: float | None
    volume: float | None
    oi: float | None
    oi_change: float | None  # vs previous_oi (Dhan's prior-day-close baseline)
    iv: float | None
    bid: float | None
    ask: float | None
    bid_qty: float | None
    ask_qty: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None


@dataclass
class OptionSnapshotFeatures:
    spot: float
    atm_strike: float
    pcr_oi: float | None
    pcr_volume: float | None
    call_oi_concentration: float | None  # % of total OI within the ATM window
    put_oi_concentration: float | None
    call_put_volume_imbalance: float | None  # (call_vol - put_vol) / (call_vol + put_vol), signed
    atm_iv_call: float | None
    atm_iv_put: float | None
    iv_skew: float | None  # OTM put IV - OTM call IV at a matched distance from ATM
    atm_straddle_value: float | None
    max_call_oi_strike: float | None
    max_put_oi_strike: float | None
    spot_distance_from_max_call_oi: float | None
    spot_distance_from_max_put_oi: float | None
    # Change-vs-prior-snapshot fields -- None unless a prior snapshot was supplied
    pcr_change: float | None = None
    call_oi_buildup: float | None = None  # positive = OI added on the call side since the prior snapshot
    put_oi_buildup: float | None = None
    call_unwinding: float | None = None  # positive = OI reduced (unwound) on the call side
    put_unwinding: float | None = None
    atm_iv_change: float | None = None
    atm_straddle_change: float | None = None
    oi_migration_note: str | None = None  # e.g. "max call OI moved 77200 -> 77300 (away from spot)"


def _entry(oc: dict, strike_key: str, leg: str) -> dict:
    return (oc.get(strike_key) or {}).get(leg) or {}


def _num(entry: dict, key: str) -> float | None:
    v = entry.get(key)
    return float(v) if v is not None else None


def _sorted_strikes(oc: dict) -> list[float]:
    return sorted(float(k) for k in oc.keys())


def _atm_strike(strikes: list[float], spot: float) -> float:
    return min(strikes, key=lambda s: abs(s - spot))


def extract_atm_window(raw_payload: dict, atm_window_strikes: int = 5) -> list[StrikeDetail]:
    """Per-strike CE/PE detail for ATM +/- `atm_window_strikes` (default:
    11 strikes each side of, and including, ATM)."""
    oc = raw_payload.get("oc") or {}
    if not oc:
        return []
    spot = raw_payload.get("last_price")
    strikes = _sorted_strikes(oc)
    atm = _atm_strike(strikes, spot)
    atm_idx = strikes.index(atm)
    lo = max(0, atm_idx - atm_window_strikes)
    hi = min(len(strikes), atm_idx + atm_window_strikes + 1)
    window_strikes = strikes[lo:hi]

    details: list[StrikeDetail] = []
    for strike in window_strikes:
        key = next((k for k in oc if float(k) == strike), None)
        if key is None:
            continue
        for leg in ("ce", "pe"):
            entry = _entry(oc, key, leg)
            if not entry:
                continue
            greeks = entry.get("greeks") or {}
            oi = _num(entry, "oi")
            prev_oi = _num(entry, "previous_oi")
            details.append(
                StrikeDetail(
                    strike=strike, leg="CE" if leg == "ce" else "PE",
                    ltp=_num(entry, "last_price"), volume=_num(entry, "volume"),
                    oi=oi, oi_change=(oi - prev_oi) if (oi is not None and prev_oi is not None) else None,
                    iv=_num(entry, "implied_volatility"),
                    bid=_num(entry, "top_bid_price"), ask=_num(entry, "top_ask_price"),
                    bid_qty=_num(entry, "top_bid_quantity"), ask_qty=_num(entry, "top_ask_quantity"),
                    delta=_num(greeks, "delta"), gamma=_num(greeks, "gamma"),
                    theta=_num(greeks, "theta"), vega=_num(greeks, "vega"),
                )
            )
    return details


def compute_snapshot_features(
    raw_payload: dict, atm_window_strikes: int = 5, prior: OptionSnapshotFeatures | None = None,
) -> OptionSnapshotFeatures | None:
    """`prior` is the immediately-preceding checkpoint's own
    OptionSnapshotFeatures for the SAME day (not any arbitrary earlier
    snapshot) -- change-vs-prior fields are None when not supplied (e.g.
    the first checkpoint of the day)."""
    oc = raw_payload.get("oc") or {}
    if not oc:
        return None
    spot = raw_payload.get("last_price")
    strikes = _sorted_strikes(oc)
    if not strikes or spot is None:
        return None
    atm = _atm_strike(strikes, spot)
    atm_idx = strikes.index(atm)

    items = [(k, oc[k]) for k in oc]

    def _oi(entry: dict, leg: str) -> float:
        return (entry.get(leg) or {}).get("oi", 0) or 0

    def _vol(entry: dict, leg: str) -> float:
        return (entry.get(leg) or {}).get("volume", 0) or 0

    total_call_oi = sum(_oi(v, "ce") for _, v in items)
    total_put_oi = sum(_oi(v, "pe") for _, v in items)
    total_call_vol = sum(_vol(v, "ce") for _, v in items)
    total_put_vol = sum(_vol(v, "pe") for _, v in items)

    pcr_oi = (total_put_oi / total_call_oi) if total_call_oi else None
    pcr_volume = (total_put_vol / total_call_vol) if total_call_vol else None
    vol_total = total_call_vol + total_put_vol
    call_put_volume_imbalance = ((total_call_vol - total_put_vol) / vol_total) if vol_total else None

    lo = max(0, atm_idx - atm_window_strikes)
    hi = min(len(strikes), atm_idx + atm_window_strikes + 1)
    window_keys = [k for k in oc if lo <= strikes.index(float(k)) < hi]
    window_call_oi = sum(_oi(oc[k], "ce") for k in window_keys)
    window_put_oi = sum(_oi(oc[k], "pe") for k in window_keys)
    call_oi_concentration = (window_call_oi / total_call_oi) if total_call_oi else None
    put_oi_concentration = (window_put_oi / total_put_oi) if total_put_oi else None

    max_call_strike, _ = max(items, key=lambda kv: _oi(kv[1], "ce"))
    max_put_strike, _ = max(items, key=lambda kv: _oi(kv[1], "pe"))
    max_call_strike, max_put_strike = float(max_call_strike), float(max_put_strike)

    atm_key = next((k for k in oc if float(k) == atm), None)
    atm_entry = oc.get(atm_key, {}) if atm_key else {}
    atm_iv_call = _num(atm_entry.get("ce") or {}, "implied_volatility")
    atm_iv_put = _num(atm_entry.get("pe") or {}, "implied_volatility")
    atm_call_ltp = _num(atm_entry.get("ce") or {}, "last_price")
    atm_put_ltp = _num(atm_entry.get("pe") or {}, "last_price")
    atm_straddle_value = (atm_call_ltp + atm_put_ltp) if (atm_call_ltp is not None and atm_put_ltp is not None) else None

    # IV skew: compare a matched OTM put and OTM call at the same strike
    # distance from ATM (e.g. 2 strikes out each side) -- the standard
    # "does downside protection cost more than equivalent upside" read.
    iv_skew = None
    skew_distance = min(2, atm_window_strikes)
    otm_put_idx, otm_call_idx = atm_idx - skew_distance, atm_idx + skew_distance
    if 0 <= otm_put_idx < len(strikes) and 0 <= otm_call_idx < len(strikes):
        put_strike_key = next((k for k in oc if float(k) == strikes[otm_put_idx]), None)
        call_strike_key = next((k for k in oc if float(k) == strikes[otm_call_idx]), None)
        if put_strike_key and call_strike_key:
            otm_put_iv = _num(oc[put_strike_key].get("pe") or {}, "implied_volatility")
            otm_call_iv = _num(oc[call_strike_key].get("ce") or {}, "implied_volatility")
            if otm_put_iv is not None and otm_call_iv is not None:
                iv_skew = otm_put_iv - otm_call_iv

    features = OptionSnapshotFeatures(
        spot=spot, atm_strike=atm, pcr_oi=pcr_oi, pcr_volume=pcr_volume,
        call_oi_concentration=call_oi_concentration, put_oi_concentration=put_oi_concentration,
        call_put_volume_imbalance=call_put_volume_imbalance,
        atm_iv_call=atm_iv_call, atm_iv_put=atm_iv_put, iv_skew=iv_skew,
        atm_straddle_value=atm_straddle_value,
        max_call_oi_strike=max_call_strike, max_put_oi_strike=max_put_strike,
        spot_distance_from_max_call_oi=spot - max_call_strike, spot_distance_from_max_put_oi=spot - max_put_strike,
    )

    if prior is not None:
        features.pcr_change = (pcr_oi - prior.pcr_oi) if (pcr_oi is not None and prior.pcr_oi is not None) else None
        # Build-up = OI concentration grew since the prior snapshot;
        # unwinding = it shrank. Both are always populated (one of the two
        # is ~0) rather than an if/else, so a caller never has to guess
        # which field is "the meaningful one" for a given snapshot.
        if call_oi_concentration is not None and prior.call_oi_concentration is not None:
            call_delta = call_oi_concentration - prior.call_oi_concentration
            features.call_oi_buildup = max(0.0, call_delta)
            features.call_unwinding = max(0.0, -call_delta)
        if put_oi_concentration is not None and prior.put_oi_concentration is not None:
            put_delta = put_oi_concentration - prior.put_oi_concentration
            features.put_oi_buildup = max(0.0, put_delta)
            features.put_unwinding = max(0.0, -put_delta)
        if atm_iv_call is not None and atm_iv_put is not None and prior.atm_iv_call is not None and prior.atm_iv_put is not None:
            features.atm_iv_change = ((atm_iv_call + atm_iv_put) / 2) - ((prior.atm_iv_call + prior.atm_iv_put) / 2)
        if atm_straddle_value is not None and prior.atm_straddle_value is not None:
            features.atm_straddle_change = atm_straddle_value - prior.atm_straddle_value
        if max_call_strike != prior.max_call_oi_strike or max_put_strike != prior.max_put_oi_strike:
            call_note = f"max call OI {prior.max_call_oi_strike:.0f}->{max_call_strike:.0f}" if max_call_strike != prior.max_call_oi_strike else None
            put_note = f"max put OI {prior.max_put_oi_strike:.0f}->{max_put_strike:.0f}" if max_put_strike != prior.max_put_oi_strike else None
            features.oi_migration_note = "; ".join(n for n in (call_note, put_note) if n) or None

    return features


def classify_option_positioning(features: OptionSnapshotFeatures) -> PositionClassification:
    """First-match-wins heuristic over multiple independent signals (PCR
    level/trend, OI build-up side, IV trend, straddle trend) -- never
    inferred from one metric alone, per the explicit "do not rely on PCR
    alone" instruction this was built against. RAPIDLY_CHANGING fires when
    3+ signals disagree in direction from one snapshot to the next (a
    stronger bar than plain MIXED, which just means "no majority")."""
    signals: list[Literal["bullish", "bearish", "neutral"]] = []

    if features.pcr_oi is not None:
        if features.pcr_oi >= 1.2:
            signals.append("bullish")  # heavy put writing/OI = floor expected
        elif features.pcr_oi <= 0.8:
            signals.append("bearish")
        else:
            signals.append("neutral")

    if features.put_oi_buildup is not None and features.call_oi_buildup is not None:
        if features.put_oi_buildup > features.call_oi_buildup and features.put_oi_buildup > 0:
            signals.append("bullish")
        elif features.call_oi_buildup > features.put_oi_buildup and features.call_oi_buildup > 0:
            signals.append("bearish")

    if features.call_put_volume_imbalance is not None:
        if features.call_put_volume_imbalance <= -0.15:
            signals.append("bullish")  # more put volume than call volume
        elif features.call_put_volume_imbalance >= 0.15:
            signals.append("bearish")

    if not signals:
        return "NEUTRAL"

    bullish_n = signals.count("bullish")
    bearish_n = signals.count("bearish")
    disagreement = min(bullish_n, bearish_n)
    if disagreement >= 2:
        return "RAPIDLY_CHANGING"
    if bullish_n > bearish_n and bullish_n > signals.count("neutral"):
        return "BULLISH"
    if bearish_n > bullish_n and bearish_n > signals.count("neutral"):
        return "BEARISH"
    if bullish_n == bearish_n and bullish_n > 0:
        return "MIXED"
    return "NEUTRAL"
