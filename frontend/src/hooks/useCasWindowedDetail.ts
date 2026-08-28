import { useQuery } from "@tanstack/react-query";

import { fetchCasWindowedDetail } from "../api/endpoints/marketTransition";

// Only fetched when a day row is actually expanded (`enabled`) -- this is
// historical, already-computed detail, not a live-ticking value, so no
// polling interval is needed once it's loaded.
export function useCasWindowedDetail(symbol: string, sessionDate: string, enabled: boolean) {
  return useQuery({
    queryKey: ["market-transition", "cas-windowed-detail", symbol, sessionDate],
    queryFn: () => fetchCasWindowedDetail(symbol, sessionDate),
    enabled,
    retry: 1,
    staleTime: Infinity,
  });
}
