from datetime import date, datetime, time, timedelta

from app.core.config import settings
from app.exceptions import NoDataAvailableError, SymbolNotFoundError
from app.repositories.option_risk_repository import OptionRiskRepository
from app.schemas.option_risk import OptionRiskClosingStateDTO
from config.instruments import INSTRUMENTS
from option_risk_12b.engine import build_session


class OptionRiskService:
    """Computes the 12B option risk & closing-state view fresh on every request
    from EXISTING 1-minute option-chain snapshots. Read-only: no writes, no new
    tables, no orders. Risk states are advisory -- the 11D exit engine remains
    authoritative and nothing here can open or close a position."""

    def __init__(self, repo: OptionRiskRepository) -> None:
        self._repo = repo

    async def get_closing_state(self, symbol: str, session_date: date | None = None) -> OptionRiskClosingStateDTO:
        if symbol not in INSTRUMENTS:
            raise SymbolNotFoundError(symbol)
        now = datetime.now(settings.ist)
        if session_date is None:
            latest = await self._repo.latest_session_date(symbol)
            if latest is None:
                raise NoDataAvailableError(symbol)
            latest = latest if isinstance(latest, date) else latest.date()
            session_date = now.date() if latest >= now.date() else latest
        start = datetime.combine(session_date, time(14, 25), tzinfo=settings.ist)   # the LTP chart starts at 14:30
        end = datetime.combine(session_date, time(15, 41), tzinfo=settings.ist)
        snaps = await self._repo.list_snapshots(symbol, start, end)
        candles = await self._repo.list_candles(symbol, start, end)
        positions = await self._repo.list_positions(symbol, session_date)
        live = session_date == now.date()
        as_of = now.strftime("%H:%M") if live else None
        result = build_session(
            symbol, session_date,
            [dict(fetched_at=s.fetched_at.astimezone(settings.ist), spot=s.spot, expiry=s.expiry, payload=s.raw_payload) for s in snaps],
            [dict(timestamp=c.timestamp.astimezone(settings.ist), open=c.open, high=c.high, low=c.low, close=c.close, volume=c.volume)
             for c in candles],
            positions=[self._position(p) for p in positions],
            as_of=as_of,
        )
        return OptionRiskClosingStateDTO(is_live_session=live, **{k: result[k] for k in (
            "version", "config_hash", "symbol", "session_date", "as_of", "advisory_only", "caveat", "positions", "minutes",
            "ltp_series", "summary")})

    @staticmethod
    def _position(p) -> dict:
        ist = settings.ist
        return dict(option_type=p.option_type, strike=float(p.strike), entry_minute=p.entry_timestamp.astimezone(ist).strftime("%H:%M"),
                    exit_minute=p.exit_timestamp.astimezone(ist).strftime("%H:%M") if p.exit_timestamp else None,
                    entry_spread_pct=p.entry_spread_pct, is_open=bool(p.is_open), entry_price=p.entry_price,
                    label=f"PAPER BUY {p.symbol} {p.option_type} {p.strike:g}")
