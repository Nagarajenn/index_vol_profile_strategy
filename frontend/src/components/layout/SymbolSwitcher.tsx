import { ToggleButton, ToggleButtonGroup, CircularProgress } from "@mui/material";

import { useSymbols } from "../../hooks/useDashboardData";
import { useSymbolStore } from "../../store/useSymbolStore";

export function SymbolSwitcher() {
  const { data: symbols, isLoading } = useSymbols();
  const selectedSymbol = useSymbolStore((s) => s.selectedSymbol);
  const setSelectedSymbol = useSymbolStore((s) => s.setSelectedSymbol);

  if (isLoading) return <CircularProgress size={20} />;

  return (
    <ToggleButtonGroup
      value={selectedSymbol}
      exclusive
      size="small"
      onChange={(_, value) => value && setSelectedSymbol(value)}
    >
      {(symbols ?? []).map((s) => (
        <ToggleButton key={s.symbol} value={s.symbol} sx={{ px: 2, fontWeight: 600 }}>
          {s.symbol}
        </ToggleButton>
      ))}
    </ToggleButtonGroup>
  );
}
