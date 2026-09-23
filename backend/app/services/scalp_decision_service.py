import asyncio
from datetime import date, datetime, time, timedelta

from app.core.config import settings
from app.exceptions import NoDataAvailableError, SymbolNotFoundError
from app.repositories.option_risk_repository import OptionRiskRepository
from app.repositories.scalp_decision_repository import ScalpDecisionRepository
from app.schemas.scalp_decision import ScalpDecisionDTO, SimPositionHistoryDTO
from config.instruments import INSTRUMENTS
from option_risk_12b.engine import prepare
from position_sim_12c.config import DEFAULT as SIM_CFG
from position_sim_12c.history import to_row
from position_sim_12c.simulator import close_out, simulate
from scalp_decision_12c.config import DEFAULT as DECISION_CFG
from scalp_decision_12c.engine import decide_at, decide_prepared
from scalp_decision_12c.loader import LEVELS_COLUMNS


# A full-session replay costs a few seconds, so it is cached per minute: the result can only
# change when a new minute of data arrives. Keyed by (symbol, session_date, as_of minute).
_REPLAY_CACHE: dict[tuple, list[dict]] = {}
_REPLAY_CACHE_MAX = 8


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
        snap_dicts = [dict(fetched_at=s.fetched_at.astimezone(settings.ist), spot=s.spot, expiry=s.expiry,
                           payload=s.raw_payload) for s in snaps]
        candle_dicts = [dict(timestamp=c.timestamp.astimezone(settings.ist), open=c.open, high=c.high, low=c.low,
                             close=c.close, volume=c.volume) for c in candles]
        result = decide_at(symbol, session_date, snap_dicts, candle_dicts, levels=levels, position=position,
                           as_of=as_of)
        sim = await self._simulation(symbol, session_date, snap_dicts, candle_dicts, start, cutoff,
                                     result.get("minute"))
        entry = result.get("entry") or {}
        passthrough = {k: v for k, v in result.items() if k in ScalpDecisionDTO.model_fields
                       and k not in ("decision", "confirmation", "reason", "is_live_session", "position_source")}
        return ScalpDecisionDTO(is_live_session=live, position_source=source, position_simulation=sim,
                                decision=entry.get("decision", result.get("decision")),
                                confirmation=entry.get("confirmation", result.get("confirmation")),
                                reason=entry.get("reason", result.get("reason")), **passthrough)

    async def get_history(self, symbol: str, session_date: date | None = None, limit: int = 200) -> SimPositionHistoryDTO:
        """Closed hypothetical positions for the session. Stored rows win; a session that has not
        been stored yet is replayed on the fly so the history is never blank during the day."""
        if symbol not in INSTRUMENTS:
            raise SymbolNotFoundError(symbol)
        now = datetime.now(settings.ist)
        if session_date is None:
            latest = await self._option_repo.latest_session_date(symbol)
            session_date = (now.date() if latest and latest >= now.date() else latest) or now.date()
        rows = await self._levels_repo.simulated_positions(symbol, session_date, limit)
        source = "STORED"
        if not rows:
            key = (symbol, session_date, now.strftime("%H:%M") if session_date == now.date() else "final")
            if key not in _REPLAY_CACHE:
                if len(_REPLAY_CACHE) >= _REPLAY_CACHE_MAX:
                    _REPLAY_CACHE.clear()
                # off the event loop: this is seconds of CPU work and the decision endpoint
                # is being polled at the same time
                _REPLAY_CACHE[key] = await self._replay_session(symbol, session_date, now)
            rows, source = _REPLAY_CACHE[key], "LIVE_REPLAY"
        pnl = [r["realised_pnl"] for r in rows if r.get("realised_pnl") is not None]
        by_reason: dict[str, int] = {}
        for r in rows:
            by_reason[r.get("exit_reason") or "OPEN"] = by_reason.get(r.get("exit_reason") or "OPEN", 0) + 1
        summary = dict(positions=len(rows), priced=len(pnl), wins=sum(1 for x in pnl if x > 0),
                       losses=sum(1 for x in pnl if x <= 0), gross=round(sum(pnl), 2) if pnl else None,
                       best=round(max(pnl), 2) if pnl else None, worst=round(min(pnl), 2) if pnl else None,
                       closed_by=by_reason)
        return SimPositionHistoryDTO(symbol=symbol, session_date=str(session_date), source=source,
                                     positions=[{k: (str(v) if hasattr(v, "isoformat") else v) for k, v in r.items()}
                                                for r in rows], summary=summary)

    async def _replay_session(self, symbol, session_date, now) -> list[dict]:
        """Replay the session's decisions and return its closed positions as storable rows."""
        start = datetime.combine(session_date, time(9, 0), tzinfo=settings.ist)
        end = datetime.combine(session_date, time(15, 31), tzinfo=settings.ist)
        snaps = await self._option_repo.list_snapshots(symbol, start, end)
        if not snaps:
            return []
        candles = await self._option_repo.list_candles(symbol, start, end)
        snap_dicts = [dict(fetched_at=s.fetched_at.astimezone(settings.ist), spot=s.spot, expiry=s.expiry,
                           payload=s.raw_payload) for s in snaps]
        candle_dicts = [dict(timestamp=c.timestamp.astimezone(settings.ist), open=c.open, high=c.high, low=c.low,
                             close=c.close, volume=c.volume) for c in candles]
        as_of = now.strftime("%H:%M") if session_date == now.date() else "15:30"
        levels = await self._levels_by_minute(symbol, start, end)
        sim = await asyncio.to_thread(self._simulate_sync, symbol, session_date, snap_dicts, candle_dicts,
                                      levels, as_of)
        if not sim:
            return []
        if session_date != now.date():          # a finished session carries nothing overnight
            series, _ = prepare(snap_dicts, candle_dicts)
            sim = close_out(sim, series, "15:30", SIM_CFG)
        return [to_row(p, session_date, DECISION_CFG.config_hash(), SIM_CFG) for p in sim["closed_positions"]
                if p.get("exit_minute")]

    async def _levels_by_minute(self, symbol, start, cutoff) -> dict:
        out = {}
        for row in await self._levels_repo.levels_between(symbol, start, cutoff):
            m = row.as_of.astimezone(settings.ist).strftime("%H:%M")
            out[m] = {c: getattr(row, c, None) for c in LEVELS_COLUMNS} | {"as_of": m}
        return out

    @staticmethod
    def _simulate_sync(symbol, session_date, snap_dicts, candle_dicts, levels_by_minute, as_of):
        """Pure CPU work, safe to run in a worker thread: replay the decisions, then simulate."""
        series, cmap = prepare(snap_dicts, candle_dicts)
        rows, lv = [], None
        for m in sorted(x for x in series if x <= as_of):
            lv = levels_by_minute.get(m, lv)
            out = decide_prepared(symbol, session_date, series, cmap, lv, minute=m)
            if out["status"] == "OK":
                rows.append(dict(minute=m, decision=out["entry"]["decision"], confirmation=out["entry"]["confirmation"],
                                 reason=out["entry"]["reason"], atm=out["option_state"]["atm_strike"],
                                 evidence=out["evidence"]))
        return simulate(symbol, series, rows, SIM_CFG, as_of=as_of) if rows else None

    async def _simulation(self, symbol, session_date, snap_dicts, candle_dicts, start, cutoff, as_of):
        """The hypothetical position view for the window: replays the SAME 12C decisions minute by
        minute (each one causal, with the levels row published by that minute) and hands them to the
        simulator. Observability only -- it places nothing and writes nothing."""
        if not as_of:
            return None
        levels = await self._levels_by_minute(symbol, start, cutoff)
        return self._simulate_sync(symbol, session_date, snap_dicts, candle_dicts, levels, as_of)

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
