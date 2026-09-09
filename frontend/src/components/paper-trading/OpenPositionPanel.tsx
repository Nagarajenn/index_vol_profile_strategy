import { Box, Chip, Divider, LinearProgress, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";

import type { PaperPositionDTO } from "../../types/paperTrading";
import { pnlColor, rupees } from "./PaperHeader";

const MAX_HOLD_MINUTES = 19;

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <Box sx={{ minWidth: 108 }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2" sx={{ fontWeight: 600, color }}>
        {value}
      </Typography>
    </Box>
  );
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", {
    timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false,
  });
}

function momentumColor(m: string | null): "success" | "warning" | "error" | "default" {
  if (m === "STRONG") return "success";
  if (m === "MODERATE") return "default";
  if (m === "WEAKENING") return "warning";
  if (m === "FAILED") return "error";
  return "default";
}

export function OpenPositionPanel({ position }: { position: PaperPositionDTO }) {
  const p = position;
  const latest = p.events.length ? p.events[p.events.length - 1] : null;
  const minutesIn = latest?.minutes_in_trade ?? 0;
  const unrealized = latest?.unrealized_pnl ?? null;
  const stopMoved = p.current_stop !== p.initial_stop;
  const targetMoved = p.current_target !== p.initial_target;

  return (
    <Paper sx={{ p: 1.5 }}>
      <Stack direction="row" spacing={1} sx={{ mb: 1, alignItems: "center" }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          Open Paper Position - {p.symbol} {p.strike.toFixed(0)} {p.option_type}
        </Typography>
        <Chip label="OPEN" color="info" size="small" sx={{ fontWeight: 700 }} />
        {latest?.momentum && <Chip label={latest.momentum} color={momentumColor(latest.momentum)} size="small" />}
        <Typography variant="caption" color="text.secondary" sx={{ ml: "auto" }}>
          entered {fmtTime(p.entry_timestamp)} - simulated
        </Typography>
      </Stack>

      <Stack direction="row" spacing={2} sx={{ mb: 1, flexWrap: "wrap" }}>
        <Stat label="Entry (ASK)" value={p.entry_price.toFixed(2)} />
        <Stat label="Quantity" value={`${p.quantity}`} />
        <Stat label="Capital" value={rupees(p.capital_allocated)} />
        <Stat label="Current Bid" value={latest?.option_bid?.toFixed(2) ?? "--"} />
        <Stat label="Unrealized" value={rupees(unrealized)} color={pnlColor(unrealized)} />
        <Stat label="MFE" value={p.mfe_pct === null ? "--" : `${p.mfe_pct.toFixed(1)}%`} />
        <Stat label="MAE" value={p.mae_pct === null ? "--" : `${p.mae_pct.toFixed(1)}%`} />
      </Stack>

      <Box sx={{ mb: 1 }}>
        <Typography variant="caption" color="text.secondary">
          Time in trade: {minutesIn} / {MAX_HOLD_MINUTES} min (hard force-exit at {MAX_HOLD_MINUTES})
        </Typography>
        <LinearProgress
          variant="determinate"
          value={Math.min(100, (minutesIn / MAX_HOLD_MINUTES) * 100)}
          sx={{ height: 6, borderRadius: 3 }}
        />
      </Box>

      <Divider sx={{ my: 1 }} />
      <Typography variant="caption" sx={{ fontWeight: 700, textTransform: "uppercase" }}>
        Dynamic Management
      </Typography>
      <Stack direction="row" spacing={2} sx={{ mb: 0.5, flexWrap: "wrap" }}>
        <Stat label="Original SL" value={p.initial_stop.toFixed(2)} />
        <Stat label="Current SL" value={p.current_stop.toFixed(2)} color={stopMoved ? "success.main" : undefined} />
        <Stat label="Original Target" value={p.initial_target.toFixed(2)} />
        <Stat label="Current Target" value={p.current_target.toFixed(2)} color={targetMoved ? "warning.main" : undefined} />
      </Stack>
      <Typography variant="caption" color="text.secondary">
        {latest?.note || "Awaiting the first management minute."}
        {stopMoved ? " (a stop may only tighten, never widen)" : ""}
      </Typography>

      {p.events.length > 0 && (
        <>
          <Divider sx={{ my: 1 }} />
          <Typography variant="caption" sx={{ fontWeight: 700, textTransform: "uppercase" }}>
            Management Events
          </Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Time</TableCell>
                <TableCell>Min</TableCell>
                <TableCell>Event</TableCell>
                <TableCell align="right">Underlying</TableCell>
                <TableCell align="right">Bid</TableCell>
                <TableCell align="right">Unrealized</TableCell>
                <TableCell>Momentum</TableCell>
                <TableCell>Note</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {p.events.map((e) => (
                <TableRow key={e.event_timestamp}>
                  <TableCell>{fmtTime(e.event_timestamp)}</TableCell>
                  <TableCell>{e.minutes_in_trade}</TableCell>
                  <TableCell>{e.event_type}</TableCell>
                  <TableCell align="right">{e.underlying_price?.toFixed(0) ?? "--"}</TableCell>
                  <TableCell align="right">{e.option_bid?.toFixed(2) ?? "--"}</TableCell>
                  <TableCell align="right" sx={{ color: pnlColor(e.unrealized_pnl) }}>
                    {rupees(e.unrealized_pnl)}
                  </TableCell>
                  <TableCell>{e.momentum ?? "--"}</TableCell>
                  <TableCell sx={{ maxWidth: 320 }}>{e.note}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </Paper>
  );
}
