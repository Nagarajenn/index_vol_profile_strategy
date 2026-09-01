import { Box, Chip, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Tooltip, Typography } from "@mui/material";

import { useSessionAmd } from "../../hooks/useSessionAmd";
import type { CurrentPhase, DistributionStatus } from "../../types/sessionAmd";

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Box sx={{ minWidth: 150 }}>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body1" sx={{ fontWeight: 600 }}>
        {value}
      </Typography>
      {sub && (
        <Typography variant="caption" color="text.secondary">
          {sub}
        </Typography>
      )}
    </Box>
  );
}

function phaseColor(phase: CurrentPhase, distributionDirection?: "up" | "down"): "success" | "error" | "warning" | "info" | "default" {
  if (phase === "Distribution") return distributionDirection === "down" ? "error" : "success";
  if (phase === "Testing Range") return "warning";
  if (phase === "Breakout (not manipulation)") return "info";
  return "default";
}

function statusColor(status: DistributionStatus): "success" | "warning" | "error" {
  if (status === "Confirmed") return "success";
  if (status === "Developing") return "warning";
  return "error";
}

function fmtTime(iso: string): string {
  // Backend timestamps are UTC ISO strings -- render in IST, matching
  // every other live-session panel in this app.
  return new Date(iso).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
}

function fmtPrice(v: number): string {
  return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export function SessionAmdPanel({ symbol }: { symbol: string }) {
  const { data, isLoading, isError } = useSessionAmd(symbol);

  return (
    <Paper sx={{ p: 1.5 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
        Session AMD (Accumulation / Manipulation / Distribution)
      </Typography>

      {isLoading && (
        <Typography variant="body2" color="text.secondary">
          Loading...
        </Typography>
      )}
      {isError && !isLoading && (
        <Typography variant="body2" color="text.secondary">
          Not enough data yet for this symbol.
        </Typography>
      )}

      {data && (
        <Stack spacing={1.5}>
          <Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              Accumulation Range
            </Typography>
            {data.accumulation ? (
              <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 1, alignItems: "center" }}>
                <Typography variant="body1" sx={{ fontWeight: 600 }}>
                  {fmtPrice(data.accumulation.low)} - {fmtPrice(data.accumulation.high)}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  ({fmtPrice(data.accumulation.range)} pt range, {fmtTime(data.accumulation.start_time)}-{fmtTime(data.accumulation.end_time)})
                </Typography>
                <Chip
                  size="small"
                  label={data.accumulation.is_complete ? "established" : "still building"}
                  color={data.accumulation.is_complete ? "default" : "info"}
                  variant="outlined"
                />
              </Stack>
            ) : (
              <Typography variant="caption" color="text.secondary">
                Not enough data yet.
              </Typography>
            )}
          </Box>

          <Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              Sweep Timeline
            </Typography>
            {data.sweeps.length === 0 ? (
              <Typography variant="caption" color="text.secondary">
                No sweep detected yet.
              </Typography>
            ) : (
              <TableContainer>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Direction</TableCell>
                      <TableCell align="right">Extreme</TableCell>
                      <TableCell>Breakout</TableCell>
                      <TableCell>Reversal</TableCell>
                      <TableCell align="right">Candles</TableCell>
                      <TableCell>Expected</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {data.sweeps.map((s, i) => (
                      <TableRow key={i} hover>
                        <TableCell sx={{ textTransform: "capitalize" }}>{s.direction.replace("swept_", "swept ")}</TableCell>
                        <TableCell align="right">{fmtPrice(s.extreme_price)}</TableCell>
                        <TableCell>{fmtTime(s.breakout_time)}</TableCell>
                        <TableCell>{fmtTime(s.reversal_time)}</TableCell>
                        <TableCell align="right">{s.candles_to_reverse}</TableCell>
                        <TableCell sx={{ textTransform: "capitalize" }}>{s.expected_distribution_direction}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}
          </Box>

          <Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              Current Phase
            </Typography>
            <Chip
              size="small"
              label={data.current_phase}
              color={phaseColor(data.current_phase, data.distribution?.direction)}
              sx={{ fontWeight: 700 }}
            />
          </Box>
          <Typography variant="body2">{data.narrative}</Typography>

          {data.distribution && (
            <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 1.5 }}>
              <Stat label="Distribution Direction" value={data.distribution.direction === "up" ? "Up" : "Down"} />
              <Stat
                label="Net Move Since Reversal"
                value={`${data.distribution.net_move_points >= 0 ? "+" : ""}${fmtPrice(data.distribution.net_move_points)} pts`}
                sub={`${data.distribution.net_move_pct >= 0 ? "+" : ""}${data.distribution.net_move_pct.toFixed(2)}%`}
              />
              <Box sx={{ minWidth: 150 }}>
                <Typography variant="body2" color="text.secondary">
                  Status
                </Typography>
                <Chip size="small" label={data.distribution.status} color={statusColor(data.distribution.status)} />
              </Box>
              <Box sx={{ minWidth: 150 }}>
                <Typography variant="body2" color="text.secondary">
                  Dominance Confirms
                </Typography>
                <Tooltip title="Whether buy/sell volume dominance since the reversal agrees with the expected distribution direction (Chaikin-style proxy, same as the Volume Intelligence panel).">
                  <span>
                    <Chip
                      size="small"
                      label={data.distribution.dominant_side_confirms === null ? "N/A" : data.distribution.dominant_side_confirms ? "Yes" : "Not yet"}
                      color={data.distribution.dominant_side_confirms ? "success" : "default"}
                      variant="outlined"
                    />
                  </span>
                </Tooltip>
              </Box>
            </Stack>
          )}

          <Typography variant="caption" color="text.secondary">
            A documented, deterministic ICT-style AMD heuristic (opening accumulation range, liquidity-sweep detection,
            distribution confirmation) -- not a claim of matching any single canonical/proprietary definition.
            Informational only -- does not feed the strategy engine.
          </Typography>
        </Stack>
      )}
    </Paper>
  );
}
