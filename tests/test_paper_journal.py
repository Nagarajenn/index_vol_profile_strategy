"""Journal persistence tests. These touch the real database using a
sentinel session_date far in the future, and clean up after themselves.
"""

from datetime import date, datetime

import pytest

pytest.importorskip("psycopg")

import config  # noqa: F401 -- truststore bootstrap before any DB call
from db.connection import execute, fetch_all, fetch_one
from paper_trading import journal
from paper_trading.config import DEFAULT_CONFIG as CFG

SENTINEL = date(2099, 12, 31)


@pytest.fixture
def clean_sentinel():
    def _clean():
        execute(
            "DELETE FROM paper_position_events WHERE position_id IN "
            "(SELECT id FROM paper_positions WHERE session_date=%s)", (SENTINEL,))
        execute("DELETE FROM paper_positions WHERE session_date=%s", (SENTINEL,))
        execute("DELETE FROM paper_decisions WHERE session_date=%s", (SENTINEL,))
        execute("DELETE FROM paper_account_snapshots WHERE session_date=%s", (SENTINEL,))
        execute("DELETE FROM paper_sessions WHERE session_date=%s", (SENTINEL,))
    _clean()
    yield
    _clean()


def _decision(decision="NO_TRADE", reason="LOW_CONFIDENCE", confidence=30):
    from tests.test_paper_agent import _decision as base
    d = base()
    d.session_date = SENTINEL
    d.state.session_date = SENTINEL
    d.decision_timestamp = datetime(2099, 12, 31, 14, 59)
    d.decision = decision
    d.no_trade_reason = reason if decision == "NO_TRADE" else None
    d.confidence = confidence
    d.configuration_hash = CFG.config_hash()
    if decision == "NO_TRADE":
        d.candidate = None
        d.risk_plan = None
        d.quantity = None
        d.capital_allocated = None
    return d


def test_no_trade_decisions_are_persisted_too(clean_sentinel):
    """Every decision is journaled, including NO TRADE -- a NO TRADE day
    must remain auditable."""
    did = journal.save_decision(_decision())
    assert did is not None
    row = fetch_one(
        "SELECT decision, no_trade_reason FROM paper_decisions WHERE session_date=%s", (SENTINEL,))
    assert row == ("NO_TRADE", "LOW_CONFIDENCE")


def test_decision_is_immutable_a_second_save_never_overwrites(clean_sentinel):
    """Re-running the agent must not rewrite a frozen 14:59 snapshot."""
    first_id = journal.save_decision(_decision(confidence=30))
    second_id = journal.save_decision(_decision(reason="CONFLICTING_SIGNALS", confidence=99))
    assert first_id == second_id, "a re-save must return the existing row, not create a new one"
    row = fetch_one(
        "SELECT no_trade_reason, confidence FROM paper_decisions WHERE session_date=%s", (SENTINEL,))
    assert row == ("LOW_CONFIDENCE", 30), "the original frozen decision must survive untouched"
    assert fetch_all("SELECT count(*) FROM paper_decisions WHERE session_date=%s", (SENTINEL,))[0][0] == 1


def test_kill_switch_persists_and_releases(clean_sentinel):
    h = CFG.config_hash()
    assert journal.is_kill_switch_active(SENTINEL, h) is False
    journal.set_agent_state(SENTINEL, "RISK_BLOCKED", h, heartbeat=datetime.now(), kill_switch=True)
    assert journal.is_kill_switch_active(SENTINEL, h) is True
    journal.set_agent_state(SENTINEL, "MARKET_MONITORING", h, heartbeat=datetime.now(), kill_switch=False)
    assert journal.is_kill_switch_active(SENTINEL, h) is False


def test_kill_switch_does_not_delete_records(clean_sentinel):
    h = CFG.config_hash()
    journal.save_decision(_decision())
    journal.set_agent_state(SENTINEL, "RISK_BLOCKED", h, heartbeat=datetime.now(), kill_switch=True)
    remaining = fetch_all("SELECT count(*) FROM paper_decisions WHERE session_date=%s", (SENTINEL,))[0][0]
    assert remaining == 1, "the kill switch must never delete journal records"


def test_agent_state_heartbeat_round_trips(clean_sentinel):
    h = CFG.config_hash()
    journal.set_agent_state(SENTINEL, "POSITION_MANAGEMENT", h, heartbeat=datetime.now())
    row = fetch_one(
        "SELECT agent_state FROM paper_sessions WHERE session_date=%s AND configuration_hash=%s", (SENTINEL, h))
    assert row[0] == "POSITION_MANAGEMENT"
