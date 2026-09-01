import { apiClient } from "../client";
import type { SessionAmdDTO } from "../../types/sessionAmd";

export async function fetchSessionAmd(symbol: string): Promise<SessionAmdDTO> {
  const { data } = await apiClient.get<SessionAmdDTO>(`/session-amd/${symbol}`);
  return data;
}
