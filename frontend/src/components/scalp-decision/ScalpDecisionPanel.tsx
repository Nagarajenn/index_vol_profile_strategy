import {
  Alert, Box, Chip, CircularProgress, Divider, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow,
  TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from "@mui/material";
import { useState } from "react";

import { useScalpDecision, useScalpHistory } from "../../hooks/useScalpDecision";
import { useSymbolStore } from "../../store/useSymbolStore";
import type { ClosingRow, ScalpDecisionDTO, SimPositionHistoryDTO, SimulatedPosition } from "../../types/scalpDecision";

// 12C-scalp-decision-v1. ADVISORY ONLY: rule-based and explainable. This panel has no
// control that can place an order or open/close a position; the 11D exit engine and the
// trader remain authoritative.

const UP = "#2e7d32";
const DOWN = "#c62828";

function num(x: unknown, d = 2): string {
  return typeof x === "number" ? x.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d }) : "–";
}

function signed(x: unknown, d = 2, suffix = ""): string {
  if (typeof x !== "number") return "–";
  return `${x > 0 ? "+" : ""}${x.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d })}${suffix}`;
}

type ChipColor = "success" | "warning" | "error" | "default" | "info";

function decisionStyle(d: string | null | undefined): { bg: string; fg: string } {
  if (d === "BUY_CE") return { bg: "rgba(46,125,50,0.16)", fg: UP };
  if (d === "BUY_PE") return { bg: "rgba(198,40,40,0.16)", fg: DOWN };
  return { bg: "rgba(120,120,120,0.14)", fg: "text.primary" };
}

function actionColor(a: string | null | undefined): ChipColor {
  if (a === "HOLD") return "success";
  if (a === "CAUTION") return "warning";
  if (a === "PREPARE_EXIT" || a === "EXIT") return "error";
  return "default";
}

function riskColor(r: string | null | undefined): ChipColor {
  if (r === "LOW") return "success";
  if (r === "NORMAL") return "default";
  if (r === "ELEVATED") return "warning";
  return "error";
}

function stateColor(v: string): ChipColor {
  if (/BULLISH|CALL_RELATIVE|CE_STRONG|GOOD|EXPANDING|LONG_BUILDUP|RISING|ACCELERATING|LIVE|ACTIVE/.test(v)) return "success";
  if (/BEARISH|PUT_RELATIVE|PE_STRONG|POOR|CONTRACTION|SHORT_BUILDUP|FALLING|MISSING/.test(v)) return "error";
  if (/STALE|MIXED|WEAK|ACCEPTABLE|DECELERATING|EXPANSION|UNCERTAIN/.test(v)) return "warning";
  return "default";
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <Box sx={{ minWidth: 104 }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="body2" sx={{ fontWeight: 600, color }}>{value}</Typography>
    </Box>
  );
}

function EvidenceGrid({ data }: { data: ScalpDecisionDTO }) {
  const row = data.summary?.evidence_row ?? {};
  const ev = data.evidence ?? {};
  const notes: Record<string, string | undefined> = {
    DIRECTION: ev.underlying?.note,
    CE_VS_PE: ev.option_relative?.note,
    CE_MOMENTUM: ev.ce_momentum?.note,
    PE_MOMENTUM: ev.pe_momentum?.note,
    PARTICIPATION: ev.participation?.note,
    OI: ev.oi?.note,
    STRADDLE: ev.straddle?.note,
    LIQUIDITY: `${ev.liquidity_ce?.note ?? ""} ${ev.liquidity_pe?.note ?? ""}`.trim(),
    UNDERLYING_DATA: ev.data_quality?.note,
  };
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>EVIDENCE</Typography>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(3, minmax(0, 1fr))" }, gap: 0.75 }}>
        {Object.entries(row).map(([k, v]) => (
          <Tooltip key={k} title={notes[k] ?? ""} placement="top">
            <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 1 }}>
              <Typography variant="caption" color="text.secondary">{k.replace(/_/g, " ")}</Typography>
              <Chip size="small" color={stateColor(v)} label={v.replace(/_/g, " ")} sx={{ maxWidth: "70%" }} />
            </Box>
          </Tooltip>
        ))}
      </Box>
    </Box>
  );
}

