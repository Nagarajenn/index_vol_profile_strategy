import { useQuery } from "@tanstack/react-query";

import { fetchLiveTransitionAdvisor } from "../api/endpoints/liveTransitionAdvisor";

// "Every minute it should update" per spec -- poll a bit faster than that
// so the displayed read never lags a full minute behind.
const POLL_INTERVAL_MS = 20_000;

export function useLiveTransitionAdvisor(symbol: string) {
  return useQuery({
    queryKey: ["market-transition", "live-advisor", symbol],
    queryFn: () => fetchLiveTransitionAdvisor(symbol),
    refetchInterval: POLL_INTERVAL_MS,
    retry: 1,
  });
}
