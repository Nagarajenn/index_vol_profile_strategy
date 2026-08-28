import { Stack } from "@mui/material";

import { CasIntelligencePanel } from "../components/market-transition/CasIntelligencePanel";
import { LiveAdvisorPanel } from "../components/market-transition/LiveAdvisorPanel";
import { useSymbolStore } from "../store/useSymbolStore";

// The original 2:00-3:01pm Market Transition Intelligence research view
// (Factor Correlation Study + Daily Transition Results, keyed off the
// pre-CAS window) has been removed from this page -- superseded by
// CasIntelligencePanel below, which re-does the same analysis over the
// CAS-adjusted 14:31-14:59 vs 15:00-15:39 windows. The old research
// engine (market_transition/research.py, scripts/run_market_transition_
// research.py, the mti_daily_transitions/mti_factor_correlations tables)
// is untouched -- CasIntelligencePanel's "Original engine" column still
// reads from it for the day-by-day agreement comparison.
export function MarketTransitionPage() {
  const selectedSymbol = useSymbolStore((s) => s.selectedSymbol);

  return (
    <Stack spacing={2} sx={{ width: "100%" }}>
      <LiveAdvisorPanel />
      <CasIntelligencePanel symbol={selectedSymbol} />
    </Stack>
  );
}