function simRiskColor(r: string | undefined): ChipColor {
  if (r === "NORMAL") return "success";
  if (r === "ELEVATED") return "warning";
  if (r === "HIGH" || r === "STOP_BREACH") return "error";
  return "default";
}

/** The hypothetical position that would exist if the signal had been taken when it appeared.
 * Observability only: nothing here places an order or touches an account. */
function SimulatedPositionBlock({ sim }: { sim: SimulatedPosition }) {
  const c = sim.current;
  const money = (x: number | null | undefined) => (typeof x === "number" ? `₹${num(x, 2)}` : "–");
  const pnlColor = (sim.pnl_per_unit ?? 0) > 0 ? UP : (sim.pnl_per_unit ?? 0) < 0 ? DOWN : undefined;
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>
        IF THIS SIGNAL HAD BEEN TAKEN — hypothetical position (no order, no account)
      </Typography>
      <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 1, alignItems: "flex-start" }}>
        <Stat label="Contract" value={sim.contract} />
        <Stat label="Signal time" value={sim.signal_minute} />
        <Stat label="Buy price (ASK)" value={money(sim.entry_price)} />
        <Stat label="Current LTP" value={money(c.ltp)} />
        <Stat label="Current BID (exit)" value={money(c.bid)} />
        <Stat label="Current ASK" value={money(c.ask)} />
        <Stat label="Quantity" value={sim.quantity ? String(sim.quantity) : "UNKNOWN"} />
        <Stat label="Entry value" value={money(sim.entry_value)} />
        <Stat label="Current value" value={money(sim.current_value)} />
        <Stat label="P&L (on BID)" value={sim.pnl_status === "OK" ? money(sim.pnl) : "unavailable"} color={pnlColor} />
        <Stat label="P&L %" value={sim.pnl_pct === null ? "–" : `${signed(sim.pnl_pct, 2)}%`} color={pnlColor} />
        <Stat label={`Stop loss (${sim.stop_loss_pct}%)`} value={money(sim.stop_loss_price)} />
        <Stat label="Distance to SL" value={sim.distance_to_stop === null ? "–" : `${money(sim.distance_to_stop)} (${num(sim.distance_to_stop_pct, 1)}%)`} />
        <Stat label="Hold time" value={sim.hold_text} />
        <Stat label="MFE / MAE" value={`${money(sim.excursions.mfe)} / ${money(sim.excursions.mae)}`} />
        <Box>
          <Typography variant="caption" color="text.secondary">Position risk</Typography>
          <Box>
            <Chip size="small" color={simRiskColor(sim.risk.risk_state)} label={sim.risk.risk_state.replace("_", " ")} />
          </Box>
        </Box>
      </Stack>
      <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 0.5 }}>
        SINCE SIGNAL {sim.signal_minute}: entry ASK {money(sim.since_signal.entry_ask)} → current BID{" "}
        {money(sim.since_signal.current_bid)} = {signed(sim.since_signal.price_change, 2)} per unit
        {sim.pnl_status === "OK" ? ` (${money(sim.pnl)}, ${signed(sim.pnl_pct, 2)}%)` : " (monetary value unavailable)"}.
        {c.data_status !== "OK" ? ` OPTION DATA: ${c.data_status}.` : ""}
        {sim.quantity_status !== "OK" ? " Quantity unknown, so monetary values are withheld." : ""}
        {sim.stop_breach_minute ? ` Stop breached at ${sim.stop_breach_minute}.` : ""}
      </Typography>
      {sim.risk.reasons.slice(0, 3).map((r) => (
        <Typography key={r} variant="caption" component="div" color="text.secondary">• {r}</Typography>
      ))}
    </Box>
  );
}

