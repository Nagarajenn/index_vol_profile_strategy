import { Box, Paper, Typography } from "@mui/material";

import type { CandleDTO, LevelsSummaryDTO } from "../../types/dashboard";
import { CHART_AXIS, CHART_BG, CHART_BORDER, CHART_TEXT } from "./chartTheme";
import { ChartTooltip } from "./ChartTooltip";
import { LevelBandOverlay } from "./LevelBandOverlay";
import { useCandlestickChart } from "./useCandlestickChart";

// Occupies ~45-50% of viewport height on tall screens (bounded so it stays
// usable on short laptop screens); the chart itself auto-resizes via
// ResizeObserver in useCandlestickChart, so this is layout-only.
const CHART_HEIGHT = { xs: 420, md: "clamp(440px, 48vh, 680px)" };

export function CandlestickChart({
  candles,
  levels,
}: {
  candles: CandleDTO[];
  levels: LevelsSummaryDTO | null;
}) {
  const { containerRef, bands, hover } = useCandlestickChart(candles, levels);

  if (candles.length === 0) {
    return (
      <Paper sx={{ p: 1.5, bgcolor: CHART_BG, border: `1px solid ${CHART_BORDER}` }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1, color: CHART_TEXT }}>
          Price Chart
        </Typography>
        <Typography sx={{ color: CHART_AXIS }}>No candle data available yet.</Typography>
      </Paper>
    );
  }

  return (
    <Paper sx={{ p: 1.5, bgcolor: CHART_BG, border: `1px solid ${CHART_BORDER}` }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1, color: CHART_TEXT }}>
        Price Chart — previous session + today
      </Typography>
      <Box sx={{ position: "relative", width: "100%", height: CHART_HEIGHT }}>
        <Box ref={containerRef} sx={{ position: "absolute", inset: 0 }} />
        {bands.map((band) => (
          <LevelBandOverlay key={band.key} band={band} />
        ))}
        {hover && containerRef.current && (
          <ChartTooltip candle={hover.candle} x={hover.x} containerWidth={containerRef.current.clientWidth} />
        )}
      </Box>
    </Paper>
  );
}
