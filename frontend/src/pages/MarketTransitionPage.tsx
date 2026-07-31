import { KeyboardArrowDown, KeyboardArrowRight } from "@mui/icons-material";
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { useState } from "react";

import { LiveAdvisorPanel } from "../components/market-transition/LiveAdvisorPanel";
import { useMarketTransitionResearch } from "../hooks/useMarketTransitionResearch";
import { useSymbolStore } from "../store/useSymbolStore";
import type { ConfidenceLabel, MtiDailyResultDTO, MtiFactorCorrelationDTO } from "../types/marketTransition";

function confidenceColor(label: ConfidenceLabel | null): "success" | "primary" | "warning" | "default" {
  if (label === "Strong") return "success";
  if (label === "Moderate") return "primary";
  if (label === "Weak") return "warning";
  return "default";
}

function outcomeColor(outcome: MtiDailyResultDTO["outcome"]): "success" | "error" | "default" {
  if (outcome === "continuation") return "success";
  if (outcome === "reversal") return "error";
  return "default";
}

function fmtPct(v: number | null): string {
  return v === null ? "N/A" : `${Math.round(v * 100)}%`;
}

function fmtNum(v: number | null, digits = 2): string {
  return v === null ? "N/A" : v.toFixed(digits);
}

function CorrelationSection({ correlations }: { correlations: MtiFactorCorrelationDTO[] }) {
  return (
    <Paper sx={{ p: 1.5 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 0.5 }}>
        Factor Correlation Study
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
        Every candidate factor tested against both whether the 3pm move reverses and how large the post-3pm move is.
        Confidence requires both statistical significance and a minimum sample size -- a low p-value from a handful
        of days is labeled "Insufficient data", not "Strong".
      </Typography>
      <TableContainer sx={{ maxHeight: 420 }}>
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

function DailyRow({ day }: { day: MtiDailyResultDTO }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <TableRow hover sx={{ cursor: "pointer" }} onClick={() => setOpen((o) => !o)}>
        <TableCell sx={{ width: 32 }}>
          <IconButton size="small">{open ? <KeyboardArrowDown fontSize="small" /> : <KeyboardArrowRight fontSize="small" />}</IconButton>
        </TableCell>
        <TableCell sx={{ whiteSpace: "nowrap" }}>{day.session_date}</TableCell>
        <TableCell>
          <Chip size="small" label={day.outcome} color={outcomeColor(day.outcome)} />
        </TableCell>
        <TableCell align="right">{day.transition_risk_score !== null ? Math.round(day.transition_risk_score) : "N/A"}</TableCell>
        <TableCell align="right">{fmtPct(day.probability_reversal)}</TableCell>
        <TableCell align="right">{fmtPct(day.probability_continuation)}</TableCell>
        <TableCell sx={{ textTransform: "capitalize" }}>{day.expected_direction ?? "N/A"}</TableCell>
        <TableCell align="right">{fmtNum(day.expected_volatility)}</TableCell>
        <TableCell align="right">{fmtPct(day.historical_similarity_score)}</TableCell>
        <TableCell>
          <Chip size="small" label={day.statistical_confidence ?? "N/A"} color={confidenceColor(day.statistical_confidence)} variant="outlined" />
        </TableCell>
      </TableRow>
      {open && (
        <TableRow>
          <TableCell colSpan={10} sx={{ bgcolor: "background.default", py: 1.5 }}>
            <Stack spacing={1}>
              <Typography variant="body2">{day.explanation}</Typography>
              <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 0.5 }}>
                <Typography variant="caption" color="text.secondary">
                  Profile shape: {day.profile_shape_1459 ?? "N/A"}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Market regime: {day.market_regime_1459 ?? "N/A"}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Expiry: {day.expiry_type ?? "None"}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Transition move: {day.transition_move.toFixed(2)} ({day.transition_direction})
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  Post-3pm move: {day.post_transition_move.toFixed(2)}
                </Typography>
              </Stack>
              {day.top_contributing_factors.length > 0 && (
                <Box>
                  <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.25 }}>
                    Top contributing factors
                  </Typography>
                  <Stack spacing={0.25}>
                    {day.top_contributing_factors.map((f) => (
                      <Typography key={f.factor_name} variant="caption">
                        {f.factor_name}: {f.note}
                      </Typography>
                    ))}
                  </Stack>
                </Box>
              )}
            </Stack>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

function DailyResultsSection({ days }: { days: MtiDailyResultDTO[] }) {
  return (
    <Paper sx={{ p: 1.5 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 0.5 }}>
        Daily Transition Results
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
        Most recent first. Click a row for the full explanation and contributing factors.
      </Typography>
      {days.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No complete days analyzed yet.
        </Typography>
      ) : (
        <TableContainer sx={{ maxHeight: 560 }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell sx={{ width: 32 }} />
                <TableCell>Date</TableCell>
                <TableCell>Outcome</TableCell>
                <TableCell align="right">Risk Score</TableCell>
                <TableCell align="right">P(Reversal)</TableCell>
                <TableCell align="right">P(Continuation)</TableCell>
                <TableCell>Exp. Direction</TableCell>
                <TableCell align="right">Exp. Volatility</TableCell>
                <TableCell align="right">Similarity</TableCell>
                <TableCell>Confidence</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {days.map((d) => (
                <DailyRow key={d.session_date} day={d} />
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Paper>
  );
}

export function MarketTransitionPage() {
  const selectedSymbol = useSymbolStore((s) => s.selectedSymbol);
  const { data, isLoading, isError, error } = useMarketTransitionResearch(selectedSymbol);

  return (
    <Stack spacing={2} sx={{ width: "100%" }}>
      <LiveAdvisorPanel />

      {isLoading && (
        <Box sx={{ display: "flex", justifyContent: "center", mt: 4 }}>
          <CircularProgress />
        </Box>
      )}

      {(isError || (!isLoading && !data)) && (
        <Alert severity="error" sx={{ mt: 2 }}>
          Failed to load Market Transition research: {error instanceof Error ? error.message : "unknown error"}
        </Alert>
      )}

      {data && (
        <>
          <Box>
            <Typography variant="h6" sx={{ fontWeight: 700 }}>
              Market Transition Intelligence -- {data.symbol}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Research engine discovering statistical predictors of the 2:00-3:01pm intraday transition. Not a
              trading signal -- entirely independent of the live decision engine. {data.total_days_analyzed} trading
              days analyzed.
            </Typography>
          </Box>

          <CorrelationSection correlations={data.correlations} />
          <DailyResultsSection days={data.daily_results} />
        </>
      )}
    </Stack>
  );
}
