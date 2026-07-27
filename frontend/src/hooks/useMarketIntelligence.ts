import { useQuery } from "@tanstack/react-query";

import { fetchMarketIntelligenceLatest } from "../api/endpoints/marketIntelligence";

// News/events change slowly relative to price data -- symbol-independent,
// so one poll serves the whole dashboard regardless of which index is selected.
const POLL_INTERVAL_MS = 60_000;

export function useMarketIntelligence() {
  return useQuery({
    queryKey: ["market-intelligence", "latest"],
    queryFn: fetchMarketIntelligenceLatest,
    refetchInterval: POLL_INTERVAL_MS,
    retry: 1,
  });
}
