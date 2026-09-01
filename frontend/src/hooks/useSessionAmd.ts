import { useQuery } from "@tanstack/react-query";

import { fetchSessionAmd } from "../api/endpoints/sessionAmd";

// Lighter compute than Volume Intelligence's 90s poll -- no multi-day
// history fetch or similarity calc, just today's candles. Matches Volume
// Profile Intelligence's 60s cadence.
const POLL_INTERVAL_MS = 60_000;

export function useSessionAmd(symbol: string) {
  return useQuery({
    queryKey: ["session-amd", symbol],
    queryFn: () => fetchSessionAmd(symbol),
    refetchInterval: POLL_INTERVAL_MS,
    retry: 1,
  });
}
