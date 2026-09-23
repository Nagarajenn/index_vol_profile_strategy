"""13-live-trading-v1: caps, qualifiers, contract resolution and package isolation.

These tests are the enforcement mechanism for the trader's risk decisions. If someone
loosens a cap, one of these fails -- that is the point of keeping the caps in code.
"""

from datetime import date, datetime
from pathlib import Path

import pytest

from live_trading import VERSION
from live_trading.broker import build_entry, build_exit, send
from live_trading.config import (DEFAULT, DRY_RUN_DEFAULT, HALT_AFTER_FIRST_LOSS, LOTS_PER_ENTRY,
                                 MAX_ENTRIES_PER_DAY, MAX_ENTRY_COST_RS, STARTING_CAPITAL_RS,
                                 SYMBOL_BY_WEEKDAY)
from live_trading.contracts import Contract, limit_price, resolve
from live_trading.guards import EntryContext, check, correlation_id
from live_trading.trigger import episode_minutes

ROOT = Path(__file__).resolve().parent.parent
THU = date(2026, 9, 24)          # a Thursday -> SENSEX day


def ctx(**over) -> EntryContext:
    base = dict(symbol="SENSEX", session_date=THU, now=datetime(2026, 9, 24, 10, 0), minute="10:00",
                decision="BUY_CE", confirmation="STRONG", episode_minutes=2, armed=True, halted=False,
                halt_reason=None, kill_switch=False, entries_used=0, open_position=False,
                realised_pnl=0.0, correlation_id="c", already_seen=False, last_entry_minute=None,
                contract_ok=True, contract_reason="OK", lot_size=20, ask=250.0, spread_pct=0.2,
                snapshot_age_min=1.0)
    return EntryContext(**{**base, **over})


def refused(c: EntryContext) -> set[str]:
    return {r.split(":")[0] for r in check(c)[0]}


# ---------------------------------------------------------------- the caps are real
def test_a_clean_context_is_allowed():
    assert check(ctx())[0] == []


def test_the_stated_caps_are_what_the_trader_agreed():
    assert (MAX_ENTRIES_PER_DAY, LOTS_PER_ENTRY, HALT_AFTER_FIRST_LOSS) == (2, 1, True)
    assert (MAX_ENTRY_COST_RS, STARTING_CAPITAL_RS) == (9000.0, 10000.0)


def test_third_entry_of_the_day_is_refused():
    assert "MAX_ENTRIES" in refused(ctx(entries_used=MAX_ENTRIES_PER_DAY))


def test_a_realised_loss_halts_the_day():
    assert "LOSS_HALT" in refused(ctx(realised_pnl=-1.0))


def test_an_open_position_blocks_a_second_entry():
    assert "ONE_AT_A_TIME" in refused(ctx(open_position=True))


def test_disarmed_and_kill_switch_each_refuse_on_their_own():
    assert "ARMED" in refused(ctx(armed=False))
    assert "KILL_SWITCH" in refused(ctx(kill_switch=True))


def test_cost_over_the_cap_is_refused_and_says_why():
    reasons = check(ctx(lot_size=65, ask=150.0))[0]          # 65 * 150 = 9,750
    assert any("ENTRY_COST" in r and "quantised to the lot" in r for r in reasons)


def test_cost_exactly_at_the_cap_is_allowed():
    assert "ENTRY_COST" not in refused(ctx(lot_size=20, ask=MAX_ENTRY_COST_RS / 20))


# ---------------------------------------------------------------- the entry qualifiers
def test_only_strong_confirmation_qualifies():
    for weak in ("MODERATE", "WEAK", "NONE", None):
        assert "CONFIRMATION" in refused(ctx(confirmation=weak))
    assert "CONFIRMATION" not in refused(ctx(confirmation="STRONG"))


def test_a_one_minute_flicker_cannot_fire_an_order():
    assert "EPISODE" in refused(ctx(episode_minutes=1))
    assert "EPISODE" not in refused(ctx(episode_minutes=2))


def test_nothing_before_0945_or_after_1445():
    assert "TIME_WINDOW" in refused(ctx(minute="09:44"))
    assert "TIME_WINDOW" in refused(ctx(minute="14:46"))
    assert "TIME_WINDOW" not in refused(ctx(minute="09:45"))
    assert "TIME_WINDOW" not in refused(ctx(minute="14:45"))


def test_one_entry_per_episode():
    """The 2026-09-23 dry run took both slots at 09:51 and 09:52 on one continuous PE run,
    because episode length only ever grows. An entry inside the same episode is refused."""
    same = ctx(minute="09:52", episode_minutes=3, last_entry_minute="09:51")   # episode began 09:50
    assert "NEW_EPISODE" in refused(same)
    fresh = ctx(minute="09:56", episode_minutes=2, last_entry_minute="09:51")  # episode began 09:55
    assert "NEW_EPISODE" not in refused(fresh)


def test_episode_minutes_counts_only_an_unbroken_run():
    h = [("09:50", "BUY_PE"), ("09:51", "BUY_PE"), ("09:52", "WAIT"), ("09:53", "BUY_PE")]
    assert episode_minutes(h, "09:51", "BUY_PE") == 2
    assert episode_minutes(h, "09:53", "BUY_PE") == 1
    assert episode_minutes(h, "09:52", "WAIT") == 1


# ---------------------------------------------------------------- data quality and schedule
def test_stale_or_unknown_data_refuses_rather_than_assuming():
    assert "DATA_FRESH" in refused(ctx(snapshot_age_min=5.0))
    assert "DATA_FRESH" in refused(ctx(snapshot_age_min=None))
    assert "SPREAD" in refused(ctx(spread_pct=None))
    assert "SPREAD" in refused(ctx(spread_pct=9.0))


