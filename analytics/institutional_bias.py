from dataclasses import dataclass

from option_chain.summary import OptionChainSummary

PCR_BULLISH_THRESHOLD = 1.2
PCR_BEARISH_THRESHOLD = 0.8

LABELS = {
    -2: "Bearish",
    -1: "Mildly Bearish",
    0: "Neutral",
    1: "Mildly Bullish",
    2: "Bullish",
}


@dataclass
class InstitutionalBiasResult:
    label: str
    score: int | None
    available: bool


def classify_institutional_bias(summary: OptionChainSummary | None, current_price: float) -> InstitutionalBiasResult:
    """Reads OI positioning as an options-writer signal: heavy Call-OI
    buildup at/above spot acts as writer resistance (bearish for the
    underlying), heavy Put-OI buildup at/below spot acts as writer support
    (bullish), corroborated by PCR. Unavailable for backfilled/historical
    snapshots since Dhan's option chain is live-data-only.
    """
    if summary is None:
        return InstitutionalBiasResult(label="Unavailable (historical)", score=None, available=False)

    call_signal = -1 if (summary.max_call_oi_strike >= current_price and summary.call_oi_change_near_atm > 0) else 0
    put_signal = 1 if (summary.max_put_oi_strike <= current_price and summary.put_oi_change_near_atm > 0) else 0

    pcr_signal = 0
    if summary.pcr is not None:
        if summary.pcr > PCR_BULLISH_THRESHOLD:
            pcr_signal = 1
        elif summary.pcr < PCR_BEARISH_THRESHOLD:
            pcr_signal = -1

    score = max(-2, min(2, call_signal + put_signal + pcr_signal))
    return InstitutionalBiasResult(label=LABELS[score], score=score, available=True)
