from fastapi import APIRouter
from pydantic import BaseModel

from config.instruments import INSTRUMENTS

router = APIRouter()


class SymbolInfoDTO(BaseModel):
    symbol: str
    exchange: str


@router.get("/symbols", response_model=list[SymbolInfoDTO])
async def list_symbols() -> list[SymbolInfoDTO]:
    # Static config, not the database -- no repository here (see backend/README's
    # Repository/Service rule: don't wrap static config in a fake repository).
    return [SymbolInfoDTO(symbol=key, exchange=meta["exchange"]) for key, meta in INSTRUMENTS.items()]
