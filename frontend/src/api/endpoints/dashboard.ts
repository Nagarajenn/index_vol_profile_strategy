import { apiClient } from "../client";
import type { DashboardResponseDTO, SymbolInfoDTO } from "../../types/dashboard";

export async function fetchSymbols(): Promise<SymbolInfoDTO[]> {
  const { data } = await apiClient.get<SymbolInfoDTO[]>("/symbols");
  return data;
}

export async function fetchDashboardLatest(symbol: string): Promise<DashboardResponseDTO> {
  const { data } = await apiClient.get<DashboardResponseDTO>(`/dashboard/${symbol}/latest`);
  return data;
}
