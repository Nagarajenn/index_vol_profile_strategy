"""Pre-entry risk: every number is fixed BEFORE the hypothetical entry.

Maximum rupee loss, maximum premium loss (stop), underlying invalidation
level and maximum holding duration. The stop can only tighten afterwards
(enforced in exits.py).
"""

import math

from scalp_12a.config import ScalpConfig
from scalp_12a.models import Event, RiskPlan, Selection
from scalp_12a.taxonomy import RISK_TOO_LARGE, SPREAD_TOO_WIDE


def plan_risk(event: Event, selection: Selection, config: ScalpConfig) -> RiskPlan | None:
    if not selection or not selection.quote or not selection.quote.valid:
        return None
    ask = selection.quote.ask
    reasons: list[str] = []
    stop_pct, target_pct = config.stop_pct, config.target_pct
    stop_price = ask * (1 - stop_pct / 100.0)
    target_price = ask * (1 + target_pct / 100.0)
    per_unit_loss = ask - stop_price
    units_by_risk = math.floor(config.max_rupee_loss_per_trade / per_unit_loss) if per_unit_loss > 0 else 0
    units_by_capital = math.floor(config.max_capital_per_trade / ask)
    lot = max(1, config.lot_size_units)
    quantity = (min(units_by_risk, units_by_capital) // lot) * lot
    if quantity < lot:
        reasons.append(RISK_TOO_LARGE)
    spread_pct = selection.quote.spread_pct or 0.0
    if stop_pct < config.stop_spread_multiple * spread_pct:
        reasons.append(SPREAD_TOO_WIDE)
    rupee_risk = quantity * per_unit_loss
    return RiskPlan(entry_ref_ask=ask, stop_price=stop_price, target_price=target_price, stop_pct=stop_pct,
                    target_pct=target_pct, quantity=quantity, rupee_risk=round(rupee_risk, 2),
                    underlying_invalidation=event.origin_price, max_hold_seconds=config.max_hold_seconds,
                    reasons=reasons)
