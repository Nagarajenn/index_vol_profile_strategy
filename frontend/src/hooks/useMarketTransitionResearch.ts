import { useQuery } from "@tanstack/react-query";

import { fetchMarketTransitionResearch } from "../api/endpoints/marketTransition";

// This is a research view over historical data, recomputed only when
// scripts/run_market_transition_research.py is re-run (not on every tick) --
// no need for a fast poll interval.
const POLL_INTERVAL_MS = 5 * 60_000;

export function useMarketTransitionResearch(symbol: string) {
  return useQuery({
    queryKey: ["market-transition", "research", symbol],
    queryFn: () => fetchMarketTransitionResearch(symbol),
    refetchInterval: POLL_INTERVAL_MS,
    retry: 1,
  });
}
