import { useQuery } from "@tanstack/react-query";

import { fetchScalpDecision, fetchScalpHistory } from "../api/endpoints/scalpDecision";

// Option snapshots and levels both land once a minute; a 20 s poll keeps a scalper's
// panel at most one snapshot behind. Historical sessions never change, so they don't poll.
const LIVE_POLL_MS = 20_000;

export function useScalpDecision(symbol: string, sessionDate?: string, position?: { type: string; strike: number }) {
  return useQuery({
    queryKey: ["scalp-decision-12c", symbol, sessionDate ?? "latest", position?.type ?? "none", position?.strike ?? 0],
    queryFn: () => fetchScalpDecision(symbol, sessionDate, position),
    refetchInterval: (q) => (q.state.data?.is_live_session ? LIVE_POLL_MS : false),
    retry: 1,
  });
}

// Closed positions change only when one closes, so this polls far more slowly than the decision.
const HISTORY_POLL_MS = 60_000;

export function useScalpHistory(symbol: string, sessionDate?: string, live = true) {
  return useQuery({
    queryKey: ["scalp-decision-12c", "history", symbol, sessionDate ?? "latest"],
    queryFn: () => fetchScalpHistory(symbol, sessionDate),
    refetchInterval: live ? HISTORY_POLL_MS : false,
    retry: 1,
  });
}
