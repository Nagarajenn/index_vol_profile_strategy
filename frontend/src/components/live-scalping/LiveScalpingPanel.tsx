import {
  Alert, Box, Chip, CircularProgress, Divider, Paper, Stack, Table, TableBody, TableCell,
  TableHead, TableRow, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from "@mui/material";
import { useState } from "react";

import { useLiveScalping } from "../../hooks/useLiveScalping";
import { useSymbolStore } from "../../store/useSymbolStore";
import type { LivePositionCard, LiveScalpingDTO } from "../../types/liveScalping";

// 13A-live-scalping-engine-v1. DECISION SUPPORT ONLY: this panel has no control that can place,
// modify or cancel an order, and no broker path exists behind the endpoint it reads.

const UP = "#2e7d32";
const DOWN = "#c62828";
type ChipColor = "success" | "warning" | "error" | "default" | "info";

function rs(v: number | null | undefined, d = 2): string {
  return typeof v === "number"
    ? `₹${v.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d })}`
    : "–";
}
function num(v: number | null | undefined, d = 2): string {
  return typeof v === "number" ? v.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d }) : "–";
}
function pct(v: number | null | undefined, d = 2): string {
  return typeof v === "number" ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "–";
}

function regimeColor(v: string | null): ChipColor {
  if (v === "TRENDING_UP" || v === "TRENDING_DOWN") return "success";
  if (v === "RANGE") return "warning";
  if (v === "REVERSING") return "error";
  return "default";
}
function okColor(v: boolean | null | undefined): ChipColor {
  return v === true ? "success" : v === false ? "error" : "default";
}
function timingColor(v: string | null): ChipColor {
  if (v === "NORMAL") return "success";
  if (v === "EARLY") return "info";
  if (v === "EXTENDED") return "error";
  return "default";
}
function ivColor(v: string | null): ChipColor {
  if (v === "IV_TAILWIND") return "success";
  if (v === "IV_HEADWIND") return "error";
  if (v === "IV_NEUTRAL") return "default";
  return "default";
}
function qualityColor(q: string): ChipColor {
  if (q === "A") return "success";
  if (q === "B") return "info";
  if (q === "C") return "warning";
  return "default";
}
function decisionStyle(d: string): { bg: string; fg: string; label: string } {
  if (d === "BUY_CE") return { bg: "rgba(46,125,50,0.16)", fg: UP, label: "BUY CE" };
  if (d === "BUY_PE") return { bg: "rgba(198,40,40,0.16)", fg: DOWN, label: "BUY PE" };
  return { bg: "rgba(120,120,120,0.14)", fg: "text.primary", label: "WAIT" };
}

function Stat({ label, value, color, hint }: { label: string; value: string; color?: string; hint?: string }) {
  const body = (
    <Box sx={{ minWidth: 118 }}>
      <Typography variant="caption" color="text.secondary" component="div">{label}</Typography>
      <Typography variant="body2" sx={{ fontWeight: 600, color }}>{value}</Typography>
    </Box>
  );
  return hint ? <Tooltip title={hint} placement="top">{body}</Tooltip> : body;
}

