import { Box, LinearProgress, Typography } from "@mui/material";

function colorFor(score: number): "success" | "warning" | "error" {
  if (score >= 70) return "success";
  if (score >= 40) return "warning";
  return "error";
}

export function ConfidenceGauge({ score }: { score: number | null }) {
  const value = score ?? 0;
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, minWidth: 160 }}>
      <Box sx={{ flexGrow: 1 }}>
        <LinearProgress
          variant="determinate"
          value={value}
          color={colorFor(value)}
          sx={{ height: 8, borderRadius: 1, bgcolor: "#e2e0d8" }}
        />
      </Box>
      <Typography variant="body2" sx={{ fontWeight: 700, minWidth: 42 }}>
        {score ?? "N/A"}
        {score !== null && "/100"}
      </Typography>
    </Box>
  );
}
