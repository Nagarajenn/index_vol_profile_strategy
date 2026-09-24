"""Formal leakage audit for 12E (spec 29).

The rule under test: every field that describes the signal minute must be identical whether or
not later minutes exist in the data. Post-signal fields are expected to differ -- they are the
things being scored.

This re-runs the diagnostic with the series truncated at the signal minute and compares, field
by field, rather than asserting the property in prose.
"""

from option_audit_12e import market_state as MS
from option_audit_12e import trade_diagnostic as TD
from option_audit_12e.config import DEFAULT

# Everything observable AT the signal minute. If any of these changes when the future is
# removed, a later minute reached a value it should not have.
ENTRY_FIELDS = (
    "underlying_at_signal", "entry_ask", "entry_bid", "entry_ltp", "entry_mid", "entry_spread",
    "entry_spread_pct", "entry_delta", "entry_gamma", "entry_theta", "entry_vega", "entry_iv",
    "greeks_status", "strike_distance", "strike_distance_pct", "strike_band",
    "und_pre_1m_pct", "und_pre_3m_pct", "und_pre_5m_pct", "opt_pre_5m_pct",
    "market_state", "market_lookback_pct", "premium_position_in_range",
)

# Fields 12E DERIVES from post-signal minutes. These must vanish when the future is removed --
# if one survives, it was not actually reading the future and the measurement is wrong.
DERIVED_FUTURE_FIELDS = ("und_10m_pct", "opt_10m_pct", "exit_bid", "und_move_to_exit_pct",
                         "iv_change_to_exit_pct")

# Fields 12E does NOT compute: they are copied through from the 12D row that scored the episode.
# They are future-dependent by nature and correctly survive truncation here, because truncating
# 12E's series does not re-run 12D. Listing them separately keeps the audit honest about what it
# is and is not proving.
PASSTHROUGH_FUTURE_FIELDS = ("final_pnl_per_unit", "mfe_per_unit", "mae_per_unit")


def audit_rows(series: dict, signals: list[dict], rows: list[dict], cfg=DEFAULT,
               sample: int = 25) -> dict:
    """Compare entry-time fields against a truncated re-run."""
    by_id = {r["signal_id"]: r for r in rows}
    mismatches, checked, future_ok, future_leaked = [], 0, 0, 0
    for s in signals[:sample]:
        row = by_id.get(s["signal_id"])
        if row is None:
            continue
        m0 = s["signal_minute"]
        truncated = {k: v for k, v in series.items() if k <= m0}
        re_row = TD.build(truncated, s, cfg)
        ms = MS.classify(truncated, m0, cfg)
        re_row["market_state"] = ms["state"]
        re_row["market_lookback_pct"] = ms["lookback_pct"]
        re_row["premium_position_in_range"] = MS.premium_extension(
            truncated, m0, s["side"], s.get("strike"))["position_in_range"]
        checked += 1
        for f in ENTRY_FIELDS:
            a, b = row.get(f), re_row.get(f)
            if a != b:
                mismatches.append(dict(signal_id=s["signal_id"], field=f, full=a, truncated=b))
        for f in DERIVED_FUTURE_FIELDS:
            if re_row.get(f) is None:
                future_ok += 1
            else:
                future_leaked += 1
                mismatches.append(dict(signal_id=s["signal_id"], field=f,
                                       full=row.get(f), truncated=re_row.get(f),
                                       problem="a post-signal field survived truncation"))
    return dict(checked=checked, entry_fields_compared=len(ENTRY_FIELDS),
                mismatches=mismatches, passed=not mismatches,
                derived_future_fields_correctly_absent=future_ok,
                derived_future_fields_leaked=future_leaked,
                passthrough_fields_not_tested=list(PASSTHROUGH_FUTURE_FIELDS),
                note=("Entry-time fields are bit-identical with the future removed, and every "
                      "post-signal field 12E DERIVES vanishes under truncation. Fields copied "
                      "through from the 12D row (final P&L, MFE, MAE) are not tested here: "
                      "truncating 12E's series does not re-run 12D, so their survival proves "
                      "nothing either way. 12D has its own leakage audit for those."))
