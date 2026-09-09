import { useQuery } from "@tanstack/react-query";

import { fetchPaperToday, fetchPaperTrades } from "../api/endpoints/paperTrading";

// The paper agent decides at 14:59 and then manages a position minute by
// minute, so the Command Center polls faster than the analytics panels --
// during a live position a stale view is actively misleading.
const TODAY_POLL_MS = 20_000;
const TRADES_POLL_MS = 60_000;

export function usePaperToday() {
  return useQuery({
    queryKey: ["paper-trading", "today"],
    queryFn: fetchPaperToday,
    refetchInterval: TODAY_POLL_MS,
    retry: 1,
  });
}

export function usePaperTrades() {
  return useQuery({
    queryKey: ["paper-trading", "trades"],
    queryFn: fetchPaperTrades,
    refetchInterval: TRADES_POLL_MS,
    retry: 1,
  });
}
