import {
  Alert, Box, Chip, CircularProgress, Divider, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField,
  ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import { Fragment, useState } from "react";

import { useOptionRiskClosingState } from "../../hooks/useOptionRisk";
import { useSymbolStore } from "../../store/useSymbolStore";
import type { LtpPoint, OptionRiskClosingStateDTO, OptionRiskMinute, PositionRisk } from "../../types/optionRisk";

// 12B-option-risk-v1. ADVISORY / RESEARCH ONLY: this section only reads data.
// It has no control that can open, close or modify a position; the 11D exit
// engine remains authoritative.

const CE_COLOR = "#2e7d32";
const PE_COLOR = "#c62828";
const STRADDLE_COLOR = "#1565c0";

function num(x: number | null | undefined, d = 2): string {
  return x === null || x === undefined ? "–" : x.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
}

function signed(x: number | null | undefined, d = 2, suffix = ""): string {
  if (x === null || x === undefined) return "–";
  return `${x > 0 ? "+" : ""}${x.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d })}${suffix}`;
}

function signColor(x: number | null | undefined): string | undefined {
  if (x === null || x === undefined || x === 0) return undefined;
  return x > 0 ? CE_COLOR : PE_COLOR;
}

type ChipColor = "success" | "warning" | "error" | "default" | "info";

function underlyingColor(state: string, newPrint: boolean): ChipColor {
  if (newPrint) return "info";
  if (state === "LIVE") return "success";
  if (state === "STALE") return "warning";
  if (state === "MISSING") return "error";
  return "default";
}

function riskColor(r: string | undefined): ChipColor {
  if (r === "LOW") return "success";
  if (r === "NORMAL") return "default";
  if (r === "ELEVATED") return "warning";
  if (r === "HIGH" || r === "EXTREME") return "error";
  return "default";
}

function pressureColor(l: string | undefined): ChipColor {
  if (l === "UP") return "success";
  if (l === "DOWN") return "error";
  if (l === "MIXED") return "warning";
  return "default";
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <Box sx={{ minWidth: 118 }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="body2" sx={{ fontWeight: 600, color }}>{value}</Typography>
    </Box>
  );
}

// ---------------------------------------------------------------- tiny SVG line chart (no chart dependency)
interface Series { name: string; color: string; values: (number | null)[]; dashed?: boolean }

function MiniLineChart({ title, labels, series, unit, splitAt, decimals = 1, meta, full = false, valueArrows = false,
  zeroBaseline = true, labelLatest = false, tailTicks = 0 }: {
  title: string; labels: string[]; series: Series[]; unit: string; splitAt?: string; decimals?: number;
  meta?: (i: number) => string | null; full?: boolean; valueArrows?: boolean; zeroBaseline?: boolean;
  labelLatest?: boolean; tailTicks?: number;
}) {
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null);
  const W = full ? 1100 : 520, H = full ? 190 : 170, L = 46, R = 8, T = 10, B = tailTicks > 0 ? 34 : 22;
  const vals = series.flatMap((s) => s.values.filter((v): v is number => v !== null));
  if (!vals.length) {
    return (
      <Paper variant="outlined" sx={{ p: 1, flex: 1, minWidth: 300 }}>
        <Typography variant="caption" sx={{ fontWeight: 700 }}>{title}</Typography>
        <Typography variant="body2" color="text.secondary">No data.</Typography>
      </Paper>
    );
  }
  // A change/flow chart is read against zero; a price chart is read against its own range.
  let lo = zeroBaseline ? Math.min(0, ...vals) : Math.min(...vals);
  let hi = zeroBaseline ? Math.max(0, ...vals) : Math.max(...vals);
  if (hi === lo) { hi += 1; lo -= 1; }
  if (!zeroBaseline) { const pad = (hi - lo) * 0.08; lo -= pad; hi += pad; }
  const x = (i: number) => L + (i * (W - L - R)) / Math.max(1, labels.length - 1);
  const y = (v: number) => T + ((hi - v) * (H - T - B)) / (hi - lo);
  const split = splitAt ? labels.indexOf(splitAt) : -1;
  const path = (vs: (number | null)[]) => {
    let d = "", pen = false;
    vs.forEach((v, i) => {
      if (v === null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };
  // Pointer -> nearest minute. The SVG scales to its box, so the pointer is mapped back into viewBox units.
  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const vx = ((e.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(labels.length - 1, Math.round(((vx - L) / (W - L - R)) * (labels.length - 1))));
    setHover({ i, x: e.clientX - r.left, y: e.clientY - r.top });
  };
  const fmt = (v: number) => `${v.toLocaleString("en-IN", { maximumFractionDigits: decimals, minimumFractionDigits: decimals })}${unit}`;
  // Only the latest reading is written on the chart (small), with its change against the previous
  // reading. Everything else stays on hover.
  const withValue = labelLatest && series[0] ? series[0].values.map((v, i) => ({ v, i })).filter((p) => p.v !== null) : [];
  const latest = withValue.length ? withValue[withValue.length - 1] : null;
  const prevValue = withValue.length > 1 ? withValue[withValue.length - 2] : null;
  const latestDelta = latest && prevValue ? (latest.v as number) - (prevValue.v as number) : null;
  const tailFrom = tailTicks > 0 ? Math.max(0, labels.length - tailTicks) : labels.length;
  return (
    <Paper variant="outlined" sx={{ p: 1, flex: 1, minWidth: 300, position: "relative" }}>
      <Typography variant="caption" sx={{ fontWeight: 700 }}>{title}</Typography>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={title}
        onMouseMove={onMove} onMouseLeave={() => setHover(null)} style={{ cursor: "crosshair" }}>
        {split >= 0 && <rect x={x(split)} y={T} width={W - R - x(split)} height={H - T - B} fill="rgba(255,152,0,0.08)" />}
        {zeroBaseline && <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} stroke="#999" strokeDasharray="3 3" />}
        <text x={L - 4} y={y(hi) + 4} fontSize="10" textAnchor="end" fill="currentColor">{hi.toFixed(decimals)}{unit}</text>
        <text x={L - 4} y={y(lo)} fontSize="10" textAnchor="end" fill="currentColor">{lo.toFixed(decimals)}{unit}</text>
        {labels.map((lb, i) => (i % 5 === 0 && i < tailFrom - 2 ? (   // keep clear of the per-minute tail
          <text key={lb} x={x(i)} y={H - B + 12} fontSize="10" textAnchor="middle" fill="currentColor">{lb}</text>
        ) : null))}
        {labels.slice(tailFrom).map((lb, k) => {
          const i = tailFrom + k;   // every minute of the last stretch, written vertically so they fit
          return (
            // anchored at the bottom with textAnchor="end", so the rotated label hangs in the
            // margin below the axis instead of running up into the plot
            <text key={`t${lb}`} x={x(i)} y={H - B + 2} fontSize="8" textAnchor="end" fill="currentColor"
              transform={`rotate(-90 ${x(i)} ${H - B + 2})`}>{lb}</text>
          );
        })}
        {split >= 0 && <text x={x(split) + 3} y={T + 10} fontSize="9" fill="#e65100">underlying stale / option continuation →</text>}
        {series.map((s) => (
          <path key={s.name} d={path(s.values)} fill="none" stroke={s.color} strokeWidth={1.8} strokeDasharray={s.dashed ? "5 3" : undefined} />
        ))}
        {latest && (
          <g>
            <circle cx={x(latest.i)} cy={y(latest.v as number)} r={2.6} fill={series[0].color} stroke="#fff" strokeWidth={0.8} />
            <text x={x(latest.i) - 6} y={y(latest.v as number) - 5} fontSize="9" textAnchor="end" fontWeight={700}
              fill={series[0].color}>
              {fmt(latest.v as number)}
              <tspan fill={latestDelta === null ? "#888" : latestDelta > 0 ? CE_COLOR : latestDelta < 0 ? PE_COLOR : "#888"}>
                {latestDelta === null ? "" : ` ${latestDelta > 0 ? "▲" : latestDelta < 0 ? "▼" : "▬"}${signed(latestDelta, decimals)}`}
              </tspan>
            </text>
          </g>
        )}
        {hover && (
          <>
            <line x1={x(hover.i)} x2={x(hover.i)} y1={T} y2={H - B} stroke="#888" strokeWidth={1} />
            {series.map((s) => {
              const v = s.values[hover.i];
              return v === null || v === undefined ? null : (
                <circle key={s.name} cx={x(hover.i)} cy={y(v)} r={3} fill={s.color} stroke="#fff" strokeWidth={1} />
              );
            })}
          </>
        )}
      </svg>
      {hover && (
        <Paper elevation={6} sx={{
          position: "absolute", left: Math.min(hover.x + 12, 240), top: Math.max(hover.y - 8, 0), px: 1, py: 0.5,
          pointerEvents: "none", zIndex: 5, minWidth: 130,
        }}>
          <Typography variant="caption" sx={{ fontWeight: 700 }}>{labels[hover.i]}</Typography>
          {meta?.(hover.i) && (
            <Typography variant="caption" component="div" color="text.secondary">{meta(hover.i)}</Typography>
          )}
          {series.map((s) => {
            const v = s.values[hover.i];
            // arrow against the previous minute that actually has a value (a gap is not a move)
            const prev = valueArrows ? s.values.slice(0, hover.i).reverse().find((x) => x !== null) ?? null : null;
            const d = v !== null && v !== undefined && prev !== null && prev !== undefined ? v - prev : null;
            return (
              <Typography key={s.name} variant="caption" component="div" sx={{ color: s.color, fontWeight: 600 }}>
                {s.name}: {v === null || v === undefined ? "no data" : fmt(v)}
                {d === null ? "" : ` ${d > 0 ? "▲" : d < 0 ? "▼" : "▬"} ${signed(d, decimals)}`}
              </Typography>
            );
          })}
        </Paper>
      )}
      <Stack direction="row" spacing={1.5}>
        {series.map((s) => (
          <Typography key={s.name} variant="caption" sx={{ color: s.color, fontWeight: 600 }}>— {s.name}</Typography>
        ))}
      </Stack>
    </Paper>
  );
}

/** Chain-link one-minute % changes of the SAME contract into a cumulative % path, so an ATM strike change
 * between minutes never shows up as a fake jump. A missing minute breaks the chain (no interpolation). */
function chainLink(rows: OptionRiskMinute[], pick: (r: OptionRiskMinute) => number | null | undefined): (number | null)[] {
  let level: number | null = 0;
  return rows.map((r, i) => {
    if (i === 0) return r.snapshot_present ? 0 : null;
    const c = pick(r);
    if (!r.snapshot_present || c === null || c === undefined) { level = null; return null; }
    if (level === null) { level = 0; return 0; }
    level = ((1 + level / 100) * (1 + c / 100) - 1) * 100;
    return level;
  });
}

// ---------------------------------------------------------------- blocks
function UnderlyingStrip({ rows, data }: { rows: OptionRiskMinute[]; data: OptionRiskClosingStateDTO }) {
  const s = data.summary;
  const group = (seg: string, title: string, tint: string) => (
    <Box sx={{ flex: 1, p: 1, borderRadius: 1, bgcolor: tint }}>
      <Typography variant="caption" sx={{ fontWeight: 700 }}>{title}</Typography>
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 0.5 }}>
        {rows.filter((r) => r.segment === seg).map((r) => {
          const u = r.underlying;
          const label = u.new_print ? "NEW PRINT" : u.state.replace("CLOSING_STATE_UNCERTAIN", "UNCERTAIN");
          // outlined = no option snapshot captured that minute (the underlying state is still shown)
          return (
            <Chip key={r.minute} size="small" variant={r.snapshot_present ? "filled" : "outlined"}
              color={underlyingColor(u.state, u.new_print)}
              label={`${r.minute} ${label}${r.snapshot_present ? "" : " · no option snapshot"}`}
              title={u.value !== null ? `print ${num(u.value)}` : "no print"} />
          );
        })}
      </Box>
    </Box>
  );
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>UNDERLYING STATUS</Typography>
      <Stack direction={{ xs: "column", md: "row" }} spacing={1}>
        {group("ACTUAL_UNDERLYING", "15:00–15:15 · ACTUAL UNDERLYING", "rgba(46,125,50,0.06)")}
        {group("CLOSING_STALE_UNDERLYING_OPTION_CONTINUATION", "15:15–15:30 · CLOSING / STALE UNDERLYING + OPTION CHAIN CONTINUATION", "rgba(255,152,0,0.08)")}
      </Stack>
      <Stack direction="row" spacing={2} sx={{ mt: 1, flexWrap: "wrap", rowGap: 1 }}>
        <Stat label="Last reliable underlying" value={num(s.last_reliable_underlying)} />
        <Stat label="Last reliable time" value={s.last_reliable_minute ?? "–"} />
        <Stat label="Current time (latest snapshot)" value={s.latest_minute ?? "–"} />
        <Stat label="Age" value={s.underlying_age_minutes === null || s.underlying_age_minutes === undefined ? "–" : `${s.underlying_age_minutes} min`} />
        <Stat label="State" value={s.underlying_state ?? "–"} />
        <Stat label="Next new print" value={s.new_print_minute ? `${s.new_print_minute} · ${num(s.new_print_value)}` : "not yet"} />
      </Stack>
    </Box>
  );
}

