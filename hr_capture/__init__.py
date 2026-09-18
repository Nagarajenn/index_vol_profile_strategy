"""HR-1: High-Resolution Option Intelligence Capture.

DATA CAPTURE, DATA QUALITY AND MARKET-STATE FOUNDATION ONLY.

This package is deliberately isolated from the rest of the platform:

* it runs as its own process (scripts/run_hr_capture.py), with its own
  WebSocket connection and its own database connection;
* it writes only to ``hr_*`` tables;
* it never imports ``paper_trading``, ``pipeline.live_loop``,
  ``pipeline.run_snapshot`` or ``dhan_client``, and nothing in the existing
  platform imports it (enforced by tests/test_hr_isolation.py);
* it makes no Dhan REST calls and contains no order functionality of any kind.

Nothing here produces, scores or executes a trade. The option-implied spot
in ``chain_state`` is an observational RESEARCH ONLY metric.
"""
