import { apiClient } from "../client";
import type { PaperPositionDTO, PaperTodayDTO } from "../../types/paperTrading";

export async function fetchPaperToday(): Promise<PaperTodayDTO> {
  const { data } = await apiClient.get<PaperTodayDTO>("/paper-trading/today");
  return data;
}

export async function fetchPaperTrades(): Promise<PaperPositionDTO[]> {
  const { data } = await apiClient.get<PaperPositionDTO[]>("/paper-trading/trades");
  return data;
}
