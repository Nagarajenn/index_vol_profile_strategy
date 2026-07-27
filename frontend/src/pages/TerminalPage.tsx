import { Alert, Box, CircularProgress, Stack } from "@mui/material";

import { CandlestickChart } from "../components/chart/CandlestickChart";
import { DecisionCardPanel } from "../components/decision-card/DecisionCardPanel";
import { MarketIntelligencePanel } from "../components/market-intelligence/MarketIntelligencePanel";
import { OptionChainPanel } from "../components/option-chain/OptionChainPanel";
import { VolumeProfileIntelligencePanel } from "../components/volume-profile/VolumeProfileIntelligencePanel";
import { useDashboardData } from "../hooks/useDashboardData";
import { useSymbolStore } from "../store/useSymbolStore";

export function TerminalPage() {
  const selectedSymbol = useSymbolStore((s) => s.selectedSymbol);
  const { data, isLoading, isError, error } = useDashboardData(selectedSymbol);

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
      <Box sx={{ display: "flex", gap: 2, flexDirection: { xs: "column", md: "row" }, alignItems: "flex-start" }}>
        <Box sx={{ width: { xs: "100%", md: 360 }, flexShrink: 0 }}>
          <VolumeProfileIntelligencePanel symbol={selectedSymbol} />
        </Box>
        <Box sx={{ flex: 1, minWidth: 0, width: "100%" }}>
          <CandlestickChart candles={data.candles} levels={data.levels} />
        </Box>
      </Box>
      <OptionChainPanel data={data.option_chain} />
      <MarketIntelligencePanel />
    </Stack>
  );
}
