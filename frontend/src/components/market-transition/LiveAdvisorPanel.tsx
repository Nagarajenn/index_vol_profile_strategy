import { Box, Chip, CircularProgress, Divider, Paper, Stack, Typography } from "@mui/material";

import { useLiveTransitionAdvisor } from "../../hooks/useLiveTransitionAdvisor";
import { useSymbolStore } from "../../store/useSymbolStore";
import type { ConfidenceLabel, TransitionRiskLevel } from "../../types/liveTransitionAdvisor";

const RISK_COLOR: Record<TransitionRiskLevel, string> = {
  Observe: "#5c6470",
  Low: "#2e7d32",
  Medium: "#ed6c02",
  High: "#c2410c",
  "Very High": "#ff5c5c",
};

function confidenceColor(label: ConfidenceLabel): "success" | "primary" | "warning" | "default" {
  if (label === "Strong") return "success";
  if (label === "Moderate") return "primary";
  if (label === "Weak") return "warning";
  return "default";
}

function outcomeColor(outcome: "continuation" | "reversal" | "neutral"): "success" | "error" | "default" {
  if (outcome === "continuation") return "success";
  if (outcome === "reversal") return "error";
  return "default";
}

function fmtPct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

export function LiveAdvisorPanel() {
  const selectedSymbol = useSymbolStore((s) => s.selectedSymbol);
  const { data, isLoading, isError } = useLiveTransitionAdvisor(selectedSymbol);

  return (
    <Paper sx={{ p: 1.5 }}>
      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 1, mb: 1 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          Live Market Transition Advisor -- {selectedSymbol}
        </Typography>
        {data && (
          <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <Chip size="small" label={data.stage} variant="outlined" />
            <Typography variant="caption" color="text.secondary">
              as of {new Date(data.as_of).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </Typography>
          </Stack>
        )}
      </Stack>

      {isLoading && (
        <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
          <CircularProgress size={20} />
        </Box>
      )}
      {isError && !isLoading && (
        <Typography variant="body2" color="text.secondary">
          Live advisor unavailable.
        </Typography>
      )}

      {data && !data.is_active && (
        <Stack spacing={1}>
          <Typography variant="body2" color="text.secondary">
            {data.explanation}
          </Typography>
          <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 0.5 }}>
            {data.institutional_bias_label && (
              <Typography variant="caption" color="text.secondary">
                Institutional bias: {data.institutional_bias_label}
              </Typography>
            )}
            {data.news_risk_score !== null && (
              <Typography variant="caption" color="text.secondary">
                News risk: {data.news_risk_score}/100 ({data.news_sentiment})
              </Typography>
            )}
          </Stack>
        </Stack>
      )}

      {data && data.is_active && (
        <Stack spacing={1.5}>
          {/* Risk level + explanation -- the headline read */}
          <Stack direction="row" spacing={1.5} sx={{ alignItems: "flex-start", flexWrap: "wrap" }}>
            <Box
              sx={{
                px: 1.5,
                py: 0.75,
                borderRadius: 1,
                bgcolor: RISK_COLOR[data.risk_level],
                color: "#fff",
                fontWeight: 700,
                fontSize: "0.85rem",
                whiteSpace: "nowrap",
              }}
            >
              {data.risk_level === "Observe" ? "Observe" : `${data.risk_level} Transition Risk`}
            </Box>
            <Chip size="small" label={`Confidence: ${data.statistical_confidence}`} color={confidenceColor(data.statistical_confidence)} variant="outlined" />
          </Stack>

          <Typography variant="body2">{data.explanation}</Typography>

          <Divider />

          {/* Core numbers */}
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(4, 1fr)", md: "repeat(6, 1fr)" }, gap: 1.5 }}>
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                Similarity
              </Typography>
              <Typography variant="body1" sx={{ fontWeight: 700 }}>
                {fmtPct(data.historical_similarity_score)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                P(Reversal)
              </Typography>
              <Typography variant="body1" sx={{ fontWeight: 700 }}>
                {fmtPct(data.probability_reversal)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                P(Continuation)
              </Typography>
              <Typography variant="body1" sx={{ fontWeight: 700 }}>
                {fmtPct(data.probability_continuation)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                Expected Direction
              </Typography>
              <Typography variant="body1" sx={{ fontWeight: 700, textTransform: "capitalize" }}>
                {data.expected_direction}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                Expected Volatility
              </Typography>
              <Typography variant="body1" sx={{ fontWeight: 700 }}>
                {data.expected_volatility.toFixed(1)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                Estimated Move
              </Typography>
              <Typography variant="body1" sx={{ fontWeight: 700, color: data.estimated_move >= 0 ? "success.main" : "error.main" }}>
                {data.estimated_move >= 0 ? "+" : ""}
                {data.estimated_move.toFixed(1)}
              </Typography>
            </Box>
          </Box>

          {data.expected_timing && (
            <Typography variant="caption" color="text.secondary">
              Expected timing:{" "}
              {data.expected_timing.earliest && data.expected_timing.latest
                ? `between ${data.expected_timing.earliest} and ${data.expected_timing.latest}`
                : data.expected_timing.note}
            </Typography>
          )}

          <Divider />

          <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
            {/* Most similar days */}
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="caption" sx={{ color: "text.secondary", letterSpacing: 0.5, fontSize: "0.65rem" }}>
                MOST SIMILAR TRADING DAYS
              </Typography>
              <Stack spacing={0.5} sx={{ mt: 0.5 }}>
                {data.most_similar_days.slice(0, 6).map((d) => (
                  <Stack key={d.session_date} direction="row" spacing={1} sx={{ alignItems: "center" }}>
                    <Typography variant="caption" sx={{ minWidth: 78 }}>
                      {d.session_date}
                    </Typography>
                    <Chip size="small" label={d.outcome} color={outcomeColor(d.outcome)} sx={{ height: 18, fontSize: "0.65rem" }} />
                    <Typography variant="caption" color="text.secondary">
                      {fmtPct(d.similarity)} match
                    </Typography>
                  </Stack>
                ))}
                {data.most_similar_days.length === 0 && (
                  <Typography variant="caption" color="text.secondary">
                    No close historical analogs found yet.
                  </Typography>
                )}
              </Stack>
            </Box>

            {/* Top contributing factors */}
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="caption" sx={{ color: "text.secondary", letterSpacing: 0.5, fontSize: "0.65rem" }}>
                TOP CONTRIBUTING FACTORS
              </Typography>
              <Stack spacing={0.5} sx={{ mt: 0.5 }}>
                {data.top_contributing_factors.map((f) => (
                  <Typography key={f.factor_name} variant="caption" sx={{ display: "block" }}>
                    {f.factor_name}: {f.note}
                  </Typography>
                ))}
                {data.top_contributing_factors.length === 0 && (
                  <Typography variant="caption" color="text.secondary">
                    No significant factors identified yet.
                  </Typography>
                )}
              </Stack>
            </Box>

            {/* Context: institutional bias + news */}
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <Typography variant="caption" sx={{ color: "text.secondary", letterSpacing: 0.5, fontSize: "0.65rem" }}>
                CONTEXT (NOT WEIGHTED IN SCORE)
              </Typography>
              <Stack spacing={0.5} sx={{ mt: 0.5 }}>
                {data.institutional_bias_label && (
                  <Typography variant="caption" sx={{ display: "block" }}>
                    Institutional bias: {data.institutional_bias_label}
                  </Typography>
                )}
                {data.news_risk_score !== null && (
                  <Typography variant="caption" sx={{ display: "block" }}>
                    News risk: {data.news_risk_score}/100 ({data.news_sentiment})
                  </Typography>
                )}
              </Stack>
            </Box>
          </Stack>
        </Stack>
      )}
    </Paper>
  );
}
