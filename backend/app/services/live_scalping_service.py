import asyncio
from datetime import date, datetime, time, timedelta

from app.core.config import settings
from app.exceptions import NoDataAvailableError, SymbolNotFoundError
from app.repositories.option_risk_repository import OptionRiskRepository
from app.repositories.scalp_decision_repository import ScalpDecisionRepository
from app.schemas.live_scalping import LiveScalpingDTO
from config.instruments import INSTRUMENTS
from live_scalping_13a import engine as EN
from live_scalping_13a import replay as RP
from live_scalping_13a import risk_brake as RB
from live_scalping_13a.config import DEFAULT as CFG
from live_scalping_13a.config import LIVE_DECISION_SUPPORT_NOTE
from price_action_13b import decide as PA13B
from price_action_13b.config import DEFAULT as PA_CFG
from scalp_decision_12c.loader import LEVELS_COLUMNS

# A full-session 13A replay costs a few seconds. It can only change when a new minute of data
# arrives, so it is cached per minute -- the same pattern the 12C history endpoint uses.
_CACHE: dict[tuple, dict] = {}
_CACHE_MAX = 8


class LiveScalpingService:
    """13A-live-scalping-engine, served read-only.

    LIVE DECISION SUPPORT: live market data, real-time gates, a hypothetical position and the
    risk brake. It places no order and there is no broker path anywhere in this service or in
    the package behind it. The trader decides whether to act.
    """

    def __init__(self, option_repo: OptionRiskRepository, levels_repo: ScalpDecisionRepository) -> None:
        self._option_repo = option_repo
        self._levels_repo = levels_repo

    async def get_panel(self, symbol: str, session_date: date | None = None) -> LiveScalpingDTO:
        if symbol not in INSTRUMENTS:
            raise SymbolNotFoundError(symbol)
        now = datetime.now(settings.ist)
        if session_date is None:
            latest = await self._option_repo.latest_session_date(symbol)
            if latest is None:
                raise NoDataAvailableError(symbol)
            session_date = now.date() if latest >= now.date() else latest
        live = session_date == now.date()

        key = (symbol, session_date, now.strftime("%H:%M") if live else "final")
        if key not in _CACHE:
            if len(_CACHE) >= _CACHE_MAX:
                _CACHE.clear()
            _CACHE[key] = await self._replay(symbol, session_date, now, live)
        state = _CACHE[key]
        if state is None:
            raise NoDataAvailableError(symbol)

        return LiveScalpingDTO(
            version=state["version"], config_hash=state["config_hash"], mode="LIVE_DECISION_SUPPORT",
            symbol=symbol, session_date=str(session_date), is_live_session=live,
            minute=state["minute"], decision=state["decision"], quality=state["quality"],
            primary_rejection_reason=state["primary_rejection_reason"],
            reason_note=state["reason_note"], panel=state["panel"], risk=state["risk"],
            open_position=state["open_position"], closed_positions=state["closed_positions"],
            price_action=state.get("price_action"),
            daily_review=state["daily_review"], config=CFG.to_json(),
            notice=LIVE_DECISION_SUPPORT_NOTE,
        )

    async def _replay(self, symbol, session_date, now, live) -> dict | None:
        start = datetime.combine(session_date, time(9, 0), tzinfo=settings.ist)
        end = datetime.combine(session_date, time(15, 41), tzinfo=settings.ist)
        snaps = await self._option_repo.list_snapshots(symbol, start, end)
        if not snaps:
            return None
        candles = await self._option_repo.list_candles(symbol, start, end)
        snap_dicts = [dict(fetched_at=s.fetched_at.astimezone(settings.ist), spot=s.spot,
                           expiry=s.expiry, payload=s.raw_payload) for s in snaps]
        candle_dicts = [dict(timestamp=c.timestamp.astimezone(settings.ist), open=c.open, high=c.high,
                             low=c.low, close=c.close, volume=c.volume) for c in candles]
        levels = {}
        for row in await self._levels_repo.levels_between(symbol, start, end):
            m = row.as_of.astimezone(settings.ist).strftime("%H:%M")
            levels[m] = {c: getattr(row, c, None) for c in LEVELS_COLUMNS} | {"as_of": m}
        as_of = now.strftime("%H:%M") if live else "15:30"
        return await asyncio.to_thread(_run_sync, symbol, session_date, snap_dicts, candle_dicts,
                                       levels, as_of)


