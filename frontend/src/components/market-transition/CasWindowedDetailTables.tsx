import { Chip, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Tooltip, Typography } from "@mui/material";

import type { PostTransitionMinuteDTO, PreTransitionWindowDTO } from "../../types/marketTransition";

// Shared between CasIntelligencePanel's expand-a-past-day interaction and
// LiveCasTrackerPanel's today-in-progress view -- same two tables, same
// FORECAST INFORMATION / ACTUAL OUTCOME distinction either way.

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

// FORECAST INFORMATION -- 14:30-14:59, six 5-minute windows. Every field
// here is knowable by the window's own end time; nothing from 15:00
// onward appears in this table. `nowTime` (optional, "HH:MM") marks the
// window still in progress as "developing" -- only meaningful for today's
// live view, unused (undefined) for a past, fully-closed day.
export function PreTransitionWindowsTable({ windows, nowTime }: { windows: PreTransitionWindowDTO[]; nowTime?: string }) {
  return (
    <TableContainer sx={{ maxHeight: 280 }}>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            <TableCell>Window</TableCell>
            <TableCell align="right">Close</TableCell>
            <TableCell align="right">Net pts</TableCell>
            <TableCell align="right">Volume</TableCell>
            <TableCell align="right">RVOL%</TableCell>
            <TableCell align="right">Vol accel</TableCell>
            <TableCell>Dominance</TableCell>
            <TableCell align="right">VWAP dist</TableCell>
            <TableCell align="right">POC</TableCell>
            <TableCell align="right">PCR chg</TableCell>
            <TableCell align="right">Opt. pressure</TableCell>
            <TableCell>Regime</TableCell>
            <TableCell>Inst. bias</TableCell>
            <TableCell align="right">News risk</TableCell>
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
                <TableCell align="right">{w.volume_acceleration_ratio !== null ? `${w.volume_acceleration_ratio.toFixed(2)}x` : "N/A"}</TableCell>
                <TableCell>
                  <Chip size="small" label={w.dominant_side} color={dominantSideColor(w.dominant_side)} variant="outlined" sx={{ height: 18 }} />
                </TableCell>
                <TableCell align="right">{fmtSigned(w.price_distance_from_vwap, 1)}</TableCell>
                <TableCell align="right">{fmt(w.poc_at_window_end, 1)}</TableCell>
                <TableCell align="right">{fmtSigned(w.pcr_change, 3)}</TableCell>
                <TableCell align="right">{fmtSigned(w.option_pressure_score, 2)}</TableCell>
                <TableCell>{w.market_regime ?? "N/A"}</TableCell>
                <TableCell>
                  <Typography variant="caption">{w.institutional_bias_label ?? "N/A"}</Typography>
                </TableCell>
                <TableCell align="right">{w.news_risk_score ?? "-"}</TableCell>
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
export function PostTransitionMinutesTable({ minutes }: { minutes: PostTransitionMinuteDTO[] }) {
  return (
    <TableContainer sx={{ maxHeight: 280 }}>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            <TableCell>Minute</TableCell>
            <TableCell align="right">Close</TableCell>
            <TableCell align="right">Price chg</TableCell>
            <TableCell align="right">Volume</TableCell>
            <TableCell align="right">RVOL%</TableCell>
            <TableCell>Dominance</TableCell>
            <TableCell align="right">POC chg</TableCell>
            <TableCell align="right">VWAP chg</TableCell>
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
              <TableCell align="right">{fmtSigned(m.poc_change, 1)}</TableCell>
              <TableCell align="right">{fmtSigned(m.vwap_change, 2)}</TableCell>
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
