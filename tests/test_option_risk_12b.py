"""12B-option-risk-v1 tests (synthetic data only; no DB, no network).

Covers the 25 required behaviours: OI differencing, CE/PE pressure, relative movement,
acceleration, underlying staleness, closing states, the advisory risk ladder, BUY CE /
BUY PE interpretation, Greeks / spread / missing-minute handling, implied-spot validity,
leakage, the 15:15 and 15:30 cutoffs, symbol separation, the next-print study, read-only
UI/API, and isolation from 11D and 12A.
"""

import ast
import hashlib
import math
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from config.settings import IST
from option_risk_12b import research as R
from option_risk_12b.closing_state import STALE, closing_state, implied_spot, underlying_states
from option_risk_12b.config import DEFAULT, RiskConfig, VERSION
from option_risk_12b.engine import _clean, build_session, minute_view, prepare, truncate
from option_risk_12b.option_pressure import directional_pressure, oi_price_state
from option_risk_12b.option_risk import assess
from option_risk_12b.option_snapshot import minute_range, parse_snapshot
from option_risk_12b.option_state import leg_state
from option_risk_12b.option_trajectory import label

ROOT = Path(__file__).resolve().parent.parent
D = date(2026, 9, 18)
STEP = 50.0


# ---------------------------------------------------------------- synthetic factory
def price(S, K, typ):
    tv = 60.0 * math.exp(-((S - K) / 150.0) ** 2) + 5.0
    return (max(S - K, 0.0) if typ == "CE" else max(K - S, 0.0)) + tv


def make_day(spot_path=None, freeze_from="15:15", start="14:55", end="15:29", atm=23400.0, extra_minutes=(),
             drop_minutes=(), spread_pct=0.5, greeks=True, vol_ce=1000, vol_pe=1000, oi_step=(10, 10), symbol="NIFTY",
             ce_bias=None, pe_bias=None, pe_flow_growth=0.0, ce_bidq_decay=0.0):
    """Returns (snapshots, candles). spot_path(minute_index) -> index level. After `freeze_from` the index print
    (snapshot spot and 1-min candle) is frozen at its freeze_from value while option prices keep following the path.
    ce_bias / pe_bias(minute_index) add extra premium % to CE / PE mids (to create CE-vs-PE divergence)."""
    minutes = minute_range(start, end) + list(extra_minutes)
    spot_path = spot_path or (lambda i: atm + 3 * math.sin(i / 2.0))
    snaps, candles = [], []
    frozen = None
    for i, m in enumerate(minutes):
        S = spot_path(i)
        if freeze_from and m >= freeze_from and frozen is None:
            frozen = S
        shown = frozen if (freeze_from and m >= freeze_from) else S
        h, mm = map(int, m.split(":"))
        ts = datetime.combine(D, time(h, mm), tzinfo=IST)
        flat = bool(freeze_from) and m > freeze_from          # the bar ENDING at the freeze minute still traded
        candles.append(dict(timestamp=ts - timedelta(minutes=1), open=shown, high=shown if flat else shown + 2,
                            low=shown if flat else shown - 2, close=shown, volume=1000.0))
        if m in drop_minutes:
            continue
        oc = {}
        for off in range(-7, 8):
            K = atm + off * STEP
            legs = {}
            for typ, vol, oist in (("CE", vol_ce, oi_step[0]), ("PE", vol_pe, oi_step[1])):
                mid = price(S, K, typ)
                if typ == "CE" and ce_bias:
                    mid *= 1 + ce_bias(i) / 100
                if typ == "PE" and pe_bias:
                    mid *= 1 + pe_bias(i) / 100
                half = max(mid * spread_pct / 200, 0.025)
                g = dict(delta=0.5 if typ == "CE" else -0.5, gamma=0.001, theta=-3.0, vega=2.0) if greeks else {}
                cum = 10_000 + vol * i + (pe_flow_growth * vol * i * i if typ == "PE" else 0)
                bq = 500 * (1 - ce_bidq_decay) ** i if typ == "CE" else 500
                legs[typ.lower()] = dict(last_price=round(mid, 2), top_bid_price=round(mid - half, 2), top_ask_price=round(mid + half, 2),
                                         top_bid_quantity=bq, top_ask_quantity=500, volume=cum, oi=50_000 + oist * i,
                                         previous_oi=1, implied_volatility=12.0 if greeks else 0.0, greeks=g)
            oc[f"{K:.6f}"] = legs
        snaps.append(dict(fetched_at=ts, spot=shown, expiry=D, payload={"oc": oc, "last_price": shown}))
    return snaps, candles


