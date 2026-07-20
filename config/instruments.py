"""Per-symbol constants used across analytics/charting.

Security IDs are resolved at runtime from the Dhan scrip master
(see dhan_client/scrip_master.py) — the values below are only the
symbol names / exchange we search for and the analysis parameters,
never a hardcoded security ID.
"""

INSTRUMENTS = {
    "SENSEX": {
        "trading_symbol": "SENSEX",
        "exchange": "BSE",
        "segment": "I",
        "exchange_segment_api": "IDX_I",  # dhanhq.dhanhq.INDEX
        "instrument_type": "INDEX",
        "fno_exchange_segment": "BSE_FNO",
        "volume_profile_bin_size": 25,
        "round_number_step": 100,
        "sr_cluster_tolerance_pct": 0.0015,
        "option_chain_atm_window": 10,
    },
    "NIFTY": {
        "trading_symbol": "NIFTY",
        "exchange": "NSE",
        "segment": "I",
        "exchange_segment_api": "IDX_I",
        "instrument_type": "INDEX",
        "fno_exchange_segment": "NSE_FNO",
        "volume_profile_bin_size": 5,
        "round_number_step": 50,
        "sr_cluster_tolerance_pct": 0.0015,
        "option_chain_atm_window": 10,
    },
}

VALUE_AREA_PCT = 0.70
SWING_LOOKBACK_BARS = 2
TRENDLINE_MIN_R2 = 0.7
SR_CLUSTER_TOLERANCE_PCT_DEFAULT = 0.0015
CONSOLIDATION_WINDOW_BARS = 12  # 12 * 5min = 1hr
COMPRESSION_ATR_THRESHOLD = 2.0
VOLUME_BREAKOUT_MULTIPLIER = 1.5
EMA_TREND_PERIOD = 20
ATR_PERIOD = 14
