import { Alert, Box, Chip, CircularProgress, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Tooltip, Typography } from "@mui/material";

import { useCasIntelligence } from "../../hooks/useCasIntelligence";
import type { CasDailyResultDTO } from "../../types/marketTransition";

function outcomeColor(outcome: "continuation" | "reversal" | "neutral"): "success" | "error" | "default" {
  if (outcome === "continuation") return "success";
  if (outcome === "reversal") return "error";
  return "default";
}

function directionLabel(d: "up" | "down" | "flat" | null): string {
  return d ?? "N/A";
}

function fmtVol(v: number | null): string {
  if (v === null) return "N/A";
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  return v.toFixed(0);
}

function fmtPoints(v: number | null): string {
  return v === null ? "N/A" : `+${v.toFixed(0)}`;
}

function CasDailyRow({ day }: { day: CasDailyResultDTO }) {
  const agrees = day.old_methodology_outcome !== null && day.old_methodology_outcome === day.conclusion;
  return (
    <TableRow hover sx={day.data_quality_flag ? { opacity: 0.6 } : undefined}>
      <TableCell sx={{ whiteSpace: "nowrap" }}>
        {day.session_date}
        {day.data_quality_flag && (
          <Tooltip title={`Data quality: ${day.data_quality_flag} -- excluded from trend reading`}>
            <Chip size="small" label="!" color="warning" sx={{ ml: 0.5, minWidth: 20, height: 18 }} />
          </Tooltip>
        )}
      </TableCell>
      <TableCell sx={{ textTransform: "capitalize" }}>{directionLabel(day.pre_direction)}</TableCell>
      <TableCell sx={{ textTransform: "capitalize" }}>{directionLabel(day.post_direction)}</TableCell>
      <TableCell align="right">
        <Tooltip title="Points gained toward the pre-window's own direction, using the best print reached (high for up, low for down) -- not just the close-to-close move.">
          <span>{fmtPoints(day.pre_window_points_move)}</span>
        </Tooltip>
      </TableCell>
      <TableCell align="right">
        <Tooltip title="Points gained toward the post-window's own direction, using the best print reached between 15:00-15:39 -- price stays reliable through this window even though volume doesn't.">
          <span>{fmtPoints(day.post_window_points_move)}</span>
        </Tooltip>
      </TableCell>
      <TableCell>
        <Chip size="small" label={day.conclusion} color={outcomeColor(day.conclusion)} />
      </TableCell>
      <TableCell>
        <Stack direction="row" spacing={0.5} sx={{ alignItems: "center" }}>
          <Typography variant="caption" sx={{ textTransform: "capitalize" }}>
            {day.old_methodology_outcome ?? "N/A"}
          </Typography>
          {day.old_methodology_outcome !== null && (
            <Chip size="small" label={agrees ? "agree" : "differ"} color={agrees ? "success" : "warning"} variant="outlined" sx={{ height: 18 }} />
          )}
        </Stack>
      </TableCell>
      <TableCell align="right">{fmtVol(day.pre_window_volume)}</TableCell>
      <TableCell align="right">{fmtVol(day.post_window_pre_auction_volume)}</TableCell>
      <TableCell align="right">{day.volume_ratio !== null ? day.volume_ratio.toFixed(2) : "N/A"}</TableCell>
      <TableCell align="right">{day.pcr_1459 !== null ? day.pcr_1459.toFixed(2) : "N/A"}</TableCell>
      <TableCell>
        <Typography variant="caption">{day.institutional_bias_label_1459 ?? "N/A"}</Typography>
      </TableCell>
      <TableCell>{day.expiry_type ?? "-"}</TableCell>
    </TableRow>
  );
}

export function CasIntelligencePanel({ symbol }: { symbol: string }) {
  const { data, isLoading, isError, error } = useCasIntelligence(symbol);

  return (
    <Paper sx={{ p: 1.5 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 0.5 }}>
        CAS Intelligence -- {symbol}
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
        Re-frames the 3pm transition for NSE's post-2026-08-03 Closing Auction Session: trend from 14:31-14:59 vs.
        trend from 15:00-15:39, compared against the same day's call under the original (unchanged) methodology
        above. Additive research view -- never feeds the trading decision engine.{" "}
        <strong>Post-window volume only covers 14:31-14:59 vs. 15:00-15:14</strong> ("pre-auction volume"): Dhan's
        1-minute feed does not report reliable volume once the Closing Auction Session begins at 15:15, even though
        price keeps moving genuinely through it.
      </Typography>

      {isLoading && (
        <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
          <CircularProgress size={24} />
        </Box>
      )}

      {(isError || (!isLoading && !data)) && (
        <Alert severity="error">CAS Intelligence failed to load: {error instanceof Error ? error.message : "unknown error"}</Alert>
      )}

      {data && data.total_days_analyzed === 0 && (
        <Alert severity="info">
          No post-CAS trading days analyzed yet -- run scripts/run_cas_intelligence.py once at least one session has
          closed after 2026-08-03.
        </Alert>
      )}

      {data && data.total_days_analyzed > 0 && (
        <>
          <Alert severity={data.total_days_analyzed < 30 ? "warning" : "info"} sx={{ mb: 1 }}>
            {data.total_days_analyzed} post-CAS trading day{data.total_days_analyzed === 1 ? "" : "s"} analyzed
            {data.agreement_pct !== null && (
              <>
                {" "}
                -- agrees with the original methodology's call on {data.agreement_count}/{data.total_days_analyzed} (
                {data.agreement_pct}%)
              </>
            )}
            . {data.total_days_analyzed < 30 && "Sample is still small -- read this directionally, not as proof."}
          </Alert>
          <TableContainer sx={{ maxHeight: 420 }}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  <TableCell>Date</TableCell>
                  <TableCell>Pre (14:31-14:59)</TableCell>
                  <TableCell>Post (15:00-15:39)</TableCell>
                  <TableCell align="right">Pre pts</TableCell>
                  <TableCell align="right">Post pts</TableCell>
                  <TableCell>Conclusion</TableCell>
                  <TableCell>Original engine</TableCell>
                  <TableCell align="right">Pre-vol</TableCell>
                  <TableCell align="right">Post-vol (pre-auction)</TableCell>
                  <TableCell align="right">Vol ratio</TableCell>
                  <TableCell align="right">PCR@14:59</TableCell>
                  <TableCell>Inst. bias@14:59</TableCell>
                  <TableCell>Expiry</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {data.daily_results.map((d) => (
                  <CasDailyRow key={d.session_date} day={d} />
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </>
      )}
    </Paper>
  );
}
