from analytics.levels import LevelsResult
from analytics.support_resistance import Zone

ZONE_SINGLE_NUMBER_WIDTH_PCT = 0.001  # below this width, show one rounded number instead of a range


def _format_zone(zone: Zone | None) -> str | None:
    if zone is None:
        return None
    mid = (zone.high + zone.low) / 2
    width_pct = (zone.high - zone.low) / mid if mid else 0
    if width_pct < ZONE_SINGLE_NUMBER_WIDTH_PCT:
        return f"{round(mid):,}"
    return f"{round(zone.low):,}–{round(zone.high):,}"


def _action_text(levels: LevelsResult) -> str:
    trend_score = levels.trend.score
    vwap = levels.vwap_now
    poc = levels.today_vp.poc if levels.today_vp else None
    support = _format_zone(levels.support)
    resistance = _format_zone(levels.resistance)

    vwap_poc_txt = None
    if vwap and poc:
        vwap_poc_txt = f"VWAP ({vwap:,.0f}) and POC ({poc:,.0f})"
    elif vwap:
        vwap_poc_txt = f"VWAP ({vwap:,.0f})"
    elif poc:
        vwap_poc_txt = f"POC ({poc:,.0f})"

    if trend_score <= -1:
        parts = [f"Wait for a reclaim of {vwap_poc_txt} before considering calls" if vwap_poc_txt else "Wait for a clear reversal signal before considering calls"]
        if support:
            parts.append(f"below {support}, favor bearish setups / puts")
        return "; ".join(parts) + "."

    if trend_score >= 1:
        parts = [f"Favor calls while price holds above {vwap_poc_txt}" if vwap_poc_txt else "Favor calls while the uptrend structure holds"]
        if resistance:
            parts.append(f"above {resistance}, momentum can extend further")
        if support:
            parts.append(f"invalidate the bullish view below {support}")
        return "; ".join(parts) + "."

    if support and resistance:
        return f"No clear edge - wait for a decisive break of the {support} - {resistance} range with volume confirmation before choosing CE/PE."
    return "No clear edge - wait for a decisive directional move with volume confirmation before choosing CE/PE."


def build_decision_card(levels: LevelsResult) -> dict:
    return {
        "symbol": levels.symbol,
        "as_of": levels.as_of.isoformat(),
        "close": levels.close,
        "trend": f"{levels.trend.label} intraday",
        "trend_score": levels.trend.score,
        "institutional_bias": levels.institutional_bias.label,
        "institutional_bias_data": "live" if levels.institutional_bias.available else "unavailable_backfill",
        "confidence": levels.confidence.score,
        "confidence_partial_data": levels.confidence.partial_data,
        "confidence_sub_scores": levels.confidence.sub_scores,
        "confidence_weights_used": levels.confidence.weights_used,
        "support": _format_zone(levels.support),
        "support_raw": {"low": levels.support.low, "high": levels.support.high} if levels.support else None,
        "resistance": _format_zone(levels.resistance),
        "resistance_raw": {"low": levels.resistance.low, "high": levels.resistance.high} if levels.resistance else None,
        "poc": round(levels.today_vp.poc) if levels.today_vp else None,
        "value_area": {"vah": levels.today_vp.vah, "val": levels.today_vp.val} if levels.today_vp else None,
        "prior_day_poc": round(levels.yesterday_vp.poc) if levels.yesterday_vp else None,
        "vwap": round(levels.vwap_now, 2) if levels.vwap_now else None,
        "action": _action_text(levels),
    }


def format_decision_text(card: dict) -> str:
    lines = [
        f"Trend: {card['trend']}",
        f"Institutional Bias: {card['institutional_bias']}",
        f"Confidence: {card['confidence']}/100",
        f"Support: {card['support']}" if card["support"] else "Support: n/a",
        f"Resistance: {card['resistance']}" if card["resistance"] else "Resistance: n/a",
        f"POC: {card['poc']:,}" if card["poc"] is not None else "POC: n/a",
        "Trend can move above or below the POC",
        f"Action: {card['action']}",
    ]
    return "\n".join(lines)