function PressureTable({ rows }: { rows: OptionRiskMinute[] }) {
  const risk = (r: OptionRiskMinute) => r.position_risk[0];
  return (
    <Box sx={{ overflowX: "auto" }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>OPTION CHAIN PRESSURE (ATM, one row per minute)</Typography>
      <Table size="small" sx={{ "& td, & th": { px: 0.75, py: 0.25, whiteSpace: "nowrap", fontSize: 12 } }}>
        <TableHead>
          <TableRow>
            {["Time", "ATM", "CE", "CE Δ%", "PE", "PE Δ%", "PCR", "CE OI Δ", "PE OI Δ", "CE Vol Δ", "PE Vol Δ", "CE IV", "PE IV",
              "Straddle", "Pressure", "Underlying", "Implied spot", "Risk"].map((h) => <TableCell key={h}>{h}</TableCell>)}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((r) => (
            <Fragment key={r.minute}>
              {r.minute === "15:15" && (
                <TableRow>
                  <TableCell colSpan={18} sx={{ bgcolor: "rgba(255,152,0,0.12)", fontWeight: 700 }}>
                    15:15 → 15:30 · closing / stale underlying — option chain continuation
                  </TableCell>
                </TableRow>
              )}
              {!r.snapshot_present ? (
                <TableRow>
                  <TableCell>{r.minute}</TableCell>
                  <TableCell colSpan={17} sx={{ color: "error.main" }}>MISSING option snapshot — not interpolated, not filled</TableCell>
                </TableRow>
              ) : (
                <TableRow>
                  <TableCell>{r.minute}</TableCell>
                  <TableCell>{r.atm_strike ?? "–"}</TableCell>
                  <TableCell>{num(r.ce.mid)}</TableCell>
                  <TableCell sx={{ color: signColor(r.ce.premium_change_pct), fontWeight: 600 }}>{signed(r.ce.premium_change_pct, 2, "%")}</TableCell>
                  <TableCell>{num(r.pe.mid)}</TableCell>
                  <TableCell sx={{ color: signColor(r.pe.premium_change_pct === null || r.pe.premium_change_pct === undefined ? null : -r.pe.premium_change_pct), fontWeight: 600 }}>
                    {signed(r.pe.premium_change_pct, 2, "%")}
                  </TableCell>
                  <TableCell>{num(r.trajectory?.pcr?.value, 3)}</TableCell>
                  <TableCell>{signed(r.ce.intraday_oi_change, 0)}</TableCell>
                  <TableCell>{signed(r.pe.intraday_oi_change, 0)}</TableCell>
                  <TableCell>{signed(r.ce.volume_change, 0)}</TableCell>
                  <TableCell>{signed(r.pe.volume_change, 0)}</TableCell>
                  <TableCell>{r.ce.greeks_status === "VALID" ? num(r.ce.iv) : "INVALID"}</TableCell>
                  <TableCell>{r.pe.greeks_status === "VALID" ? num(r.pe.iv) : "INVALID"}</TableCell>
                  <TableCell>{num(r.trajectory?.straddle?.value)}</TableCell>
                  <TableCell><Chip size="small" color={pressureColor(r.pressure.label)} label={r.pressure.label} /></TableCell>
                  <TableCell>{r.underlying.state === "LIVE" ? num(r.underlying.value) : `${r.underlying.state.replace("CLOSING_STATE_UNCERTAIN", "UNCERTAIN")}`}</TableCell>
                  <TableCell title={`quality ${r.implied.quality}`}>{r.implied.implied_spot === null ? "INVALID" : num(r.implied.implied_spot)}</TableCell>
                  <TableCell>{risk(r) ? <Chip size="small" color={riskColor(risk(r).risk_state)} label={risk(r).risk_state} /> : "–"}</TableCell>
                </TableRow>
              )}
            </Fragment>
          ))}
        </TableBody>
      </Table>
    </Box>
  );
}

