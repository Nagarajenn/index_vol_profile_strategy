import { Chip } from "@mui/material";

function colorFor(label: string | null): "success" | "error" | "default" {
  if (!label) return "default";
  const lower = label.toLowerCase();
  if (lower.includes("bullish")) return "success";
  if (lower.includes("bearish")) return "error";
  return "default";
}

export function TrendBadge({ label }: { label: string | null }) {
  return <Chip label={label ?? "N/A"} color={colorFor(label)} size="small" sx={{ fontWeight: 600 }} />;
}
