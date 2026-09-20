import { useQuery } from "@tanstack/react-query";

import { fetchOptionRiskClosingState } from "../api/endpoints/optionRisk";

// Option-chain snapshots land once a minute, so a 30 s poll keeps the live
// 15:00-15:30 view at most one snapshot behind. Historical sessions never change.
const LIVE_POLL_MS = 30_000;

export function useOptionRiskClosingState(symbol: string, sessionDate?: string) {
  return useQuery({
    queryKey: ["option-risk-12b", symbol, sessionDate ?? "default"],
    queryFn: () => fetchOptionRiskClosingState(symbol, sessionDate),
    refetchInterval: (q) => (q.state.data?.is_live_session ? LIVE_POLL_MS : false),
    retry: 1,
  });
}
