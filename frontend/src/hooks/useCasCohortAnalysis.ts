import { useQuery } from "@tanstack/react-query";

import { fetchCasCohortAnalysis } from "../api/endpoints/marketTransition";

// Same cadence as useCasIntelligence -- recomputed only when
// scripts/run_cas_cohort_analysis.py runs, not on every tick.
const POLL_INTERVAL_MS = 5 * 60_000;

export function useCasCohortAnalysis(symbol: string) {
  return useQuery({
    queryKey: ["market-transition", "cas-cohort-analysis", symbol],
    queryFn: () => fetchCasCohortAnalysis(symbol),
    refetchInterval: POLL_INTERVAL_MS,
    retry: 1,
  });
}
