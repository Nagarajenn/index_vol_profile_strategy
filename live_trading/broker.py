"""The ONLY module in this project permitted to call a broker's order API.

Every other package is structurally sealed against order placement and tests assert that
seal; tests/test_live_trading_isolation.py asserts that this file is the single exception.

Safety posture:
  * `dry_run` defaults to True. A caller that forgets to decide gets a simulation.
  * The request dict is built and returned even in dry run, so the journal records exactly
    what WOULD have been sent, field for field.
  * Nothing here decides anything. It receives an already-guarded order and sends it.
"""

from dataclasses import dataclass

from live_trading.config import DEFAULT, DRY_RUN_DEFAULT
from live_trading.contracts import Contract


@dataclass(frozen=True)
class OrderRequest:
    security_id: str
    exchange_segment: str
    transaction_type: str
    quantity: int
    order_type: str
    product_type: str
    price: float
    tag: str

    def as_dict(self) -> dict:
        return dict(security_id=self.security_id, exchange_segment=self.exchange_segment,
                    transaction_type=self.transaction_type, quantity=self.quantity,
                    order_type=self.order_type, product_type=self.product_type,
                    price=self.price, tag=self.tag)


def build_entry(contract: Contract, limit: float, correlation_id: str, lots: int = 1, cfg=DEFAULT) -> OrderRequest:
    """A BUY entry. Quantity is lots x the scrip master's lot size -- never a free-form number."""
    return OrderRequest(security_id=contract.security_id, exchange_segment=contract.exchange_segment,
                        transaction_type="BUY", quantity=contract.lot_size * lots,
                        order_type=cfg.order_type, product_type=cfg.product_type,
                        price=float(limit), tag=correlation_id[:24])


def build_exit(contract: Contract, quantity: int, limit: float, correlation_id: str, cfg=DEFAULT) -> OrderRequest:
    """A SELL to flatten. Used by the trader's EXIT NOW and by the 15:10 force-flat."""
    return OrderRequest(security_id=contract.security_id, exchange_segment=contract.exchange_segment,
                        transaction_type="SELL", quantity=int(quantity),
                        order_type=cfg.order_type, product_type=cfg.product_type,
                        price=float(limit), tag=(correlation_id + ":X")[:24])


def send(req: OrderRequest, dry_run: bool = DRY_RUN_DEFAULT) -> dict:
    """Place the order, or simulate it.

    Returns a response dict that always carries `dry_run` and `status`, so a caller can
    journal a dry run and a real send through exactly the same path."""
    if dry_run:
        return dict(dry_run=True, status="DRY_RUN", note="not sent: dry run", request=req.as_dict())

    # Imported here, not at module import time: nothing loads a broker client just by
    # importing this module, so a dry-run process never constructs one.
    from dhan_client.client import get_client

    client = get_client()
    resp = client.place_order(**req.as_dict())
    return dict(dry_run=False, status=_status_of(resp), raw=resp, request=req.as_dict())


def _status_of(resp) -> str:
    if not isinstance(resp, dict):
        return "ERROR"
    if str(resp.get("status", "")).lower() in ("success", "ok"):
        return "SENT"
    return "REJECTED"


def order_id_of(resp: dict) -> str | None:
    raw = (resp or {}).get("raw") or {}
    data = raw.get("data") if isinstance(raw, dict) else None
    for src in (data, raw):
        if isinstance(src, dict):
            for k in ("orderId", "order_id", "orderid"):
                if src.get(k):
                    return str(src[k])
    return None
