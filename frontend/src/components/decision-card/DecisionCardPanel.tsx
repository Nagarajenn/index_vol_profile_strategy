import { Box, Chip, Divider, Paper, Stack, Typography } from "@mui/material";

import type { DashboardResponseDTO } from "../../types/dashboard";
import { ConfidenceGauge } from "./ConfidenceGauge";
import { TrendBadge } from "./TrendBadge";

function formatRange(low: number | null, high: number | null): string {
  if (low === null || high === null) return "N/A";
  const mid = (low + high) / 2;
  if (mid !== 0 && (high - low) / mid < 0.001) return Math.round(mid).toLocaleString();
  return `${Math.round(low).toLocaleString()}–${Math.round(high).toLocaleString()}`;
}

function statusColor(status: DashboardResponseDTO["status"]): "success" | "warning" | "default" {
  if (status === "live") return "success";
  if (status === "stale") return "warning";
  return "default";
}

export function DecisionCardPanel({ data }: { data: DashboardResponseDTO }) {
  const { levels, status, as_of } = data;

  return (
    <Paper sx={{ p: 2 }}>
      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", mb: 1.5 }}>
        <Typography variant="h6">{data.symbol}</Typography>
        <Chip
          label={status === "no_data" ? "No data" : `${status} · ${as_of ? new Date(as_of).toLocaleTimeString() : ""}`}
          color={statusColor(status)}
          size="small"
          variant="outlined"
        />
      </Stack>

      {!levels ? (
        <Typography color="text.secondary">No snapshot available yet for this symbol.</Typography>
      ) : (
        <Stack spacing={1.25}>
          <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <Typography variant="body2" color="text.secondary" sx={{ minWidth: 110 }}>
              Trend
            </Typography>
            <TrendBadge label={levels.trend_label} />
          </Stack>

          <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <Typography variant="body2" color="text.secondary" sx={{ minWidth: 110 }}>
              Institutional Bias
            </Typography>
            <Typography variant="body2">{levels.institutional_bias_label ?? "N/A"}</Typography>
          </Stack>

          <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <Typography variant="body2" color="text.secondary" sx={{ minWidth: 110 }}>
              Confidence
            </Typography>
            <ConfidenceGauge score={levels.confidence_score} />
          </Stack>

          <Divider sx={{ my: 0.5 }} />

          <Stack direction="row" spacing={4}>
            <Box>
              <Typography variant="body2" color="text.secondary">
                Support
              </Typography>
              <Typography variant="body1" sx={{ fontWeight: 600 }}>
                {formatRange(levels.support_low, levels.support_high)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="body2" color="text.secondary">
                Resistance
              </Typography>
              <Typography variant="body1" sx={{ fontWeight: 600 }}>
                {formatRange(levels.resistance_low, levels.resistance_high)}
              </Typography>
            </Box>
            <Box>
              <Typography variant="body2" color="text.secondary">
                POC
              </Typography>
              <Typography variant="body1" sx={{ fontWeight: 600 }}>
                {levels.today_poc !== null ? Math.round(levels.today_poc).toLocaleString() : "N/A"}
              </Typography>
            </Box>
            <Box>
              <Typography variant="body2" color="text.secondary">
                VWAP
              </Typography>
              <Typography variant="body1" sx={{ fontWeight: 600 }}>
                {levels.vwap_now !== null ? Math.round(levels.vwap_now).toLocaleString() : "N/A"}
              </Typography>
            </Box>
          </Stack>

          <Divider sx={{ my: 0.5 }} />

          <Typography variant="body2" color="text.secondary">
            Action
          </Typography>
          <Typography variant="body2">{levels.action_text ?? "N/A"}</Typography>
        </Stack>
      )}
    </Paper>
  );
}
