import { VolumeOff, VolumeUp } from "@mui/icons-material";
import { AppBar, Box, IconButton, Stack, Toolbar, Tooltip, Typography } from "@mui/material";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import { useDashboardData } from "../../hooks/useDashboardData";
import { useTrendAlert } from "../../hooks/useTrendAlert";
import { useAlertSoundStore } from "../../store/useAlertSoundStore";
import { useSymbolStore } from "../../store/useSymbolStore";
import { unlockTrendAlertAudio } from "../../utils/trendAlertSounds";
import { SymbolSwitcher } from "./SymbolSwitcher";

const navLinkSx = {
  color: "text.secondary",
  textDecoration: "none",
  fontSize: "0.85rem",
  fontWeight: 600,
  "&.active": { color: "primary.main" },
};

export function AppShell({ children }: { children: ReactNode }) {
  const selectedSymbol = useSymbolStore((s) => s.selectedSymbol);
  const { data, dataUpdatedAt } = useDashboardData(selectedSymbol);
  const soundEnabled = useAlertSoundStore((s) => s.enabled);
  const toggleSound = useAlertSoundStore((s) => s.toggle);

  // Lives at the shell level (not TerminalPage) so a 2-candle trend alarm
  // fires no matter which page the trader currently has open. Shares the
  // same TanStack Query cache entry as TerminalPage's own dashboard poll --
  // no extra network requests.
  useTrendAlert(selectedSymbol, data?.levels?.trend_label ?? null, dataUpdatedAt, soundEnabled);

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="static" elevation={0}>
        <Toolbar variant="dense" sx={{ gap: 3 }}>
          <Typography variant="h6" sx={{ letterSpacing: 0.5 }}>
            Trading Intelligence Terminal
          </Typography>
          <SymbolSwitcher />
          <Stack direction="row" spacing={2.5} sx={{ ml: "auto", alignItems: "center" }}>
            <Box component={NavLink} to="/" end sx={navLinkSx}>
              Terminal
            </Box>
            <Box component={NavLink} to="/market-intelligence" sx={navLinkSx}>
              Market Intelligence
            </Box>
            <Box component={NavLink} to="/market-transition-intelligence" sx={navLinkSx}>
              Market Transition Intelligence
            </Box>
            <Tooltip title={soundEnabled ? "Mute trend alarm (2-candle Bullish/Bearish sound)" : "Unmute trend alarm"}>
              <IconButton
                size="small"
                onClick={() => {
                  unlockTrendAlertAudio();
                  toggleSound();
                }}
                sx={{ color: soundEnabled ? "primary.main" : "text.secondary" }}
              >
                {soundEnabled ? <VolumeUp fontSize="small" /> : <VolumeOff fontSize="small" />}
              </IconButton>
            </Tooltip>
          </Stack>
        </Toolbar>
      </AppBar>
      <Box component="main" sx={{ p: 2 }}>
        {children}
      </Box>
    </Box>
  );
}