/** Spec 20: the market read, as chips, before the decision. */
function MarketState({ d }: { d: LiveScalpingDTO }) {
  const p = d.panel;
  const cells: [string, string, ChipColor, string][] = [
    ["REGIME", (p.regime ?? "UNKNOWN").replace(/_/g, " "), regimeColor(p.regime), p.regime_note ?? ""],
    ["DIRECTION", p.underlying_confirmed === null ? "–" : p.underlying_confirmed ? "CONFIRMED" : "NOT CONFIRMED",
      okColor(p.underlying_confirmed), p.direction_note ?? ""],
    ["OPTION", p.option_confirmed === null ? "–" : p.option_confirmed ? `${p.option_categories.length}/4 AGREE` : "NOT CONFIRMED",
      okColor(p.option_confirmed), p.option_note ?? ""],
    ["ENTRY TIMING", (p.entry_timing ?? "–").replace(/_/g, " "), timingColor(p.entry_timing), p.entry_timing_note ?? ""],
    ["IV", (p.iv_state ?? "–").replace(/IV_/, ""), ivColor(p.iv_state),
      `IV change into the signal: ${pct(p.iv_change_pct)}. An IV headwind downgrades quality; it never rejects on its own.`],
    ["SPREAD", p.spread_pct === null ? "–" : `${p.spread_pct.toFixed(2)}%`, okColor(p.spread_ok),
      `Judged relative to premium, never as a fixed rupee amount.`],
    ["ECONOMICS", p.economics_ratio === null ? "–" : `${p.economics_ratio.toFixed(1)}×`, okColor(p.economics_ok),
      p.economics_note ?? ""],
    ["TRADE QUALITY", d.quality, qualityColor(d.quality), "A: all gates clean · B: one risk flag · C: several · NO TRADE: a gate failed."],
  ];
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.75 }}>MARKET STATE</Typography>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4, minmax(0,1fr))" }, gap: 1 }}>
        {cells.map(([k, v, c, note]) => (
          <Tooltip key={k} title={note} placement="top">
            <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 1 }}>
              <Typography variant="caption" color="text.secondary">{k}</Typography>
              <Chip size="small" color={c} label={v} sx={{ fontWeight: 700, maxWidth: "68%" }} />
            </Box>
          </Tooltip>
        ))}
      </Box>
    </Box>
  );
}

/** Spec 22: the four money numbers must never be confused with one another. */
function RiskBrake({ d }: { d: LiveScalpingDTO }) {
  const r = d.risk;
  const locked = r.state === "LOCKED";
  return (
    <Box>
      <Stack direction="row" spacing={1} sx={{ alignItems: "baseline", mb: 0.75 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>RISK BRAKE</Typography>
        <Chip size="small" color={locked ? "error" : "success"} label={r.state} sx={{ fontWeight: 800 }} />
      </Stack>
      <Stack direction="row" spacing={2.5} sx={{ flexWrap: "wrap", rowGap: 1 }}>
        <Stat label="Allocated capital" value={rs(r.allocated_capital, 0)}
              hint="Money set aside for the experiment. This is NOT the loss limit." />
        <Stat label="Daily loss limit" value={rs(-r.max_daily_loss, 0)} color={DOWN}
              hint="The most the day may lose before trading locks. Separate from allocated capital." />
        <Stat label="Daily P&L (realised)" value={rs(r.daily_realised_pnl)}
              color={r.daily_realised_pnl >= 0 ? UP : DOWN}
              hint="Realised only. The lockout is driven by realised losses, not unrealised." />
        <Stat label="Remaining daily risk" value={rs(r.remaining_daily_risk)}
              hint="Daily loss limit minus realised losses." />
        <Stat label="Unrealised" value={rs(r.daily_unrealised_pnl)}
              color={r.daily_unrealised_pnl >= 0 ? UP : DOWN} />
        <Stat label="Consecutive losses" value={`${r.consecutive_losses} / ${r.max_consecutive_losses}`}
              color={r.consecutive_losses >= r.max_consecutive_losses ? DOWN : undefined} />
        <Stat label="Trades today" value={`${r.trades_today} / ${r.max_trades_per_day}`} />
        <Stat label="Position value" value={`${rs(r.open_position_value, 0)} / ${rs(r.max_position_value, 0)}`} />
      </Stack>
      {locked && (
        <Alert severity="error" sx={{ mt: 1 }}>
          <b>TRADING LOCKED.</b> {r.lock_reasons.join("; ")}. New entries are disabled; an open position is still managed.
        </Alert>
      )}
    </Box>
  );
}

/** Spec 21. */
function PositionCard({ p }: { p: LivePositionCard }) {
  const pnl = p.pnl ?? 0;
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.75 }}>
        HYPOTHETICAL POSITION <Chip size="small" label="SIMULATION — never an order" sx={{ ml: 1 }} />
      </Typography>
      <Stack direction="row" spacing={2.5} sx={{ flexWrap: "wrap", rowGap: 1 }}>
        <Stat label="Contract" value={p.contract ?? "–"} />
        <Stat label="Quality" value={p.quality ?? "–"} />
        <Stat label="Entry ASK" value={num(p.entry_ask)} hint="Entry always fills at the ASK." />
        <Stat label="Current BID" value={num(p.current_bid)} hint="Marked on the BID — what a seller receives." />
        <Stat label="Current LTP" value={num(p.current_ltp)} />
        <Stat label="Quantity" value={String(p.quantity ?? "–")} />
        <Stat label="Entry value" value={rs(p.entry_value, 0)} />
        <Stat label="Current value" value={rs(p.current_value, 0)} />
        <Stat label="P&L" value={rs(p.pnl)} color={pnl >= 0 ? UP : DOWN} />
        <Stat label="P&L %" value={pct(p.pnl_pct)} color={pnl >= 0 ? UP : DOWN} />
        <Stat label="Stop loss" value={num(p.stop_loss)} hint="Set once at entry. It is never widened or moved." />
        <Stat label="Distance to stop" value={`${num(p.distance_to_stop)} (${pct(p.distance_to_stop_pct)})`} />
        <Stat label="MFE" value={rs(p.mfe)} color={UP} />
        <Stat label="MAE" value={rs(p.mae)} color={DOWN} />
        <Stat label="Hold" value={`${p.hold_minutes ?? "–"}m`} />
      </Stack>
    </Box>
  );
}

