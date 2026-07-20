from app.models import LevelsSnapshot

UNAVAILABLE_BIAS_LABEL = "Unavailable (historical)"


def build_interpretation(row: LevelsSnapshot) -> str | None:
    """Synthesizes a one/two-sentence narrative from already-computed
    fields on a levels_snapshots row -- the "AI Interpretation" layer the
    V2 terminal philosophy requires on every panel, distinct from both the
    raw numeric values and the trading-implication text (`action_text`).

    Deliberately computed here (backend service layer) from fields the API
    already exposes, not in the pipeline with a new persisted column --
    everything this sentence needs (close vs vwap/poc, trend_label,
    institutional_bias_label) is already available. If a future panel needs
    individual signal-level detail (e.g. the EMA-slope/structure/VWAP votes
    behind trend_score) that the backend can't see, that's the point to
    revisit a schema addition -- not speculatively now.
    """
    if row.trend_label is None:
        return None

    parts: list[str] = []
    if row.vwap_now is not None:
        rel = "above" if row.close > row.vwap_now else "below" if row.close < row.vwap_now else "at"
        parts.append(f"trading {rel} VWAP")
    if row.today_poc is not None:
        rel = "above" if row.close > row.today_poc else "below" if row.close < row.today_poc else "at"
        parts.append(f"{rel} today's POC")

    if parts:
        sentence = "Price is " + " and ".join(parts) + f", consistent with a {row.trend_label.lower()} trend."
    else:
        sentence = f"Trend reads {row.trend_label.lower()}."

    if row.institutional_bias_label and row.institutional_bias_label != UNAVAILABLE_BIAS_LABEL:
        sentence += f" Institutional positioning is currently {row.institutional_bias_label.lower()}."

    return sentence
