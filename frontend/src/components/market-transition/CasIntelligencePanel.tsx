import { KeyboardArrowDown, KeyboardArrowRight } from "@mui/icons-material";
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Divider,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import { useState } from "react";

import { CasCohortAnalysisPanel } from "./CasCohortAnalysisPanel";
import { PostTransitionMinutesTable, PreTransitionWindowsTable } from "./CasWindowedDetailTables";
import { useCasIntelligence } from "../../hooks/useCasIntelligence";
import { useCasWindowedDetail } from "../../hooks/useCasWindowedDetail";
import type { CasDailyResultDTO, ConfidenceLabel, MtiFactorCorrelationDTO, TransitionForecastDTO } from "../../types/marketTransition";

const TRANSITION_TYPE_LABELS: Record<CasDailyResultDTO["transition_type"], string> = {
  CONTINUATION_UP: "Continuation (Up)",
  CONTINUATION_DOWN: "Continuation (Down)",
  REVERSAL_UP: "Reversal (Up)",
  REVERSAL_DOWN: "Reversal (Down)",
  POST_WINDOW_INITIATION_UP: "Post-Window Move (Up)",
  POST_WINDOW_INITIATION_DOWN: "Post-Window Move (Down)",
  NO_MATERIAL_TRANSITION: "No Material Transition",
};

function transitionTypeColor(t: CasDailyResultDTO["transition_type"]): "success" | "error" | "info" | "default" {
  if (t === "CONTINUATION_UP" || t === "CONTINUATION_DOWN") return "success";
  if (t === "REVERSAL_UP" || t === "REVERSAL_DOWN") return "error";
  // A genuinely distinct 3rd category -- no pre-window trend to reverse or
  // continue, but a real post-window move -- exactly what used to be
  // indistinguishable from a quiet day under the old "Neutral" label.
  if (t === "POST_WINDOW_INITIATION_UP" || t === "POST_WINDOW_INITIATION_DOWN") return "info";
  return "default"; // NO_MATERIAL_TRANSITION
}

function magnitudeTierColor(tier: CasDailyResultDTO["magnitude_tier"]): "default" | "info" | "warning" | "error" {
  if (tier === "EXTREME") return "error";
  if (tier === "LARGE") return "warning";
  if (tier === "MODERATE") return "info";
  return "default"; // NORMAL or null
}

function confidenceColor(label: ConfidenceLabel | null): "success" | "primary" | "warning" | "default" {
  if (label === "Strong") return "success";
  if (label === "Moderate") return "primary";
  if (label === "Weak") return "warning";
  return "default";
}

