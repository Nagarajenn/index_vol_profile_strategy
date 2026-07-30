import type { Sentiment } from "../types/marketIntelligence";

export function sentimentColor(sentiment: Sentiment): "success" | "error" | "default" {
  if (sentiment === "Bullish") return "success";
  if (sentiment === "Bearish") return "error";
  return "default";
}

export function riskColor(score: number): string {
  if (score >= 70) return "error.main";
  if (score >= 40) return "warning.main";
  return "success.main";
}

export function formatTime(iso: string | null): string {
  if (!iso) return "N/A";
  return new Date(iso).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
