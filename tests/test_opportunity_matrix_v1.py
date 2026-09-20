"""Opportunity Matrix v1 tests: causality / leakage, execution realism, chronology, separation,
baseline population, closing-state handling, and regression protection of 11D / 12A / shadow / HR."""

import ast
import hashlib
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from config.settings import IST
from opportunity_matrix_v1 import counterfactual as CF
from opportunity_matrix_v1 import experiments
from opportunity_matrix_v1.baseline import baseline_rows
from opportunity_matrix_v1.closing_state import closing_rows, persistence_movements
from opportunity_matrix_v1.config import DEFAULT as CFG
from opportunity_matrix_v1.events import detect_events, lead_lag
from opportunity_matrix_v1.market_state import market_state
from opportunity_matrix_v1.response import option_response_rows, strike_universe
from opportunity_matrix_v1.setup import snapshots
from opportunity_matrix_v1.thresholds import day_roles, hr_thresholds, minute_thresholds
from tests.om1_factory import ATM, burst_path, make_day
from tests.test_hr_isolation import FROZEN_FILES
from tests.test_scalp12a_isolation import FROZEN_HR_FILES

ROOT = Path(__file__).resolve().parent.parent
D1, D2, D3 = date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17)

FROZEN_12A_FILES = {
    "scalp_12a/__init__.py": "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b",
    "scalp_12a/config.py": "1c808280c3b09b10245592f885eb8400715fbd2ea19d2449dbc749a027ef2a6a",
    "scalp_12a/confirmation.py": "7cb91a995202af8b7871b2ffc9a27f8d1ecd116fbaaf45dbda5b5d04738fe81a",
    "scalp_12a/counterfactual.py": "029fe36c0f434d148a3b760b0e9d88c85c586406d67279fe0b09112054855735",
    "scalp_12a/db.py": "11024513e0e397127ca0e9cf57ab523ff905550b227c87141fe0ff5487e06a27",
    "scalp_12a/engine.py": "868145f1e81f209e15f2cdbf35239529c94004cbd2845015d1b3ac130cf93f43",
    "scalp_12a/events.py": "8a08c3e03350ea1f1a59dcce030f472ce43c085924ebb317e266ff46d5c589bb",
    "scalp_12a/exits.py": "7e4d309b08ef6cf842d513ea5d25a4a1bc4af7692fcce58c7468f3105fc8eeb4",
    "scalp_12a/models.py": "f3c3e6158904a3fda0cd83b1e5dd321c8b59632e8a5a031beaa4140143796fdc",
    "scalp_12a/modes.py": "d96bbba5a6492264f00dbaf5a75f6725809c3dcb2bf045e6b46958300739240b",
    "scalp_12a/opportunity.py": "a5ab7dfbfeb0259abd63309c58b21d914d51014e8dd58ab2a20754c5dd9ccbe7",
    "scalp_12a/option_selector.py": "bf0d231428962d8ebea42775e59b1e47286195e79e409c73188bce2c4877d2ab",
    "scalp_12a/report.py": "f30b8c4ec640c9a8c087ebab196f1751a5f2a8f9a4815639811ceae289c9bace",
    "scalp_12a/research_1min.py": "ec7f64b606b0db0d9a0cf4c4852c72029566f0a8fa9c57c4db5eb0098ad38bc6",
    "scalp_12a/research_hr.py": "3e9bf4b50a77cee7364698959c5cdc2dc4ad4054f233da7e0e7d9560a0303a5f",
    "scalp_12a/risk.py": "5d83755e30df10b94f5c15be6330d75325646a9dd4c6a5e588aff620e4e59108",
    "scalp_12a/taxonomy.py": "f91f5f02ad2ca528f5c5d34e57b19554eb1d21e90a2853d8e0f7ef86894f0538",
    "scalp_12a/thresholds.py": "7eceeb5b7cd679678d359c5adcb49ddbd3a29e465767b4e2115669b1652c4eff",
    "scalp_12a/schema.sql": "b1b29dfaf6d8e92ee8c65a24271c2b0f292c362cd7d41a986ce079c7ac076686",
}
FROZEN_SHADOW_FILES = {
    "scripts/run_scalp12a_shadow.py": "267d004b57f516b938f556159fa03ded2a52d60f02622b5d7ae08ae50da09861",
    "scripts/run_scalp12a_shadow_daily.bat": "b26d3678587503b9489e246624d22c97c1091114cff4975b61e2be41af452966",
    "scripts/run_scalp12a_shadow_daily.vbs": "757f5e383183bd42958fc84352fea8f3261fd9484ee27291c01ab5a46d07be19",
    "scripts/run_scalp12a_research.py": "4464fb8a98445be8f12fa11ee19fa5a48caeb18922b1463d8f4136199e6d6181",
}


