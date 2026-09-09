"""Paper Trading Command Center service.

Owns every "what does this mean" decision for the UI: agent state,
data-health ages, experiment day counter, and the decision-quality
classification that keeps DIRECTION correctness separate from OPTION
profitability.

Read-only. This service never writes; the paper agent process is the sole
writer to the paper_* tables.
"""

from datetime import date, datetime, timezone

from app.repositories.paper_trading_repository import PaperTradingRepository
from app.schemas.paper_trading import (
    DecisionOutcomeDTO,
    PaperAccountDTO,
    PaperDecisionDTO,
    PaperPositionDTO,
    PaperPositionEventDTO,
    PaperStatusDTO,
    PaperTodayDTO,
)

EXPERIMENT_TOTAL_DAYS = 5
STARTING_CAPITAL = 15_000.0


class PaperTradingService:
    def __init__(self, repo: PaperTradingRepository) -> None:
        self._repo = repo

    # ---------------------------------------------------------- status
    async def get_status(self, session_date: date | None = None) -> PaperStatusDTO:
        from paper_trading.config import CONFIG_VERSION, DEFAULT_CONFIG, STRATEGY_VERSION
        from paper_trading.safety import PAPER_MODE

        target = session_date or date.today()
        session = await self._repo.get_session(target)
        dates = await self._repo.list_session_dates()
        experiment_day = (dates.index(target) + 1) if target in dates else (len(dates) + 1 if dates else 1)

        return PaperStatusDTO(
            paper_mode=PAPER_MODE,
            agent_state=session.agent_state if session else "PRE_MARKET",
            kill_switch_active=bool(session.kill_switch_active) if session else False,
            session_date=target,
            last_heartbeat=session.last_heartbeat if session else None,
            strategy_version=STRATEGY_VERSION,
            configuration_version=CONFIG_VERSION,
            configuration_hash=DEFAULT_CONFIG.config_hash(),
            experiment_day=experiment_day,
            experiment_total_days=EXPERIMENT_TOTAL_DAYS,
        )

    # --------------------------------------------------------- account
    async def get_account(self) -> PaperAccountDTO:
        snapshot = await self._repo.get_latest_account()
        if snapshot is None:
            return PaperAccountDTO(
                starting_capital=STARTING_CAPITAL, current_capital=STARTING_CAPITAL,
                available_capital=STARTING_CAPITAL, capital_in_trade=0.0, realized_pnl=0.0,
                unrealized_pnl=0.0, daily_pnl=0.0, total_pnl=0.0, daily_drawdown=0.0,
                max_drawdown=0.0, max_drawdown_pct=0.0, trade_count=0, win_count=0,
                loss_count=0, consecutive_wins=0, consecutive_losses=0,
            )
        decided = snapshot.win_count + snapshot.loss_count
        return PaperAccountDTO(
            session_date=snapshot.session_date,
            starting_capital=snapshot.starting_capital, current_capital=snapshot.current_capital,
            available_capital=snapshot.available_capital, capital_in_trade=snapshot.capital_in_trade,
            realized_pnl=snapshot.realized_pnl, unrealized_pnl=snapshot.unrealized_pnl,
            daily_pnl=snapshot.daily_pnl, total_pnl=snapshot.total_pnl,
            daily_drawdown=snapshot.daily_drawdown, max_drawdown=snapshot.max_drawdown,
            max_drawdown_pct=round(snapshot.max_drawdown / snapshot.starting_capital * 100, 2)
            if snapshot.starting_capital else 0.0,
            trade_count=snapshot.trade_count, win_count=snapshot.win_count,
            loss_count=snapshot.loss_count,
            win_rate=round(snapshot.win_count / decided, 3) if decided else None,
            consecutive_wins=snapshot.consecutive_wins, consecutive_losses=snapshot.consecutive_losses,
            average_win=snapshot.average_win, average_loss=snapshot.average_loss,
            largest_win=snapshot.largest_win, largest_loss=snapshot.largest_loss,
            profit_factor=snapshot.profit_factor,
        )

    # ------------------------------------------------------- decisions
    async def list_decisions(self, session_date: date | None = None, limit: int = 100) -> list[PaperDecisionDTO]:
        rows = await self._repo.list_decisions(session_date, limit)
        return [self._to_decision_dto(r) for r in rows]

    @staticmethod
    def _to_decision_dto(row) -> PaperDecisionDTO:
        dto = PaperDecisionDTO.model_validate(row)
        dto.supporting_factors = row.supporting_factors or []
        dto.conflicting_factors = row.conflicting_factors or []
        dto.risk_factors = row.risk_factors or []
        dto.explanation = row.explanation or []
        dto.missing_fields = row.missing_fields or []
        return dto

    # -------------------------------------------------------- positions
    async def get_open_position(self) -> PaperPositionDTO | None:
        row = await self._repo.get_open_position()
        return await self._to_position_dto(row) if row else None

    async def list_trades(self, limit: int = 200) -> list[PaperPositionDTO]:
        rows = await self._repo.list_closed_positions(limit)
        return [await self._to_position_dto(r) for r in rows]

    async def _to_position_dto(self, row) -> PaperPositionDTO:
        dto = PaperPositionDTO.model_validate(row)
        events = await self._repo.list_events(row.id)
        dto.events = [PaperPositionEventDTO.model_validate(e) for e in events]
        return dto

    # ----------------------------------------------------------- today
    async def get_today(self, session_date: date | None = None) -> PaperTodayDTO:
        target = session_date or date.today()
        status = await self.get_status(target)
        account = await self.get_account()
        decisions = await self.list_decisions(target)
        open_position = await self.get_open_position()
        positions = await self._repo.list_positions(target)
        closed = [await self._to_position_dto(p) for p in positions if not p.is_open]
        outcomes = self._classify_outcomes(decisions, closed)
        return PaperTodayDTO(
            session_date=target, status=status, account=account, decisions=decisions,
            open_position=open_position, closed_today=closed, outcomes=outcomes,
        )

    # ------------------------------------------------- decision quality
    @staticmethod
    def _classify_outcomes(decisions: list[PaperDecisionDTO], closed: list[PaperPositionDTO]) -> list[DecisionOutcomeDTO]:
        """Keeps the two questions apart on purpose:
             was the DIRECTION right?      (signal quality)
             did the OPTION make money?    (expression quality)
        A right call that lost money is 'direction right / option expression
        poor', not a success -- and a wrong call that happened to profit is
        never counted as evidence of skill."""
        by_symbol = {p.symbol: p for p in closed}
        outcomes: list[DecisionOutcomeDTO] = []
        for d in decisions:
            position = by_symbol.get(d.symbol)
            forecast_direction = (
                "up" if d.decision == "TRADE_CALL" else "down" if d.decision == "TRADE_PUT" else None
            )
            if d.decision == "NO_TRADE":
                quality = "NO TRADE"
                actual_direction = None
                direction_correct = None
                option_profitable = None
                net_pnl = None
            elif position is None:
                quality = "OPEN / PENDING"
                actual_direction = direction_correct = option_profitable = net_pnl = None
            else:
                direction_correct = position.direction_correct
                net_pnl = position.net_pnl
                option_profitable = (net_pnl or 0) > 0
                actual_direction = None
                if position.underlying_move is not None:
                    actual_direction = "up" if position.underlying_move > 0 else "down"
                if direction_correct and option_profitable:
                    quality = "GOOD"
                elif direction_correct and not option_profitable:
                    quality = "DIRECTION RIGHT / OPTION EXPRESSION POOR"
                elif not direction_correct and option_profitable:
                    quality = "PROFITABLE BUT DIRECTION WRONG (not evidence of skill)"
                else:
                    quality = "BAD TRADE"
            outcomes.append(DecisionOutcomeDTO(
                symbol=d.symbol, session_date=d.session_date, decision=d.decision,
                forecast_direction=forecast_direction, actual_direction=actual_direction,
                direction_correct=direction_correct, option_profitable=option_profitable,
                net_pnl=net_pnl, decision_quality=quality,
            ))
        return outcomes