/** One side's last-traded-price chart. Price only, with an arrow against the previous minute;
 * the hover readout carries just the time and that minute's ATM strike. */
function LtpChart({ side, points }: { side: "CE" | "PE"; points: LtpPoint[] }) {
  const labels = points.map((p) => p.minute);
  const values = points.map((p) => (side === "CE" ? p.ce_ltp : p.pe_ltp) ?? null);
  const color = side === "CE" ? CE_COLOR : PE_COLOR;
  return (
    <Box sx={{ flex: 1, minWidth: 300, position: "relative" }}>
      <MiniLineChart
        title={`ATM ${side} last traded price (each minute's ATM contract)`}
        labels={labels} unit="" splitAt="15:15" decimals={2} valueArrows zeroBaseline={false} labelLatest tailTicks={5}
        meta={(i) => (points[i]?.atm_strike ? `ATM ${points[i].atm_strike}` : "no ATM resolved")}
        series={[{ name: `${side} LTP`, color, values }]} />
    </Box>
  );
}

function Charts({ rows, ltp }: { rows: OptionRiskMinute[]; ltp: LtpPoint[] }) {
  const labels = rows.map((r) => r.minute);
  // The ATM contract can change from minute to minute, so a line steps when it does.
  // The hover readout names the strike for that minute, which is what explains a step.
  const strikeAt = (i: number) => (rows[i]?.atm_strike ? `ATM ${rows[i].atm_strike}` : "no ATM resolved");
  return (
    <Stack spacing={1}>
      <Stack direction={{ xs: "column", lg: "row" }} spacing={1}>
        <LtpChart side="CE" points={ltp} />
        <LtpChart side="PE" points={ltp} />
      </Stack>
    <Stack direction={{ xs: "column", lg: "row" }} spacing={1}>
      <MiniLineChart title="CE vs PE premium % since 15:00 (ATM, chain-linked) + ATM straddle %" labels={labels} unit="%"
        splitAt="15:15" decimals={2} meta={strikeAt}
        series={[
          { name: "CE %", color: CE_COLOR, values: chainLink(rows, (r) => r.ce.premium_change_pct) },
          { name: "PE %", color: PE_COLOR, values: chainLink(rows, (r) => r.pe.premium_change_pct) },
          { name: "Straddle %", color: STRADDLE_COLOR, dashed: true, values: chainLink(rows, (r) => r.trajectory?.straddle?.chg_1m) },
        ]} />
      <MiniLineChart title="Intraday OI change per minute (ATM, consecutive snapshots)" labels={labels} unit=""
        splitAt="15:15" decimals={0} meta={strikeAt}
        series={[
          { name: "CE OI Δ", color: CE_COLOR, values: rows.map((r) => r.ce.intraday_oi_change ?? null) },
          { name: "PE OI Δ", color: PE_COLOR, values: rows.map((r) => r.pe.intraday_oi_change ?? null) },
        ]} />
      <MiniLineChart title="Volume traded per minute (ATM)" labels={labels} unit=""
        splitAt="15:15" decimals={0} meta={strikeAt}
        series={[
          { name: "CE volume", color: CE_COLOR, values: rows.map((r) => r.ce.volume_change ?? null) },
          { name: "PE volume", color: PE_COLOR, values: rows.map((r) => r.pe.volume_change ?? null) },
        ]} />
    </Stack>
    </Stack>
  );
}

