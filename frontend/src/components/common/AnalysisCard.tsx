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

function MicroLabel({ children }: { children: ReactNode }) {
  return (
    <Typography
      variant="overline"
      sx={{ color: "text.secondary", letterSpacing: 0.5, fontSize: "0.65rem", lineHeight: 1.4, display: "block" }}
    >
      {children}
    </Typography>
  );
}

// Compact "top status strip" shell: everything a trader needs for a 5-second
// read -- metrics ticker, interpretation, confidence, implication -- packed
// into one dense card instead of four separately-labeled sections.
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
    <Paper sx={{ p: 1.5 }}>
      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", mb: 0.75 }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: "baseline" }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
            {title}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {question}
          </Typography>
        </Stack>
        {headerRight}
      </Stack>

      {rawValues.length > 0 && (
        <Stack
          direction="row"
          divider={<Divider orientation="vertical" flexItem />}
          sx={{ overflowX: "auto", flexWrap: "wrap", rowGap: 0.75, py: 0.5, mb: 0.75 }}
        >
          {rawValues.map((rv) => (
            <Box key={rv.label} sx={{ px: 1.25, minWidth: "fit-content" }}>
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", lineHeight: 1.2, fontSize: "0.68rem" }}>
                {rv.label}
              </Typography>
              <Box sx={{ fontWeight: 700, fontSize: "0.9rem", lineHeight: 1.3 }}>{rv.value}</Box>
            </Box>
          ))}
        </Stack>
      )}

      <Divider sx={{ mb: 0.75 }} />

      <MicroLabel>AI Interpretation</MicroLabel>
      <Typography variant="body2" sx={{ mb: 1 }}>
        {interpretation ?? "Not enough data yet to interpret."}
      </Typography>

      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ alignItems: { sm: "center" } }}>
        <Box sx={{ minWidth: { sm: 190 } }}>
          <MicroLabel>Confidence</MicroLabel>
          <ConfidenceGauge score={confidence} />
        </Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <MicroLabel>{implicationLabel}</MicroLabel>
          <Typography
            variant="body2"
            sx={{
              py: 0.5,
              px: 1,
              borderLeft: "3px solid",
              borderColor: "primary.main",
              bgcolor: "rgba(77,163,255,0.06)",
            }}
          >
            {implication ?? "No actionable read yet."}
          </Typography>
        </Box>
      </Stack>
    </Paper>
  );
}
