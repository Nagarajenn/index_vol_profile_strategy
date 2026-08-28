import { Chip, Divider, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Tooltip, Typography } from "@mui/material";

import type {
  CasDailyResultDTO,
  ConfidenceLabel,
  PostTransitionMinuteDTO,
  PreTransitionWindowDTO,
  TransitionForecastDTO,
} from "../../types/marketTransition";

// Shared between CasIntelligencePanel's daily table, CasDayDetailPage's
// dedicated full-page view, and LiveCasTrackerPanel's today-in-progress
// view -- same two tables, same FORECAST INFORMATION / ACTUAL OUTCOME
// distinction, same transition-type/magnitude labeling everywhere.

export const TRANSITION_TYPE_LABELS: Record<CasDailyResultDTO["transition_type"], string> = {
  CONTINUATION_UP: "Continuation (Up)",
  CONTINUATION_DOWN: "Continuation (Down)",
  REVERSAL_UP: "Reversal (Up)",
  REVERSAL_DOWN: "Reversal (Down)",
  POST_WINDOW_INITIATION_UP: "Post-Window Move (Up)",
  POST_WINDOW_INITIATION_DOWN: "Post-Window Move (Down)",
  NO_MATERIAL_TRANSITION: "No Material Transition",
};

export function transitionTypeColor(t: CasDailyResultDTO["transition_type"]): "success" | "error" | "info" | "default" {
  if (t === "CONTINUATION_UP" || t === "CONTINUATION_DOWN") return "success";
  if (t === "REVERSAL_UP" || t === "REVERSAL_DOWN") return "error";
  // A genuinely distinct 3rd category -- no pre-window trend to reverse or
  // continue, but a real post-window move -- exactly what used to be
  // indistinguishable from a quiet day under the old "Neutral" label.
  if (t === "POST_WINDOW_INITIATION_UP" || t === "POST_WINDOW_INITIATION_DOWN") return "info";
  return "default"; // NO_MATERIAL_TRANSITION
}

export function magnitudeTierColor(tier: CasDailyResultDTO["magnitude_tier"]): "default" | "info" | "warning" | "error" {
  if (tier === "EXTREME") return "error";
  if (tier === "LARGE") return "warning";
  if (tier === "MODERATE") return "info";
  return "default"; // NORMAL or null
}

export function confidenceColor(label: ConfidenceLabel | null): "success" | "primary" | "warning" | "default" {
  if (label === "Strong") return "success";
  if (label === "Moderate") return "primary";
  if (label === "Weak") return "warning";
  return "default";
}

export function ForecastVsActualStrip({ forecast, day }: { forecast: TransitionForecastDTO | undefined; day: CasDailyResultDTO }) {
  if (!forecast) return null;
  return (
    <Paper variant="outlined" sx={{ p: 1, mt: 1 }}>
      <Typography variant="caption" sx={{ fontWeight: 700, display: "block", mb: 0.5 }}>
        14:59 Forecast vs. What Actually Happened
      </Typography>
      <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 0.5, alignItems: "center" }}>
        <Typography variant="caption">No material: {(forecast.probability_no_material_transition * 100).toFixed(0)}%</Typography>
        <Typography variant="caption">Large up: {(forecast.probability_large_up * 100).toFixed(0)}%</Typography>
        <Typography variant="caption">Large down: {(forecast.probability_large_down * 100).toFixed(0)}%</Typography>
        <Typography variant="caption">Reversal: {(forecast.probability_reversal * 100).toFixed(0)}%</Typography>
        <Typography variant="caption">Continuation: {(forecast.probability_continuation * 100).toFixed(0)}%</Typography>
        <Chip size="small" label={forecast.confidence_label} color={confidenceColor(forecast.confidence_label)} variant="outlined" />
        <Typography variant="caption" color="text.secondary">
          (n={forecast.n_analogs})
        </Typography>
        <Divider orientation="vertical" flexItem />
        <Typography variant="caption" sx={{ fontWeight: 700 }}>
          Actual: {TRANSITION_TYPE_LABELS[day.transition_type]}
          {day.magnitude_tier && ` (${day.magnitude_tier})`}
        </Typography>
      </Stack>
    </Paper>
  );
}

export function fmtSigned(v: number | null, digits = 2): string {
  if (v === null) return "N/A";
  const s = v.toFixed(digits);
  return v > 0 ? `+${s}` : s;
}

