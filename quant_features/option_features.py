"""Option-chain features. Reuses option_chain.summary.summarize_option_chain
unmodified for PCR/ATM-IV/OI-wall/ATM-strike, and adds two things no
existing function in this codebase provides:

1. Genuine intraday OI deltas -- summarize_option_chain's
   call_oi_change_near_atm/put_oi_change_near_atm are always vs Dhan's
   `previous_oi` (a fixed prior-session-close baseline), so they conflate
   "built up over the whole session" with "built up in the last few
   minutes." compute_intraday_oi_deltas() instead diffs `oi` against the
   immediately-prior option_chain_raw snapshot for the same symbol/expiry.
2. A 7-strike (ATM +/- 3) per-side ladder parsed directly from the raw
   payload's `oc` dict -- no existing function surfaces per-strike
   volume/IV/LTP/delta today.

Only computable while a snapshot exists in option_chain_raw at/before the
requested timestamp -- callers pass already-fetched raw chain payload
dict(s) (the JSONB `raw_payload` shape: {"oc": {strike: {"ce": {...},
"pe": {...}}}, "expiry": "...", "last_price": ...}); this module never
queries the DB itself, matching every other pure analytics module's
DB-independence. `previous_chain` must be the immediately-prior snapshot
for the SAME symbol/expiry -- selecting the right prior row is the
caller's responsibility, exactly like every other point-in-time-safety
guarantee in this package (see quant_features.cutoff).
"""

from datetime import date, datetime

from option_chain.summary import summarize_option_chain

from .models import DataQualityFlags, Moneyness, OptionFeatureRow, OptionType, StrikeLadderEntry

DEFAULT_LADDER_WIDTH = 3


def _sorted_items(chain: dict) -> list[tuple[float, dict]]:
    oc = chain.get("oc") or {}
    return sorted(((float(k), v) for k, v in oc.items()), key=lambda kv: kv[0])


def _find_atm_index(items: list[tuple[float, dict]], spot: float) -> int:
    return min(range(len(items)), key=lambda i: abs(items[i][0] - spot))


def _oi(entry: dict, leg: str) -> float:
    return (entry.get(leg) or {}).get("oi", 0) or 0


def compute_intraday_oi_deltas(
    current_chain: dict,
    previous_chain: dict | None,
    atm_window_strikes: int,
) -> tuple[float | None, float | None]:
    """Sums oi(now) - oi(previous snapshot) over the same near-ATM window
    summarize_option_chain() uses, so it's directly comparable to (and a
    genuinely intraday complement of) call_oi_change_near_atm/
    put_oi_change_near_atm. None/None if there's no prior snapshot to diff
    against, or no strikes matched between the two snapshots."""
    if previous_chain is None:
        return None, None

    current_items = _sorted_items(current_chain)
    if not current_items:
        return None, None
    spot = current_chain.get("last_price")
    if spot is None:
        return None, None

    prev_by_strike = dict(_sorted_items(previous_chain))
    atm_idx = _find_atm_index(current_items, spot)
    lo = max(0, atm_idx - atm_window_strikes)
    hi = min(len(current_items), atm_idx + atm_window_strikes + 1)

    call_delta = 0.0
    put_delta = 0.0
    matched_any = False
    for strike, entry in current_items[lo:hi]:
        prev_entry = prev_by_strike.get(strike)
        if prev_entry is None:
            continue
        matched_any = True
        call_delta += _oi(entry, "ce") - _oi(prev_entry, "ce")
        put_delta += _oi(entry, "pe") - _oi(prev_entry, "pe")

    if not matched_any:
        return None, None
    return call_delta, put_delta


def _moneyness(i: int, atm_idx: int, strike: float, spot: float, option_type: OptionType) -> Moneyness:
    if i == atm_idx:
        return "ATM"
    if option_type == "CE":
        return "ITM" if strike < spot else "OTM"
    return "ITM" if strike > spot else "OTM"


