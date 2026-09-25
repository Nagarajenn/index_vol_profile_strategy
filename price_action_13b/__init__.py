"""13B-price-action-v1 -- does the UNDERLYING actually show a clean scalp setup?

13A asks whether the option economics and market regime justify a trade. It never looks at the
shape of price itself: whether a level broke, whether the break held, whether the move is a
continuation or a rotation inside a range.

13B answers exactly that one question at the 13A candidate minute, and nothing else. It is a
CONFIRMATION LAYER: it can downgrade a 13A BUY to WAIT, and it can never create a BUY that 13A
did not already produce.

Causality rule that governs every feature here
----------------------------------------------
A 1-minute candle stamped 09:30 covers 09:30:00-09:30:59 and is only COMPLETE at 09:31. So at
signal minute m the newest usable bar is the one stamped m-1. Every swing, break, follow-through
and volume reading in this package obeys that, which is why `leakage.audit` can delete every
later bar and get identical answers.

Not here: RSI, MACD, stochastics, or any indicator pile. Four ideas only -- structure, the
break, the context it happens in, and whether volume went with it.
"""

VERSION = "13B-price-action-v1"