function PositionRiskBlock({ data, rows }: { data: OptionRiskClosingStateDTO; rows: OptionRiskMinute[] }) {
  const latest = [...rows].reverse().find((r) => r.snapshot_present);
  if (!data.positions.length) {
    return (
      <Box>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>MARKET OPTION STATE (no paper position this session)</Typography>
        {latest && (
          <Stack spacing={0.5} sx={{ mt: 0.5 }}>
            <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 1 }}>
              <Chip size="small" color={pressureColor(latest.pressure.label)} label={`Option pressure ${latest.pressure.label}`} />
              <Chip size="small" label={latest.market_state.replace(/_/g, " ")} />
              <Chip size="small" variant="outlined" label={latest.combination_state.replace(/_/g, " ")} />
            </Stack>
            {(latest.pressure.up_evidence?.length ?? 0) > 0 && (
              <Typography variant="caption">UP evidence: {latest.pressure.up_evidence?.join(" · ")}</Typography>
            )}
            {(latest.pressure.down_evidence?.length ?? 0) > 0 && (
              <Typography variant="caption">DOWN evidence: {latest.pressure.down_evidence?.join(" · ")}</Typography>
            )}
          </Stack>
        )}
      </Box>
    );
  }
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>POSITION RISK (ADVISORY — the 11D exit engine remains authoritative)</Typography>
      {data.positions.map((p) => {
        const trail = rows.map((r) => r.position_risk.find((x) => x.position_label === p.label)).filter((x): x is PositionRisk => !!x);
        const cur = trail[trail.length - 1];
        return (
          <Paper key={p.label} variant="outlined" sx={{ p: 1, mt: 0.5 }}>
            <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 1 }}>
              <Stat label="Position" value={`BUY ${data.symbol} ${p.option_type} ${p.strike}`} />
              <Stat label="Held" value={`${p.entry_minute} → ${p.exit_minute ?? "open"}`} />
              <Stat label="Current option" value={cur ? `₹${num(cur.own_mid)}` : "–"} />
              <Stat label="Option support" value={cur?.position_support ?? "–"} />
              <Box>
                <Typography variant="caption" color="text.secondary">Risk / Action</Typography>
                <Stack direction="row" spacing={0.5}>
                  <Chip size="small" color={riskColor(cur?.risk_state)} label={cur?.risk_state ?? "–"} />
                  <Chip size="small" variant="outlined" label={cur ? cur.risk_action.replace("_", " / ") : "–"} />
                </Stack>
              </Box>
            </Stack>
            {cur && (
              <Box component="ul" sx={{ m: 0, mt: 0.5, pl: 2 }}>
                {cur.reasons.map((x) => <li key={x}><Typography variant="caption">{x}</Typography></li>)}
              </Box>
            )}
            {!cur && <Typography variant="caption" color="text.secondary">Position is outside the 15:00–15:30 window shown.</Typography>}
          </Paper>
        );
      })}
    </Box>
  );
}

