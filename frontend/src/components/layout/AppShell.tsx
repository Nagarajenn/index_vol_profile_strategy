import { AppBar, Box, Toolbar, Typography } from "@mui/material";
import type { ReactNode } from "react";

import { SymbolSwitcher } from "./SymbolSwitcher";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="static" elevation={0}>
        <Toolbar variant="dense" sx={{ gap: 3 }}>
          <Typography variant="h6" sx={{ letterSpacing: 0.5 }}>
            Trading Intelligence Terminal
          </Typography>
          <SymbolSwitcher />
        </Toolbar>
      </AppBar>
      <Box component="main" sx={{ p: 2 }}>
        {children}
      </Box>
    </Box>
  );
}