function CasCorrelationSection({ correlations }: { correlations: MtiFactorCorrelationDTO[] }) {
  return (
    <Paper sx={{ p: 1.5, mt: 1.5 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 0.5 }}>
        CAS Factor Correlation Study
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
        The original engine's 13 factors, recomputed over the CAS-adjusted 14:31-14:59 window, plus new factors this
        panel introduces (points move, volume, PCR, institutional bias) -- tested against whether the CAS-adjusted
        call reverses and how large the post-3pm move is. Same statistics as the original methodology's study (needs {"≥"}20 days
        for any confidence label beyond "Insufficient data"), just a separate, additive result set.
      </Typography>
      <TableContainer sx={{ maxHeight: 360 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell>Factor</TableCell>
              <TableCell>Target</TableCell>
              <TableCell align="right">N</TableCell>
              <TableCell align="right">Statistic</TableCell>
              <TableCell align="right">p-value</TableCell>
              <TableCell>Confidence</TableCell>
              <TableCell>Finding</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {correlations.map((c) => (
              <TableRow key={`${c.factor_name}-${c.target}`} hover>
                <TableCell sx={{ whiteSpace: "nowrap" }}>{c.factor_name}</TableCell>
                <TableCell sx={{ textTransform: "capitalize" }}>{c.target}</TableCell>
                <TableCell align="right">{c.n_days}</TableCell>
                <TableCell align="right">{c.statistic !== null ? c.statistic.toFixed(2) : "N/A"}</TableCell>
                <TableCell align="right">{c.p_value !== null ? c.p_value.toFixed(3) : "N/A"}</TableCell>
                <TableCell>
                  <Chip size="small" label={c.confidence_label} color={confidenceColor(c.confidence_label)} variant="outlined" />
                </TableCell>
                <TableCell sx={{ maxWidth: 320 }}>
                  <Typography variant="caption">{c.direction_note}</Typography>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
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
  if (v === null) return "N/A";
  return v > 0 ? `+${v.toFixed(0)}` : v.toFixed(0); // negative values already carry their own "-"
}

function ForecastVsActualStrip({ forecast, day }: { forecast: TransitionForecastDTO | undefined; day: CasDailyResultDTO }) {
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

function CasWindowedDetailSection({ symbol, day }: { symbol: string; day: CasDailyResultDTO }) {
  const { data, isLoading, isError } = useCasWindowedDetail(symbol, day.session_date, true);

  if (isLoading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
        <CircularProgress size={20} />
      </Box>
    );
  }
  if (isError || !data) {
    return <Alert severity="error">Failed to load windowed detail for {day.session_date}.</Alert>;
  }
  if (data.pre_transition_windows.length === 0 && data.post_transition_minutes.length === 0) {
    return (
      <Alert severity="info">
        No windowed detail yet for {day.session_date} -- run scripts/run_cas_windowed_analysis.py.
      </Alert>
    );
  }

  const forecast1459 = data.forecasts.find((f) => f.checkpoint_time === "14:59");

  return (
    <Stack spacing={1}>
      <Chip
        size="small"
        label="2:30-2:59 PRE-TRANSITION — FORECAST INFORMATION"
        sx={{ alignSelf: "flex-start", bgcolor: "info.dark", color: "info.contrastText", fontWeight: 700 }}
      />
      <PreTransitionWindowsTable windows={data.pre_transition_windows} />

      <Divider sx={{ "&::before, &::after": { borderColor: "warning.main" } }}>
        <Chip size="small" label="⬇ 3 PM TRANSITION ⬇" color="warning" sx={{ fontWeight: 700 }} />
      </Divider>

      <Chip
        size="small"
        label="3:00-3:15 — ACTUAL OUTCOME"
        sx={{ alignSelf: "flex-start", bgcolor: "success.dark", color: "success.contrastText", fontWeight: 700 }}
      />
      <PostTransitionMinutesTable minutes={data.post_transition_minutes} />

      <ForecastVsActualStrip forecast={forecast1459} day={day} />
    </Stack>
  );
}

function CasDailyRow({ symbol, day }: { symbol: string; day: CasDailyResultDTO }) {
  const [open, setOpen] = useState(false);
  const agrees = day.old_methodology_outcome !== null && day.old_methodology_outcome === day.conclusion;
  return (
    <>
    <TableRow hover sx={day.data_quality_flag ? { opacity: 0.6 } : undefined}>
      <TableCell sx={{ width: 32 }}>
        <IconButton size="small" onClick={() => setOpen((o) => !o)}>
          {open ? <KeyboardArrowDown fontSize="small" /> : <KeyboardArrowRight fontSize="small" />}
        </IconButton>
      </TableCell>
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
        <Tooltip title="Signed points move using the best print reached in the pre-window (high for up, low for down; positive = ran up, negative = ran down) -- not just the close-to-close move.">
          <span>{fmtPoints(day.pre_window_points_move)}</span>
        </Tooltip>
      </TableCell>
      <TableCell align="right">
        <Tooltip title="Signed points move using the best print reached between 15:00-15:39 (positive = ran up, negative = ran down) -- price stays reliable through this window even though volume doesn't.">
          <span>{fmtPoints(day.post_window_points_move)}</span>
        </Tooltip>
      </TableCell>
      <TableCell>
        <Chip size="small" label={TRANSITION_TYPE_LABELS[day.transition_type]} color={transitionTypeColor(day.transition_type)} />
      </TableCell>
      <TableCell>
        {day.magnitude_tier !== null ? (
          <Tooltip
            title={`${day.magnitude_pct_return !== null ? day.magnitude_pct_return.toFixed(2) : "N/A"}% return, ${
              day.magnitude_atr_normalized !== null ? day.magnitude_atr_normalized.toFixed(2) : "N/A"
            }x prior day's 14-day ATR`}
          >
            <Chip size="small" label={day.magnitude_tier} color={magnitudeTierColor(day.magnitude_tier)} variant="outlined" />
          </Tooltip>
        ) : (
          <Typography variant="caption" color="text.secondary">
            N/A
          </Typography>
        )}
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
    {open && (
      <TableRow>
        <TableCell colSpan={15} sx={{ bgcolor: "background.default", py: 1.5 }}>
          <CasWindowedDetailSection symbol={symbol} day={day} />
        </TableCell>
      </TableRow>
    )}
    </>
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
        (see the "Original engine" column below). Additive research view -- never feeds the trading decision engine.{" "}
        <strong>Pre-window state and post-window outcome are classified independently</strong> -- a flat pre-window
        no longer hides a large post-window move under "Neutral" (see Transition Type); Magnitude is
        volatility-normalized against the prior day's 14-day ATR, not just raw points.{" "}
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
                  <TableCell sx={{ width: 32 }} />
                  <TableCell>Date</TableCell>
                  <TableCell>Pre (14:31-14:59)</TableCell>
                  <TableCell>Post (15:00-15:39)</TableCell>
                  <TableCell align="right">Pre pts</TableCell>
                  <TableCell align="right">Post pts</TableCell>
                  <TableCell>Transition Type</TableCell>
                  <TableCell>Magnitude</TableCell>
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
                  <CasDailyRow key={d.session_date} symbol={symbol} day={d} />
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          {data.correlations.length > 0 && <CasCorrelationSection correlations={data.correlations} />}
          <CasCohortAnalysisPanel symbol={symbol} />
        </>
      )}
    </Paper>
  );
}
