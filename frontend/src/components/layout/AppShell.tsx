import { AppBar, Box, Stack, Toolbar, Typography } from "@mui/material";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { SymbolSwitcher } from "./SymbolSwitcher";

const navLinkSx = {
  color: "text.secondary",
  textDecoration: "none",
  fontSize: "0.85rem",
  fontWeight: 600,
  "&.active": { color: "primary.main" },
};

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="static" elevation={0}>
        <Toolbar variant="dense" sx={{ gap: 3 }}>
          <Typography variant="h6" sx={{ letterSpacing: 0.5 }}>
            Trading Intelligence Terminal
          </Typography>
          <SymbolSwitcher />
          <Stack direction="row" spacing={2.5} sx={{ ml: "auto" }}>
            <Box component={NavLink} to="/" end sx={navLinkSx}>
              Terminal
            </Box>
            <Box component={NavLink} to="/market-intelligence" sx={navLinkSx}>
              Market Intelligence
            </Box>
            <Box component={NavLink} to="/market-transition-intelligence" sx={navLinkSx}>
              Market Transition Intelligence
            </Box>
          </Stack>
        </Toolbar>
      </AppBar>
      <Box component="main" sx={{ p: 2 }}>
        {children}
      </Box>
    </Box>
  );
}
