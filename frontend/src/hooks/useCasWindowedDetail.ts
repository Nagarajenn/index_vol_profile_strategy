import { useQuery } from "@tanstack/react-query";

import { fetchCasWindowedDetail } from "../api/endpoints/marketTransition";

// Only fetched when a day row is actually expanded (`enabled`). For a past
// (closed) day this is immutable once computed -- no polling needed, hence
// staleTime: Infinity by default. `refetchIntervalMs`, when passed, opts
// into polling instead -- used by LiveCasTrackerPanel for TODAY's
// in-progress session, where the same session_date's data keeps changing
// underneath the same query key as the live loop writes new rows.
export function useCasWindowedDetail(symbol: string, sessionDate: string, enabled: boolean, refetchIntervalMs?: number) {
  return useQuery({
    queryKey: ["market-transition", "cas-windowed-detail", symbol, sessionDate],
    queryFn: () => fetchCasWindowedDetail(symbol, sessionDate),
    enabled,
    retry: 1,
    staleTime: refetchIntervalMs ? 0 : Infinity,
    refetchInterval: refetchIntervalMs,
  });
}