function ClosingStateBlock({ data }: { data: OptionRiskClosingStateDTO }) {
  const s = data.summary;
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>CLOSING STATE 15:15 → 15:30</Typography>
      <Stack direction="row" spacing={2} sx={{ mt: 0.5, flexWrap: "wrap", rowGap: 1 }}>
        <Stat label="Underlying" value={s.underlying_state ?? "–"} />
        <Stat label="Options" value={s.options_state ?? "–"} />
        <Stat label="Option-derived state" value={s.option_derived_state ?? "–"} />
        <Stat label="Implied spot (research)" value={s.implied_spot === null || s.implied_spot === undefined ? `INVALID` : num(s.implied_spot)} />
        <Stat label="Gap vs last reliable" value={`${signed(s.implied_gap_points, 1)} (${signed(s.implied_gap_percent, 3, "%")})`}
          color={signColor(s.implied_gap_points)} />
        <Stat label="Confidence" value={s.confidence ?? "UNKNOWN"} />
        <Stat label="Stale minutes / options active" value={`${s.stale_minutes ?? 0} / ${s.options_active_while_stale ?? 0}`} />
        <Stat label="Missing option minutes" value={s.missing_option_minutes?.length ? s.missing_option_minutes.join(", ") : "none"} />
      </Stack>
    </Box>
  );
}

