import { ChevronLeft } from "@mui/icons-material";
import { Stack, Typography } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";

import { MarketIntelligencePanel } from "../components/market-intelligence/MarketIntelligencePanel";

export function MarketIntelligencePage() {
  return (
    <Stack spacing={2} sx={{ width: "100%" }}>
      <Stack
        component={RouterLink}
        to="/"
        direction="row"
        sx={{ alignItems: "center", color: "primary.main", textDecoration: "none", width: "fit-content" }}
      >
        <ChevronLeft fontSize="small" />
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          Back to Terminal
        </Typography>
      </Stack>
      <MarketIntelligencePanel />
    </Stack>
  );
}
