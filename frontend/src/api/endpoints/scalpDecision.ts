import { apiClient } from "../client";
import type { ScalpDecisionDTO } from "../../types/scalpDecision";

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