def view(snaps, candles, m, symbol="NIFTY", positions=(), cfg=DEFAULT):
    series, cmap = prepare(snaps, candles)
    und = underlying_states(series, cmap, minute_range(cfg.lookback_start, cfg.window_end), cfg)
    return minute_view(series, cmap, m, und, D, symbol, cfg, positions), series, und


# ---------------------------------------------------------------- 1
def test_consecutive_oi_difference_not_previous_oi():
    snaps, c = make_day(oi_step=(37, 11))
    series, _ = prepare(snaps, c)
    st = leg_state(series, "15:10", "CE", 23400.0)
    assert st["intraday_oi_change"] == 37                  # consecutive snapshots, NOT oi - previous_oi (= huge)
    assert leg_state(series, "15:10", "PE", 23400.0)["intraday_oi_change"] == 11
    snaps2, c2 = make_day(drop_minutes=("15:09",))
    s2, _ = prepare(snaps2, c2)
    assert leg_state(s2, "15:10", "CE", 23400.0)["intraday_oi_change"] is None   # gap -> no bridged difference


# ---------------------------------------------------------------- 2 / 3 / 4
def _trend_day(sign):
    return make_day(spot_path=lambda i: 23400.0 + sign * 4.0 * i, freeze_from=None)


def test_ce_pressure_positive_when_calls_strengthen():
    snaps, c = _trend_day(+1)
    v, *_ = view(snaps, c, "15:10")
    assert v["pressure"]["CE_PRESSURE"] > 0.1
    assert v["pressure"]["ce_components"]["premium"]["raw_pct_3m"] > 0


def test_pe_pressure_positive_when_puts_strengthen():
    snaps, c = _trend_day(-1)
    v, *_ = view(snaps, c, "15:10")
    assert v["pressure"]["PE_PRESSURE"] > 0.1
    assert v["pressure"]["label"] == "DOWN"


def test_ce_pe_relative_movement():
    snaps, c = _trend_day(+1)
    p = view(snaps, c, "15:10")[0]["pressure"]
    assert p["CALL_RELATIVE_STRENGTH"] > 0 and p["PUT_RELATIVE_STRENGTH"] == -p["CALL_RELATIVE_STRENGTH"]
    assert p["label"] == "UP" and p["up_evidence"]


# ---------------------------------------------------------------- 5 / 6
def test_premium_acceleration_labels():
    assert label(2.0, 3.0, 0.5, 0.5, 0.3) == "ACCELERATING"
    assert label(0.2, 3.0, 1.5, 0.5, 0.3) == "DECELERATING"
    assert label(0.1, 0.2, 0.1, 0.5, 0.3) == "FLAT"
    assert label(None, None, None, 0.5, 0.3) == "INSUFFICIENT_DATA"
    snaps, c = make_day(spot_path=lambda i: 23400.0 + 0.3 * i * i, freeze_from=None)
    tr = view(snaps, c, "15:12")[0]["trajectory"]["ce_premium"]
    assert tr["chg_3m"] > 0 and tr["label"] in ("ACCELERATING", "DECELERATING", "RISING")
    assert tr["acceleration"] == pytest.approx(tr["chg_1m"] - view(snaps, c, "15:11")[0]["trajectory"]["ce_premium"]["chg_1m"])


def test_volume_acceleration():
    snaps, c = make_day()
    series, _ = prepare(snaps, c)
    st = leg_state(series, "15:10", "CE", 23400.0)
    assert st["volume_change"] == 1000 and st["volume_acceleration"] == 0     # steady flow
    # volume without a premium direction is not directional evidence
    comp = view(snaps, c, "15:10")[0]["pressure"]["ce_components"]["volume_acceleration"]
    assert comp["premium_sign"] == 0 or comp["value"] is not None