// ---------------------------------------------------------------- panel
export function OptionRiskClosingPanel({ symbol: fixedSymbol }: { symbol?: string }) {
  const storeSymbol = useSymbolStore((s) => s.selectedSymbol);
  const [chosen, setChosen] = useState<string | null>(null);
  const [date, setDate] = useState<string>("");
  const symbol = fixedSymbol ?? chosen ?? storeSymbol;
  const { data, isLoading, isError, error } = useOptionRiskClosingState(symbol, date || undefined);
  const rows = data?.minutes ?? [];

  return (
    <Paper sx={{ p: 2 }}>
      <Stack direction="row" spacing={1} useFlexGap sx={{ alignItems: "center", flexWrap: "wrap", mb: 1 }}>
        <Typography variant="h6" sx={{ fontWeight: 700, flex: "1 1 340px" }}>15:15–15:30 OPTION RISK &amp; CLOSING STATE</Typography>
        <Chip size="small" color="warning" label="ADVISORY ONLY" />
        {data && <Chip size="small" variant="outlined" label={`${data.version} · ${data.config_hash}`} />}
        {data && <Chip size="small" color={data.is_live_session ? "success" : "default"} label={data.is_live_session ? `LIVE · as of ${data.as_of}` : `SESSION ${data.session_date}`} />}
        {!fixedSymbol && (
          <ToggleButtonGroup size="small" exclusive value={symbol} onChange={(_, v) => v && setChosen(v)}>
            <ToggleButton value="NIFTY">NIFTY</ToggleButton>
            <ToggleButton value="SENSEX">SENSEX</ToggleButton>
          </ToggleButtonGroup>
        )}
        <TextField size="small" type="date" label="Session" value={date} onChange={(e) => setDate(e.target.value)}
          slotProps={{ inputLabel: { shrink: true } }} sx={{ width: 170 }} />
      </Stack>

      {isLoading && <Box sx={{ display: "flex", justifyContent: "center", p: 3 }}><CircularProgress size={28} /></Box>}
      {isError && (
        <Alert severity="info">No option-chain data for {symbol}{date ? ` on ${date}` : ""}: {error instanceof Error ? error.message : "unknown error"}</Alert>
      )}
      {data && rows.length === 0 && (
        <Alert severity="info">No minutes to show yet for {data.session_date} — the view covers 15:00–15:30 IST.</Alert>
      )}
      {data && rows.length > 0 && (
        <Stack spacing={1.5} divider={<Divider flexItem />}>
          <UnderlyingStrip rows={rows} data={data} />
          <PositionRiskBlock data={data} rows={rows} />
          <ClosingStateBlock data={data} />
          <Charts rows={rows} ltp={data.ltp_series ?? []} />
          <PressureTable rows={rows} />
        </Stack>
      )}
      <Alert severity="warning" sx={{ mt: 1.5 }}>
        {data?.caveat ?? "Research / advisory only."} Historical research (milestone12b report) found the warning ladder is not selective and
        option pressure did not beat a simple base rate for the next print, so treat these states as a description, not a signal.
      </Alert>
    </Paper>
  );
}