def _run_sync(symbol, session_date, snaps, candles, levels, as_of) -> dict | None:
    """Pure CPU: replay the session under 13A and return the panel for the latest minute."""
    from option_risk_12b.engine import prepare
    from live_scalping_13a import analysis, position as POS
    from live_scalping_13a.config import BUY_CE, BUY_PE
    from position_sim_12c.lots import lot_size

    series, cmap = prepare(snaps, candles)
    base = RP.base_decisions(symbol, session_date, series, cmap, levels)
    base = [b for b in base if b["minute"] <= as_of]
    if not base:
        return None

    risk = RB.RiskState()
    decisions, closed, open_pos, last_out = [], [], None, None
    for row in base:
        m, strike = row["minute"], row["atm"]
        expiry = series[m].get("expiry") if m in series else None
        qty, _ = lot_size(symbol, expiry) if expiry else (None, "")
        if open_pos is not None:
            card = open_pos.mark(series, m)
            if card.get("priced") and card["stop_breached"]:
                open_pos.close(series, m, "STOP_LOSS")
            elif row["decision"] in (BUY_CE, BUY_PE) and row["decision"][-2:] != open_pos.side:
                open_pos.close(series, m, "SIGNAL_FLIP")
            if open_pos.status == POS.CLOSED:
                if open_pos.realised_pnl is not None:
                    risk.record_close(open_pos.realised_pnl)
                closed.append(open_pos.to_dict())
                open_pos = None
        out = EN.decide(series, m, row["decision"], row["confirmation"], strike, risk,
                        position_open=open_pos is not None, quantity=qty, cfg=CFG)
        decisions.append(EN.audit_row(out))
        last_out = out
        if out["decision"] in (BUY_CE, BUY_PE) and open_pos is None:
            open_pos = POS.open_position(series, m, symbol, session_date, out["side"], strike,
                                         qty, out["quality"], CFG)

    card = None
    if open_pos is not None:
        risk.unrealised_pnl = 0.0
        card = open_pos.mark(series, max(m for m in series if m <= as_of))
        if card.get("priced"):
            risk.unrealised_pnl = card["pnl"]
            risk.open_position_value = open_pos.entry_value
        card = {**card, **open_pos.to_dict()}

    rej = {}
    for d in decisions:
        r = d.get("primary_rejection_reason")
        if r:
            rej[r] = rej.get(r, 0) + 1

    # 13B price-action confirmation for the minute being shown. Read-only over 13A's output:
    # it can veto a BUY, never create one.
    last_minute = last_out["minute"]
    last_levels = None
    for mm in sorted(levels):
        if mm <= last_minute:
            last_levels = levels[mm]
    # A confirmation verdict only makes sense against a proposed side. When there is no
    # candidate the structural read (structure, VWAP, value, volume) is still shown as context
    # and flagged `is_candidate=False`, so the section does not vanish for most of the session.
    base = last_out.get("base_decision")
    side = last_out.get("side") or (base[-2:] if base in ("BUY_CE", "BUY_PE") else None)
    pa = None
    if side:
        pa = PA13B.evaluate(cmap, last_minute, side, last_levels, PA_CFG)
        applied = PA13B.apply(last_out["decision"], pa, PA_CFG)
        pa = {**pa, **applied, "is_candidate": last_out["decision"] in ("BUY_CE", "BUY_PE")}
    else:
        pa = PA13B.evaluate(cmap, last_minute, "CE", last_levels, PA_CFG)
        pa = {**pa, "is_candidate": False, "price_action_block": False,
              "final_decision": last_out["decision"], "applies_to": None,
              "reason": "No BUY candidate this minute -- the structural read is shown as context only."}

    f = (last_out.get("features") or {})
    checks = last_out.get("checks") or {}
    panel = dict(
        market=symbol, underlying=f.get("underlying"),
        regime=(last_out.get("regime") or {}).get("state"),
        regime_note=(last_out.get("regime") or {}).get("note"),
        direction_note=(checks.get("underlying") or {}).get("note"),
        underlying_confirmed=(checks.get("underlying") or {}).get("ok"),
        und_1m=f.get("und_pre_1m"), und_3m=f.get("und_pre_3m"), und_5m=f.get("und_pre_5m"),
        option_confirmed=(checks.get("option") or {}).get("ok"),
        option_categories=(checks.get("option") or {}).get("categories") or [],
        option_note=(checks.get("option") or {}).get("note"),
        entry_timing=(last_out.get("timing") or {}).get("state"),
        entry_timing_note=(last_out.get("timing") or {}).get("note"),
        iv_state=(last_out.get("iv") or {}).get("state"),
        iv_change_pct=(last_out.get("iv") or {}).get("change_pct"),
        spread=f.get("spread"), spread_pct=(checks.get("spread") or {}).get("spread_pct"),
        spread_ok=(checks.get("spread") or {}).get("ok"),
        economics_ratio=(last_out.get("economics") or {}).get("ratio"),
        economics_note=(last_out.get("economics") or {}).get("note"),
        economics_ok=(checks.get("economics") or {}).get("ok"),
        contract=f"{symbol} {f.get('strike'):g} {last_out.get('side')}" if f.get("strike") else None,
        strike=f.get("strike"), bid=f.get("bid"), ask=f.get("ask"), ltp=f.get("ltp"),
        delta=f.get("delta"), iv=f.get("iv"), theta=f.get("theta"),
        quantity=last_out.get("quantity"), entry_value=last_out.get("entry_value"),
    )
    return dict(version=last_out["version"], config_hash=last_out["config_hash"],
                minute=last_out["minute"], decision=last_out["decision"],
                quality=last_out["quality"],
                primary_rejection_reason=last_out["primary_rejection_reason"],
                reason_note=last_out.get("reason_note"), panel=panel,
                risk=RB.evaluate(risk, CFG), open_position=card, closed_positions=closed,
                price_action=pa,
                daily_review=analysis.daily_review(decisions, closed, rej))