export function fmt(v: number | null, digits = 2): string {
  return v === null ? "N/A" : v.toFixed(digits);
}

export function dominantSideColor(side: PreTransitionWindowDTO["dominant_side"]): "success" | "error" | "default" {
  if (side === "buy") return "success";
  if (side === "sell") return "error";
  return "default";
}

export function shockScoreColor(score: number): "default" | "info" | "warning" | "error" {
  if (score >= 70) return "error";
  if (score >= 40) return "warning";
  if (score >= 15) return "info";
  return "default";
}

// Fixed pixel widths for the columns both tables share. Same column ORDER
// alone isn't enough to keep them visually lined up -- these are two
// separate <Table>s with different trailing columns (Vol accel/Regime/
// Inst. bias here vs. Range exp./Shock there), so each table's own
// auto-layout sizes its shared columns independently and they drift
// apart. table-layout: fixed + identical explicit widths on every shared
// column removes that drift, so "VWAP dist" sits directly above "VWAP
// chg", "POC" above "POC chg", etc.
const SHARED_COL_WIDTHS = {
  time: 112,
  close: 90,
  priceChg: 84,
  volume: 96,
  rvol: 70,
  dominance: 90,
  vwap: 84,
  poc: 84,
  pcrChg: 84,
  optPressure: 100,
};

// News risk (max classified-event severity in the trailing window before
// each window's close) is a real, occasionally-populated signal, but is
// "-" on the vast majority of windows (most 5-min stretches simply have
// no news event in them) -- dropped from the table per user feedback, not
// shown at all rather than shown mostly-empty. Still computed/returned by
// cas_windows.py and present on the DTO; just not rendered here.
const PRE_ONLY_COL_WIDTHS = { volAccel: 84, regime: 90, instBias: 110 };
const POST_ONLY_COL_WIDTHS = { rangeExp: 80, shock: 70 };

const SHARED_TOTAL_WIDTH = Object.values(SHARED_COL_WIDTHS).reduce((a, b) => a + b, 0);
// Explicit total table width, not "auto" -- with table-layout:fixed, an
// "auto"-width table wider than its container gets shrunk by the CSS
// shrink-to-fit algorithm, compressing every <col> below its declared
// px value (proportionally, and by a DIFFERENT factor per table since
// they have different trailing-column totals) -- which was the actual
// cause of the misalignment the col-width fix alone didn't solve. An
// explicit width forces the browser to honor it exactly and, if it
// doesn't fit, scroll horizontally instead of silently compressing.
const PRE_TABLE_WIDTH = SHARED_TOTAL_WIDTH + Object.values(PRE_ONLY_COL_WIDTHS).reduce((a, b) => a + b, 0);
const POST_TABLE_WIDTH = SHARED_TOTAL_WIDTH + Object.values(POST_ONLY_COL_WIDTHS).reduce((a, b) => a + b, 0);