function EntryBlock({ data }: { data: ScalpDecisionDTO }) {
  const st = decisionStyle(data.decision);
  const e = data.entry;
  const label = data.decision === "BUY_CE" ? "BUY CE" : data.decision === "BUY_PE" ? "BUY PE" : "WAIT";
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>ENTRY DECISION (no position)</Typography>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ alignItems: { sm: "center" } }}>
        <Box sx={{ px: 3, py: 1.25, borderRadius: 1, bgcolor: st.bg, minWidth: 190, textAlign: "center" }}>
          <Typography variant="h5" sx={{ fontWeight: 800, color: st.fg, letterSpacing: 1 }}>{label}</Typography>
          <Typography variant="caption" color="text.secondary" component="div">Confirmation: {data.confirmation ?? "NONE"}</Typography>
          <Typography variant="caption" color="text.secondary">
            {typeof e?.held_minutes === "number"
              ? e.held_minutes === 0 ? "new this minute" : `held ${e.held_minutes} min`
              : ""}
          </Typography>
        </Box>
        <Box sx={{ flex: 1 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>WHY?</Typography>
          <Typography variant="body2">{data.reason}</Typography>
        </Box>
      </Stack>
      {e && (
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mt: 1 }}>
          {[["Supporting", e.supporting, UP, "✓"], ["Contradicting", e.contradicting, "#ed6c02", "⚠"],
            ["Blocking", e.blocking, DOWN, "✕"]].map(([title, items, color, mark]) => {
            const list = items as [string, string][];
            return list.length ? (
              <Box key={title as string} sx={{ flex: 1 }}>
                <Typography variant="caption" sx={{ fontWeight: 700 }}>{title as string}</Typography>
                {list.map(([cat, text]) => (
                  <Typography key={cat + text} variant="caption" component="div" sx={{ color: color as string }}>
                    {mark as string} {text}
                  </Typography>
                ))}
              </Box>
            ) : null;
          })}
        </Stack>
      )}
    </Box>
  );
}

// 12D. WHERE IN THE MOVE the signal landed -- deliberately its own strip, because "BUY CE while
// CE is already decelerating into an extended move" and "BUY CE at the start of a move" are the
// same decision to the entry engine and very different things to a scalper.
function timingColor(v: string): ChipColor {
  if (v === "GOOD") return "success";
  if (v === "EARLY") return "info";
  if (v === "LATE") return "warning";
  if (v === "EXHAUSTED") return "error";
  return "default";
}

function moveColor(v: string): ChipColor {
  if (/^(ACTIVE|ACCELERATING|RISING|PERSISTENT)$/.test(v)) return "success";
  if (/^(EXTENDING)$/.test(v)) return "info";
  if (/^(SLOWING|DECELERATING|FLAT)$/.test(v)) return "warning";
  if (/^(EXHAUSTING|REVERSING|FALLING)$/.test(v)) return "error";
  return "default";
}

function SignalQualityBlock({ data }: { data: ScalpDecisionDTO }) {
  const s = data.signal_learning;
  if (!s) return null;
  const cells: [string, string, ChipColor, string][] = [
    ["DIRECTION", s.direction || "UNKNOWN", moveColor(s.direction), "The underlying's own direction vote at this minute."],
    ["ENTRY TIMING", s.entry_timing, timingColor(s.entry_timing), s.entry_timing_note],
    ["MOMENTUM", s.momentum_state, moveColor(s.momentum_state), s.momentum_note],
    ["MOVE STATE", s.exhaustion_state, moveColor(s.exhaustion_state), s.exhaustion_note],
    ["SIGNAL AGE", s.signal_age_minutes === null ? "–" : `${s.signal_age_minutes}m`, "default",
      "Minutes this signal state has held. Not the same as a position's hold time."],
  ];
  return (
    <Box>
      <Stack direction="row" spacing={1} sx={{ alignItems: "baseline", mb: 0.5 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>SIGNAL QUALITY</Typography>
        <Typography variant="caption" color="text.secondary">
          12D · where in the move this signal landed{s.is_signal ? "" : " (no BUY this minute)"}
        </Typography>
      </Stack>
      <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 1 }}>
        {cells.map(([label, value, color, note]) => (
          <Tooltip key={label} title={note} placement="top">
            <Box sx={{ minWidth: 132 }}>
              <Typography variant="caption" color="text.secondary" component="div">{label}</Typography>
              <Chip size="small" color={color} label={value.replace(/_/g, " ")} sx={{ fontWeight: 700 }} />
            </Box>
          </Tooltip>
        ))}
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
        Provisional measurement boundaries, not validated quality judgements — they describe where in a move the
        signal arrived, not whether it will work.
      </Typography>
    </Box>
  );
}

