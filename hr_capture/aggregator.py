"""Deterministic 5-second aggregation.

All derived rows are computed from the ordered event stream alone:
``ingest`` only files events into receive-time buckets, and every state
change (quotes, cumulative volume, OI, feed liveness) is applied inside
``_finalize`` bucket by bucket, in arrival order. The same events in the
same order therefore always produce identical rows -- live, in replay and
in tests.
"""

from collections import defaultdict
from datetime import date

from hr_capture.bars import build_bar
from hr_capture.chain_state import build_chain_row
from hr_capture.config import HRConfig
from hr_capture.market_state import classify_feed_status
from hr_capture.option_state import QuoteState, build_option_row
from hr_capture.timeutil import (
    LTT_UNDETERMINED, NS_PER_S, detect_ltt_convention, ist_ns, ns_to_ist,
)
from hr_capture.universe import FUTIDX, INDEX, OPTIDX, HRInstrument


class Aggregator:
    def __init__(self, config: HRConfig, trading_date: date, instruments: list[HRInstrument],
                 band_atm_by_symbol: dict[str, float | None], session_id: str, source: str = "WEBSOCKET"):
        self.config = config
        self.session_id = str(session_id)
        self.source = source
        self.trading_date = trading_date
        self.meta: dict[tuple[str, int], HRInstrument] = {i.key: i for i in instruments}
        self.band_atm = dict(band_atm_by_symbol)
        self.symbols = sorted({i.symbol for i in instruments})

        self.start_ns = ist_ns(trading_date, config.window_start)
        self.end_ns = ist_ns(trading_date, config.window_end)
        self.closing_ns = ist_ns(trading_date, config.closing_phase_start)
        self.bar_ns = config.bar_seconds * NS_PER_S
        self.grace_ns = int(config.bucket_grace_seconds * NS_PER_S)
        self.n_buckets = (self.end_ns - self.start_ns) // self.bar_ns

        self.states: dict[tuple[str, int], QuoteState] = {k: QuoteState() for k in self.meta}
        self.last_volume: dict[tuple[str, int], int | None] = {k: None for k in self.meta}
        self.last_reliable: dict[str, tuple[float | None, int | None]] = {s: (None, None) for s in self.symbols}
        self.pending: dict[int, dict[tuple[str, int], list]] = defaultdict(lambda: defaultdict(list))
        self.pre_window: list = []
        self.pre_window_applied = False
        self.next_bucket = 0
        self.prev_chain: dict[str, dict | None] = {s: None for s in self.symbols}
        self.market_state: dict[str, str | None] = {s: None for s in self.symbols}
        self.gaps: list[list[int | None]] = []

        self.ltt_samples: list[tuple[int, int]] = []
        self.ltt_convention = LTT_UNDETERMINED

        self.stats = {
            "late_events": 0, "unregistered_events": 0, "gap_buckets": 0,
            "no_update_buckets": defaultdict(int), "missing_bid_ask_buckets": defaultdict(int),
            "crossed_buckets": defaultdict(int), "stale_quote_buckets": defaultdict(int),
            "state_changes": [],
        }

    # ---------------------------------------------------------------- input

    def note_disconnect(self, ns: int) -> None:
        if not self.gaps or self.gaps[-1][1] is not None:
            self.gaps.append([ns, None])

    def note_reconnect(self, ns: int) -> None:
        if self.gaps and self.gaps[-1][1] is None:
            self.gaps[-1][1] = ns

    def _sample_ltt(self, receive_ns: int, ev) -> None:
        if self.ltt_convention != LTT_UNDETERMINED or not ev.ltt_epoch:
            return
        self.ltt_samples.append((receive_ns, ev.ltt_epoch))
        if len(self.ltt_samples) >= self.config.ltt_detection_samples:
            self.ltt_convention = detect_ltt_convention(
                self.ltt_samples, self.config.ltt_detection_samples, self.config.ltt_convention_tolerance_s)
            if self.ltt_convention == LTT_UNDETERMINED and len(self.ltt_samples) >= 4 * self.config.ltt_detection_samples:
                self.ltt_samples = self.ltt_samples[-self.config.ltt_detection_samples:]

    def ingest(self, receive_ns: int, ev, is_duplicate: bool) -> None:
        if ev.key not in self.meta:
            self.stats["unregistered_events"] += 1
            return
        self._sample_ltt(receive_ns, ev)
        if receive_ns < self.start_ns:
            self.pre_window.append((receive_ns, ev, is_duplicate))
            return
        if receive_ns >= self.end_ns:
            return
        index = (receive_ns - self.start_ns) // self.bar_ns
        if index < self.next_bucket:
            self.stats["late_events"] += 1
            return
        self.pending[index][ev.key].append((receive_ns, ev, is_duplicate))

    # ---------------------------------------------------------------- output

    def finalize_due(self, now_ns: int) -> dict[str, list[dict]]:
        out = {"hr_ohlc_5s": [], "hr_option_5s": [], "hr_option_transition_state": [], "hr_capture_events": []}
        while self.next_bucket < self.n_buckets:
            bucket_end = self.start_ns + (self.next_bucket + 1) * self.bar_ns
            if bucket_end + self.grace_ns > now_ns:
                break
            self._finalize(self.next_bucket, out)
            self.next_bucket += 1
        return out

    def finalize_all(self) -> dict[str, list[dict]]:
        return self.finalize_due(self.end_ns + self.grace_ns + self.bar_ns)

    def _apply_pre_window(self) -> None:
        """Pre-window packets establish baselines (quotes, cumulative volume,
        OI, liveness) but are never persisted."""
        for receive_ns, ev, is_duplicate in self.pre_window:
            state = self.states[ev.key]
            if is_duplicate:
                state.last_packet_ns = receive_ns
                state.ever_seen = True
                continue
            state.apply(receive_ns, ev)
            if ev.volume is not None:
                self.last_volume[ev.key] = ev.volume
            self._track_reliable(ev.key, state)
        self.pre_window = []
        self.pre_window_applied = True

    def _track_reliable(self, key, state: QuoteState) -> None:
        inst = self.meta[key]
        if inst.instrument_type == INDEX and state.last_price_change_ns is not None:
            self.last_reliable[inst.symbol] = (state.ltp, state.last_price_change_ns)

    def _check_band_edge(self, symbol: str, row: dict, rows: list[dict], bar_ts, out: dict) -> None:
        """HR-1 keeps the band fixed at resolution time. When the observed
        parity ATM reaches the band edge, record it (once per edge) so a
        future milestone can decide whether dynamic resubscription is needed."""
        strike = row["parity_atm_strike"]
        if strike is None:
            return
        offset = next((r["atm_offset"] for r in rows if r["strike"] == strike), None)
        edge = None
        if offset is not None and abs(offset) >= self.config.atm_band_strikes:
            edge = "UPPER" if offset > 0 else "LOWER"
        emitted = self.stats.setdefault("band_edges", [])
        if edge and not any(e["symbol"] == symbol and e["edge"] == edge for e in emitted):
            detail = {"edge": edge, "parity_atm_strike": strike, "band_atm_strike": row["band_atm_strike"]}
            emitted.append({"symbol": symbol, "bar_ts": bar_ts.isoformat(), **detail})
            out["hr_capture_events"].append({"session_id": self.session_id, "event_ts": bar_ts,
                                             "event_type": "BAND_EDGE", "symbol": symbol, "detail": detail})

    def _is_gap(self, start_ns: int, end_ns: int) -> bool:
        return any(s < end_ns and (e is None or e > start_ns) for s, e in self.gaps)

    def _feed(self, key, bucket_end_ns: int, stale_after: float, frozen_after: float) -> dict:
        state = self.states[key]
        since_packet = (bucket_end_ns - state.last_packet_ns) / NS_PER_S if state.last_packet_ns is not None else None
        since_change = (bucket_end_ns - state.last_price_change_ns) / NS_PER_S if state.last_price_change_ns is not None else None
        return {
            "state": state,
            "status": classify_feed_status(state.ever_seen, since_packet, since_change, stale_after, frozen_after),
            "seconds_since_packet": round(since_packet, 3) if since_packet is not None else None,
            "seconds_since_change": round(since_change, 3) if since_change is not None else None,
        }

    def _finalize(self, index: int, out: dict) -> None:
        if not self.pre_window_applied:
            self._apply_pre_window()
        cfg = self.config
        start_ns = self.start_ns + index * self.bar_ns
        end_ns = start_ns + self.bar_ns
        bar_ts = ns_to_ist(start_ns)
        is_gap = self._is_gap(start_ns, end_ns)
        if is_gap:
            self.stats["gap_buckets"] += 1
        bucket = self.pending.pop(index, {})

        option_rows: dict[str, list[dict]] = defaultdict(list)
        packets_by_symbol: dict[str, int] = defaultdict(int)
        futures_volume: dict[str, int | None] = {}

        for key, inst in self.meta.items():
            entries = bucket.get(key, [])
            packets_by_symbol[inst.symbol] += len(entries)
            state = self.states[key]
            prev_oi = state.oi
            unique = [(ns, ev) for ns, ev, dup in entries if not dup]
            oi_observed = False
            for ns, ev, dup in entries:
                if dup:
                    state.last_packet_ns = ns
                    state.ever_seen = True
                elif state.apply(ns, ev):
                    oi_observed = True
            self._track_reliable(key, state)

            bar, self.last_volume[key] = build_bar(unique, self.last_volume[key], self.ltt_convention, is_gap)
            if not unique:
                self.stats["no_update_buckets"][str(key)] += 1
            out["hr_ohlc_5s"].append({
                "session_id": self.session_id, "symbol": inst.symbol, "exchange_segment": inst.exchange_segment,
                "security_id": inst.security_id, "instrument_type": inst.instrument_type, "bar_ts": bar_ts,
                "source": self.source, **bar,
            })

            if inst.instrument_type == FUTIDX:
                futures_volume[inst.symbol] = bar["volume"]
            if inst.instrument_type == OPTIDX:
                row = build_option_row(state, end_ns, len(unique), oi_observed, prev_oi, bar, is_gap,
                                       cfg.option_quote_stale_after_s)
                quality = row["data_quality"]
                if "MISSING_BID_ASK" in quality:
                    self.stats["missing_bid_ask_buckets"][str(key)] += 1
                if "CROSSED" in quality:
                    self.stats["crossed_buckets"][str(key)] += 1
                if "STALE_QUOTE" in quality:
                    self.stats["stale_quote_buckets"][str(key)] += 1
                row.update({
                    "session_id": self.session_id, "symbol": inst.symbol, "exchange_segment": inst.exchange_segment,
                    "security_id": inst.security_id, "expiry": inst.expiry, "strike": inst.strike,
                    "option_type": inst.option_type, "atm_offset": inst.atm_offset, "bar_ts": bar_ts,
                })
                out["hr_option_5s"].append(row)
                option_rows[inst.symbol].append(row)

        for symbol in self.symbols:
            index_key = next((k for k, i in self.meta.items() if i.symbol == symbol and i.instrument_type == INDEX), None)
            fut_key = next((k for k, i in self.meta.items() if i.symbol == symbol and i.instrument_type == FUTIDX), None)
            if index_key is not None:
                f = self._feed(index_key, end_ns, cfg.underlying_stale_after_s, cfg.underlying_frozen_after_s)
                reliable_price, reliable_ns = self.last_reliable[symbol]
                underlying = {
                    "last_price": f["state"].ltp, "status": f["status"],
                    "seconds_since_packet": f["seconds_since_packet"], "seconds_since_change": f["seconds_since_change"],
                    "last_reliable_price": reliable_price,
                    "last_reliable_ts": ns_to_ist(reliable_ns) if reliable_ns is not None else None,
                }
            else:
                underlying = {"last_price": None, "status": "MISSING", "seconds_since_packet": None,
                              "seconds_since_change": None, "last_reliable_price": None, "last_reliable_ts": None}
            if fut_key is not None:
                f = self._feed(fut_key, end_ns, cfg.futures_stale_after_s, cfg.futures_frozen_after_s)
                futures = {"last_price": f["state"].ltp, "status": f["status"], "bid": f["state"].bid,
                           "ask": f["state"].ask, "volume_delta": futures_volume.get(symbol)}
            else:
                futures = {"last_price": None, "status": "MISSING", "bid": None, "ask": None, "volume_delta": None}

            row = build_chain_row(
                option_rows=option_rows[symbol], band_atm_strike=self.band_atm.get(symbol), underlying=underlying,
                futures=futures, prev=self.prev_chain[symbol], symbol_packets=packets_by_symbol[symbol], is_gap=is_gap,
                closing_phase_reached=start_ns >= self.closing_ns, after_window_end=start_ns >= self.end_ns,
                bucket_end_ts=ns_to_ist(end_ns), stale_after_s=cfg.option_quote_stale_after_s,
                min_strikes=cfg.implied_spot_min_strikes,
            )
            row.update({"session_id": self.session_id, "symbol": symbol, "bar_ts": bar_ts})
            out["hr_option_transition_state"].append(row)
            self.prev_chain[symbol] = row
            self._check_band_edge(symbol, row, option_rows[symbol], bar_ts, out)

            if row["market_state"] != self.market_state[symbol]:
                change = {"from": self.market_state[symbol], "to": row["market_state"],
                          "underlying_status": row["underlying_status"], "futures_status": row["futures_status"]}
                self.stats["state_changes"].append({"symbol": symbol, "bar_ts": bar_ts.isoformat(), **change})
                out["hr_capture_events"].append({"session_id": self.session_id, "event_ts": bar_ts,
                                                 "event_type": "STATE_CHANGE", "symbol": symbol, "detail": change})
                self.market_state[symbol] = row["market_state"]
