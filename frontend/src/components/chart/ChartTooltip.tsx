import { Box, Typography } from "@mui/material";

import { CHART_BORDER, CHART_TEXT, DOWN_COLOR, UP_COLOR } from "./chartTheme";
import type { IndexedCandle } from "./useCandlestickChart";

const TOOLTIP_WIDTH = 190;

export function ChartTooltip({
  candle,
  x,
  containerWidth,
}: {
  candle: IndexedCandle;
  x: number;
  containerWidth: number;
}) {
  const isUp = candle.close >= candle.open;
  const left = x + TOOLTIP_WIDTH + 16 > containerWidth ? x - TOOLTIP_WIDTH - 12 : x + 12;

  return (
    <Box
      sx={{
        position: "absolute",
        left,
        top: 8,
        width: TOOLTIP_WIDTH,
        bgcolor: "#ffffff",
        border: `1px solid ${CHART_BORDER}`,
        borderRadius: 1,
        p: 1,
        pointerEvents: "none",
        boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
      }}
    >
      <Typography variant="caption" sx={{ display: "block", color: CHART_TEXT, fontWeight: 700, mb: 0.5 }}>
        {new Date(candle.timestamp).toLocaleString([], {
          day: "2-digit",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        })}
      </Typography>
      <Typography variant="caption" sx={{ display: "block", color: CHART_TEXT }}>
        O <b>{candle.open.toFixed(2)}</b> &nbsp; H <b>{candle.high.toFixed(2)}</b>
      </Typography>
      <Typography variant="caption" sx={{ display: "block", color: CHART_TEXT }}>
        L <b>{candle.low.toFixed(2)}</b> &nbsp; C{" "}
        <b style={{ color: isUp ? UP_COLOR : DOWN_COLOR }}>{candle.close.toFixed(2)}</b>
      </Typography>
      <Typography variant="caption" sx={{ display: "block", color: CHART_TEXT, mt: 0.25 }}>
        Vol {Math.round(candle.volume).toLocaleString()}
      </Typography>
    </Box>
  );
}