function ClosedTable({ rows }: { rows: LivePositionCard[] }) {
  if (!rows.length) return null;
  const total = rows.reduce((a, r) => a + (r.realised_pnl ?? 0), 0);
  return (
    <Box>
      <Stack direction="row" spacing={1} sx={{ alignItems: "baseline", mb: 0.5 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>CLOSED (SIMULATION)</Typography>
        <Typography variant="caption" color="text.secondary">
          {rows.length} · gross <b style={{ color: total >= 0 ? UP : DOWN }}>{rs(total)}</b>
        </Typography>
      </Stack>
      <Table size="small">
        <TableHead>
          <TableRow>{["Signal", "Contract", "Q", "Entry ASK", "Exit BID", "Exit", "Hold", "P&L"].map((h) => (
            <TableCell key={h} sx={{ fontWeight: 700 }}>{h}</TableCell>))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((r, i) => (
            <TableRow key={`${r.signal_minute}-${i}`}>
              <TableCell>{r.signal_minute}</TableCell>
              <TableCell>{r.contract}</TableCell>
              <TableCell>{r.quality}</TableCell>
              <TableCell>{num(r.entry_ask)}</TableCell>
              <TableCell>{num((r as never as { exit_bid?: number }).exit_bid)}</TableCell>
              <TableCell>{(r.exit_reason ?? "").replace(/_/g, " ")}</TableCell>
              <TableCell>{r.hold_minutes}m</TableCell>
              <TableCell sx={{ color: (r.realised_pnl ?? 0) >= 0 ? UP : DOWN, fontWeight: 600 }}>
                {rs(r.realised_pnl)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}

function WhyNot({ d }: { d: LiveScalpingDTO }) {
  if (!d.primary_rejection_reason) return null;
  return (
    <Box sx={{ flex: 1 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>WHY NOT?</Typography>
      <Chip size="small" color="default" label={d.primary_rejection_reason.replace(/_/g, " ")}
            sx={{ fontWeight: 700, mb: 0.5 }} />
      <Typography variant="body2" color="text.secondary">{d.reason_note}</Typography>
    </Box>
  );
}

export function LiveScalpingPanel({ symbol: fixed }: { symbol?: string }) {
  const stored = useSymbolStore((s) => s.selectedSymbol);
  const [override, setOverride] = useState<string | null>(null);
  const [sessionDate, setSessionDate] = useState<string>("");
  const symbol = fixed ?? override ?? stored;
  const { data, isLoading, isError, error } = useLiveScalping(symbol, sessionDate || undefined);

  if (isLoading) return <Paper sx={{ p: 3, display: "flex", justifyContent: "center" }}><CircularProgress /></Paper>;
  if (isError || !data) {
    return <Alert severity="warning">13A is not available{error instanceof Error ? `: ${error.message}` : ""}.</Alert>;
  }
  const st = decisionStyle(data.decision);
  const rv = data.daily_review;

  return (
    <Paper sx={{ p: 1.5, width: "100%" }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap", mb: 1 }}>
        <Typography variant="h6" sx={{ fontWeight: 800 }}>SCALPING DECISION + RISK BRAKE</Typography>
        <Chip size="small" color="warning" label="DECISION SUPPORT — NO ORDERS" sx={{ fontWeight: 700 }} />
        <Chip size="small" variant="outlined" label={`${data.version} · ${data.config_hash}`} />
        <Chip size="small" color={data.is_live_session ? "success" : "default"}
              label={data.is_live_session ? `LIVE · ${data.minute}` : `${data.session_date} · ${data.minute}`} />
        <Box sx={{ ml: "auto", display: "flex", gap: 1, alignItems: "center" }}>
          {!fixed && (
            <ToggleButtonGroup size="small" exclusive value={symbol}
                               onChange={(_, v) => v && setOverride(v)}>
              <ToggleButton value="NIFTY">NIFTY</ToggleButton>
              <ToggleButton value="SENSEX">SENSEX</ToggleButton>
            </ToggleButtonGroup>
          )}
          <TextField size="small" type="date" label="Session"
                     slotProps={{ inputLabel: { shrink: true } }} sx={{ width: 165 }}
                     value={sessionDate} onChange={(e) => setSessionDate(e.target.value)} />
        </Box>
      </Stack>

      <Stack spacing={1.5} divider={<Divider flexItem />}>
        <MarketState d={data} />

        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ alignItems: { sm: "center" } }}>
          <Box sx={{ px: 3, py: 1.25, borderRadius: 1, bgcolor: st.bg, minWidth: 190, textAlign: "center" }}>
            <Typography variant="h5" sx={{ fontWeight: 800, color: st.fg, letterSpacing: 1 }}>{st.label}</Typography>
            <Typography variant="caption" color="text.secondary" component="div">
              Quality: {data.quality}
            </Typography>
          </Box>
          {data.decision === "WAIT" ? <WhyNot d={data} /> : (
            <Box sx={{ flex: 1 }}>
              <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>ORDER DETAIL (you decide)</Typography>
              <Stack direction="row" spacing={2.5} sx={{ flexWrap: "wrap", rowGap: 1 }}>
                <Stat label="Contract" value={data.panel.contract ?? "–"} />
                <Stat label="ASK" value={num(data.panel.ask)} />
                <Stat label="Quantity" value={String(data.panel.quantity ?? "–")} />
                <Stat label="Entry value" value={rs(data.panel.entry_value, 0)} />
                <Stat label="Delta" value={num(data.panel.delta, 3)} />
                <Stat label="IV" value={num(data.panel.iv, 2)} />
              </Stack>
              <Typography variant="caption" color="text.secondary">{data.reason_note}</Typography>
            </Box>
          )}
        </Stack>

        <RiskBrake d={data} />
        {data.open_position && <PositionCard p={data.open_position} />}
        <ClosedTable rows={data.closed_positions} />

        {rv && (
          <Box>
            <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>SESSION REVIEW</Typography>
            <Stack direction="row" spacing={2.5} sx={{ flexWrap: "wrap", rowGap: 1 }}>
              <Stat label="BUY CE / BUY PE" value={`${rv.buy_ce} / ${rv.buy_pe}`} />
              <Stat label="WAIT" value={String(rv.wait)} />
              <Stat label="Trades" value={`${rv.trades} (${rv.wins}W / ${rv.losses}L)`} />
              <Stat label="Realised" value={rs(rv.realised_pnl)} color={rv.realised_pnl >= 0 ? UP : DOWN} />
              <Stat label="Max drawdown" value={rs(rv.max_drawdown)} color={DOWN} />
              <Stat label="Rejected: RANGE" value={String(rv.rejected_range)} />
              <Stat label="Rejected: EXTENDED" value={String(rv.rejected_extended)} />
              <Stat label="Rejected: spread / economics" value={`${rv.rejected_spread} / ${rv.rejected_economics}`} />
              <Stat label="Rejected: risk lock" value={String(rv.rejected_risk_lock)} />
            </Stack>
          </Box>
        )}
      </Stack>

      <Alert severity="warning" sx={{ mt: 1.5 }}>{data.notice}</Alert>
    </Paper>
  );
}
