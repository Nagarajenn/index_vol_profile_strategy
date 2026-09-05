import { Box, Chip, Paper, Stack, Tooltip, Typography } from "@mui/material";

import { confidenceColor } from "./CasWindowedDetailTables";
import type { TransitionForecastDTO, TransitionVerdict } from "../../types/marketTransition";

function verdictColor(verdict: TransitionVerdict | null): "success" | "error" | "default" | "warning" {
  if (verdict === "UP") return "success";
  if (verdict === "DOWN") return "error";
  if (verdict === "NO_MATERIAL_MOVE") return "default";
  if (verdict === "CONFLICTED") return "warning";
  return "default"; // NO_CLEAR_EDGE / INSUFFICIENT_EVIDENCE / null
}

function verdictLabel(verdict: TransitionVerdict | null): string {
  if (verdict === null) return "N/A";
  const labels: Record<TransitionVerdict, string> = {
    UP: "UP", DOWN: "DOWN", NO_MATERIAL_MOVE: "NO MATERIAL MOVE",
    NO_CLEAR_EDGE: "NO CLEAR EDGE", CONFLICTED: "CONFLICTED — DO NOT RELY ON DIRECTIONAL FORECAST",
    INSUFFICIENT_EVIDENCE: "INSUFFICIENT HISTORICAL EVIDENCE",
  };
  return labels[verdict];
}

function riskTierColor(tier: string | null): "default" | "info" | "warning" | "error" {
  if (tier === "EXTREME") return "error";
  if (tier === "LARGE") return "warning";
  if (tier === "MODERATE") return "info";
  return "default"; // NORMAL or null
}

function pct(v: number | null): string {
  return v === null ? "N/A" : `${(v * 100).toFixed(0)}%`;
}

function pts(v: number | null): string {
  if (v === null) return "N/A";
  return v > 0 ? `+${v.toFixed(0)}` : v.toFixed(0);
}

// The "3 PM TRANSITION FORECAST" headline (spec Part 15) -- the most
// prominent read on the page: a candid UP/DOWN/NO-MATERIAL-MOVE verdict
// (which can honestly be NO_CLEAR_EDGE/CONFLICTED/INSUFFICIENT_EVIDENCE
// instead of a forced call), expected move range, transition risk tier,
// and the top-3 drivers behind it. Deliberately compact -- a single Paper,
// not a sprawling dashboard section.
export function TransitionForecastHeadline({ forecast }: { forecast: TransitionForecastDTO | undefined }) {
  if (!forecast) return null;

  const hasCall = forecast.verdict === "UP" || forecast.verdict === "DOWN" || forecast.verdict === "NO_MATERIAL_MOVE";

  return (
    <Paper variant="outlined" sx={{ p: 1.5 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
        3 PM Transition Forecast — {forecast.checkpoint_time} checkpoint
      </Typography>

      <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 1, alignItems: "center", mb: 1 }}>
        <Chip label={verdictLabel(forecast.verdict)} color={verdictColor(forecast.verdict)} sx={{ fontWeight: 700 }} />
        {hasCall && (
          <Stack direction="row" spacing={1.5}>
            <Typography variant="body2">UP {pct(forecast.probability_up)}</Typography>
            <Typography variant="body2">DOWN {pct(forecast.probability_down)}</Typography>
            <Typography variant="body2">NO MATERIAL MOVE {pct(forecast.probability_no_material_transition)}</Typography>
          </Stack>
        )}
      </Stack>

      <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 1, alignItems: "center", mb: forecast.primary_driver ? 1 : 0 }}>
        <Box>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
            Confidence
          </Typography>
          <Chip size="small" label={forecast.confidence_label} color={confidenceColor(forecast.confidence_label)} variant="outlined" />
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
            Historical N
          </Typography>
          <Typography variant="body2">{forecast.n_analogs}</Typography>
        </Box>
        <Box>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
            Similarity
          </Typography>
          <Typography variant="body2">{(forecast.historical_similarity_score * 100).toFixed(0)}%</Typography>
        </Box>
        {(forecast.expected_move_low !== null || forecast.expected_move_high !== null) && (
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
              Expected move
            </Typography>
            <Tooltip title={forecast.expected_move_percentile !== null ? `${forecast.expected_move_percentile}th percentile of historical moves` : ""}>
              <Typography variant="body2">
                {pts(forecast.expected_move_low)} to {pts(forecast.expected_move_high)}
              </Typography>
            </Tooltip>
          </Box>
        )}
        {forecast.transition_risk_tier && (
          <Box>
            <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
              Transition risk
            </Typography>
            <Chip size="small" label={forecast.transition_risk_tier} color={riskTierColor(forecast.transition_risk_tier)} variant="outlined" />
          </Box>
        )}
      </Stack>

      {(forecast.primary_driver || forecast.contradictory_factors.length > 0) && (
        <Box sx={{ mt: 1 }}>
          <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700, display: "block" }}>
            WHY?
          </Typography>
          <Stack spacing={0.25} sx={{ mt: 0.25 }}>
            {[forecast.primary_driver, forecast.secondary_driver, forecast.tertiary_driver]
              .filter((d): d is string => Boolean(d))
              .map((d, i) => (
                <Typography key={d} variant="body2">
                  {i + 1}. {d}
                </Typography>
              ))}
            {forecast.contradictory_factors.map((c) => (
              <Typography key={c} variant="body2" color="warning.main">
                Conflicting: {c}
              </Typography>
            ))}
          </Stack>
        </Box>
      )}
    </Paper>
  );
}
