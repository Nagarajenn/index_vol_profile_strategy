"""13-live-trading-v1 -- the ONLY package in this project permitted to reach a broker's
order API.

Everything else (paper_trading/, scalp_decision_12c/, option_risk_12b/, position_sim_12c/,
scalp12a/, the FastAPI backend) is structurally sealed against order placement, and
tests assert that seal. This package is the single, deliberate exception.

Safety posture:
  * DRY_RUN defaults to True in source. Turning it off is a deliberate act by the trader.
  * live_trading.broker is the only module that may call dhanhq order methods.
  * Every order intent -- placed, refused or failed -- is journalled before anything else.
  * Hard caps live in guards.py as code, not configuration.
"""

VERSION = "13-live-trading-v1"
