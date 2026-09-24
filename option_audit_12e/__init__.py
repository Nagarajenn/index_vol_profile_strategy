"""12E-option-audit-v1 -- why a correct market call can still be a losing option trade.

The question this package exists to answer, stated plainly:

    When the underlying moves the way the signal expected, does the SELECTED CONTRACT at the
    SIGNAL'S ENTRY PRICE actually produce a viable trade?

"Market down" and "BUY PE profitable" are two different claims, and this package refuses to
treat them as one. It separates six things the existing metrics blend together:

    1. underlying direction          did spot go the expected way?
    2. option directional response   did the premium move, and by how much per unit of spot?
    3. option pricing                IV, theta, greeks at entry
    4. execution cost                the ASK-to-BID round trip
    5. timing                        how much of the move happened BEFORE the signal
    6. exit behaviour                what ended the position and what it cost

Diagnosis only. No 12C rule is read for anything but its output, no threshold is changed, no
model is fitted, and nothing here places an order.
"""

VERSION = "12E-option-audit-v1"
