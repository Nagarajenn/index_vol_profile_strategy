-- HR-1 High-Resolution Option Intelligence Capture -- DDL
--
-- Creates ONLY new hr_* tables and hr_* indexes. It never alters, drops,
-- references or writes to any existing table. There are intentionally no
-- foreign keys to existing tables (and none between hr_ tables, so capture
-- writes never wait on referential checks). Validated by
-- hr_capture/schema_guard.py before it can be applied.

CREATE TABLE IF NOT EXISTS hr_capture_sessions (
    session_id            UUID PRIMARY KEY,
    trading_date          DATE NOT NULL,
    mode                  TEXT NOT NULL,              -- LIVE / DRY_RUN / REPLAY
    pipeline_version      TEXT NOT NULL,
    parser_version        TEXT NOT NULL,
    implied_spot_method   TEXT NOT NULL,
    window_start          TIMESTAMPTZ NOT NULL,
    window_end            TIMESTAMPTZ NOT NULL,
    started_at            TIMESTAMPTZ NOT NULL,
    ended_at              TIMESTAMPTZ,
    status                TEXT NOT NULL,              -- RUNNING / COMPLETED / COMPLETED_WITH_GAPS / FAILED_AUTH / FAILED_CONNECTION / FAILED / HARD_STOP
    instruments_expected  INTEGER NOT NULL,
    instruments_received  INTEGER,
    packets_received      BIGINT,
    ticks_persisted       BIGINT,
    duplicates_dropped    BIGINT,
    reconnect_count       INTEGER,
    gap_count             INTEGER,
    error_count           INTEGER,
    ltt_convention        TEXT,                       -- UTC_EPOCH / IST_WALLCLOCK_EPOCH / UNDETERMINED
    config                JSONB NOT NULL,
    quality_summary       JSONB,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hr_instruments (
    id                BIGSERIAL PRIMARY KEY,
    session_id        UUID NOT NULL,
    symbol            TEXT NOT NULL,                  -- underlying: NIFTY / SENSEX
    exchange_segment  TEXT NOT NULL,                  -- IDX_I / NSE_FNO / BSE_FNO
    security_id       BIGINT NOT NULL,
    instrument_type   TEXT NOT NULL,                  -- INDEX / FUTIDX / OPTIDX
    trading_symbol    TEXT,
    expiry            DATE,
    strike            DOUBLE PRECISION,
    option_type       TEXT,                           -- CE / PE
    atm_offset        SMALLINT,                       -- strikes from band ATM (-5..+5)
    band_atm_strike   DOUBLE PRECISION,
    reference_spot    DOUBLE PRECISION,
    subscribe_mode    TEXT NOT NULL,                  -- TICKER / QUOTE / FULL
    id_source         TEXT NOT NULL,                  -- OPTION_CHAIN_RAW / SCRIP_MASTER
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, exchange_segment, security_id)
);

CREATE TABLE IF NOT EXISTS hr_raw_ticks (
    id                BIGSERIAL PRIMARY KEY,
    session_id        UUID NOT NULL,
    packet_seq        BIGINT NOT NULL,                -- per-session arrival order
    symbol            TEXT NOT NULL,
    exchange_segment  TEXT NOT NULL,
    security_id       BIGINT NOT NULL,
    instrument_type   TEXT NOT NULL,
    expiry            DATE,
    strike            DOUBLE PRECISION,
    option_type       TEXT,
    packet_type       TEXT NOT NULL,                  -- TICKER / QUOTE / OI / PREV_CLOSE / FULL
    ltt_epoch         BIGINT,                         -- raw exchange last-trade-time integer (1-second resolution)
    exchange_ts       TIMESTAMPTZ,                    -- ltt_epoch interpreted via session ltt_convention; NULL if undetermined
    receive_ts        TIMESTAMPTZ NOT NULL,           -- local arrival time
    receive_ns        BIGINT NOT NULL,
    ltp               DOUBLE PRECISION,
    ltq               BIGINT,
    avg_price         DOUBLE PRECISION,
    volume            BIGINT,                         -- cumulative day volume as reported
    oi                BIGINT,
    oi_day_high       BIGINT,
    oi_day_low        BIGINT,
    total_buy_qty     BIGINT,
    total_sell_qty    BIGINT,
    day_open          DOUBLE PRECISION,
    day_high          DOUBLE PRECISION,
    day_low           DOUBLE PRECISION,
    day_close_field   DOUBLE PRECISION,               -- the packet's "close" field as labelled by the SDK; semantics unverified
    prev_close        DOUBLE PRECISION,
    prev_oi           BIGINT,
    bid_price_1       DOUBLE PRECISION,
    bid_qty_1         BIGINT,
    bid_orders_1      INTEGER,
    ask_price_1       DOUBLE PRECISION,
    ask_qty_1         BIGINT,
    ask_orders_1      INTEGER,
    depth             JSONB,                          -- all 5 levels: bid/ask price, quantity, order count
    payload_hash      TEXT NOT NULL,
    raw_packet        BYTEA NOT NULL,                 -- forensic source of truth
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, packet_seq)
);
CREATE INDEX IF NOT EXISTS hr_raw_ticks_session_receive_idx ON hr_raw_ticks (session_id, receive_ts);
CREATE INDEX IF NOT EXISTS hr_raw_ticks_instrument_receive_idx ON hr_raw_ticks (exchange_segment, security_id, receive_ts);

