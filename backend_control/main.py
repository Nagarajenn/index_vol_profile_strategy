"""Local-only control service for live trading (13-live-trading-v1).

Deliberately SEPARATE from backend/ : that service is read-only by contract
(`allow_methods=["GET"]`, "never writes to the DB") and several milestones depend on that
guarantee. Adding POST there would quietly turn the whole dashboard into a write path.

This app binds to 127.0.0.1 only and exposes exactly five things: status, arm, disarm, kill
switch, and flatten-now. It cannot place an ENTRY -- entries come only from the trader
process after the guards pass. The only order this service can cause is an EXIT, which is
the trader's own EXIT NOW button.

    venv/Scripts/python.exe -m uvicorn backend_control.main:app --host 127.0.0.1 --port 8100
"""

import sys
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.instruments import INSTRUMENTS                              # noqa: E402
from config.settings import IST                                         # noqa: E402
from live_trading import VERSION, journal, runner, state                # noqa: E402
from live_trading.config import (DEFAULT as CFG, DRY_RUN_DEFAULT, MAX_ENTRIES_PER_DAY,   # noqa: E402
                                 MAX_ENTRY_COST_RS, STARTING_CAPITAL_RS, SYMBOL_BY_WEEKDAY)

app = FastAPI(title="Live Trading Control", version=VERSION,
              description="Local-only. Arm/disarm, kill switch and flatten-now for 13-live-trading-v1.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["GET", "POST"], allow_headers=["*"])


def _today() -> date:
    return datetime.now(IST).date()


def _check(symbol: str) -> str:
    s = symbol.upper()
    if s not in INSTRUMENTS:
        raise HTTPException(404, f"unknown symbol {symbol}")
    return s


class ArmRequest(BaseModel):
    confirm: bool = False
    """The UI must send confirm=true explicitly. Arming is never a side effect of loading a page."""


@app.get("/api/control/status")
def status() -> dict:
    d = _today()
    c = state.connect()
    try:
        scheduled = list(SYMBOL_BY_WEEKDAY.get(d.weekday(), ()))
        out = []
        for sym in INSTRUMENTS:
            s = state.session(c, sym, d)
            counters = state.refresh_counters(c, sym, d)
            pos = state.open_position(c, sym, d)
            out.append(dict(symbol=sym, scheduled_today=sym in scheduled, **s, **counters,
                            open_position=dict(pos) if pos else None))
        return dict(session_date=str(d), weekday=d.strftime("%A"), scheduled=scheduled,
                    version=VERSION, config_hash=CFG.config_hash(), dry_run_default=DRY_RUN_DEFAULT,
                    caps=dict(max_entries=MAX_ENTRIES_PER_DAY, lots=1, halt_after_first_loss=True,
                              max_entry_cost=MAX_ENTRY_COST_RS, capital=STARTING_CAPITAL_RS,
                              entry_window=[CFG.entry_window_start, CFG.entry_window_end],
                              min_confirmation=CFG.min_confirmation,
                              min_episode_minutes=CFG.min_episode_minutes,
                              force_flat_at=CFG.force_flat_at),
                    symbols=out, journal=[{**j, "at": j["at"].isoformat()} for j in journal.recent(c, d, 60)])
    finally:
        c.close()


@app.post("/api/control/{symbol}/arm")
def arm(symbol: str, body: ArmRequest) -> dict:
    sym = _check(symbol)
    if not body.confirm:
        raise HTTPException(400, "arming requires an explicit confirmation")
    d = _today()
    if sym not in SYMBOL_BY_WEEKDAY.get(d.weekday(), ()):
        raise HTTPException(409, f"{sym} is not scheduled for {d.strftime('%A')}")
    c = state.connect()
    try:
        state.session(c, sym, d)
        state.set_flags(c, sym, d, armed=True, kill_switch=False)
        journal.log(c, d, "ARMED", "armed from the live trading page", symbol=sym)
        return dict(symbol=sym, armed=True)
    finally:
        c.close()


@app.post("/api/control/{symbol}/disarm")
def disarm(symbol: str) -> dict:
    sym, d = _check(symbol), _today()
    c = state.connect()
    try:
        state.session(c, sym, d)
        state.set_flags(c, sym, d, armed=False)
        journal.log(c, d, "DISARMED", "disarmed from the live trading page", symbol=sym)
        return dict(symbol=sym, armed=False)
    finally:
        c.close()


@app.post("/api/control/{symbol}/kill")
def kill(symbol: str, on: bool = True) -> dict:
    """The kill switch is checked before every order and takes effect on the next tick."""
    sym, d = _check(symbol), _today()
    c = state.connect()
    try:
        state.session(c, sym, d)
        # Killing also disarms: re-enabling must be a deliberate, separate act.
        if on:
            state.set_flags(c, sym, d, kill_switch=True, armed=False)
        else:
            state.set_flags(c, sym, d, kill_switch=False)
        journal.log(c, d, "KILL_SWITCH", f"kill switch {'ON' if on else 'OFF'}", symbol=sym)
        return dict(symbol=sym, kill_switch=on)
    finally:
        c.close()


@app.post("/api/control/{symbol}/flatten")
def flatten(symbol: str, live: bool = False) -> dict:
    """EXIT NOW -- the trader's own exit. `live=false` simulates, matching the trader process's
    own dry-run default, so the button can be rehearsed without sending anything."""
    sym = _check(symbol)
    out = runner.force_flat(sym, dry_run=not live)
    return out
