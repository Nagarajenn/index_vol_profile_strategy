import { useQuery } from "@tanstack/react-query";

import { fetchCasIntelligence } from "../api/endpoints/marketTransition";

// Same cadence as useMarketTransitionResearch -- recomputed only when
// scripts/run_cas_intelligence.py runs (once daily, post-market), not on
// every tick.
const POLL_INTERVAL_MS = 5 * 60_000;

export function useCasIntelligence(symbol: string) {
  return useQuery({
    queryKey: ["market-transition", "cas-intelligence", symbol],
    queryFn: () => fetchCasIntelligence(symbol),
    refetchInterval: POLL_INTERVAL_MS,
    retry: 1,
  });
}
