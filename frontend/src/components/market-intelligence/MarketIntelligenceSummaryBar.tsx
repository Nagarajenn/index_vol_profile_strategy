import { ChevronRight } from "@mui/icons-material";
import { Box, Chip, Stack, Typography } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";

import { useMarketIntelligence } from "../../hooks/useMarketIntelligence";
import { formatTime, riskColor, sentimentColor } from "../../utils/marketIntelligenceFormat";

// Compact entry point on the main terminal page -- the full panel (events,
// sector heat map) lives on its own page now, reached via the link here, so
// the terminal page stays focused on the primary technical decision.
export function MarketIntelligenceSummaryBar() {
  const { data, isLoading, isError } = useMarketIntelligence();

  return (
    <Box
      component={RouterLink}
      to="/market-intelligence"
      sx={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 1.5,
        p: 1.25,
        borderRadius: 1,
        border: "1px solid",
        borderColor: "divider",
        bgcolor: "background.paper",
        textDecoration: "none",
        color: "inherit",
        "&:hover": { borderColor: "primary.main" },
      }}
    >
      <Stack direction="row" spacing={2} sx={{ alignItems: "center", flexWrap: "wrap", rowGap: 1 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
          Market Intelligence &amp; Sentiment
        </Typography>

        {isLoading && (
          <Typography variant="body2" color="text.secondary">
            Loading...
          </Typography>
        )}
        {isError && !isLoading && (
          <Typography variant="body2" color="text.secondary">
            Unavailable
          </Typography>
        )}

        {data && (
          <>
            <Chip size="small" label={data.overall_sentiment} color={sentimentColor(data.overall_sentiment)} />
            <Typography variant="body2">
              Risk:{" "}
              <Box component="span" sx={{ fontWeight: 700, color: riskColor(data.news_risk_score) }}>
                {data.news_risk_score}/100
              </Box>
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {data.events.length} high-impact event{data.events.length === 1 ? "" : "s"}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              Updated {formatTime(data.last_updated)}
            </Typography>
          </>
        )}
      </Stack>

      <Stack direction="row" spacing={0.25} sx={{ alignItems: "center", color: "primary.main" }}>
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          View full report
        </Typography>
        <ChevronRight fontSize="small" />
      </Stack>
    </Box>
  );
}
