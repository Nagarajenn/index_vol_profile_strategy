import type { MarketIntelligenceEventDTO, Sentiment } from "../types/marketIntelligence";

const TRUMP_PATTERN = /trump/i;

// Client-side keyword flag, not a classifier field -- Trump/US-Iran
// commentary is currently the dominant global driver, so surface it without
// needing a schema change or reclassifying already-stored events.
export function mentionsTrump(event: Pick<MarketIntelligenceEventDTO, "title" | "rationale">): boolean {
  return TRUMP_PATTERN.test(event.title) || TRUMP_PATTERN.test(event.rationale);
}

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
