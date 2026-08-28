import { CssBaseline, ThemeProvider } from "@mui/material";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { CasDayDetailPage } from "./pages/CasDayDetailPage";
import { MarketIntelligencePage } from "./pages/MarketIntelligencePage";
import { MarketTransitionPage } from "./pages/MarketTransitionPage";
import { TerminalPage } from "./pages/TerminalPage";
import { appTheme } from "./theme/theme";

const queryClient = new QueryClient();

function App() {
  return (
    <ThemeProvider theme={appTheme}>
      <CssBaseline />
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AppShell>
            <Routes>
              <Route path="/" element={<TerminalPage />} />
              <Route path="/market-intelligence" element={<MarketIntelligencePage />} />
              <Route path="/market-transition-intelligence" element={<MarketTransitionPage />} />
              <Route path="/market-transition-intelligence/cas-day/:symbol/:date" element={<CasDayDetailPage />} />
            </Routes>
          </AppShell>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

export default App;