# ---------------------------------------------------------------- 7 / 8 / 9
def test_stale_underlying_detected():
    snaps, c = make_day(freeze_from="15:15")
    v, _, und = view(snaps, c, "15:20")
    assert und["15:10"]["state"] == "LIVE"
    assert und["15:20"]["state"] == STALE and und["15:20"]["last_reliable_minute"] == "15:15"
    assert und["15:20"]["age_minutes"] == 5
    assert "STALE_UNDERLYING" in v["data_quality"]


def test_missing_underlying():
    snaps, c = make_day(freeze_from=None)
    snaps = [s for s in snaps if s["fetched_at"].strftime("%H:%M") != "15:20"]
    c = [x for x in c if x["timestamp"].strftime("%H:%M") != "15:19"]
    v, _, und = view(snaps, c, "15:20")
    assert und["15:20"]["state"] == "MISSING"
    assert v["closing_state"] == "UNDERLYING_MISSING" and "MISSING_UNDERLYING" in v["data_quality"]


def test_options_active_while_underlying_stale():
    snaps, c = make_day(spot_path=lambda i: 23400.0 + 5.0 * i, freeze_from="15:15")
    v, *_ = view(snaps, c, "15:22")
    assert v["closing_state"] == "OPTIONS_ACTIVE_UNDERLYING_STALE"
    assert v["combination_state"] == "UNDERLYING_UNAVAILABLE_OPTIONS_AVAILABLE"
    assert v["market_state"] == "OPTIONS_LED_WHILE_UNDERLYING_STALE"
    assert closing_state("STALE", "LOW_ACTIVITY") == "UNDERLYING_STALE"
    assert "AUCTION" not in str(v)                       # no mechanism is invented


# ---------------------------------------------------------------- 10 / 11 / 12 / 13
CE_POS = dict(option_type="CE", strike=23400.0, entry_minute="15:00", exit_minute=None, label="REF CE")
PE_POS = dict(option_type="PE", strike=23400.0, entry_minute="15:00", exit_minute=None, label="REF PE")


def _risk(sign, pos, m="15:12", **kw):
    snaps, c = make_day(spot_path=lambda i: 23400.0 + sign * 6.0 * i, freeze_from=None, **kw)
    v, *_ = view(snaps, c, m, positions=[pos])
    return v["position_risk"][0]


# a falling market with several INDEPENDENT adverse observations for a held CE:
# price + relative (the move itself), positioning (CE OI building while premium falls),
# flow (PE volume accelerating) and liquidity (CE bid quantity draining)
ADVERSE_FOR_CE = dict(oi_step=(400, 10), pe_flow_growth=0.3, ce_bidq_decay=0.08)
ADVERSE_FOR_PE = dict(oi_step=(10, 400), vol_ce=1000, ce_bidq_decay=0.0)


def test_risk_state_ladder_counts_independent_families():
    r = _risk(-1, CE_POS, **ADVERSE_FOR_CE)
    assert r["risk_state"] in ("HIGH", "EXTREME") and r["risk_action"] in ("PREPARE_EXIT", "BREAK_EXIT")
    assert {"PRICE", "RELATIVE", "POSITIONING"} <= set(r["negative_families"]) and len(r["negative_families"]) >= 3
    assert all(":" in x for x in r["reasons"])          # every state carries explicit reasons
    assert r["advisory_only"] is True
    # a pure price move is ONE observation seen through correlated signals -> ELEVATED / CAUTION only
    plain = _risk(-1, CE_POS)
    assert plain["risk_state"] == "ELEVATED" and plain["risk_action"] == "CAUTION"
    assert set(plain["negative_families"]) <= {"PRICE", "RELATIVE", "VOLATILITY"}


