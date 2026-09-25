"""13A-live-scalping-engine -- a SELECTIVE decision layer for buy-only option scalping.

Why this exists
---------------
12E showed the existing signal is not failing because options respond badly (median response
efficiency ~1.0) or because the exit is wrong (no holding rule rescues it). It fires almost
entirely in RANGE conditions -- 211 of 241 historical PE signals -- where there is no trend to
capture, and the ASK-to-BID round trip then consumes 84% of the gross result.

13A therefore does not try to predict better. It tries to TRADE LESS, and to be explicit about
why each trade was refused.

What it is
----------
Decision support. It produces BUY CE / BUY PE / WAIT with a full audit trail, simulates one
hypothetical position at a time, and enforces a risk brake. The trader decides whether to act.

What it is not
--------------
It places no order. It contains no broker call. It introduces no machine learning, sells no
options, and does not modify 11D, 12A, 12B, 12C, 12D or 12E -- all of which remain available
unchanged for comparison.
"""

VERSION = "13A-live-scalping-engine-v1"

RESEARCH, PAPER, LIVE_DECISION_SUPPORT = "RESEARCH", "PAPER", "LIVE_DECISION_SUPPORT"
MODES = (RESEARCH, PAPER, LIVE_DECISION_SUPPORT)
