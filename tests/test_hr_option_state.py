"""HR-1 option 5-second state."""

from hr_capture.config import DEFAULT_HR_CONFIG
from hr_capture.option_state import QuoteState, build_option_row, has_valid_two_sided_quote
from hr_capture.protocol import parse_message
from hr_capture.service import CaptureSession
from tests.hr_packet_factory import TRADING_DATE, ListWriter, full, make_universe, ns_at, oi_packet, option_id

EMPTY_BAR = {"trade_count": 0, "volume": None}


def _ev(raw):
    return parse_message(raw)[0]


def test_spread_mid_and_depth_imbalance():
    levels = [(300, 100, 1, 1, 99.0, 101.0)] + [(100, 100, 1, 1, 98.0, 102.0)] * 4
    state = QuoteState()
    state.apply(ns_at(15, 0, 1), _ev(full("NSE_FNO", 1, 100.0, levels=levels)))
    row = build_option_row(state, ns_at(15, 0, 5), 1, False, None, EMPTY_BAR, False, 30.0)
    assert row["bid"] == 99.0 and row["ask"] == 101.0 and row["mid"] == 100.0
    assert row["spread"] == 2.0 and row["spread_pct"] == 2.0
    assert row["bid_qty_total5"] == 700 and row["ask_qty_total5"] == 500
    assert row["depth_imbalance"] == round(200 / 1200, 6)
    assert row["quote_age_s"] == 4.0 and row["data_quality"] == "OK"


def test_oi_delta_only_when_oi_actually_observed_in_bucket():
    state = QuoteState()
    state.apply(1, _ev(full("NSE_FNO", 1, 10.0, oi=1000, bid=9.0, ask=11.0, bid_qty=1, ask_qty=1)))
    carried = build_option_row(state, 2, 0, oi_observed=False, prev_bucket_oi=1000, bar=EMPTY_BAR, is_gap=False,
                               stale_after_s=30.0)
    assert carried["oi"] == 1000 and carried["oi_delta"] is None
    observed = state.apply(3, _ev(oi_packet("NSE_FNO", 1, 1250)))
    row = build_option_row(state, 4, 1, observed, 1000, EMPTY_BAR, False, 30.0)
    assert observed is True and row["oi_delta"] == 250


def test_quality_flags_missing_crossed_stale_and_no_data():
    never = build_option_row(QuoteState(), 10, 0, False, None, EMPTY_BAR, False, 30.0)
    assert never["data_quality"] == "NO_DATA_YET" and never["bid"] is None

    one_sided = QuoteState()
    one_sided.apply(0, _ev(full("NSE_FNO", 1, 5.0, bid=0.0, ask=5.5, bid_qty=0, ask_qty=10)))
    assert "MISSING_BID_ASK" in build_option_row(one_sided, 1, 1, False, None, EMPTY_BAR, False, 30.0)["data_quality"]

    crossed = QuoteState()
    crossed.apply(0, _ev(full("NSE_FNO", 1, 5.0, bid=6.0, ask=5.0, bid_qty=1, ask_qty=1)))
    assert "CROSSED" in build_option_row(crossed, 1, 1, False, None, EMPTY_BAR, False, 30.0)["data_quality"]

    stale = QuoteState()
    stale.apply(0, _ev(full("NSE_FNO", 1, 5.0, bid=4.9, ask=5.1, bid_qty=1, ask_qty=1)))
    row = build_option_row(stale, 45 * 1_000_000_000, 0, False, None, EMPTY_BAR, False, 30.0)
    assert "STALE_QUOTE" in row["data_quality"] and "NO_UPDATE" in row["data_quality"]
    assert not has_valid_two_sided_quote(row, 30.0)


def test_option_rows_preserve_contract_metadata():
    universe = make_universe()
    writer = ListWriter()
    session = CaptureSession(DEFAULT_HR_CONFIG, TRADING_DATE, {"NIFTY": universe}, writer, session_id="s")
    sid = option_id(universe, -2, "PE")
    session.handle_message(ns_at(15, 0, 1), full("NSE_FNO", sid, 42.0, bid=41.5, ask=42.5, bid_qty=5, ask_qty=5))
    session.finalize_all()
    row = next(r for r in writer.rows["hr_option_5s"] if r["security_id"] == sid and r["updated_in_bucket"])
    assert (row["strike"], row["option_type"], row["atm_offset"], row["expiry"]) == (23300.0, "PE", -2, TRADING_DATE)
    tick = next(r for r in writer.rows["hr_raw_ticks"] if r["security_id"] == sid)
    assert (tick["strike"], tick["option_type"], tick["instrument_type"], tick["symbol"]) == (23300.0, "PE", "OPTIDX", "NIFTY")