def _sha(rel):
    return hashlib.sha256((ROOT / rel).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


@pytest.fixture(scope="module")
def world():
    prior = [make_day(D1), make_day(D2)]
    th = hr_thresholds(D3, prior, CFG)
    day = make_day(D3, fut_path=burst_path(90))
    mth = minute_thresholds(D3, {D1: make_day(D1).candles, D2: make_day(D2).candles}, 5.0, CFG)
    events = detect_events(day, th, CFG)
    return dict(prior=prior, th=th, day=day, mth=mth, events=events)


def _event(world):
    e = dict(world["events"][0])
    e.update(lead_lag(world["day"], e["i"], e["dir"], world["th"], CFG))
    return e


# ------------------------------------------------------------------ causality
def test_market_state_no_future_data(world):
    day = world["day"]
    for hhmm in ("14:30", "14:57", "15:05"):
        T = datetime.combine(D3, time.fromisoformat(hhmm), tzinfo=IST)
        assert market_state(day, T, world["mth"], CFG) == market_state(day.truncate(T), T, world["mth"], CFG)


def test_setup_snapshot_no_future_data(world):
    day = world["day"]
    T = datetime.combine(D3, time(15, 0), tzinfo=IST)
    assert snapshots(day, world["mth"], CFG) == snapshots(day.truncate(T), world["mth"], CFG)


def test_event_detection_no_future_data(world):
    day, th = world["day"], world["th"]
    assert world["events"], "fixture must produce an event"
    for k in range(20, len(day), 20):
        T = day.known_at(k)
        part = detect_events(day.truncate(T), th, CFG)
        full = [e for e in world["events"] if e["i"] <= k]
        assert [(e["event_id"], e["event_type"], e["direction"]) for e in part] == [(e["event_id"], e["event_type"], e["direction"]) for e in full]


def test_option_response_no_future_data(world):
    e, day = _event(world), world["day"]
    tday = day.truncate(day.known_at(e["i"]))
    et = dict(e, **lead_lag(tday, e["i"], e["dir"], world["th"], CFG))
    assert option_response_rows(e, day, world["th"], CFG) == option_response_rows(et, tday, world["th"], CFG)


def test_strike_selection_no_future_data(world):
    e, day = _event(world), world["day"]
    g_full = CF.gates(e, e, day, world["th"], CFG)
    changed = make_day(D3, fut_path=burst_path(90)[: e["i"] + 1] + [ATM + 400] * (420 - e["i"] - 1))   # wild future
    g_changed = CF.gates(e, e, changed, world["th"], CFG)
    assert (g_full["selected_option"], g_full["selected_offset"]) == (g_changed["selected_option"], g_changed["selected_offset"])
    ei = e["i"] + 2
    assert strike_universe(day, ei, e["dir"], CFG) == strike_universe(day.truncate(day.known_at(ei)), ei, e["dir"], CFG)


# ------------------------------------------------------------------ execution realism
def test_entry_price_is_ask(world):
    e, day = _event(world), world["day"]
    g = CF.gates(e, e, day, world["th"], CFG)
    c = CF.counterfactual(e, g, day, CFG, "i+2")
    key = (g["selected_option"], g["selected_offset"])
    assert c["entry_ask"] == day.opt[key][e["i"] + 2]["ask"]


def test_exit_price_is_bid(world):
    e, day = _event(world), world["day"]
    g = CF.gates(e, e, day, world["th"], CFG)
    c = CF.counterfactual(e, g, day, CFG, "i+2")
    key = (g["selected_option"], g["selected_offset"])
    exit_i = e["i"] + 2 + CFG.trade_horizon_s // 5
    assert c["exit_bid"] == day.opt[key][exit_i]["bid"]
    assert c["net_return"] == pytest.approx((c["exit_bid"] - c["entry_ask"]) / c["entry_ask"] * 100)


def test_no_event_bar_fill_as_realistic_execution(world):
    assert "event_bar" not in CFG.executable_entries and CFG.primary_entry in CFG.executable_entries
    e, day = _event(world), world["day"]
    g = CF.gates(e, e, day, world["th"], CFG)
    assert CF.counterfactual(e, g, day, CFG, "event_bar")["executable"] is False
    assert CF.counterfactual(e, g, day, CFG, "i+1")["executable"] is True


# ------------------------------------------------------------------ chronology
def test_chronological_thresholds():
    days = [make_day(D1), make_day(D2), make_day(D3)]
    th = hr_thresholds(D3, days, CFG)
    assert all(d < D3 for d in th.source_days) and th.source_days == (D1, D2)


def test_no_same_day_threshold_fitting():
    days = [make_day(D1), make_day(D2), make_day(D3)]
    assert D3 not in hr_thresholds(D3, days, CFG).source_days
    assert hr_thresholds(D2, days, CFG) is None                      # only 1 prior day -> seed only, no fitting


def test_no_test_day_contamination():
    later = [date(2026, 9, d) for d in (15, 16, 17, 18, 21, 22, 23, 24, 25, 28)]
    roles = day_roles(later, CFG)
    order = {"SEED": 0, "TRAIN": 1, "VALIDATION": 2, "UNSEEN": 3}
    seq = [order[roles[d]] for d in later]
    assert seq == sorted(seq) and "UNSEEN" in roles.values()
    days = [make_day(d) for d in later[:4]]
    th = hr_thresholds(later[2], days, CFG)                          # a TRAIN-day threshold never sees later days
    assert all(s < later[2] for s in th.source_days)


# ------------------------------------------------------------------ separation
def _mini_rows():
    return [dict(symbol="NIFTY", expiry_flag=False, v=1), dict(symbol="NIFTY", expiry_flag=True, v=2),
            dict(symbol="SENSEX", expiry_flag=False, v=3), dict(symbol="SENSEX", expiry_flag=True, v=4)]


def test_expiry_separation():
    g = experiments.by_sym_day(_mini_rows())
    assert [r["v"] for r in g["NIFTY | NORMAL"]] == [1] and [r["v"] for r in g["NIFTY | EXPIRY"]] == [2]
    # the existing expiry restriction is preserved (never relaxed): an event at 15:11 on an expiry day fails
    # the WINDOW stage, the identical event on a normal day passes it
    th = hr_thresholds(D3, [make_day(D1), make_day(D2)], CFG)
    bar = next(k for k in range(420) if make_day(D3).known_at(k).time() >= time(15, 11))
    for expiry, expect in ((D3, False), (date(2026, 9, 22), True)):
        day = make_day(D3, fut_path=burst_path(bar - 3), expiry=expiry)
        e = next(x for x in detect_events(day, th, CFG) if x["i"] >= bar - 3)
        e.update(lead_lag(day, e["i"], e["dir"], th, CFG))
        g2 = CF.gates(e, e, day, th, CFG)
        assert g2["stage_results"]["WINDOW"] is expect
        if not expect:
            assert "EXPIRY_RESTRICTION" in g2["rejection_reasons"] and not g2["research_approved"]


def test_symbol_separation():
    g = experiments.by_sym_day(_mini_rows())
    assert all(r["symbol"] == "SENSEX" for k in ("SENSEX | NORMAL", "SENSEX | EXPIRY") for r in g[k])
    assert all(r["symbol"] == "NIFTY" for k in ("NIFTY | NORMAL", "NIFTY | EXPIRY") for r in g[k])


def test_event_cluster_grouping():
    p = burst_path(90)
    for k in range(100, 420):
        p[k] = p[99]
    for k in range(104, 420):                                        # second burst 20 s later (same cluster)
        p[k] = p[103] - 3.0 * min(4, k - 103)
    for k in range(200, 420):                                        # third burst far later (new cluster)
        p[k] = p[199] + 3.0 * min(4, k - 199)
    th = hr_thresholds(D3, [make_day(D1), make_day(D2)], CFG)
    ev = detect_events(make_day(D3, fut_path=p), th, CFG)
    assert len(ev) >= 3
    by = {}
    for e in ev:
        by.setdefault(e["event_cluster_id"], []).append(e)
    for es in by.values():
        assert all((x["i"] - es[0]["i"]) * 5 <= CFG.cluster_gap_s for x in es)
        assert sum(1 for x in es if x["cluster_first"]) == 1
    assert len(by) >= 2


def test_random_baseline_population(world):
    rows = baseline_rows(world["day"], world["events"], CFG)
    assert rows
    wins = {e["event_id"]: e["window"] for e in world["events"]}
    for r in rows:
        assert r["symbol"] == world["day"].symbol and r["trade_date"] == str(D3)
        assert r["window"] == wins[r["paired_event"]] and r["entry"] in CFG.executable_entries and r["entry_spread_pct"] <= CFG.max_spread_pct
    assert rows == baseline_rows(world["day"], world["events"], CFG)   # seeded, reproducible


# ------------------------------------------------------------------ closing state
def test_closing_state_stale_reference(world):
    day = make_day(D3, und_frozen_from=time(15, 15))
    rows = closing_rows(day, world["th"], CFG)
    stale = [r for r in rows if r["data_quality"] == "UNDERLYING_STALE"]
    assert stale and all(r["underlying_reference_type"] == "LAST_RELIABLE_INDEX" for r in stale)
    assert len({r["underlying_reference"] for r in stale}) == 1 and all(r["last_reliable_timestamp"] for r in stale)


def test_option_implied_spot_persistence(world):
    base = [ATM - 20.0] * 420
    fi = next(k for k in range(420) if (make_day(D3).times[k]).time() >= time(15, 16))
    persistent = list(base)
    for k in range(fi, 420):
        persistent[k] = base[k] + 40.0
    transient = list(base)
    transient[fi] = base[fi] + 40.0
    th = hr_thresholds(D3, [make_day(D1), make_day(D2)], CFG)
    for path, expect in ((persistent, True), (transient, False)):
        day = make_day(D3, implied_path=path, und_frozen_from=time(15, 15))
        mv = persistence_movements(day, closing_rows(day, th, CFG), th, CFG)
        assert mv and mv[0]["persist_30s"] is expect


# ------------------------------------------------------------------ regression protection
def test_11d_unchanged():
    for rel, digest in FROZEN_FILES.items():
        assert _sha(rel) == digest, rel
    from paper_trading.config import DEFAULT_CONFIG
    assert DEFAULT_CONFIG.config_hash() == "9c7c362d7e0c6a14"


def test_12a_unchanged():
    for rel, digest in FROZEN_12A_FILES.items():
        assert _sha(rel) == digest, rel


def test_12a_config_hash_unchanged():
    from scalp_12a.config import DEFAULT_CONFIG, STRATEGY_VERSION
    assert STRATEGY_VERSION == "12A-scalp-v1" and DEFAULT_CONFIG.config_hash() == "994667c6d552111e"


def test_shadow_recorder_unchanged():
    for rel, digest in FROZEN_SHADOW_FILES.items():
        assert _sha(rel) == digest, rel


def test_hr_capture_unchanged():
    for rel, digest in FROZEN_HR_FILES.items():
        assert _sha(rel) == digest, rel


def test_om1_is_isolated_read_only_and_order_free():
    pkg = sorted((ROOT / "opportunity_matrix_v1").glob("*.py")) + [ROOT / "scripts" / "run_opportunity_matrix_v1.py"]
    forbidden = ("paper_trading", "scalp_12a", "hr_capture", "dhan_client", "dhanhq", "backend", "pipeline.live_loop", "db.writer")
    for p in pkg:
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not any(node.module == f or node.module.startswith(f + ".") for f in forbidden), (p, node.module)
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith(forbidden) for a in node.names), p
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not re.search(r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE|TRUNCATE)\b",
                                     node.value), (p, node.value[:60])     # SQL is written in upper case
        text = p.read_text(encoding="utf-8").lower()
        for frag in ("place_order", "modify_order", "cancel_order", "/orders"):
            assert frag not in text, (p, frag)
    assert "default_transaction_read_only=on" in (ROOT / "opportunity_matrix_v1" / "loader.py").read_text(encoding="utf-8")
    for folder in ("paper_trading", "scalp_12a", "hr_capture", "pipeline", "backend/app"):
        for p in (ROOT / folder).rglob("*.py"):
            if "venv" in p.parts:
                continue
            assert "opportunity_matrix_v1" not in p.read_text(encoding="utf-8", errors="ignore"), p