function BrakeBlock({ data }: { data: ScalpDecisionDTO }) {
  const r = data.risk_brake;
  if (!r) return null;
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>
        RISK BRAKE (advisory — the 11D exit engine decides)
      </Typography>
      <Stack direction="row" spacing={2} sx={{ alignItems: "center", flexWrap: "wrap", rowGap: 1 }}>
        <Stat label="Position" value={r.position} />
        <Stat label="Source" value={data.position_source === "PAPER_POSITION" ? "open paper position" : "entered by hand"} />
        <Box>
          <Typography variant="caption" color="text.secondary">Risk</Typography>
          <Box><Chip size="small" color={riskColor(r.risk_level)} label={r.risk_level} /></Box>
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary">Action</Typography>
          <Box>
            <Chip color={actionColor(r.risk_action)} label={r.risk_action.replace("_", " ")} sx={{ fontWeight: 700 }} />
          </Box>
        </Box>
        <Typography variant="body2" sx={{ flex: 1 }}>{r.summary}.</Typography>
      </Stack>
      <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mt: 0.5 }}>
        {r.against.length > 0 && (
          <Box sx={{ flex: 1 }}>
            <Typography variant="caption" sx={{ fontWeight: 700 }}>Against position</Typography>
            {r.against.map((x) => (
              <Typography key={x.family + x.text} variant="caption" component="div" sx={{ color: DOWN }}>
                ⚠ [{x.family}] {x.text}
              </Typography>
            ))}
          </Box>
        )}
        {r.supporting.length > 0 && (
          <Box sx={{ flex: 1 }}>
            <Typography variant="caption" sx={{ fontWeight: 700 }}>Supporting</Typography>
            {r.supporting.map((x) => (
              <Typography key={x.family + x.text} variant="caption" component="div" sx={{ color: UP }}>
                ✓ [{x.family}] {x.text}
              </Typography>
            ))}
          </Box>
        )}
      </Stack>
    </Box>
  );
}

/** Every hypothetical position that has already closed today, with the decision that closed it.
 * SIMULATION ONLY: none of these was an order and none touched an account. */