def build_strike_ladder(
    current_chain: dict,
    previous_chain: dict | None,
    ladder_width: int = DEFAULT_LADDER_WIDTH,
) -> list[StrikeLadderEntry]:
    items = _sorted_items(current_chain)
    if not items:
        return []
    spot = current_chain.get("last_price")
    if spot is None:
        return []

    atm_idx = _find_atm_index(items, spot)
    prev_by_strike = dict(_sorted_items(previous_chain)) if previous_chain else {}
    lo = max(0, atm_idx - ladder_width)
    hi = min(len(items), atm_idx + ladder_width + 1)

    entries: list[StrikeLadderEntry] = []
    for i in range(lo, hi):
        strike, entry = items[i]
        prev_entry = prev_by_strike.get(strike)
        for option_type, leg in (("CE", "ce"), ("PE", "pe")):
            leg_data = entry.get(leg) or {}
            oi = leg_data.get("oi")
            prev_oi = (prev_entry.get(leg) or {}).get("oi") if prev_entry else None
            oi_delta = (oi - prev_oi) if (oi is not None and prev_oi is not None) else None
            entries.append(
                StrikeLadderEntry(
                    strike=strike,
                    option_type=option_type,
                    moneyness=_moneyness(i, atm_idx, strike, spot, option_type),
                    oi=oi,
                    oi_delta_intraday=oi_delta,
                    volume=leg_data.get("volume"),
                    iv=leg_data.get("implied_volatility"),
                    ltp=leg_data.get("last_price"),
                    delta=(leg_data.get("greeks") or {}).get("delta"),
                )
            )
    return entries


def compute_option_feature_row(
    symbol: str,
    timestamp: datetime,
    feature_version: str,
    current_chain: dict | None,
    previous_chain: dict | None,
    atm_window_strikes: int,
    ladder_width: int = DEFAULT_LADDER_WIDTH,
) -> OptionFeatureRow:
    """`current_chain` is the option_chain_raw.raw_payload of the snapshot
    at/before `timestamp` (None if no such snapshot exists yet, e.g. any
    date before the live pipeline started persisting option chain data)."""
    if current_chain is None:
        return OptionFeatureRow(
            symbol=symbol,
            timestamp=timestamp,
            feature_version=feature_version,
            expiry=None,
            spot=None,
            atm_strike=None,
            pcr=None,
            atm_iv_call=None,
            atm_iv_put=None,
            atm_iv_skew=None,
            call_oi_wall_strike=None,
            put_oi_wall_strike=None,
            call_oi_delta_intraday=None,
            put_oi_delta_intraday=None,
            strike_ladder=[],
            data_quality=DataQualityFlags(
                option_data_unavailable=True, notes=["no option_chain_raw snapshot at/before this timestamp"]
            ),
        )

    summary = summarize_option_chain(current_chain, atm_window_strikes)
    if summary is None:
        return OptionFeatureRow(
            symbol=symbol,
            timestamp=timestamp,
            feature_version=feature_version,
            expiry=None,
            spot=None,
            atm_strike=None,
            pcr=None,
            atm_iv_call=None,
            atm_iv_put=None,
            atm_iv_skew=None,
            call_oi_wall_strike=None,
            put_oi_wall_strike=None,
            call_oi_delta_intraday=None,
            put_oi_delta_intraday=None,
            strike_ladder=[],
            data_quality=DataQualityFlags(option_data_unavailable=True, notes=["option chain payload had no strikes"]),
        )

    call_delta, put_delta = compute_intraday_oi_deltas(current_chain, previous_chain, atm_window_strikes)
    strike_ladder = build_strike_ladder(current_chain, previous_chain, ladder_width)

    atm_iv_skew = None
    if summary.atm_iv_call is not None and summary.atm_iv_put is not None:
        atm_iv_skew = summary.atm_iv_call - summary.atm_iv_put

    expiry_date = date.fromisoformat(summary.expiry) if summary.expiry else None

    dq = DataQualityFlags()
    if previous_chain is None:
        dq.notes.append("no prior option_chain_raw snapshot available -- intraday OI deltas unavailable")

    return OptionFeatureRow(
        symbol=symbol,
        timestamp=timestamp,
        feature_version=feature_version,
        expiry=expiry_date,
        spot=summary.spot,
        atm_strike=summary.atm_strike,
        pcr=summary.pcr,
        atm_iv_call=summary.atm_iv_call,
        atm_iv_put=summary.atm_iv_put,
        atm_iv_skew=atm_iv_skew,
        call_oi_wall_strike=summary.max_call_oi_strike,
        put_oi_wall_strike=summary.max_put_oi_strike,
        call_oi_delta_intraday=call_delta,
        put_oi_delta_intraday=put_delta,
        strike_ladder=strike_ladder,
        data_quality=dq,
    )