def test_position_support_strong_when_option_evidence_supports():
    r = _risk(+1, CE_POS)
    assert r["position_support"] == "STRONG" and r["risk_state"] == "LOW" and r["risk_action"] == "HOLD"
    w = _risk(-1, CE_POS, **ADVERSE_FOR_CE)
    assert w["position_support"] == "CONTRADICTED"


def test_buy_ce_interpretation():
    assert _risk(+1, CE_POS)["risk_action"] == "HOLD"
    assert _risk(-1, CE_POS)["risk_action"] == "CAUTION"
    assert _risk(-1, CE_POS, **ADVERSE_FOR_CE)["risk_action"] in ("PREPARE_EXIT", "BREAK_EXIT")


def test_buy_pe_interpretation_is_reversed():
    assert _risk(-1, PE_POS)["risk_action"] == "HOLD"
    up = _risk(+1, PE_POS)
    assert up["risk_action"] == "CAUTION" and "OWN_PREMIUM_FALLING" in up["negative"]
    assert "OPPOSITE_PREMIUM_RISING" in up["negative"]          # for a PE the CE is the opposite leg


def test_stale_underlying_prevents_low_risk():
    snaps, c = make_day(spot_path=lambda i: 23400.0 + 6.0 * i, freeze_from="15:05")
    v, *_ = view(snaps, c, "15:12", positions=[CE_POS])
    r = v["position_risk"][0]
    assert r["risk_state"] != "LOW" and any("underlying reference" in x for x in r["reasons"])


# ---------------------------------------------------------------- 14 / 15 / 16
def test_missing_greeks_marked_not_zeroed():
    snaps, c = make_day(greeks=False)
    v, series, _ = view(snaps, c, "15:10")
    assert v["ce"]["greeks_status"] == "UNAVAILABLE" and v["ce"]["iv"] is None and v["ce"]["delta"] is None
    assert "INVALID_GREEKS" in v["data_quality"]
    q = parse_snapshot(datetime.combine(D, time(15, 0), tzinfo=IST), 1.0, D, {"oc": {"100": {"pe": dict(
        top_bid_price=1, top_ask_price=2, implied_volatility=0.0, greeks=dict(delta=0.0, gamma=0.0, theta=0.0, vega=0.0))}}})
    leg = q["legs"][("PE", 100.0)]
    assert leg["greeks_status"] == "INVALID" and leg["iv"] is None and leg["delta"] is None   # degenerate deep-ITM style


def test_wide_spread_flagged():
    snaps, c = make_day(spread_pct=8.0)
    v, *_ = view(snaps, c, "15:10", positions=[CE_POS])
    assert "WIDE_SPREAD" in v["data_quality"]
    assert "OWN_SPREAD_EXPANDING" in v["position_risk"][0]["negative"]


def test_missing_option_minute_not_filled():
    snaps, c = make_day(drop_minutes=("15:20",))
    series, cmap = prepare(snaps, c)
    und = underlying_states(series, cmap, minute_range("14:55", "15:30"), DEFAULT)
    v = minute_view(series, cmap, "15:20", und, D, "NIFTY", DEFAULT, [CE_POS])
    assert v["snapshot_present"] is False and v["ce"]["status"] == "MISSING"
    assert "MISSING_OPTION_DATA" in v["data_quality"]
    assert v["position_risk"][0]["position_support"] == "UNKNOWN"
    nxt = minute_view(series, cmap, "15:21", und, D, "NIFTY", DEFAULT)
    assert nxt["ce"]["premium_change_pct"] is None and nxt["ce"]["intraday_oi_change"] is None


# ---------------------------------------------------------------- 17
def test_implied_spot_invalid_inputs():
    snaps, c = make_day()
    series, cmap = prepare(snaps, c)
    und = dict(last_reliable_value=23400.0)
    ok = implied_spot(series, "15:10", 23400.0, und, DEFAULT, D)
    assert ok["quality"] == "OK" and abs(ok["implied_spot"] - (23400.0 + 3 * math.sin(15 / 2.0))) < 1.0
    one_sided = make_day(spread_pct=0.5)[0]
    for s in one_sided:
        for legs in s["payload"]["oc"].values():
            legs["pe"]["top_bid_price"] = 0          # no two-sided PE quote anywhere
    s1, _ = prepare(one_sided, c)
    bad = implied_spot(s1, "15:10", 23400.0, und, DEFAULT, D)
    assert bad["quality"] == "INVALID" and bad["implied_spot"] is None and bad["gap_points"] is None
    assert implied_spot(series, "15:10", None, und, DEFAULT, D)["quality"] == "INVALID"


