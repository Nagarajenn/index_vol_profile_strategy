import { useQuery } from "@tanstack/react-query";

import { fetchVolumeIntelligence } from "../api/endpoints/volumeIntelligence";

// Heavier than Volume Profile Intelligence's 60s poll: a 60-day (vs. 10-day)
// candle fetch plus an extra O(days) similarity distance calc. Kept at 90s
// rather than the full 120s considered, since dominance/momentum/the
// narrative are explicitly "the last few minutes" reads that shouldn't go
// too stale for a decision-support tool.
const POLL_INTERVAL_MS = 90_000;

export function useVolumeIntelligence(symbol: string) {
  return useQuery({
    queryKey: ["volume-intelligence", symbol],
    queryFn: () => fetchVolumeIntelligence(symbol),
    refetchInterval: POLL_INTERVAL_MS,
    retry: 1,
  });
}
