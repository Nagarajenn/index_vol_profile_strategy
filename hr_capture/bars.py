"""5-second OHLC bars derived ONLY from raw WebSocket events.

Bucketing uses receive time: the exchange last-trade time is 1-second
resolution and its epoch convention is detected per session, so it cannot
order events inside a 5-second bucket. Never derived from 1-minute candles.
"""

from hr_capture.timeutil import ltt_to_datetime, ns_to_ist

Q_OK = "OK"
Q_GAP = "GAP"
Q_NO_UPDATE = "NO_UPDATE"
Q_VOLUME_RESET = "VOLUME_RESET"
Q_BASELINE_IN_BUCKET = "BASELINE_IN_BUCKET"


def build_bar(events: list[tuple[int, object]], prev_last_volume: int | None, ltt_convention: str,
              is_gap: bool) -> tuple[dict, int | None]:
    """events: [(receive_ns, FeedEvent)] for one instrument within one bucket,
    in arrival order, duplicates already removed.

    Returns (bar_fields, last_cumulative_volume_to_carry)."""
    flags: list[str] = []
    prices = [ev.ltp for _, ev in events if ev.ltp is not None and ev.ltp > 0]
    volumes = [(ns, ev) for ns, ev in events if ev.volume is not None]

    trade_count = 0
    trade_events = []
    base = prev_last_volume
    for ns, ev in volumes:
        if base is not None and ev.volume > base:
            trade_count += 1
            trade_events.append(ev)
        if base is None or ev.volume >= base:
            base = ev.volume

    last_volume = volumes[-1][1].volume if volumes else None
    volume = None
    if last_volume is not None and prev_last_volume is not None:
        if last_volume >= prev_last_volume:
            volume = last_volume - prev_last_volume
        else:
            flags.append(Q_VOLUME_RESET)
    elif last_volume is not None and len(volumes) >= 2:
        volume = last_volume - volumes[0][1].volume
        flags.append(Q_BASELINE_IN_BUCKET)

    if not events:
        flags.append(Q_NO_UPDATE)
    if is_gap:
        flags.insert(0, Q_GAP)

    bar = {
        "open": prices[0] if prices else None,
        "high": max(prices) if prices else None,
        "low": min(prices) if prices else None,
        "close": prices[-1] if prices else None,
        "volume": volume,
        "cumulative_volume_end": last_volume,
        "update_count": len(events),
        "trade_count": trade_count,
        "first_trade_ts": ltt_to_datetime(trade_events[0].ltt_epoch, ltt_convention) if trade_events else None,
        "last_trade_ts": ltt_to_datetime(trade_events[-1].ltt_epoch, ltt_convention) if trade_events else None,
        "first_receive_ts": ns_to_ist(events[0][0]) if events else None,
        "last_receive_ts": ns_to_ist(events[-1][0]) if events else None,
        "data_quality": ",".join(flags) if flags else Q_OK,
    }
    carry = last_volume if last_volume is not None else prev_last_volume
    return bar, carry
