import { apiClient } from "../client";
import type { CasIntelligenceResponseDTO, MtiResearchResponseDTO } from "../../types/marketTransition";

export async function fetchMarketTransitionResearch(symbol: string): Promise<MtiResearchResponseDTO> {
  const { data } = await apiClient.get<MtiResearchResponseDTO>(`/market-transition/${symbol}/research`);
  return data;
}

export async function fetchCasIntelligence(symbol: string): Promise<CasIntelligenceResponseDTO> {
  const { data } = await apiClient.get<CasIntelligenceResponseDTO>(`/market-transition/${symbol}/cas-intelligence`);
  return data;
}
