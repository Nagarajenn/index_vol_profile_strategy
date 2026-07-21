import { Box, Paper, Typography } from "@mui/material";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  useXAxisScale,
  useYAxisScale,
} from "recharts";
import type { TooltipContentProps } from "recharts";

import type { CandleDTO, LevelsSummaryDTO } from "../../types/dashboard";

// Recharts 3.x deprecated <Customized> in favor of rendering arbitrary
// components directly inside the chart and reading scales via hooks --
// see node_modules/recharts/types/hooks.d.ts. This candle layer relies on
// that (useXAxisScale/useYAxisScale), not the older Customized pattern.

interface IndexedCandle extends CandleDTO {
  index: number;
}

const UP_COLOR = "#1b7a4d";
const DOWN_COLOR = "#c62828";
const CHART_HEIGHT = 420;

// The chart panel gets its own pale background + dark text, independent of
// the app's dark theme -- candles/overlays were unreadable against the
// near-black Paper background used everywhere else.
const CHART_BG = "#f7f6f1";
const CHART_GRID = "#dcd9d0";
const CHART_AXIS = "#333333";
const CHART_TEXT = "#1a1a1a";
const CHART_BORDER = "#d0cdc4";

function formatTime(timestamp: string | undefined): string {
  if (!timestamp) return "";
  return new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDateLabel(timestamp: string): string {
  return new Date(timestamp).toLocaleDateString([], { day: "2-digit", month: "short" });
}

/** Index of the first candle belonging to a later calendar date than the
 * first candle in `data` -- i.e. where "today" begins, when the series also
 * carries the previous session's candles for visual continuity. Returns -1
 * if every candle is on the same date (no previous-session data available). */
function findSessionBoundaryIndex(data: IndexedCandle[]): number {
  if (data.length === 0) return -1;
  const firstDate = new Date(data[0].timestamp).toDateString();
  return data.findIndex((d) => new Date(d.timestamp).toDateString() !== firstDate);
}

function CandleSeries({ data }: { data: IndexedCandle[] }) {
  const xScale = useXAxisScale();
  const yScale = useYAxisScale();
  if (!xScale || !yScale) return null;

  return (
    <g>
      {data.map((d) => {
        const xStart = xScale(d.index, { position: "start" });
        const xEnd = xScale(d.index, { position: "end" });
        const yOpen = yScale(d.open);
        const yClose = yScale(d.close);
        const yHigh = yScale(d.high);
        const yLow = yScale(d.low);
        if (
          xStart === undefined ||
          xEnd === undefined ||
          yOpen === undefined ||
          yClose === undefined ||
          yHigh === undefined ||
          yLow === undefined
        ) {
          return null;
        }

        const bandwidth = xEnd - xStart;
        const x = xStart + bandwidth / 2;
        const candleWidth = Math.max(2, bandwidth * 0.6);
        const isUp = d.close >= d.open;
        const color = isUp ? UP_COLOR : DOWN_COLOR;
        const bodyTop = Math.min(yOpen, yClose);
        const bodyHeight = Math.max(1, Math.abs(yClose - yOpen));

        return (
          <g key={d.index}>
            <line x1={x} x2={x} y1={yHigh} y2={yLow} stroke={color} strokeWidth={1} />
            <rect x={x - candleWidth / 2} y={bodyTop} width={candleWidth} height={bodyHeight} fill={color} />
          </g>
        );
      })}
    </g>
  );
}

function CandleTooltip({ active, payload }: TooltipContentProps) {
  if (!active || !payload || payload.length === 0) return null;
  const d = payload[0].payload as IndexedCandle;
  return (
    <Box sx={{ bgcolor: "#ffffff", border: `1px solid ${CHART_BORDER}`, p: 1, fontSize: 12 }}>
      <Typography variant="caption" sx={{ display: "block", color: CHART_TEXT, fontWeight: 600 }}>
        {new Date(d.timestamp).toLocaleString()}
      </Typography>
      <Typography variant="caption" sx={{ display: "block", color: CHART_TEXT }}>
        O {d.open.toFixed(2)} H {d.high.toFixed(2)} L {d.low.toFixed(2)} C {d.close.toFixed(2)}
      </Typography>
      <Typography variant="caption" sx={{ display: "block", color: CHART_TEXT }}>
        Vol {Math.round(d.volume).toLocaleString()}
      </Typography>
    </Box>
  );
}

export function CandlestickChart({
  candles,
  levels,
}: {
  candles: CandleDTO[];
  levels: LevelsSummaryDTO | null;
}) {
  if (candles.length === 0) {
    return (
      <Paper sx={{ p: 2, bgcolor: CHART_BG, border: `1px solid ${CHART_BORDER}` }}>
        <Typography variant="h6" sx={{ mb: 1, color: CHART_TEXT }}>
          Price Chart
        </Typography>
        <Typography sx={{ color: CHART_AXIS }}>No candle data available yet.</Typography>
      </Paper>
    );
  }

  const data: IndexedCandle[] = candles.map((c, index) => ({ ...c, index }));
  const sessionBoundaryIndex = findSessionBoundaryIndex(data);

  // Domain must cover every overlay too, not just candle highs/lows -- a
  // resistance zone above the day's high (common when price hasn't reached
  // it yet) would otherwise fall outside the Y-axis and silently not render.
  const overlayValues = levels
    ? [
        levels.support_low,
        levels.support_high,
        levels.resistance_low,
        levels.resistance_high,
        levels.today_val,
        levels.today_vah,
        levels.today_poc,
        levels.vwap_now,
      ].filter((v): v is number => v != null)
    : [];
  const allValues = [...candles.map((c) => c.high), ...candles.map((c) => c.low), ...overlayValues];
  const yMin = Math.min(...allValues);
  const yMax = Math.max(...allValues);
  const padding = (yMax - yMin) * 0.05 || 1;

  return (
    <Paper sx={{ p: 2, bgcolor: CHART_BG, border: `1px solid ${CHART_BORDER}` }}>
      <Typography variant="h6" sx={{ mb: 1.5, color: CHART_TEXT }}>
        Price Chart (5-min){sessionBoundaryIndex > 0 ? " — previous session + today" : ""}
      </Typography>
      <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
        <ComposedChart data={data} margin={{ top: 10, right: 70, bottom: 10, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART_GRID} />
          <XAxis
            dataKey="index"
            type="category"
            tickFormatter={(index: number) => formatTime(data[index]?.timestamp)}
            stroke={CHART_AXIS}
            minTickGap={40}
          />
          <YAxis
            domain={[yMin - padding, yMax + padding]}
            tickFormatter={(v: number) => v.toLocaleString()}
            stroke={CHART_AXIS}
            width={70}
          />
          <Tooltip content={CandleTooltip} />

          {sessionBoundaryIndex > 0 && (
            <ReferenceLine
              x={sessionBoundaryIndex}
              stroke={CHART_AXIS}
              strokeDasharray="4 4"
              label={{
                value: formatDateLabel(data[sessionBoundaryIndex].timestamp),
                position: "insideTop",
                fill: CHART_AXIS,
                fontSize: 11,
              }}
            />
          )}

          {levels?.support_low != null && levels?.support_high != null && (
            <ReferenceArea
              y1={levels.support_low}
              y2={levels.support_high}
              fill={UP_COLOR}
              fillOpacity={0.28}
              stroke={UP_COLOR}
              strokeOpacity={0.9}
              strokeWidth={1}
              label={{ value: "S", position: "insideTopLeft", fill: UP_COLOR, fontSize: 13, fontWeight: 700 }}
            />
          )}
          {levels?.resistance_low != null && levels?.resistance_high != null && (
            <ReferenceArea
              y1={levels.resistance_low}
              y2={levels.resistance_high}
              fill={DOWN_COLOR}
              fillOpacity={0.28}
              stroke={DOWN_COLOR}
              strokeOpacity={0.9}
              strokeWidth={1}
              label={{ value: "R", position: "insideBottomLeft", fill: DOWN_COLOR, fontSize: 13, fontWeight: 700 }}
            />
          )}
          {levels?.today_val != null && levels?.today_vah != null && (
            <ReferenceArea y1={levels.today_val} y2={levels.today_vah} fill="#2f6fb3" fillOpacity={0.1} strokeOpacity={0} />
          )}
          {levels?.today_poc != null && (
            <ReferenceLine
              y={levels.today_poc}
              stroke="#2f6fb3"
              strokeDasharray="4 2"
              label={{
                value: `POC ${Math.round(levels.today_poc).toLocaleString()}`,
                position: "insideRight",
                fill: "#2f6fb3",
                fontSize: 11,
              }}
            />
          )}
          {levels?.vwap_now != null && (
            <ReferenceLine
              y={levels.vwap_now}
              stroke="#b3690c"
              strokeDasharray="2 2"
              label={{
                value: `VWAP ${Math.round(levels.vwap_now).toLocaleString()}`,
                position: "insideTopRight",
                fill: "#b3690c",
                fontSize: 11,
              }}
            />
          )}

          {/* Invisible series: gives Recharts something to track for hover/tooltip activation
              since the candle bodies themselves are drawn manually, not as a recognized series. */}
          <Line dataKey="close" stroke="transparent" dot={false} activeDot={false} isAnimationActive={false} />

          <CandleSeries data={data} />
        </ComposedChart>
      </ResponsiveContainer>
    </Paper>
  );
}
