import { apiClient } from "../client";
import type { ScalpDecisionDTO, SimPositionHistoryDTO } from "../../types/scalpDecision";

// Read-only (GET). 12C is advisory: it cannot open, close or modify a position.
export async function fetchScalpDecision(
  symbol: string, sessionDate?: string, position?: { type: string; strike: number },
): Promise<ScalpDecisionDTO> {
  const { data } = await apiClient.get<ScalpDecisionDTO>(`/scalp-decision-12c/${symbol}`, {
    params: {
      ...(sessionDate ? { session_date: sessionDate } : {}),
      ...(position ? { position: position.type, strike: position.strike } : {}),
    },
  });
  return data;
}

// Read-only (GET). Closed hypothetical positions; never an order.
export async function fetchScalpHistory(symbol: string, sessionDate?: string): Promise<SimPositionHistoryDTO> {
  const { data } = await apiClient.get<SimPositionHistoryDTO>(`/scalp-decision-12c/${symbol}/history`, {
    params: sessionDate ? { session_date: sessionDate } : undefined,
  });
  return data;
}
