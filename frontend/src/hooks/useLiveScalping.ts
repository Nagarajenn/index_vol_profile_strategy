import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../api/client";
import type { LiveScalpingDTO } from "../types/liveScalping";

/** 13A decision support. Read-only: this hook can only GET. */
export function useLiveScalping(symbol: string, sessionDate?: string) {
  return useQuery<LiveScalpingDTO>({
    queryKey: ["live-scalping-13a", symbol, sessionDate ?? "latest"],
    queryFn: async () => {
      const { data } = await apiClient.get<LiveScalpingDTO>(`/live-scalping-13a/${symbol}`, {
        params: sessionDate ? { session_date: sessionDate } : undefined,
      });
      return data;
    },
    refetchInterval: 30_000,
    retry: 1,
  });
}
