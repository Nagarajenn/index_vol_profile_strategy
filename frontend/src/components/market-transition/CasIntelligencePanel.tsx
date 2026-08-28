import { KeyboardArrowDown, KeyboardArrowRight, OpenInNew } from "@mui/icons-material";
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Collapse,
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
import { useNavigate } from "react-router-dom";

import { CasCohortAnalysisPanel } from "./CasCohortAnalysisPanel";
import { confidenceColor, magnitudeTierColor, transitionTypeColor, TRANSITION_TYPE_LABELS } from "./CasWindowedDetailTables";
import { useCasIntelligence } from "../../hooks/useCasIntelligence";
import type { CasDailyResultDTO, MtiFactorCorrelationDTO } from "../../types/marketTransition";

function CasCorrelationSection({ correlations }: { correlations: MtiFactorCorrelationDTO[] }) {
  // Collapsed by default -- this table alone runs 40+ rows, which otherwise
  // pushes the pre/post-transition detail (the thing most worth seeing on
  // one screen for a given day) well below the fold.
  const [open, setOpen] = useState(false);
  return (
    <Paper sx={{ p: 1.5, mt: 1.5 }}>
      <Stack
        direction="row"
        spacing={1}
        sx={{ alignItems: "center", cursor: "pointer" }}
        onClick={() => setOpen((o) => !o)}
      >
        <IconButton size="small">{open ? <KeyboardArrowDown fontSize="small" /> : <KeyboardArrowRight fontSize="small" />}</IconButton>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          CAS Factor Correlation Study
        </Typography>
        <Chip size="small" label={`${correlations.length} factors`} variant="outlined" />
      </Stack>
      <Collapse in={open}>
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1, mt: 0.5 }}>
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
      </Collapse>
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

function CasDailyRow({ symbol, day }: { symbol: string; day: CasDailyResultDTO }) {
  const navigate = useNavigate();
  const agrees = day.old_methodology_outcome !== null && day.old_methodology_outcome === day.conclusion;
  return (
    <TableRow hover sx={day.data_quality_flag ? { opacity: 0.6 } : undefined}>
      <TableCell sx={{ width: 32 }}>
        <Tooltip title="View full pre/post-3pm detail on its own page">
          <IconButton size="small" onClick={() => navigate(`/market-transition-intelligence/cas-day/${symbol}/${day.session_date}`)}>
            <OpenInNew fontSize="small" />
          </IconButton>
        </Tooltip>
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