CREATE TABLE IF NOT EXISTS hr_ohlc_5s (
    id                     BIGSERIAL PRIMARY KEY,
    session_id             UUID NOT NULL,
    symbol                 TEXT NOT NULL,
    exchange_segment       TEXT NOT NULL,
    security_id            BIGINT NOT NULL,
    instrument_type        TEXT NOT NULL,
    bar_ts                 TIMESTAMPTZ NOT NULL,      -- bucket start (receive-time bucketing)
    open                   DOUBLE PRECISION,
    high                   DOUBLE PRECISION,
    low                    DOUBLE PRECISION,
    close                  DOUBLE PRECISION,
    volume                 BIGINT,                    -- cumulative-volume change within the bar; NULL if not derivable
    cumulative_volume_end  BIGINT,
    update_count           INTEGER NOT NULL,          -- distinct packets received
    trade_count            INTEGER NOT NULL,          -- observed volume increments: a LOWER BOUND on trades
    first_trade_ts         TIMESTAMPTZ,
    last_trade_ts          TIMESTAMPTZ,
    first_receive_ts       TIMESTAMPTZ,
    last_receive_ts        TIMESTAMPTZ,
    source                 TEXT NOT NULL,             -- WEBSOCKET / REPLAY
    data_quality           TEXT NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (exchange_segment, security_id, bar_ts)
);
CREATE INDEX IF NOT EXISTS hr_ohlc_5s_session_idx ON hr_ohlc_5s (session_id, bar_ts);

CREATE TABLE IF NOT EXISTS hr_option_5s (
    id                 BIGSERIAL PRIMARY KEY,
    session_id         UUID NOT NULL,
    symbol             TEXT NOT NULL,
    exchange_segment   TEXT NOT NULL,
    security_id        BIGINT NOT NULL,
    expiry             DATE,
    strike             DOUBLE PRECISION,
    option_type        TEXT,
    atm_offset         SMALLINT,
    bar_ts             TIMESTAMPTZ NOT NULL,
    updated_in_bucket  BOOLEAN NOT NULL,
    update_count       INTEGER NOT NULL,
    trade_count        INTEGER NOT NULL,              -- lower bound, see hr_ohlc_5s
    ltp                DOUBLE PRECISION,              -- last observed as of bucket end
    bid                DOUBLE PRECISION,
    ask                DOUBLE PRECISION,
    mid                DOUBLE PRECISION,
    spread             DOUBLE PRECISION,
    spread_pct         DOUBLE PRECISION,
    quote_age_s        DOUBLE PRECISION,              -- seconds since the last depth/quote observation
    volume_delta       BIGINT,
    cumulative_volume  BIGINT,
    oi                 BIGINT,
    oi_delta           BIGINT,                        -- only when an OI-bearing packet arrived in this bucket
    bid_qty_l1         BIGINT,
    ask_qty_l1         BIGINT,
    bid_qty_total5     BIGINT,
    ask_qty_total5     BIGINT,
    depth_imbalance    DOUBLE PRECISION,              -- (bid5 - ask5) / (bid5 + ask5)
    data_quality       TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (exchange_segment, security_id, bar_ts)
);
CREATE INDEX IF NOT EXISTS hr_option_5s_session_idx ON hr_option_5s (session_id, symbol, bar_ts);

