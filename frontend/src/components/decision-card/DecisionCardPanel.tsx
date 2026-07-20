import { Chip } from "@mui/material";

import { AnalysisCard, type RawValue } from "../common/AnalysisCard";
import type { DashboardResponseDTO } from "../../types/dashboard";
import { TrendBadge } from "./TrendBadge";

function formatRange(low: number | null, high: number | null): string {
  if (low === null || high === null) return "N/A";
  const mid = (low + high) / 2;
  if (mid !== 0 && (high - low) / mid < 0.001) return Math.round(mid).toLocaleString();
  return `${Math.round(low).toLocaleString()}–${Math.round(high).toLocaleString()}`;
}

function formatNumber(value: number | null): string {
  return value !== null ? Math.round(value).toLocaleString() : "N/A";
}

function statusColor(status: DashboardResponseDTO["status"]): "success" | "warning" | "default" {
  if (status === "live") return "success";
  if (status === "stale") return "warning";
  return "default";
}

/**
 * AI Decision Card (V2 enhancement #1): a thin adapter mapping
 * DashboardResponseDTO onto the generic AnalysisCard 4-layer shell. All
 * data shown previously (Trend, Institutional Bias, Confidence,
 * Support/Resistance/POC/VWAP, Action) is preserved -- just reorganized
 * into Raw Values / AI Interpretation / Confidence / Trading Implication,
 * plus the new `interpretation` field from the backend.
 */
export function DecisionCardPanel({ data }: { data: DashboardResponseDTO }) {
  const { levels, status, as_of, symbol } = data;

  const statusChip = (
    <Chip
      label={status === "no_data" ? "No data" : `${status} · ${as_of ? new Date(as_of).toLocaleTimeString() : ""}`}
      color={statusColor(status)}
      size="small"
      variant="outlined"
    />
  );

  if (!levels) {
    return (
      <AnalysisCard
        title={symbol}
        question="Should I favor calls, puts, or wait right now?"
        headerRight={statusChip}
        rawValues={[]}
        interpretation={null}
        confidence={null}
        implication="No snapshot available yet for this symbol."
      />
    );
  }

  const rawValues: RawValue[] = [
    { label: "Trend", value: <TrendBadge label={levels.trend_label} /> },
    { label: "Institutional Bias", value: levels.institutional_bias_label ?? "N/A" },
    { label: "Support", value: formatRange(levels.support_low, levels.support_high) },
    { label: "Resistance", value: formatRange(levels.resistance_low, levels.resistance_high) },
    { label: "POC", value: formatNumber(levels.today_poc) },
    { label: "VWAP", value: formatNumber(levels.vwap_now) },
  ];

  return (
    <AnalysisCard
      title={symbol}
      question="Should I favor calls, puts, or wait right now?"
      headerRight={statusChip}
      rawValues={rawValues}
      interpretation={levels.interpretation}
      confidence={levels.confidence_score}
      implication={levels.action_text}
    />
  );
}