// FORECAST INFORMATION -- 14:30-14:59, six 5-minute windows. Every field
// here is knowable by the window's own end time; nothing from 15:00
// onward appears in this table. `nowTime` (optional, "HH:MM") marks the
// window still in progress as "developing" -- only meaningful for today's
// live view, unused (undefined) for a past, fully-closed day.
export function PreTransitionWindowsTable({
  windows,
  nowTime,
  maxTableHeight = 280,
}: {
  windows: PreTransitionWindowDTO[];
  nowTime?: string;
  maxTableHeight?: number;
}) {
  return (
    <TableContainer sx={{ maxHeight: maxTableHeight }}>
      {/* Column widths come from <colgroup>/<col>, not TableCell sx --
          with table-layout:fixed, a TableCell's declared width can still
          get silently overridden to fit its own header text. The table
          itself gets an EXPLICIT pixel width (PRE_TABLE_WIDTH, the exact
          sum of its own columns), not "auto" -- an "auto"-width table
          wider than its container is shrunk by the CSS shrink-to-fit
          algorithm, compressing every <col> below its declared px value
          by a different factor per table (this one has 4 more trailing
          columns than PostTransitionMinutesTable, so it alone hit that
          cap) -- which was the actual cause of the misalignment. An
          explicit width is honored exactly; the TableContainer scrolls
          horizontally instead if it doesn't fit. Passed as a raw `style`
          prop, not `sx`, since MUI's .MuiTable-root class sets width:100%
          with higher specificity than an sx-emitted class. */}
      <Table size="small" stickyHeader sx={{ tableLayout: "fixed" }} style={{ width: PRE_TABLE_WIDTH, maxWidth: "none" }}>
        <colgroup>
          <col style={{ width: SHARED_COL_WIDTHS.time }} />
          <col style={{ width: SHARED_COL_WIDTHS.close }} />
          <col style={{ width: SHARED_COL_WIDTHS.priceChg }} />
          <col style={{ width: SHARED_COL_WIDTHS.volume }} />
          <col style={{ width: SHARED_COL_WIDTHS.rvol }} />
          <col style={{ width: SHARED_COL_WIDTHS.dominance }} />
          <col style={{ width: SHARED_COL_WIDTHS.vwap }} />
          <col style={{ width: SHARED_COL_WIDTHS.poc }} />
          <col style={{ width: SHARED_COL_WIDTHS.pcrChg }} />
          <col style={{ width: SHARED_COL_WIDTHS.optPressure }} />
          <col style={{ width: PRE_ONLY_COL_WIDTHS.volAccel }} />
          <col style={{ width: PRE_ONLY_COL_WIDTHS.regime }} />
          <col style={{ width: PRE_ONLY_COL_WIDTHS.instBias }} />
        </colgroup>
        <TableHead>
          <TableRow>
            <TableCell>Window</TableCell>
            <TableCell align="right">Close</TableCell>
            <TableCell align="right">Price chg</TableCell>
            <TableCell align="right">Volume</TableCell>
            <TableCell align="right">RVOL%</TableCell>
            <TableCell>Dominance</TableCell>
            <TableCell align="right">
              <Tooltip title="Distance from VWAP at this window's close (absolute level, points) -- not a change.">
                <span>VWAP dist</span>
              </Tooltip>
            </TableCell>
            <TableCell align="right">
              <Tooltip title="Session POC at this window's close (absolute price level) -- not a change.">
                <span>POC</span>
              </Tooltip>
            </TableCell>
            <TableCell align="right">PCR chg</TableCell>
            <TableCell align="right">Opt. pressure</TableCell>
            <TableCell align="right">Vol accel</TableCell>
            <TableCell>Regime</TableCell>
            <TableCell>Inst. bias</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {windows.map((w) => {
            const windowEnd = w.window_label.split("-")[1]; // "14:30-14:34" -> "14:34"
            const developing = nowTime !== undefined && nowTime < windowEnd;
            return (
              <TableRow key={w.window_index} hover sx={w.data_quality_flag ? { opacity: 0.6 } : undefined}>
                <TableCell sx={{ whiteSpace: "nowrap" }}>
                  {w.window_label}
                  {developing && <Chip size="small" label="developing" color="info" variant="outlined" sx={{ ml: 0.5, height: 16 }} />}
                </TableCell>
                <TableCell align="right">{fmt(w.close, 2)}</TableCell>
                <TableCell align="right">{fmtSigned(w.net_point_change, 2)}</TableCell>
                <TableCell align="right">{w.volume.toLocaleString()}</TableCell>
                <TableCell align="right">{fmt(w.rvol_pct, 0)}</TableCell>
                <TableCell>
                  <Chip size="small" label={w.dominant_side} color={dominantSideColor(w.dominant_side)} variant="outlined" sx={{ height: 18 }} />
                </TableCell>
                <TableCell align="right">{fmtSigned(w.price_distance_from_vwap, 1)}</TableCell>
                <TableCell align="right">{fmt(w.poc_at_window_end, 1)}</TableCell>
                <TableCell align="right">{fmtSigned(w.pcr_change, 3)}</TableCell>
                <TableCell align="right">{fmtSigned(w.option_pressure_score, 2)}</TableCell>
                <TableCell align="right">{w.volume_acceleration_ratio !== null ? `${w.volume_acceleration_ratio.toFixed(2)}x` : "N/A"}</TableCell>
                <TableCell>{w.market_regime ?? "N/A"}</TableCell>
                <TableCell>
                  <Typography variant="caption">{w.institutional_bias_label ?? "N/A"}</Typography>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

// ACTUAL OUTCOME -- 15:00-15:15, sixteen native 1-minute rows. This is
// what actually happened; a forecast-vs-actual strip elsewhere reads it,
// never the other way around.
export function PostTransitionMinutesTable({
  minutes,
  maxTableHeight = 280,
}: {
  minutes: PostTransitionMinuteDTO[];
  maxTableHeight?: number;
}) {
  return (
    <TableContainer sx={{ maxHeight: maxTableHeight }}>
      {/* See the matching comment in PreTransitionWindowsTable for why
          column widths are set via <colgroup>/<col> and why the table
          gets an explicit pixel width (POST_TABLE_WIDTH) as a raw
          `style` prop rather than `sx`/"auto". */}
      <Table size="small" stickyHeader sx={{ tableLayout: "fixed" }} style={{ width: POST_TABLE_WIDTH, maxWidth: "none" }}>
        <colgroup>
          <col style={{ width: SHARED_COL_WIDTHS.time }} />
          <col style={{ width: SHARED_COL_WIDTHS.close }} />
          <col style={{ width: SHARED_COL_WIDTHS.priceChg }} />
          <col style={{ width: SHARED_COL_WIDTHS.volume }} />
          <col style={{ width: SHARED_COL_WIDTHS.rvol }} />
          <col style={{ width: SHARED_COL_WIDTHS.dominance }} />
          <col style={{ width: SHARED_COL_WIDTHS.vwap }} />
          <col style={{ width: SHARED_COL_WIDTHS.poc }} />
          <col style={{ width: SHARED_COL_WIDTHS.pcrChg }} />
          <col style={{ width: SHARED_COL_WIDTHS.optPressure }} />
          <col style={{ width: POST_ONLY_COL_WIDTHS.rangeExp }} />
          <col style={{ width: POST_ONLY_COL_WIDTHS.shock }} />
        </colgroup>
        <TableHead>
          <TableRow>
            <TableCell>Minute</TableCell>
            <TableCell align="right">Close</TableCell>
            <TableCell align="right">Price chg</TableCell>
            <TableCell align="right">Volume</TableCell>
            <TableCell align="right">RVOL%</TableCell>
            <TableCell>Dominance</TableCell>
            <TableCell align="right">
              <Tooltip title="Change in distance from VWAP during this minute (delta, points) -- the pre-transition table shows the absolute distance instead, since it's a single snapshot at each window's close rather than a minute-over-minute delta.">
                <span>VWAP chg</span>
              </Tooltip>
            </TableCell>
            <TableCell align="right">
              <Tooltip title="Change in session POC during this minute (delta, points) -- the pre-transition table shows the absolute POC level instead, for the same reason.">
                <span>POC chg</span>
              </Tooltip>
            </TableCell>
            <TableCell align="right">PCR chg</TableCell>
            <TableCell align="right">Opt. pressure</TableCell>
            <TableCell align="right">Range exp.</TableCell>
            <TableCell>Shock</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {minutes.map((m) => (
            <TableRow key={m.minute_offset} hover sx={m.data_quality_flag ? { opacity: 0.6 } : undefined}>
              <TableCell sx={{ whiteSpace: "nowrap" }}>{m.minute_time}</TableCell>
              <TableCell align="right">{fmt(m.close, 2)}</TableCell>
              <TableCell align="right">{fmtSigned(m.price_change, 2)}</TableCell>
              <TableCell align="right">{m.volume.toLocaleString()}</TableCell>
              <TableCell align="right">{fmt(m.rvol_pct, 0)}</TableCell>
              <TableCell>
                <Chip size="small" label={m.dominant_side} color={dominantSideColor(m.dominant_side)} variant="outlined" sx={{ height: 18 }} />
              </TableCell>
              <TableCell align="right">{fmtSigned(m.vwap_change, 2)}</TableCell>
              <TableCell align="right">{fmtSigned(m.poc_change, 1)}</TableCell>
              <TableCell align="right">{fmtSigned(m.pcr_change, 3)}</TableCell>
              <TableCell align="right">{fmtSigned(m.option_pressure_score, 2)}</TableCell>
              <TableCell align="right">{m.range_expansion.toFixed(1)}x</TableCell>
              <TableCell>
                <Tooltip title="Deterministic 0-100 composite: ATR-normalized move, RVOL, range expansion, buy/sell dominance, option pressure.">
                  <Chip size="small" label={m.transition_shock_score.toFixed(0)} color={shockScoreColor(m.transition_shock_score)} />
                </Tooltip>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
