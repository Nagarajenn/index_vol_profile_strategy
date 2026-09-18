"""Option selection for 12A: BUY CE on up events, BUY PE on down events.

Universe: dynamically discovered legs within ATM +/- atm_window_strikes (the
HR universe), never hard-coded strikes and no symbol-specific rules.

Qualification: valid two-sided quote, spread, quote age, premium band,
moneyness band (delta proxy: HR carries no greeks), recent traded volume.
Ranking: response to the event, then tighter spread, then closeness to ATM.
Cheapness is never a criterion -- a larger % move on a tiny premium is
mostly tick noise (gap analysis / 1-minute research).
"""

from scalp_12a.config import ScalpConfig
from scalp_12a.models import Event, SessionBars, Selection
from scalp_12a.taxonomy import CONTINUATION_EVENT, LOW_LIQUIDITY, SPREAD_TOO_WIDE, STALE_DATA


def moneyness_steps(option_type: str, atm_offset: int) -> int:
    """Positive = OTM, negative = ITM, 0 = ATM."""
    return atm_offset if option_type == "CE" else -atm_offset


def response_window_bars(event: Event, config: ScalpConfig) -> int:
    seconds = 180 if event.event_type == CONTINUATION_EVENT else 30
    return seconds // config.bar_seconds


def leg_response_pct(session: SessionBars, key, i: int, lag: int) -> float | None:
    now, before = session.quote(key, i), session.quote(key, i - lag)
    if not now or not before or not now.mid or not before.mid:
        return None
    return (now.mid - before.mid) / before.mid * 100.0


def recent_volume(session: SessionBars, key, i: int, bars: int) -> float:
    total = 0.0
    for k in range(max(0, i - bars + 1), i + 1):
        q = session.quote(key, k)
        if q and q.volume_delta:
            total += q.volume_delta
    return total


def select_option(session: SessionBars, event: Event, i: int, config: ScalpConfig) -> Selection:
    option_type = "CE" if event.direction > 0 else "PE"
    lag = response_window_bars(event, config)
    rejections: dict[str, int] = {}
    qualified = []
    keys = [k for k in session.quotes if k[0] == option_type and abs(k[1]) <= config.atm_window_strikes]
    for key in keys:
        m = moneyness_steps(option_type, key[1])
        if m > config.max_otm_steps or -m > config.max_itm_steps:
            rejections["moneyness"] = rejections.get("moneyness", 0) + 1
            continue
        q = session.quote(key, i)
        if q is None or not q.valid:
            rejections["no_quote"] = rejections.get("no_quote", 0) + 1
            continue
        if q.quote_age_s is not None and q.quote_age_s > config.max_quote_age_s:
            rejections["stale_quote"] = rejections.get("stale_quote", 0) + 1
            continue
        if q.spread_pct is None or q.spread_pct > config.max_spread_pct:
            rejections["spread"] = rejections.get("spread", 0) + 1
            continue
        if not (config.min_premium <= q.ask <= config.max_premium):
            rejections["premium"] = rejections.get("premium", 0) + 1
            continue
        if recent_volume(session, key, i, lag) <= 0:
            rejections["no_volume"] = rejections.get("no_volume", 0) + 1
            continue
        resp = leg_response_pct(session, key, i, lag)
        qualified.append((key, q, resp, m))

    if not qualified:
        reasons = []
        if rejections.get("spread"):
            reasons.append(SPREAD_TOO_WIDE)
        if rejections.get("no_volume") or rejections.get("no_quote") or rejections.get("premium"):
            reasons.append(LOW_LIQUIDITY)
        if rejections.get("stale_quote") and not reasons:
            reasons.append(STALE_DATA)
        return Selection(None, None, None, None, len(keys), rejections, reasons or [LOW_LIQUIDITY])

    best_resp = max((r for _, _, r, _ in qualified if r is not None), default=None)

    def score(item):
        _, q, resp, m = item
        resp_part = (resp / best_resp) if (resp is not None and best_resp and best_resp > 0) else 0.0
        return round(resp_part - q.spread_pct / config.max_spread_pct * 0.5 - abs(m) * 0.1, 6)

    qualified.sort(key=lambda it: (-score(it), abs(it[3]), it[0][1]))
    key, q, resp, _ = qualified[0]
    return Selection(session.legs[key], q, resp, score(qualified[0]), len(keys), rejections, [])
