from datetime import date, datetime, time, timedelta

from app.core.config import settings
from app.exceptions import NoDataAvailableError, SymbolNotFoundError
from app.repositories.option_risk_repository import OptionRiskRepository
from app.repositories.scalp_decision_repository import ScalpDecisionRepository
from app.schemas.scalp_decision import ScalpDecisionDTO
from config.instruments import INSTRUMENTS
from scalp_decision_12c.engine import decide_at
from scalp_decision_12c.loader import LEVELS_COLUMNS


class ScalpDecisionService:
    """Builds the 12C scalping decision + risk brake fresh on every request from data the
    platform already stores. Read-only and advisory: it writes nothing, places no order and
    cannot open or close a position. The 11D exit engine remains authoritative."""

    def __init__(self, option_repo: OptionRiskRepository, levels_repo: ScalpDecisionRepository) -> None:
        self._option_repo = option_repo
        self._levels_repo = levels_repo

    async def get_decision(self, symbol: str, session_date: date | None = None, position_type: str | None = None,
                           strike: float | None = None) -> ScalpDecisionDTO:
        if symbol not in INSTRUMENTS:
            raise SymbolNotFoundError(symbol)
        now = datetime.now(settings.ist)
        if session_date is None:
            latest = await self._option_repo.latest_session_date(symbol)
            if latest is None:
                raise NoDataAvailableError(symbol)
            session_date = now.date() if latest >= now.date() else latest
        # Only the last ~45 minutes are needed: 20 minutes of context for the decision, plus the
        # 15:15-15:30 closing strip. Parsing a whole day of snapshots per request would be wasteful.
        end = datetime.combine(session_date, time(15, 41), tzinfo=settings.ist)
        target = min(now, end) if session_date == now.date() else datetime.combine(session_date, time(15, 30), tzinfo=settings.ist)
        start = max(datetime.combine(session_date, time(9, 0), tzinfo=settings.ist), target - timedelta(minutes=45))
        snaps = await self._option_repo.list_snapshots(symbol, start, end)
        if not snaps:
            raise NoDataAvailableError(symbol)
        candles = await self._option_repo.list_candles(symbol, start, end)
        live = session_date == now.date()
        as_of = now.strftime("%H:%M") if live else "15:30"   # historical view stops at the session window
        cutoff = min(now, end) if live else end
        levels_row = await self._levels_repo.levels_at_or_before(symbol, cutoff)
        levels = {c: getattr(levels_row, c, None) for c in LEVELS_COLUMNS} if levels_row else None
        if levels is not None:
            levels["as_of"] = levels_row.as_of.astimezone(settings.ist).strftime("%H:%M")
        position, source = await self._position(symbol, session_date, position_type, strike)
        result = decide_at(
            symbol, session_date,
            [dict(fetched_at=s.fetched_at.astimezone(settings.ist), spot=s.spot, expiry=s.expiry, payload=s.raw_payload)
             for s in snaps],
            [dict(timestamp=c.timestamp.astimezone(settings.ist), open=c.open, high=c.high, low=c.low, close=c.close,
                  volume=c.volume) for c in candles],
            levels=levels, position=position, as_of=as_of)
        entry = result.get("entry") or {}
        passthrough = {k: v for k, v in result.items() if k in ScalpDecisionDTO.model_fields
                       and k not in ("decision", "confirmation", "reason", "is_live_session", "position_source")}
        return ScalpDecisionDTO(is_live_session=live, position_source=source,
                                decision=entry.get("decision", result.get("decision")),
                                confirmation=entry.get("confirmation", result.get("confirmation")),
                                reason=entry.get("reason", result.get("reason")), **passthrough)

    async def _position(self, symbol, session_date, position_type, strike):
        """An open paper position wins; otherwise the caller may describe the position they hold,
        which gives a read-only "what would the brake say" view -- it still cannot act."""
        for p in await self._option_repo.list_positions(symbol, session_date):
            if p.is_open:
                return (dict(option_type=p.option_type, strike=float(p.strike), entry_spread_pct=p.entry_spread_pct,
                             entry_minute=p.entry_timestamp.astimezone(settings.ist).strftime("%H:%M"),
                             label=f"PAPER BUY {symbol} {p.option_type} {p.strike:g}"), "PAPER_POSITION")
        if position_type in ("CE", "PE") and strike:
            return (dict(option_type=position_type, strike=float(strike),
                         label=f"BUY {symbol} {position_type} {strike:g} (entered by hand)"), "USER_SUPPLIED")
        return None, None
