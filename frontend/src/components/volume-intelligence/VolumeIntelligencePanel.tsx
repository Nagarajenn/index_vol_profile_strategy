import { Box, Chip, Paper, Stack, Typography } from "@mui/material";

import { useVolumeIntelligence } from "../../hooks/useVolumeIntelligence";
import type { ForecastConfidence, RvolLabel, SimilarDayDTO, VolumeCharacterLabel } from "../../types/volumeIntelligence";

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

function rvolColor(label: RvolLabel | null): "success" | "error" | "default" {
  if (label === "Above Average") return "success";
  if (label === "Below Average") return "error";
  return "default";
}

function characterColor(label: VolumeCharacterLabel): "success" | "error" | "warning" | "default" {
  if (label === "Accumulation" || label === "Markup") return "success";
  if (label === "Distribution" || label === "Markdown") return "error";
  if (label === "Climactic") return "warning";
  return "default";
}

function confidenceColor(confidence: ForecastConfidence): "success" | "primary" | "default" {
  if (confidence === "High") return "success";
  if (confidence === "Medium") return "primary";
  return "default";
}

function SimilarDayChip({ day }: { day: SimilarDayDTO }) {
  return <Chip size="small" variant="outlined" label={`${day.session_date} · ${(day.similarity * 100).toFixed(0)}%`} />;
}

export function VolumeIntelligencePanel({ symbol }: { symbol: string }) {
  const { data, isLoading, isError } = useVolumeIntelligence(symbol);

  return (
    <Paper sx={{ p: 1.5 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
        Volume Intelligence
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
          <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 1.5 }}>
            <Box sx={{ minWidth: 150 }}>
              <Typography variant="body2" color="text.secondary">
                Relative Volume
              </Typography>
              <Chip
                size="small"
                label={data.rvol?.primary ? `${data.rvol.primary.label ?? "N/A"} (${data.rvol.primary.interval_rvol_pct?.toFixed(0) ?? "N/A"}%)` : "N/A"}
                color={rvolColor(data.rvol?.primary?.label ?? null)}
                variant="outlined"
              />
              {data.rvol?.primary && (
                <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                  vs 20-day avg, {data.rvol.primary.sample_days} days
                </Typography>
              )}
            </Box>
            <Stat
              label="Buy/Sell Dominance"
              value={
                data.dominance
                  ? `${data.dominance.dominant_side === "balanced" ? "Balanced" : data.dominance.dominant_side === "buy" ? "Buy" : "Sell"} (${(data.dominance.dominance_ratio * 100).toFixed(0)}%)`
                  : "N/A"
              }
              sub={
                data.dominance && data.dominance.consecutive_dominant_minutes > 0
                  ? `${data.dominance.consecutive_dominant_minutes} min streak`
                  : undefined
              }
            />
            <Stat
              label="Institutional Participation"
              value={data.institutional ? `${data.institutional.label} (${data.institutional.score})` : "N/A"}
            />
            <Stat
              label="Volume Trend"
              value={data.trend ? data.trend.label : "N/A"}
              sub={data.trend?.pct_change != null ? `${data.trend.pct_change >= 0 ? "+" : ""}${data.trend.pct_change.toFixed(0)}%` : undefined}
            />
          </Stack>

          <Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              Current Character
            </Typography>
            {data.character ? (
              <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
                <Chip size="small" label={data.character.label} color={characterColor(data.character.label)} />
                <Typography variant="caption" color="text.secondary">
                  {data.character.rationale}
                </Typography>
              </Stack>
            ) : (
              <Typography variant="body2" color="text.secondary">
                N/A
              </Typography>
            )}
          </Box>

          <Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              Historical Comparison
            </Typography>
            {data.similarity && data.similarity.top_days.length > 0 ? (
              <Stack spacing={0.5}>
                <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 0.5 }}>
                  {data.similarity.top_days.slice(0, 3).map((d) => (
                    <SimilarDayChip key={d.session_date} day={d} />
                  ))}
                </Stack>
                {data.similarity.resemblance_label && (
                  <Typography variant="caption" color="text.secondary">
                    Resembles {data.similarity.resemblance_label} ({data.similarity.n_days_compared} days compared)
                  </Typography>
                )}
              </Stack>
            ) : (
              <Typography variant="caption" color="text.secondary">
                Not enough comparable historical days yet{data.similarity ? ` (${data.similarity.n_days_compared} compared)` : ""}.
              </Typography>
            )}
          </Box>

          <Box>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              Expected Next Behaviour
            </Typography>
            {data.forecast ? (
              <Stack spacing={0.5}>
                <Stack direction="row" spacing={3} sx={{ alignItems: "baseline", flexWrap: "wrap", rowGap: 1 }}>
                  <Stat label="Continuation" value={`${(data.forecast.probability_continuation * 100).toFixed(0)}%`} />
                  <Stat label="Reversal" value={`${(data.forecast.probability_reversal * 100).toFixed(0)}%`} />
                  <Chip
                    size="small"
                    label={`${data.forecast.confidence} confidence`}
                    color={confidenceColor(data.forecast.confidence)}
                    variant="outlined"
                  />
                  <Typography variant="caption" color="text.secondary">
                    next {data.forecast.horizon_minutes} min
                  </Typography>
                </Stack>
                {data.forecast.supporting_factors.length > 0 && (
                  <Stack spacing={0.25}>
                    {data.forecast.supporting_factors.map((f) => (
                      <Typography key={f} variant="caption" color="text.secondary">
                        • {f}
                      </Typography>
                    ))}
                  </Stack>
                )}
              </Stack>
            ) : (
              <Typography variant="body2" color="text.secondary">
                N/A
              </Typography>
            )}
          </Box>

          {data.narrative && (
            <Box>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                AI Volume Narrative
              </Typography>
              <Typography variant="body1" sx={{ fontWeight: 600 }}>
                {data.narrative.headline}
              </Typography>
              {data.narrative.observations.length > 0 && (
                <Stack spacing={0.25} sx={{ mt: 0.5 }}>
                  {data.narrative.observations.map((o) => (
                    <Typography key={o} variant="body2">
                      • {o}
                    </Typography>
                  ))}
                </Stack>
              )}
            </Box>
          )}

          <Typography variant="caption" color="text.secondary">
            Buy/sell volumes are an estimated proxy derived from each candle's close position within its range
            (Chaikin-style), not real tick data. Informational only -- does not feed the strategy engine.
          </Typography>
        </Stack>
      )}
    </Paper>
  );
}
