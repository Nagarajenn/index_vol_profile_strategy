from dataclasses import dataclass


@dataclass
class OptionChainSummary:
    expiry: str
    spot: float
    atm_strike: float
    pcr: float | None
    call_oi_change_near_atm: float
    put_oi_change_near_atm: float
    total_call_oi: float
    total_put_oi: float
    atm_iv_call: float
    atm_iv_put: float
    max_call_oi_strike: float
    max_put_oi_strike: float


def summarize_option_chain(chain: dict, atm_window_strikes: int) -> OptionChainSummary | None:
    """Summarize a raw {"expiry", "last_price", "oc": {strike: {"ce":..,"pe":..}}}
    payload into PCR, near-ATM OI deltas (vs `previous_oi`, Dhan's prior-day-close
    baseline), and the max-OI "wall" strikes on each side.
    """
    oc = chain.get("oc") or {}
    if not oc:
        return None

    spot = chain["last_price"]
    items = sorted(((float(k), v) for k, v in oc.items()), key=lambda kv: kv[0])
    strikes = [k for k, _ in items]

    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
    lo = max(0, atm_idx - atm_window_strikes)
    hi = min(len(strikes), atm_idx + atm_window_strikes + 1)
    near_atm = items[lo:hi]

    def _oi(entry: dict, leg: str) -> float:
        return (entry.get(leg) or {}).get("oi", 0) or 0

    def _prev_oi(entry: dict, leg: str) -> float:
        return (entry.get(leg) or {}).get("previous_oi", 0) or 0

    total_call_oi = sum(_oi(v, "ce") for _, v in items)
    total_put_oi = sum(_oi(v, "pe") for _, v in items)

    near_call_oi_delta = sum(_oi(v, "ce") - _prev_oi(v, "ce") for _, v in near_atm)
    near_put_oi_delta = sum(_oi(v, "pe") - _prev_oi(v, "pe") for _, v in near_atm)

    max_call_strike, _ = max(items, key=lambda kv: _oi(kv[1], "ce"))
    max_put_strike, _ = max(items, key=lambda kv: _oi(kv[1], "pe"))

    atm_strike, atm_entry = items[atm_idx]
    pcr = (total_put_oi / total_call_oi) if total_call_oi else None

    return OptionChainSummary(
        expiry=chain.get("expiry", ""),
        spot=spot,
        atm_strike=atm_strike,
        pcr=pcr,
        call_oi_change_near_atm=near_call_oi_delta,
        put_oi_change_near_atm=near_put_oi_delta,
        total_call_oi=total_call_oi,
        total_put_oi=total_put_oi,
        atm_iv_call=(atm_entry.get("ce") or {}).get("implied_volatility", 0),
        atm_iv_put=(atm_entry.get("pe") or {}).get("implied_volatility", 0),
        max_call_oi_strike=max_call_strike,
        max_put_oi_strike=max_put_strike,
    )
