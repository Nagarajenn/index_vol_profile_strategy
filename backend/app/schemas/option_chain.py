from pydantic import BaseModel


class OptionChainSummaryDTO(BaseModel):
    pcr: float | None
    atm_strike: float | None
    atm_iv_call: float | None
    atm_iv_put: float | None
