"""Clock helpers. All HR timestamps are IST-aware; raw receive times are
integer nanoseconds from time.time_ns()."""

from datetime import date, datetime, time
from statistics import median

from config.settings import IST

NS_PER_S = 1_000_000_000
IST_OFFSET_S = 19_800

LTT_UTC_EPOCH = "UTC_EPOCH"
LTT_IST_WALLCLOCK_EPOCH = "IST_WALLCLOCK_EPOCH"
LTT_UNDETERMINED = "UNDETERMINED"


def ns_to_ist(ns: int) -> datetime:
    seconds, rem = divmod(int(ns), NS_PER_S)
    return datetime.fromtimestamp(seconds, tz=IST).replace(microsecond=rem // 1000)


def dt_to_ns(dt: datetime) -> int:
    return int(dt.timestamp()) * NS_PER_S + dt.microsecond * 1000


def ist_ns(trading_date: date, t: time) -> int:
    return dt_to_ns(datetime.combine(trading_date, t, tzinfo=IST))


def detect_ltt_convention(samples: list[tuple[int, int]], min_samples: int, tolerance_s: float) -> str:
    """Decide how the feed's last-trade-time integer is encoded.

    The SDK treats it as a plain epoch but does not document whether it is
    true UTC or IST wall-clock encoded as an epoch, so the convention is
    measured per session from (receive_ns, ltt_epoch) pairs rather than
    assumed. A trade's LTT can be minutes old for illiquid contracts, so the
    median is used."""
    diffs = [receive_ns / NS_PER_S - ltt for receive_ns, ltt in samples if ltt and ltt > 0]
    if len(diffs) < min_samples:
        return LTT_UNDETERMINED
    mid = median(diffs)
    if abs(mid) <= tolerance_s:
        return LTT_UTC_EPOCH
    if abs(mid + IST_OFFSET_S) <= tolerance_s:
        return LTT_IST_WALLCLOCK_EPOCH
    return LTT_UNDETERMINED


def ltt_offset_seconds(convention: str) -> int | None:
    if convention == LTT_UTC_EPOCH:
        return 0
    if convention == LTT_IST_WALLCLOCK_EPOCH:
        return IST_OFFSET_S
    return None


def ltt_to_datetime(ltt_epoch: int | None, convention: str) -> datetime | None:
    offset = ltt_offset_seconds(convention)
    if not ltt_epoch or offset is None:
        return None
    return datetime.fromtimestamp(int(ltt_epoch) - offset, tz=IST)
