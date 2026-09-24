"""12D-signal-learning-v1 -- observation and learning layer over the EXISTING 12C signal.

What this package is for
------------------------
12C produces BUY CE / BUY PE / WAIT. The hypothetical-position simulator built on it closes a
position the moment the entry decision becomes WAIT, which conflates two different questions:

    "should I open a position now?"      (ENTRY)
    "should I stay in this position?"    (POSITION MANAGEMENT)

12D separates them. It watches every signal 12C emits, records the complete evidence available
AT the signal minute, then follows what happened afterwards -- MFE/MAE at fixed horizons, how the
position would have been managed under an independent position manager, and how the episode ends.

What this package is NOT
------------------------
It does not generate, alter, tune or second-guess a 12C signal. It does not place orders. It
introduces no machine learning. It does not change position_sim_12c: the existing simulator and
its WAIT-closes-the-position behaviour stay exactly as they are, and 12D's own position manager
runs alongside so the two can be compared on the same signals.

Leakage discipline
------------------
Entry-time features are built ONLY from data at or before the signal minute. Future minutes are
used only to score an outcome that has already been decided, never to decide it.
"""

VERSION = "12D-signal-learning-v1"
