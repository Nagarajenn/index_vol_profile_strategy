import { apiClient } from "../client";
import type { LiveAdvisoryDTO } from "../../types/liveTransitionAdvisor";

export async function fetchLiveTransitionAdvisor(symbol: string): Promise<LiveAdvisoryDTO> {
  const { data } = await apiClient.get<LiveAdvisoryDTO>(`/market-transition/${symbol}/live-advisor`);
  return data;
}
