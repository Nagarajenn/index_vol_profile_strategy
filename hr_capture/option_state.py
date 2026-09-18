"""Per-contract quote state and the 5-second option-state row.

Quotes are the last OBSERVED values as of bucket end, always published with
their age (quote_age_s) so a carried-forward quote can never pass for a
fresh one. OI deltas are only reported when an OI-bearing packet actually
arrived in the bucket -- Dhan refreshes OI irregularly, and an unchanged
carried value is not evidence of zero change.
"""

from dataclasses import dataclass

from hr_capture.timeutil import NS_PER_S

Q_OK = "OK"
Q_GAP = "GAP"
Q_NO_DATA_YET = "NO_DATA_YET"
Q_NO_UPDATE = "NO_UPDATE"
Q_STALE_QUOTE = "STALE_QUOTE"
Q_MISSING_BID_ASK = "MISSING_BID_ASK"
Q_CROSSED = "CROSSED"


@dataclass
class QuoteState:
    ever_seen: bool = False
    ltp: float | None = None
    bid: float | None = None
    ask: float | None = None
    bid_qty_l1: int | None = None
    ask_qty_l1: int | None = None
    bid_qty_total5: int | None = None
    ask_qty_total5: int | None = None
    oi: int | None = None
    cumulative_volume: int | None = None
    last_quote_ns: int | None = None
    last_packet_ns: int | None = None
    last_price_change_ns: int | None = None

    def apply(self, receive_ns: int, ev) -> bool:
        """Applies one de-duplicated event. Returns True if it carried OI."""
        self.ever_seen = True
        self.last_packet_ns = receive_ns
        if ev.ltp is not None and ev.ltp > 0:
            if self.ltp is None or ev.ltp != self.ltp or self.last_price_change_ns is None:
                self.last_price_change_ns = receive_ns
            self.ltp = ev.ltp
        if ev.volume is not None:
            self.cumulative_volume = ev.volume
        if ev.depth:
            level1 = ev.depth[0]
            self.bid = level1["bid_price"] if level1["bid_price"] > 0 else None
            self.ask = level1["ask_price"] if level1["ask_price"] > 0 else None
            self.bid_qty_l1 = level1["bid_qty"]
            self.ask_qty_l1 = level1["ask_qty"]
            self.bid_qty_total5 = sum(level["bid_qty"] for level in ev.depth)
            self.ask_qty_total5 = sum(level["ask_qty"] for level in ev.depth)
            self.last_quote_ns = receive_ns
        if ev.oi is not None:
            self.oi = ev.oi
            return True
        return False


def quote_fields(state: QuoteState, bucket_end_ns: int) -> dict:
    bid, ask = state.bid, state.ask
    mid = spread = spread_pct = None
    if bid is not None and ask is not None:
        mid = round((bid + ask) / 2, 4)
        spread = round(ask - bid, 4)
        spread_pct = round(spread / mid * 100, 4) if mid > 0 else None
    age = round((bucket_end_ns - state.last_quote_ns) / NS_PER_S, 3) if state.last_quote_ns is not None else None
    total = (state.bid_qty_total5 or 0) + (state.ask_qty_total5 or 0)
    imbalance = None
    if state.bid_qty_total5 is not None and state.ask_qty_total5 is not None and total > 0:
        imbalance = round((state.bid_qty_total5 - state.ask_qty_total5) / total, 6)
    return {
        "ltp": state.ltp, "bid": bid, "ask": ask, "mid": mid, "spread": spread, "spread_pct": spread_pct,
        "quote_age_s": age, "bid_qty_l1": state.bid_qty_l1, "ask_qty_l1": state.ask_qty_l1,
        "bid_qty_total5": state.bid_qty_total5, "ask_qty_total5": state.ask_qty_total5, "depth_imbalance": imbalance,
    }


def build_option_row(state: QuoteState, bucket_end_ns: int, update_count: int, oi_observed: bool,
                     prev_bucket_oi: int | None, bar: dict, is_gap: bool, stale_after_s: float) -> dict:
    fields = quote_fields(state, bucket_end_ns)
    oi_delta = None
    if oi_observed and state.oi is not None and prev_bucket_oi is not None:
        oi_delta = state.oi - prev_bucket_oi

    flags: list[str] = []
    if is_gap:
        flags.append(Q_GAP)
    if not state.ever_seen:
        flags.append(Q_NO_DATA_YET)
    else:
        if update_count == 0:
            flags.append(Q_NO_UPDATE)
        if fields["quote_age_s"] is not None and fields["quote_age_s"] > stale_after_s:
            flags.append(Q_STALE_QUOTE)
        if fields["bid"] is None or fields["ask"] is None:
            flags.append(Q_MISSING_BID_ASK)
        elif fields["ask"] < fields["bid"]:
            flags.append(Q_CROSSED)

    return {
        **fields,
        "updated_in_bucket": update_count > 0,
        "update_count": update_count,
        "trade_count": bar["trade_count"],
        "volume_delta": bar["volume"],
        "cumulative_volume": state.cumulative_volume,
        "oi": state.oi,
        "oi_delta": oi_delta,
        "data_quality": ",".join(flags) if flags else Q_OK,
    }


def has_valid_two_sided_quote(row: dict, stale_after_s: float) -> bool:
    bid, ask, age = row.get("bid"), row.get("ask"), row.get("quote_age_s")
    return bid is not None and ask is not None and ask >= bid and age is not None and age <= stale_after_s
