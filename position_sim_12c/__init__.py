"""12C-position-simulation-v1 -- hypothetical (paper) position view for 12C signals.

OBSERVABILITY ONLY. It answers: "if I had taken this signal when it appeared, what would
the position be doing now?" It never places, modifies or cancels an order, never touches a
real or paper account, and never changes a 12C decision: the decision stream is consumed
read-only. 11D, 12A, 12B and the 12C decision logic are untouched.
"""

VERSION = "12C-position-simulation-v1"
