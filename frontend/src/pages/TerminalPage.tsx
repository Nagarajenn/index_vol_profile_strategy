import { Alert, Box, CircularProgress, Stack } from "@mui/material";

import { CandlestickChart } from "../components/chart/CandlestickChart";
import { DecisionCardPanel } from "../components/decision-card/DecisionCardPanel";
import { MarketIntelligenceSummaryBar } from "../components/market-intelligence/MarketIntelligenceSummaryBar";
import { OptionChainPanel } from "../components/option-chain/OptionChainPanel";
import { VolumeIntelligencePanel } from "../components/volume-intelligence/VolumeIntelligencePanel";
import { VolumeProfileIntelligencePanel } from "../components/volume-profile/VolumeProfileIntelligencePanel";
import { useDashboardData } from "../hooks/useDashboardData";
import { useLiveTransitionAdvisor } from "../hooks/useLiveTransitionAdvisor";
import { useSymbolStore } from "../store/useSymbolStore";

export function TerminalPage() {
  const selectedSymbol = useSymbolStore((s) => s.selectedSymbol);
  const { data, isLoading, isError, error } = useDashboardData(selectedSymbol);
  // Live Market Transition Advisor's forecast, reused here only to draw the
  // chart's directional arrow marker -- this page doesn't otherwise touch
  // the Market Transition Intelligence feature, and a fetch error here must
  // never break the main dashboard (hence no isError handling below).
  const { data: liveAdvisory } = useLiveTransitionAdvisor(selectedSymbol);

  if (isLoading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", mt: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (isError || !data) {
    return (
      <Alert severity="error" sx={{ mt: 2 }}>
        Failed to load dashboard data: {error instanceof Error ? error.message : "unknown error"}
      </Alert>
    );
  }

  return (
    <Stack spacing={2} sx={{ width: "100%" }}>
      <DecisionCardPanel data={data} />
      <Box sx={{ height: 3, bgcolor: "divider", borderRadius: 1 }} />
      <MarketIntelligenceSummaryBar />
      <Box sx={{ display: "flex", gap: 1.5, flexDirection: { xs: "column", md: "row" }, alignItems: "flex-start" }}>
        <Box sx={{ width: { xs: "100%", md: "30%" }, flexShrink: 0, minWidth: 0 }}>
          <VolumeProfileIntelligencePanel symbol={selectedSymbol} />
        </Box>
        <Box sx={{ width: { xs: "100%", md: "70%" }, minWidth: 0 }}>
          <CandlestickChart candles={data.candles} levels={data.levels} liveAdvisory={liveAdvisory ?? null} />
        </Box>
      </Box>
      <VolumeIntelligencePanel symbol={selectedSymbol} />
      <OptionChainPanel data={data.option_chain} />
    </Stack>
  );
}