# ---------------------------------------------------------------- 18
def test_no_future_data_leakage_truncation_invariance():
    snaps, c = make_day(spot_path=lambda i: 23400.0 + 7 * math.sin(i / 3.0) + i, freeze_from="15:15")
    series, cmap = prepare(snaps, c)
    full = underlying_states(series, cmap, minute_range("14:55", "15:30"), DEFAULT)
    for m in minute_range("15:00", "15:29"):
        st, ct = truncate(series, cmap, m)
        ut = underlying_states(st, ct, minute_range("14:55", m), DEFAULT)
        a = _clean(minute_view(series, cmap, m, full, D, "NIFTY", DEFAULT, [CE_POS]))
        b = _clean(minute_view(st, ct, m, ut, D, "NIFTY", DEFAULT, [CE_POS]))
        assert a == b, m


# ---------------------------------------------------------------- 19 / 20
def test_1515_cutoff_segments():
    snaps, c = make_day()
    out = build_session("NIFTY", D, snaps, c)
    segs = {r["minute"]: r["segment"] for r in out["minutes"]}
    assert out["minutes"][0]["minute"] == "15:00"
    assert segs["15:14"] == "ACTUAL_UNDERLYING"
    assert segs["15:15"] == "CLOSING_STALE_UNDERLYING_OPTION_CONTINUATION"
    assert out["summary"]["window_minutes"] == 16


def test_1530_cutoff_and_as_of():
    snaps, c = make_day(extra_minutes=("15:36", "15:37"))
    out = build_session("NIFTY", D, snaps, c)
    assert out["minutes"][-1]["minute"] == "15:30"
    assert out["summary"]["missing_option_minutes"] == ["15:30"]
    live = build_session("NIFTY", D, snaps, c, as_of="15:18")
    assert live["minutes"][-1]["minute"] == "15:18" and live["as_of"] == "15:18"


# ---------------------------------------------------------------- 21
def test_nifty_sensex_separation():
    n_snaps, n_c = make_day(atm=23400.0)
    s_snaps, s_c = make_day(atm=74500.0, spot_path=lambda i: 74500.0 - 20.0 * i)
    n = build_session("NIFTY", D, n_snaps, n_c)
    s = build_session("SENSEX", D, s_snaps, s_c)
    assert {r["atm_strike"] for r in n["minutes"] if r["atm_strike"]} <= {23350.0, 23400.0, 23450.0}
    assert all(r["atm_strike"] is None or r["atm_strike"] > 70000 for r in s["minutes"])
    assert n == build_session("NIFTY", D, n_snaps, n_c)          # the SENSEX build did not affect NIFTY
    assert DEFAULT.underlying_move_pts["NIFTY"] != DEFAULT.underlying_move_pts["SENSEX"]
    src = (ROOT / "option_risk_12b" / "loader.py").read_text(encoding="utf-8")
    assert src.count("where symbol=%s") >= 3                     # every per-day query is symbol-filtered


# ---------------------------------------------------------------- 22
def test_historical_next_print_calculation():
    snaps, c = make_day(spot_path=lambda i: 23400.0 + 2.0 * i, freeze_from="15:15")
    c = [dict(x) for x in c]
    for x in c:
        if x["timestamp"].strftime("%H:%M") == "15:28":
            x["close"] = 23480.0                                  # first changed print, observable at 15:29
    out = build_session("NIFTY", D, snaps, c)
    cmap = {x["timestamp"].strftime("%H:%M"): x for x in c}
    np_ = R.next_print(out, cmap, 23480.0, DEFAULT)
    frozen = out["minutes"][[r["minute"] for r in out["minutes"]].index("15:16")]["underlying"]["last_reliable_value"]
    assert np_["print_known_at"] == "15:29" and np_["print_value"] == 23480.0 and np_["print_move"] == 23480.0 - frozen
    series, _ = prepare(snaps, c)
    sig = R.next_print_signals(out, series, np_, DEFAULT)
    assert sig and all(s["signal_minute"] < np_["print_known_at"] for s in sig)
    assert sig[0]["implied_change"] > 0 and sig[0]["ce_minus_pe_pct"] > 0
    h = R.hit_table([dict(x=1.0, print_move=5.0), dict(x=-1.0, print_move=5.0), dict(x=2.0, print_move=0.0)], "x", 0.0)
    assert h["n"] == 2 and h["hits"] == 1 and h["excluded_flat_print"] == 1


