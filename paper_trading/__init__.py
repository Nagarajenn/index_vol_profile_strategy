"""Paper Trading Agent (Milestone 11D) -- a fully simulated, instrumented
research experiment. It NEVER places a real order.

Architecture:
    existing analytics  ->  paper decision layer  ->  paper execution
    simulator  ->  paper journal  ->  command center UI

No module in this package imports the broker client, and
paper_trading.safety enforces that structurally by scanning this
package's own source for forbidden call fragments (see
scan_package_for_real_order_calls, asserted by tests/test_paper_safety.py).
"""