-- Observations and state ONLY. No BUY / SELL / ENTER / EXIT field exists.
CREATE TABLE IF NOT EXISTS hr_option_transition_state (
    id                                  BIGSERIAL PRIMARY KEY,
    session_id                          UUID NOT NULL,
    symbol                              TEXT NOT NULL,
    bar_ts                              TIMESTAMPTZ NOT NULL,
    band_atm_strike                     DOUBLE PRECISION,
    parity_atm_strike                   DOUBLE PRECISION,
    underlying_last_price               DOUBLE PRECISION,
    underlying_status                   TEXT NOT NULL,     -- VALID / STALE / FROZEN / MISSING
    underlying_seconds_since_packet     DOUBLE PRECISION,
    underlying_seconds_since_change     DOUBLE PRECISION,
    last_reliable_underlying_price      DOUBLE PRECISION,  -- REFERENCE ONLY
    last_reliable_underlying_ts         TIMESTAMPTZ,
    futures_last_price                  DOUBLE PRECISION,
    futures_status                      TEXT NOT NULL,     -- VALID / STALE / FROZEN / MISSING
    futures_bid                         DOUBLE PRECISION,
    futures_ask                         DOUBLE PRECISION,
    futures_volume_delta                BIGINT,
    options_expected                    INTEGER NOT NULL,
    options_updated                     INTEGER NOT NULL,
    options_with_valid_quotes           INTEGER NOT NULL,
    ce_volume_delta_sum                 BIGINT,
    pe_volume_delta_sum                 BIGINT,
    ce_volume_delta_change              BIGINT,
    pe_volume_delta_change              BIGINT,
    ce_oi_delta_sum                     BIGINT,
    pe_oi_delta_sum                     BIGINT,
    ce_oi_delta_n                       INTEGER NOT NULL,
    pe_oi_delta_n                       INTEGER NOT NULL,
    ce_l1_imbalance                     DOUBLE PRECISION,
    pe_l1_imbalance                     DOUBLE PRECISION,
    ce_depth_imbalance                  DOUBLE PRECISION,
    pe_depth_imbalance                  DOUBLE PRECISION,
    straddle_mid                        DOUBLE PRECISION,
    straddle_change                     DOUBLE PRECISION,
    straddle_change_delta               DOUBLE PRECISION,
    pcr_oi                              DOUBLE PRECISION,
    pcr_oi_change                       DOUBLE PRECISION,
    pcr_volume                          DOUBLE PRECISION,
    option_implied_spot_research_only   DOUBLE PRECISION,  -- RESEARCH ONLY: never a trading input
    implied_spot_method                 TEXT,
    implied_spot_n                      INTEGER NOT NULL,
    implied_spot_iqr                    DOUBLE PRECISION,
    implied_spot_strikes                JSONB,
    implied_spot_quality                TEXT NOT NULL,     -- OK / LOW_COVERAGE / UNAVAILABLE
    implied_spot_calc_ts                TIMESTAMPTZ,
    market_state                        TEXT NOT NULL,     -- CONTINUOUS / AUCTION_OR_CLOSING_STATE / UNDERLYING_STALE / DATA_GAP / RECONNECT / CLOSED / UNKNOWN
    data_quality                        TEXT NOT NULL,
    created_at                          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, bar_ts)
);
CREATE INDEX IF NOT EXISTS hr_option_transition_state_session_idx ON hr_option_transition_state (session_id, symbol, bar_ts);

CREATE TABLE IF NOT EXISTS hr_capture_events (
    id          BIGSERIAL PRIMARY KEY,
    session_id  UUID NOT NULL,
    event_ts    TIMESTAMPTZ NOT NULL,
    event_type  TEXT NOT NULL,       -- CONNECT / SUBSCRIBED / DISCONNECT / RECONNECT_SCHEDULED / AUTH_FAIL / GAP_START / GAP_END / STATE_CHANGE / BAND_EDGE / ERROR / ...
    symbol      TEXT,
    detail      JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS hr_capture_events_session_idx ON hr_capture_events (session_id, event_ts);
