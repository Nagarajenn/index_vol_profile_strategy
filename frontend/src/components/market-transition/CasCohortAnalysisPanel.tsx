import { KeyboardArrowDown, KeyboardArrowRight } from "@mui/icons-material";
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Collapse,
  IconButton,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import { useState } from "react";

import { useCasCohortAnalysis } from "../../hooks/useCasCohortAnalysis";
import type { CohortName, CohortResultDTO, ConfidenceLabel } from "../../types/marketTransition";

const COHORT_LABELS: Record<CohortName, string> = {
  FLAT_LARGE_UP: "Flat → Large Up",
  FLAT_LARGE_DOWN: "Flat → Large Down",
  UP_REVERSAL_DOWN: "Up → Reversal Down",
  DOWN_REVERSAL_UP: "Down → Reversal Up",
  UP_CONTINUATION: "Up → Continuation",
  DOWN_CONTINUATION: "Down → Continuation",
  FLAT_NO_MATERIAL_MOVE: "Flat → No Material Move",
};

function confidenceColor(label: ConfidenceLabel): "success" | "primary" | "warning" | "default" {
  if (label === "Strong") return "success";
  if (label === "Moderate") return "primary";
  if (label === "Weak") return "warning";
  return "default";
}

function fmt(v: number | null, digits = 2): string {
  return v === null ? "N/A" : v.toFixed(digits);
}

function CohortCard({ cohort }: { cohort: CohortResultDTO }) {
  const [open, setOpen] = useState(false);
  const hasData = cohort.n_days > 0;

  return (
    <Paper variant="outlined" sx={{ p: 1, opacity: hasData ? 1 : 0.6 }}>
      <Stack
        direction="row"
        spacing={1}
        sx={{ alignItems: "center", cursor: "pointer" }}
        onClick={() => setOpen((o) => !o)}
      >
        <IconButton size="small">{open ? <KeyboardArrowDown fontSize="small" /> : <KeyboardArrowRight fontSize="small" />}</IconButton>
        <Typography variant="body2" sx={{ fontWeight: 700, minWidth: 220 }}>
          {COHORT_LABELS[cohort.cohort]}
        </Typography>
        <Chip size="small" label={`N=${cohort.n_days}`} color={hasData ? "info" : "default"} variant="outlined" />
        {!hasData && (
          <Typography variant="caption" color="text.secondary">
            No days in this cohort yet
          </Typography>
        )}
      </Stack>
      <Collapse in={open}>
        {hasData ? (
          <TableContainer sx={{ maxHeight: 320, mt: 1 }}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  <TableCell>Feature</TableCell>
                  <TableCell align="right">N</TableCell>
                  <TableCell align="right">Median</TableCell>
                  <TableCell align="right">Percentile</TableCell>
                  <TableCell align="right">Effect size</TableCell>
                  <TableCell align="right">p-value</TableCell>
                  <TableCell>Confidence</TableCell>
                  <TableCell>Direction</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {cohort.features.map((f) => (
                  <TableRow key={f.feature_name} hover>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{f.feature_name}</TableCell>
                    <TableCell align="right">{f.n}</TableCell>
                    <TableCell align="right">{fmt(f.median)}</TableCell>
                    <TableCell align="right">{f.percentile_within_full_sample !== null ? `${f.percentile_within_full_sample.toFixed(0)}th` : "N/A"}</TableCell>
                    <TableCell align="right">{fmt(f.effect_size)}</TableCell>
                    <TableCell align="right">{f.p_value !== null ? f.p_value.toFixed(3) : "N/A"}</TableCell>
                    <TableCell>
                      <Chip size="small" label={f.confidence_label} color={confidenceColor(f.confidence_label)} variant="outlined" />
                    </TableCell>
                    <TableCell sx={{ maxWidth: 280 }}>
                      <Typography variant="caption">{f.direction_note}</Typography>
                    </TableCell>
                  </TableRow>
                ))}
                {cohort.categorical.map((c) => (
                  <TableRow key={c.feature_name} hover>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{c.feature_name}</TableCell>
                    <TableCell align="right">{c.n}</TableCell>
                    <TableCell colSpan={5}>
                      <Tooltip title={`Full sample: ${JSON.stringify(c.full_sample_category_counts)}`}>
                        <Typography variant="caption">{JSON.stringify(c.category_counts)}</Typography>
                      </Tooltip>
                    </TableCell>
                    <TableCell>
                      <Typography variant="caption" color="text.secondary">
                        descriptive only
                      </Typography>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        ) : (
          <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
            No CAS-era days have been classified into this cohort yet -- e.g. no LARGE/EXTREME-magnitude flat-pre
            days have occurred so far. This is a real, honest read of a still-small sample, not an error.
          </Typography>
        )}
      </Collapse>
    </Paper>
  );
}

export function CasCohortAnalysisPanel({ symbol }: { symbol: string }) {
  const { data, isLoading, isError, error } = useCasCohortAnalysis(symbol);

  return (
    <Paper sx={{ p: 1.5, mt: 1.5 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 0.5 }}>
        Historical Cohorts &amp; Pre-3PM Warning Indicators
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
        Groups CAS-era days into 7 named outcomes (from the Transition Type/Magnitude columns above), then compares
        each cohort's 14:55-14:59 pre-3pm state against the rest of the sample -- "what conditions preceded this kind
        of day". Complementary to the Factor Correlation Study, not a replacement. Every result shows N; below a
        minimum sample size (5 days) confidence is always "Insufficient data", regardless of how low the p-value
        looks -- a low p-value from a handful of days is not predictive power.
      </Typography>

      {isLoading && (
        <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
          <CircularProgress size={24} />
        </Box>
      )}

      {(isError || (!isLoading && !data)) && (
        <Alert severity="error">Cohort analysis failed to load: {error instanceof Error ? error.message : "unknown error"}</Alert>
      )}

      {data && (
        <Stack spacing={1}>
          {data.cohorts.map((cohort) => (
            <CohortCard key={cohort.cohort} cohort={cohort} />
          ))}
        </Stack>
      )}
    </Paper>
  );
}