function HistoryBlock({ h }: { h: SimPositionHistoryDTO }) {
  const money = (x: number | null | undefined) => (typeof x === "number" ? `₹${num(x, 2)}` : "–");
  const s = h.summary;
  if (!h.positions.length) {
    return (
      <Box>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>CLOSED HYPOTHETICAL POSITIONS</Typography>
        <Typography variant="body2" color="text.secondary">None closed yet this session.</Typography>
      </Box>
    );
  }
  return (
    <Box sx={{ overflowX: "auto" }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap", rowGap: 1, mb: 0.5 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
          CLOSED HYPOTHETICAL POSITIONS — {h.session_date} (simulation only, never an order)
        </Typography>
        <Chip size="small" variant="outlined" label={h.source === "STORED" ? "stored" : "live replay"} />
        <Typography variant="caption" color="text.secondary">
          {s.positions} closed · {s.wins}W / {s.losses}L · gross{" "}
          <b style={{ color: (s.gross ?? 0) >= 0 ? UP : DOWN }}>{money(s.gross)}</b> · best {money(s.best)} · worst{" "}
          {money(s.worst)} · closed by {Object.entries(s.closed_by).map(([k, v]) => `${k.replace("_", " ")} ${v}`).join(", ")}
        </Typography>
      </Stack>
      <Table size="small" sx={{ "& td, & th": { px: 0.75, py: 0.25, whiteSpace: "nowrap", fontSize: 12 } }}>
        <TableHead>
          <TableRow>
            {["Signal", "Contract", "Conf.", "Entry ASK", "Exit", "Exit BID", "Hold", "P&L", "P&L %", "MFE / MAE",
              "Closed by", "Closing decision", "Risk at exit"].map((x) => <TableCell key={x}>{x}</TableCell>)}
          </TableRow>
        </TableHead>
        <TableBody>
          {h.positions.map((p) => (
            <TableRow key={`${p.signal_minute}-${p.side}-${p.strike}`}>
              <TableCell>{p.signal_minute}</TableCell>
              <TableCell sx={{ color: p.side === "CE" ? UP : DOWN, fontWeight: 600 }}>{p.contract}</TableCell>
              <TableCell>{p.entry_confirmation ?? "–"}</TableCell>
              <TableCell>{money(p.entry_price)}</TableCell>
              <TableCell>{p.exit_minute ?? "–"}</TableCell>
              <TableCell>{money(p.exit_bid)}</TableCell>
              <TableCell>{p.hold_minutes === null ? "–" : `${p.hold_minutes}m`}</TableCell>
              <TableCell sx={{ color: (p.realised_pnl ?? 0) > 0 ? UP : (p.realised_pnl ?? 0) < 0 ? DOWN : undefined, fontWeight: 600 }}>
                {money(p.realised_pnl)}
              </TableCell>
              <TableCell>{p.realised_pnl_pct === null ? "–" : `${signed(p.realised_pnl_pct, 2)}%`}</TableCell>
              <TableCell>{money(p.mfe)} / {money(p.mae)}</TableCell>
              <TableCell>
                <Chip size="small" variant="outlined" label={(p.exit_reason ?? "–").replace("_", " ")} />
              </TableCell>
              <TableCell title={p.closing_reason ?? ""}>
                {p.closing_decision ? `${p.closing_decision.replace("_", " ")}${p.closing_confirmation ? ` (${p.closing_confirmation})` : ""}` : "–"}
              </TableCell>
              <TableCell>{p.risk_state_at_exit ?? "–"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}

function ClosingBlock({ rows }: { rows: ClosingRow[] }) {
  if (!rows.length) return null;
  return (
    <Box sx={{ overflowX: "auto" }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>
        15:15–15:30 OPTION RISK (existing capture — underlying often stale here)
      </Typography>
      <Table size="small" sx={{ "& td, & th": { px: 0.75, py: 0.25, whiteSpace: "nowrap", fontSize: 12 } }}>
        <TableHead>
          <TableRow>
            {["Time", "CE", "PE", "Relative", "CE vol", "PE vol", "CE OI Δ", "PE OI Δ", "Underlying"].map((h) => (
              <TableCell key={h}>{h}</TableCell>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((r) => (
            <TableRow key={r.minute}>
              <TableCell>{r.minute}</TableCell>
              {!r.present ? (
                <TableCell colSpan={8} sx={{ color: "error.main" }}>no option snapshot (not filled)</TableCell>
              ) : (
                <>
                  <TableCell sx={{ color: (r.ce_1m ?? 0) > 0 ? UP : DOWN }}>{num(r.ce_premium)} ({signed(r.ce_1m, 1, "%")})</TableCell>
                  <TableCell sx={{ color: (r.pe_1m ?? 0) > 0 ? UP : DOWN }}>{num(r.pe_premium)} ({signed(r.pe_1m, 1, "%")})</TableCell>
                  <TableCell><Chip size="small" color={stateColor(r.relative ?? "")} label={r.relative} /></TableCell>
                  <TableCell>{signed(r.ce_volume, 0)}</TableCell>
                  <TableCell>{signed(r.pe_volume, 0)}</TableCell>
                  <TableCell>{signed(r.ce_oi, 0)}</TableCell>
                  <TableCell>{signed(r.pe_oi, 0)}</TableCell>
                  <TableCell>{r.underlying_state?.replace("CLOSING_STATE_UNCERTAIN", "UNCERTAIN")}</TableCell>
                </>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}

export function ScalpDecisionPanel({ symbol: fixedSymbol }: { symbol?: string }) {
  const storeSymbol = useSymbolStore((s) => s.selectedSymbol);
  const [chosen, setChosen] = useState<string | null>(null);
  const [date, setDate] = useState("");
  const [posType, setPosType] = useState<string>("NONE");
  const [strike, setStrike] = useState("");
  const symbol = fixedSymbol ?? chosen ?? storeSymbol;
  const position = posType !== "NONE" && Number(strike) > 0 ? { type: posType, strike: Number(strike) } : undefined;
  const { data, isLoading, isError, error } = useScalpDecision(symbol, date || undefined, position);
  const { data: history } = useScalpHistory(symbol, date || undefined, data?.is_live_session ?? false);

  return (
    <Paper sx={{ p: 2, borderLeft: "5px solid", borderColor: data?.decision === "BUY_CE" ? "success.main"
      : data?.decision === "BUY_PE" ? "error.main" : "divider" }}>
      <Stack direction="row" spacing={1} useFlexGap sx={{ alignItems: "center", flexWrap: "wrap", mb: 1 }}>
        <Typography variant="h6" sx={{ fontWeight: 800, flex: "1 1 320px" }}>SCALPING DECISION + RISK BRAKE</Typography>
        <Chip size="small" color="warning" label="ADVISORY ONLY — NO ORDERS" />
        {data && <Chip size="small" variant="outlined" label={`${data.version} · ${data.config_hash}`} />}
        {data && (
          <Chip size="small" color={data.is_live_session ? "success" : "default"}
            label={data.is_live_session ? `LIVE · ${data.minute}` : `${data.session_date} · ${data.minute ?? "–"}`} />
        )}
        {!fixedSymbol && (
          <ToggleButtonGroup size="small" exclusive value={symbol} onChange={(_, v) => v && setChosen(v)}>
            <ToggleButton value="NIFTY">NIFTY</ToggleButton>
            <ToggleButton value="SENSEX">SENSEX</ToggleButton>
          </ToggleButtonGroup>
        )}
        <TextField size="small" type="date" label="Session" value={date} onChange={(e) => setDate(e.target.value)}
          slotProps={{ inputLabel: { shrink: true } }} sx={{ width: 165 }} />
        <ToggleButtonGroup size="small" exclusive value={posType} onChange={(_, v) => v && setPosType(v)}>
          <ToggleButton value="NONE">No position</ToggleButton>
          <ToggleButton value="CE">Hold CE</ToggleButton>
          <ToggleButton value="PE">Hold PE</ToggleButton>
        </ToggleButtonGroup>
        {posType !== "NONE" && (
          <TextField size="small" type="number" label="Strike" value={strike} onChange={(e) => setStrike(e.target.value)}
            sx={{ width: 120 }} />
        )}
      </Stack>

      {isLoading && <Box sx={{ display: "flex", justifyContent: "center", p: 3 }}><CircularProgress size={28} /></Box>}
      {isError && (
        <Alert severity="info">No decision for {symbol}{date ? ` on ${date}` : ""}: {error instanceof Error ? error.message : "unknown error"}</Alert>
      )}
      {data && data.status !== "OK" && <Alert severity="info">{data.reason}</Alert>}
      {data && data.status === "OK" && (
        <Stack spacing={1.5} divider={<Divider flexItem />}>
          <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 1 }}>
            <Stat label="Market" value={data.symbol} />
            <Stat label="Time" value={data.minute ?? "–"} />
            <Stat label="Direction" value={(data.summary?.direction ?? "").replace("UNDERLYING_", "")}
              color={data.summary?.direction?.includes("BULLISH") ? UP : data.summary?.direction?.includes("BEARISH") ? DOWN : undefined} />
            <Stat label="Underlying data" value={data.summary?.underlying_state ?? "–"} />
            <Stat label="Options" value={data.summary?.options ?? "–"} />
            <Stat label="Position" value={data.position_state === "NONE" ? "none" : (data.position_state ?? "").replace("_", " ")} />
            {(data.summary?.data_quality?.length ?? 0) > 0 && (
              <Stat label="Data quality" value={(data.summary?.data_quality ?? []).join(", ")} />
            )}
          </Stack>
          {/* 12D: the two engines are shown as two separate things. With a position open the
              entry call is still displayed, but explicitly as information that does NOT manage
              the position -- a WAIT here is not an instruction to get out. */}
          {data.position_state === "NONE" ? (
            <EntryBlock data={data} />
          ) : (
            <>
              <BrakeBlock data={data} />
              <Box sx={{ opacity: 0.75 }}>
                <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 0.5 }}>
                  ENTRY ENGINE (would I open a NEW position now?) — informational. It does not manage the position
                  above; a WAIT here is not an exit.
                </Typography>
                <EntryBlock data={data} />
              </Box>
            </>
          )}
          <SignalQualityBlock data={data} />
          {data.position_simulation?.open_position && (
            <SimulatedPositionBlock sim={data.position_simulation.open_position} />
          )}
          <EvidenceGrid data={data} />
          {history && <HistoryBlock h={history} />}
          {data.position_state !== "NONE" && (
            <Box>
              <Typography variant="caption" color="text.secondary">
                Two independent engines: POSITION MANAGEMENT decides whether to stay in, the ENTRY ENGINE only
                decides whether a new position is warranted. They are allowed to disagree.
              </Typography>
            </Box>
          )}
          <ClosingBlock rows={data.closing_state} />
        </Stack>
      )}
      <Alert severity="warning" sx={{ mt: 1.5 }}>
        {data?.notice ?? "ADVISORY ONLY."}
      </Alert>
    </Paper>
  );
}