def test_an_unresolved_contract_refuses():
    assert "CONTRACT" in refused(ctx(contract_ok=False, contract_reason="UNKNOWN: whatever"))


def test_symbol_rotation_by_weekday():
    assert SYMBOL_BY_WEEKDAY[0] == SYMBOL_BY_WEEKDAY[1] == ("NIFTY",)
    assert SYMBOL_BY_WEEKDAY[2] == SYMBOL_BY_WEEKDAY[3] == ("SENSEX",)
    assert set(SYMBOL_BY_WEEKDAY[4]) == {"NIFTY", "SENSEX"}
    assert "SYMBOL_OF_THE_DAY" in refused(ctx(symbol="NIFTY", lot_size=65, ask=100.0))   # Thursday
    mon = date(2026, 9, 28)
    assert "SYMBOL_OF_THE_DAY" not in refused(ctx(symbol="NIFTY", session_date=mon, lot_size=65, ask=100.0))


def test_a_duplicate_correlation_id_is_refused_not_resent():
    assert "NOT_DUPLICATE" in refused(ctx(already_seen=True))
    assert correlation_id("SENSEX", THU, "10:00") == "SENSEX:2026-09-24:10:00"


def test_every_refusal_is_collected_not_just_the_first():
    reasons = check(ctx(armed=False, kill_switch=True, confirmation="WEAK"))[0]
    assert {"ARMED", "KILL_SWITCH", "CONFIRMATION"} <= {r.split(":")[0] for r in reasons}


# ---------------------------------------------------------------- contracts and orders
def test_contract_resolution_is_exact_or_refuses():
    c, why = resolve("SENSEX", "2026-09-24", 74700, "CE")
    if c is None:
        pytest.skip(f"scrip master unavailable or rolled: {why}")
    assert c.security_id.isdigit() and c.lot_size == 20 and c.exchange_segment == "BSE_FNO"
    assert resolve("SENSEX", "2026-09-24", 999999, "CE")[0] is None
    assert resolve("NOTASYMBOL", "2026-09-24", 74700, "CE")[0] is None


def test_limit_is_marketable_and_on_the_tick_grid():
    assert limit_price(250.00, 0.05, 2) == pytest.approx(250.10)
    assert limit_price(250.03, 0.05, 0) == pytest.approx(250.05)


def _contract() -> Contract:
    return Contract("SENSEX", "2026-09-24", 74700, "CE", "839161", "T", "C", "BSE_FNO", 20, 0.05)


def test_order_is_a_limit_buy_of_exactly_one_lot():
    req = build_entry(_contract(), 250.10, "SENSEX:2026-09-24:10:00")
    assert (req.transaction_type, req.order_type, req.product_type) == ("BUY", "LIMIT", "INTRADAY")
    assert req.quantity == 20 * LOTS_PER_ENTRY
    assert req.order_type != "MARKET"          # a spread blowout must fail, not fill
    assert build_exit(_contract(), 20, 240.0, "x").transaction_type == "SELL"


def test_dry_run_is_the_default_and_sends_nothing():
    assert DRY_RUN_DEFAULT is True
    resp = send(build_entry(_contract(), 250.10, "x"))
    assert resp["dry_run"] is True and resp["status"] == "DRY_RUN"
    assert resp["request"]["security_id"] == "839161"        # exactly what WOULD have been sent


def test_force_flat_time_is_configured():
    assert DEFAULT.force_flat_at == "15:10"
    assert VERSION == "13-live-trading-v1"


# ---------------------------------------------------------------- package isolation
ORDER_FRAGMENTS = ("place_order", "modify_order", "cancel_order", "place_slice_order", "place_super_order")


def test_live_trading_is_the_only_package_that_can_reach_an_order_api():
    """Every other package stays structurally sealed: only live_trading/broker.py may mention
    an order API.

    Scope is PRODUCTION source. tests/ is excluded because several suites (test_paper_safety,
    test_hr_isolation, test_opportunity_matrix_v1) name these fragments precisely in order to
    assert their absence, as does paper_trading/safety.py."""
    offenders = []
    for path in ROOT.rglob("*.py"):
        parts = set(path.parts)
        if parts & {"venv", "__pycache__", ".git", "node_modules", "tests"}:
            continue
        if path.resolve() == (ROOT / "live_trading" / "broker.py").resolve():
            continue
        if path.name == "safety.py":          # names the fragments in order to forbid them
            continue
        src = path.read_text(encoding="utf-8", errors="ignore")
        for frag in ORDER_FRAGMENTS:
            if frag in src:
                offenders.append(f"{path.relative_to(ROOT)}:{frag}")
    assert not offenders, f"order API reachable outside live_trading/broker.py: {offenders}"


def test_the_broker_module_never_imports_a_client_at_module_scope():
    """Importing live_trading.broker must not construct or import a broker client: a dry-run
    process should never have one in memory."""
    src = (ROOT / "live_trading" / "broker.py").read_text(encoding="utf-8")
    head = src.split("def send(")[0]
    assert "dhan_client" not in head and "dhanhq" not in head


def test_guards_module_is_pure():
    """No clock, no DB, no network inside the guards -- they judge an explicit context only."""
    src = (ROOT / "live_trading" / "guards.py").read_text(encoding="utf-8")
    for banned in ("datetime.now", "psycopg", "requests", "connect("):
        assert banned not in src, f"guards.py must stay pure, found {banned}"
