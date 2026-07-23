import { useQuery } from "@tanstack/react-query";

import { fetchVolumeProfileIntelligence } from "../api/endpoints/volumeProfile";

// Heavier than the core dashboard poll (multi-day candle fetch + full
// profile recomputation), so it's polled less frequently.
const POLL_INTERVAL_MS = 60_000;

export function useVolumeProfileIntelligence(symbol: string) {
  return useQuery({
    queryKey: ["volume-profile", symbol, "intelligence"],
    queryFn: () => fetchVolumeProfileIntelligence(symbol),
    refetchInterval: POLL_INTERVAL_MS,
    retry: 1,
  });
}
