import { apiClient } from "../client";
import type { OptionRiskClosingStateDTO } from "../../types/optionRisk";

// Read-only (GET). 12B-option-risk-v1 is advisory: it cannot open, close or modify a position.
export async function fetchOptionRiskClosingState(symbol: string, sessionDate?: string): Promise<OptionRiskClosingStateDTO> {
  const { data } = await apiClient.get<OptionRiskClosingStateDTO>(`/option-risk-12b/${symbol}/closing-state`, {
    params: sessionDate ? { session_date: sessionDate } : undefined,
  });
  return data;
}
