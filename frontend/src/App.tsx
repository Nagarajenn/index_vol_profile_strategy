import { CssBaseline, ThemeProvider } from "@mui/material";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { CasDayDetailPage } from "./pages/CasDayDetailPage";
import { MarketTransitionPage } from "./pages/MarketTransitionPage";
import { PaperTradingPage } from "./pages/PaperTradingPage";
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
              <Route path="/paper-trading" element={<PaperTradingPage />} />
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
