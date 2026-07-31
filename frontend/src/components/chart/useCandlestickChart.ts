import { useCallback, useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  HistogramSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";

import type { CandleDTO, LevelsSummaryDTO } from "../../types/dashboard";
import type { LiveAdvisoryDTO } from "../../types/liveTransitionAdvisor";
import {
  CHART_AXIS,
  CHART_BG,
  CHART_FONT_FAMILY,
  CHART_GRID,
  CHART_TEXT,
  DOWN_COLOR,
  POC_COLOR,
  RESISTANCE_FILL,
  SUPPORT_FILL,
  UP_COLOR,
  VAH_COLOR,
  VAL_COLOR,
  VALUE_AREA_BORDER,
  VALUE_AREA_FILL,
  VWAP_COLOR,
} from "./chartTheme";
import type { LevelBand } from "./LevelBandOverlay";

export interface IndexedCandle extends CandleDTO {
  index: number;
}

// lightweight-charts uses a time-based X-axis that renders real elapsed time
// as horizontal space -- feeding it real timestamps would draw a huge blank
// gap for the ~18h overnight gap between sessions. Instead we feed evenly
// spaced synthetic timestamps (one per bar) and keep a lookup back to the
// real candle for tick labels, the crosshair tooltip, and session markers --
// the same "index-based axis, real time for display only" approach used by
// the previous Recharts implementation.
const SYNTHETIC_STEP_SECONDS = 300;
const SYNTHETIC_BASE_SECONDS = 1_700_000_000;

function syntheticTime(index: number): UTCTimestamp {
  return (SYNTHETIC_BASE_SECONDS + index * SYNTHETIC_STEP_SECONDS) as UTCTimestamp;
}

function formatTickTime(realTimestamp: string): string {
  return new Date(realTimestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDateLabel(realTimestamp: string): string {
  return new Date(realTimestamp).toLocaleDateString([], { day: "2-digit", month: "short" });
}

export interface HoverInfo {
  x: number;
  candle: IndexedCandle;
}

// Draws the Live Market Transition Advisor's current forecast as a single
// marker on the latest candle -- not a trading signal, just a visual echo
// of the advisor already shown on the Market Transition page. Direction
// comes straight from expected_direction (itself the actual sign of
// analogs' post-transition moves, so it already reflects a reversal
// correctly -- e.g. an uptrend day where analogs mostly reversed down
// yields "down", no separate trend-vs-lean combination needed here). Only
// shown once the advisor has a genuine, non-Observe read -- otherwise the
// chart stays clean.
function buildForecastMarker(indexed: IndexedCandle[], liveAdvisory: LiveAdvisoryDTO | null): SeriesMarker<Time> | null {
  if (!liveAdvisory || !liveAdvisory.is_active || liveAdvisory.risk_level === "Observe" || indexed.length === 0) {
    return null;
  }
  const lastIndex = indexed[indexed.length - 1].index;
  const lean = liveAdvisory.probability_reversal > liveAdvisory.probability_continuation ? "Reversal" : "Continuation";

  if (liveAdvisory.expected_direction === "up") {
    return {
      time: syntheticTime(lastIndex),
      position: "belowBar",
      shape: "arrowUp",
      color: UP_COLOR,
      text: `${lean} (${liveAdvisory.risk_level})`,
    };
  }
  if (liveAdvisory.expected_direction === "down") {
    return {
      time: syntheticTime(lastIndex),
      position: "aboveBar",
      shape: "arrowDown",
      color: DOWN_COLOR,
      text: `${lean} (${liveAdvisory.risk_level})`,
    };
  }
  return {
    time: syntheticTime(lastIndex),
    position: "inBar",
    shape: "circle",
    color: CHART_AXIS,
    text: `Neutral (${liveAdvisory.risk_level})`,
  };
}

export function useCandlestickChart(candles: CandleDTO[], levels: LevelsSummaryDTO | null, liveAdvisory: LiveAdvisoryDTO | null = null) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const indexedRef = useRef<Map<UTCTimestamp, IndexedCandle>>(new Map());

  const [bands, setBands] = useState<LevelBand[]>([]);
  const [hover, setHover] = useState<HoverInfo | null>(null);

  const recomputeBands = useCallback(() => {
    const series = candleSeriesRef.current;
    if (!series || !levels) {
      setBands([]);
      return;
    }
    const next: LevelBand[] = [];
    const push = (key: string, label: string, color: string, fill: string, lo: number | null, hi: number | null) => {
      if (lo == null || hi == null) return;
      const yLo = series.priceToCoordinate(hi);
      const yHi = series.priceToCoordinate(lo);
      if (yLo == null || yHi == null) return;
      next.push({ key, label, color, fill, top: yLo, bottom: yHi });
    };
    push("va", "VA", VALUE_AREA_BORDER, VALUE_AREA_FILL, levels.today_val, levels.today_vah);
    push("support", "S", UP_COLOR, SUPPORT_FILL, levels.support_low, levels.support_high);
    push("resistance", "R", DOWN_COLOR, RESISTANCE_FILL, levels.resistance_low, levels.resistance_high);
    setBands(next);
  }, [levels]);
  const recomputeBandsRef = useRef(recomputeBands);
  recomputeBandsRef.current = recomputeBands;

  // Chart + series creation -- runs once. Resize/crosshair/range-change
  // subscriptions call through recomputeBandsRef so they always see the
  // latest `levels` without needing to be torn down and resubscribed.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: CHART_BG },
        textColor: CHART_TEXT,
        fontFamily: CHART_FONT_FAMILY,
        fontSize: 12,
      },
      grid: {
        vertLines: { color: CHART_GRID },
        horzLines: { color: CHART_GRID },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: CHART_AXIS,
        scaleMargins: { top: 0.08, bottom: 0.28 },
      },
      timeScale: {
        borderColor: CHART_AXIS,
        barSpacing: 10,
        tickMarkFormatter: (time: Time) => {
          const c = indexedRef.current.get(time as UTCTimestamp);
          return c ? formatTickTime(c.timestamp) : "";
        },
      },
      localization: {
        timeFormatter: (time: Time) => {
          const c = indexedRef.current.get(time as UTCTimestamp);
          return c ? new Date(c.timestamp).toLocaleString() : "";
        },
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: UP_COLOR,
      downColor: DOWN_COLOR,
      borderUpColor: UP_COLOR,
      borderDownColor: DOWN_COLOR,
      wickUpColor: UP_COLOR,
      wickDownColor: DOWN_COLOR,
    });
    candleSeries.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.28 } });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      color: UP_COLOR,
    });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.78, bottom: 0 }, visible: false });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    markersRef.current = createSeriesMarkers(candleSeries, []);

    const resizeObserver = new ResizeObserver(() => {
      if (!containerRef.current) return;
      chart.applyOptions({ width: containerRef.current.clientWidth, height: containerRef.current.clientHeight });
      recomputeBandsRef.current();
    });
    resizeObserver.observe(container);

    chart.timeScale().subscribeVisibleLogicalRangeChange(() => recomputeBandsRef.current());

    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !param.point) {
        setHover(null);
        return;
      }
      const c = indexedRef.current.get(param.time as UTCTimestamp);
      if (!c) {
        setHover(null);
        return;
      }
      setHover({ x: param.point.x, candle: c });
    });

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      markersRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Data updates: rebuild the synthetic-time <-> real-candle lookup, push
  // new series data, mark the previous-session/today boundary, refit.
  useEffect(() => {
    const candleSeries = candleSeriesRef.current;
    const volumeSeries = volumeSeriesRef.current;
    if (!candleSeries || !volumeSeries) return;

    const indexed: IndexedCandle[] = candles.map((c, index) => ({ ...c, index }));
    const lookup = new Map<UTCTimestamp, IndexedCandle>();
    indexed.forEach((c) => lookup.set(syntheticTime(c.index), c));
    indexedRef.current = lookup;

    candleSeries.setData(
      indexed.map((c) => ({ time: syntheticTime(c.index), open: c.open, high: c.high, low: c.low, close: c.close }))
    );
    volumeSeries.setData(
      indexed.map((c) => ({
        time: syntheticTime(c.index),
        value: c.volume,
        color: c.close >= c.open ? "rgba(27,122,77,0.5)" : "rgba(198,40,40,0.5)",
      }))
    );

    const firstDate = indexed.length > 0 ? new Date(indexed[0].timestamp).toDateString() : null;
    const boundaryCandle = indexed.find((c) => new Date(c.timestamp).toDateString() !== firstDate);
    if (markersRef.current) {
      const markers: SeriesMarker<Time>[] = [];
      if (boundaryCandle) {
        markers.push({
          time: syntheticTime(boundaryCandle.index),
          position: "aboveBar",
          shape: "arrowDown",
          color: CHART_AXIS,
          text: formatDateLabel(boundaryCandle.timestamp),
        });
      }
      const forecastMarker = buildForecastMarker(indexed, liveAdvisory);
      if (forecastMarker) markers.push(forecastMarker);
      markers.sort((a, b) => (a.time as number) - (b.time as number));
      markersRef.current.setMarkers(markers);
    }

    chartRef.current?.timeScale().fitContent();
    recomputeBandsRef.current();
  }, [candles, liveAdvisory]);

  // Level price lines (POC/VWAP/VAH/VAL) -- distinct colors + native labels.
  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series) return;

    const created = [
      levels?.today_poc != null
        ? series.createPriceLine({
            price: levels.today_poc,
            color: POC_COLOR,
            lineWidth: 2,
            lineStyle: LineStyle.Dashed,
            title: `POC ${Math.round(levels.today_poc).toLocaleString()}`,
          })
        : null,
      levels?.vwap_now != null
        ? series.createPriceLine({
            price: levels.vwap_now,
            color: VWAP_COLOR,
            lineWidth: 2,
            lineStyle: LineStyle.Dashed,
            title: `VWAP ${Math.round(levels.vwap_now).toLocaleString()}`,
          })
        : null,
      levels?.today_vah != null
        ? series.createPriceLine({
            price: levels.today_vah,
            color: VAH_COLOR,
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            title: `VAH ${Math.round(levels.today_vah).toLocaleString()}`,
          })
        : null,
      levels?.today_val != null
        ? series.createPriceLine({
            price: levels.today_val,
            color: VAL_COLOR,
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            title: `VAL ${Math.round(levels.today_val).toLocaleString()}`,
          })
        : null,
    ].filter((l): l is NonNullable<typeof l> => l != null);

    recomputeBandsRef.current();

    return () => {
      created.forEach((line) => series.removePriceLine(line));
    };
  }, [levels]);

  return { containerRef, bands, hover };
}
