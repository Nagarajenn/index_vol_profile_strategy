import { useQuery } from "@tanstack/react-query";

import { fetchDashboardLatest, fetchSymbols } from "../api/endpoints/dashboard";

const POLL_INTERVAL_MS = 20_000;

export function useSymbols() {
  return useQuery({
    queryKey: ["symbols"],
    queryFn: fetchSymbols,
    staleTime: Infinity, // static config, never changes during a session
  });
}

export function useDashboardData(symbol: string) {
  return useQuery({
    queryKey: ["dashboard", symbol, "latest"],
    queryFn: () => fetchDashboardLatest(symbol),
    refetchInterval: POLL_INTERVAL_MS,
  });
}
