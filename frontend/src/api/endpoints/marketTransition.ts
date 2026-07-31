import { apiClient } from "../client";
import type { MtiResearchResponseDTO } from "../../types/marketTransition";

export async function fetchMarketTransitionResearch(symbol: string): Promise<MtiResearchResponseDTO> {
  const { data } = await apiClient.get<MtiResearchResponseDTO>(`/market-transition/${symbol}/research`);
  return data;
}