# ---------------------------------------------------------------- 23
def test_ui_and_api_are_read_only():
    router = (ROOT / "backend/app/api/v1/routers/option_risk.py").read_text(encoding="utf-8")
    assert "@router.get" in router and not re.search(r"@router\.(post|put|patch|delete)", router)
    repo = (ROOT / "backend/app/repositories/option_risk_repository.py").read_text(encoding="utf-8")
    assert not re.search(r"\.(add|delete|commit|merge|flush)\(|insert\(|update\(", repo)
    svc = (ROOT / "backend/app/services/option_risk_service.py").read_text(encoding="utf-8")
    assert not re.search(r"\.(add|delete|commit|merge|flush)\(", svc)
    ep = (ROOT / "frontend/src/api/endpoints/optionRisk.ts").read_text(encoding="utf-8")
    assert "apiClient.get" in ep and not re.search(r"apiClient\.(post|put|patch|delete)", ep)
    loader = (ROOT / "option_risk_12b/loader.py").read_text(encoding="utf-8")
    assert "default_transaction_read_only=on" in loader
    assert not re.search(r"\b(insert|update|delete|create|drop|alter|truncate)\b", loader.lower().split('"""', 2)[-1])


# ---------------------------------------------------------------- 24 / 25
FORBIDDEN = ("paper_trading", "scalp_12a", "pipeline.live_loop", "pipeline.run_snapshot", "dhan_client", "dhanhq",
             "hr_capture", "backend", "db.writer", "option_chain.fetch", "websockets")


def _imports(path):
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def _sha(p):
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_isolation_from_11d():
    from paper_trading.config import DEFAULT_CONFIG
    from tests.test_hr_isolation import FROZEN_FILES
    assert DEFAULT_CONFIG.config_hash() == "9c7c362d7e0c6a14"
    for rel, digest in FROZEN_FILES.items():
        assert _sha(ROOT / rel) == digest, rel
    for p in (ROOT / "option_risk_12b").glob("*.py"):
        for n in _imports(p):
            assert not any(n == f or n.startswith(f + ".") for f in FORBIDDEN), (p.name, n)
    for p in (ROOT / "paper_trading").glob("*.py"):
        assert not any(n.startswith("option_risk_12b") for n in _imports(p)), p
    txt = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "option_risk_12b").glob("*.py"))
    assert not re.search("|".join(["place" + "_order", "modify" + "_order", "cancel" + "_order", "/" + "orders"]), txt)
    assert "paper_positions" in txt and "insert into" not in txt.lower()      # reads positions, never writes them


def test_isolation_from_12a():
    from scalp_12a.config import DEFAULT_CONFIG
    from tests.test_scalp12a_isolation import FROZEN_HR_FILES
    assert DEFAULT_CONFIG.config_hash() == "994667c6d552111e"
    for rel, digest in FROZEN_HR_FILES.items():
        assert _sha(ROOT / rel) == digest, rel
    for folder in ("scalp_12a", "hr_capture", "pipeline"):
        for p in (ROOT / folder).rglob("*.py"):
            assert not any(n.startswith("option_risk_12b") for n in _imports(p)), p
    assert VERSION == "12B-option-risk-v1" and DEFAULT.config_hash() == RiskConfig().config_hash()
    assert RiskConfig(adverse_premium_pct=-2.0).config_hash() != DEFAULT.config_hash()
