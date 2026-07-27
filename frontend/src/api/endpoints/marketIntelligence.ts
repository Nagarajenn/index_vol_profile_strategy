import { apiClient } from "../client";
import type { MarketIntelligenceSummaryDTO } from "../../types/marketIntelligence";

export async function fetchMarketIntelligenceLatest(): Promise<MarketIntelligenceSummaryDTO> {
  const { data } = await apiClient.get<MarketIntelligenceSummaryDTO>("/market-intelligence/latest");
  return data;
}
