import { Box, Divider, Paper, Stack, Typography } from "@mui/material";
import type { ReactNode } from "react";

import { ConfidenceGauge } from "../decision-card/ConfidenceGauge";

// Generic 4-layer "AI Trading Terminal" panel shell -- Raw Values / AI
// Interpretation / Confidence / Trading Implication -- shared by every V2
// analysis card (Decision Card now; Institutional Activity, Volume Profile
// Interpretation, Market Structure, and Risk Assessment cards later reuse
// this same shape rather than each re-implementing the 4-section layout).

export interface RawValue {
  label: string;
  /** Usually a formatted number string; ReactNode allowed so a raw value can
   * render as a colored badge (e.g. a Trend chip) instead of plain text. */
  value: ReactNode;
}

export interface AnalysisCardProps {
  title: string;
  /** The one trading question this panel answers, shown as a subtitle. */
  question: string;
  /** Optional header-right slot, e.g. a live/stale status chip. */
  headerRight?: ReactNode;
  rawValues: RawValue[];
  interpretation: string | null;
  confidence: number | null;
  implication: string | null;
  implicationLabel?: string;
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <Typography variant="overline" sx={{ color: "text.secondary", letterSpacing: 1, fontSize: "0.7rem", display: "block" }}>
      {children}
    </Typography>
  );
}

export function AnalysisCard({
  title,
  question,
  headerRight,
  rawValues,
  interpretation,
  confidence,
  implication,
  implicationLabel = "Trading Implication",
}: AnalysisCardProps) {
  return (
    <Paper sx={{ p: 2 }}>
      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "flex-start", mb: 0.5 }}>
        <Box>
          <Typography variant="h6">{title}</Typography>
          <Typography variant="caption" color="text.secondary">
            {question}
          </Typography>
        </Box>
        {headerRight}
      </Stack>

      <Divider sx={{ my: 1.5 }} />

      <SectionLabel>Raw Values</SectionLabel>
      <Stack direction="row" spacing={4} sx={{ flexWrap: "wrap", rowGap: 1, mb: 1.5, mt: 0.5 }}>
        {rawValues.map((rv) => (
          <Box key={rv.label} sx={{ minWidth: 90 }}>
            <Typography variant="body2" color="text.secondary">
              {rv.label}
            </Typography>
            <Box sx={{ fontWeight: 600, fontSize: "1rem", mt: 0.25 }}>{rv.value}</Box>
          </Box>
        ))}
      </Stack>

      <SectionLabel>AI Interpretation</SectionLabel>
      <Typography variant="body2" sx={{ mb: 1.5, mt: 0.5 }}>
        {interpretation ?? "Not enough data yet to interpret."}
      </Typography>

      <SectionLabel>Confidence</SectionLabel>
      <Box sx={{ mb: 1.5, mt: 0.5 }}>
        <ConfidenceGauge score={confidence} />
      </Box>

      <SectionLabel>{implicationLabel}</SectionLabel>
      <Typography
        variant="body2"
        sx={{
          mt: 0.5,
          p: 1,
          borderLeft: "3px solid",
          borderColor: "primary.main",
          bgcolor: "rgba(77,163,255,0.06)",
        }}
      >
        {implication ?? "No actionable read yet."}
      </Typography>
    </Paper>
  );
}
