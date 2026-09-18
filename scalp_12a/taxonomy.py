"""12A vocabulary: event types, NO-TRADE reasons and exit reasons.

Every rejection records ALL applicable reasons, never a single catch-all.
"""

# ---- events -------------------------------------------------------------
MOMENTUM_EVENT = "MOMENTUM_EVENT"
REVERSAL_EVENT = "REVERSAL_EVENT"
CONTINUATION_EVENT = "CONTINUATION_EVENT"
NO_EVENT = "NO_EVENT"
EVENT_TYPES = (MOMENTUM_EVENT, REVERSAL_EVENT, CONTINUATION_EVENT, NO_EVENT)

STRONG = "STRONG"
WEAK = "WEAK"

# ---- market modes -------------------------------------------------------
MODE_PRE = "PRE"                  # before 15:00 (HR window opens 14:55)
MODE_A = "MODE_A"                 # 15:00-15:15
MODE_B = "MODE_B"                 # 15:15-15:30, index frozen
MODE_CLOSED = "CLOSED"

# ---- NO-TRADE reasons (brief section 13) ----------------------------------
NO_EVENT_REASON = "NO_EVENT"
WEAK_MOMENTUM = "WEAK_MOMENTUM"
NO_CONFIRMATION = "NO_CONFIRMATION"
SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
LOW_LIQUIDITY = "LOW_LIQUIDITY"
OPTION_NOT_RESPONDING = "OPTION_NOT_RESPONDING"
MOVE_ALREADY_EXTENDED = "MOVE_ALREADY_EXTENDED"
RISK_TOO_LARGE = "RISK_TOO_LARGE"
STALE_DATA = "STALE_DATA"
EVENT_EXPIRED = "EVENT_EXPIRED"
TIME_WINDOW_CLOSED = "TIME_WINDOW_CLOSED"
# ---- explicit additions (12A-specific, evidence-backed or structural) ----
EXPIRY_DAY_CLOSE_VETO = "EXPIRY_DAY_CLOSE_VETO"          # expiry day and >= 15:15: HARD NO TRADE
EXPIRY_TRANSITION_ZONE = "EXPIRY_TRANSITION_ZONE"        # expiry day 15:14-15:15: research only
MODE_B_RESEARCH_ONLY = "MODE_B_RESEARCH_ONLY"            # v1: Mode B never trades
INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"            # not enough prior HR days for causal thresholds
POSITION_OPEN = "POSITION_OPEN"                          # policy: one position at a time
DAILY_LIMIT_REACHED = "DAILY_LIMIT_REACHED"              # policy: trade count or daily loss cap

NO_TRADE_REASONS = (
    NO_EVENT_REASON, WEAK_MOMENTUM, NO_CONFIRMATION, SPREAD_TOO_WIDE, LOW_LIQUIDITY, OPTION_NOT_RESPONDING,
    MOVE_ALREADY_EXTENDED, RISK_TOO_LARGE, STALE_DATA, EVENT_EXPIRED, TIME_WINDOW_CLOSED,
    EXPIRY_DAY_CLOSE_VETO, EXPIRY_TRANSITION_ZONE, MODE_B_RESEARCH_ONLY, INSUFFICIENT_HISTORY,
    POSITION_OPEN, DAILY_LIMIT_REACHED,
)

# ---- exit reasons ---------------------------------------------------------
EXIT_STOP = "STOP_LOSS"
EXIT_TRAIL = "TRAIL_STOP"
EXIT_TARGET = "TARGET"
EXIT_MOMENTUM_FAILURE = "MOMENTUM_FAILURE"              # no favourable progress in time
EXIT_MOMENTUM_FADE = "MOMENTUM_FADE"                    # peak gain given back
EXIT_UNDERLYING_INVALIDATION = "UNDERLYING_INVALIDATION"  # futures crossed the event origin
EXIT_EVENT_INVALIDATED = "EVENT_INVALIDATED"            # futures retraced most of the displacement
EXIT_FUTURES_DIVERGENCE = "FUTURES_DIVERGENCE"          # futures favourable, option not
EXIT_SPREAD_EXPANSION = "SPREAD_EXPANSION"
EXIT_STALE_DATA = "STALE_DATA_EXIT"
EXIT_TIME = "TIME_EXIT"
EXIT_EXPIRY_ZONE = "EXPIRY_ZONE_EXIT"
EXIT_SESSION_END = "SESSION_END"
EXIT_NO_DATA = "NO_EXIT_DATA"

MOMENTUM_FAILURE_EXITS = (EXIT_MOMENTUM_FAILURE, EXIT_MOMENTUM_FADE, EXIT_UNDERLYING_INVALIDATION,
                          EXIT_EVENT_INVALIDATED, EXIT_FUTURES_DIVERGENCE, EXIT_SPREAD_EXPANSION)
