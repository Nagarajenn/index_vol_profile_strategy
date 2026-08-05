import {
  Box,
  Chip,
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

import { useVolumeIntelligence } from "../../hooks/useVolumeIntelligence";
import type {
  DailyComparisonLabel,
  DailyVolumeComparisonDTO,
  ForecastConfidence,
  RvolLabel,
  SignificantIntervalDTO,
  SimilarDayDTO,
  VolumeCharacterLabel,
} from "../../types/volumeIntelligence";

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

function dailyComparisonColor(label: DailyComparisonLabel | null): "success" | "error" | "default" {
  if (label === "Much Higher" || label === "Higher") return "success";
  if (label === "Much Lower" || label === "Lower") return "error";
  return "default";
}

function fmtVolume(v: number): string {
  return Math.round(v).toLocaleString();
}

function fmtPct(v: number | null): string {
  return v === null ? "N/A" : `${v >= 0 ? "+" : ""}${v.toFixed(0)}%`;
}

function DailyVolumeTrendSection({ trend }: { trend: { elapsed_minutes: number; days: DailyVolumeComparisonDTO[] } | null }) {
  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
        5-Day Volume Trend
      </Typography>
      {!trend || trend.days.length === 0 ? (
        <Typography variant="caption" color="text.secondary">
          Not enough prior-day data yet.
        </Typography>
      ) : (
        <>
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 0.5 }}>
            Each day's volume as of {trend.elapsed_minutes} min into the session, vs. the day immediately before it.
          </Typography>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Date</TableCell>
                  <TableCell align="right">Volume (as of)</TableCell>
                  <TableCell align="right">Prior Day</TableCell>
                  <TableCell align="right">% Change</TableCell>
                  <TableCell>Signal</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {trend.days.map((d) => (
                  <TableRow key={d.session_date} hover>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{d.session_date}</TableCell>
                    <TableCell align="right">{fmtVolume(d.volume_as_of)}</TableCell>
                    <TableCell align="right">{d.prior_day_volume_as_of !== null ? fmtVolume(d.prior_day_volume_as_of) : "N/A"}</TableCell>
                    <TableCell align="right">{fmtPct(d.pct_change)}</TableCell>
                    <TableCell>
                      {d.label ? (
                        <Chip size="small" variant="outlined" label={d.label} color={dailyComparisonColor(d.label)} />
                      ) : (
                        "N/A"
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </>
      )}
    </Box>
  );
}

function formatIntervalTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function SignificantIntervalsSection({ intervals }: { intervals: SignificantIntervalDTO[] }) {
  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
        Significant 5-Minute Intervals (Today)
      </Typography>
      {intervals.length === 0 ? (
        <Typography variant="caption" color="text.secondary">
          No unusual 5-minute volume intervals detected today.
        </Typography>
      ) : (
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Time</TableCell>
                <TableCell align="right">Volume</TableCell>
                <TableCell align="right">vs Baseline</TableCell>
                <TableCell>Side</TableCell>
                <TableCell>Price Move</TableCell>
                <TableCell>Notes</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {intervals.map((i) => (
                <TableRow key={i.start_time} hover>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>
                    {formatIntervalTime(i.start_time)}–{formatIntervalTime(i.end_time)}
                  </TableCell>
                  <TableCell align="right">{fmtVolume(i.interval_volume)}</TableCell>
                  <TableCell align="right">{i.multiple !== null ? `${i.multiple.toFixed(1)}x` : "N/A"}</TableCell>
                  <TableCell sx={{ textTransform: "capitalize" }}>{i.dominant_side}</TableCell>
                  <TableCell sx={{ textTransform: "capitalize" }}>{i.price_direction}</TableCell>
                  <TableCell sx={{ minWidth: 260 }}>
                    <Typography variant="caption" sx={{ display: "block" }}>
                      {i.institutional_note}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ display: "block" }}>
                      {i.trend_note}
                    </Typography>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  );
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

          <SignificantIntervalsSection intervals={data.significant_intervals} />

          <DailyVolumeTrendSection trend={data.daily_volume_trend} />

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
