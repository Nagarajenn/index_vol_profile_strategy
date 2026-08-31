import { ArrowBack } from "@mui/icons-material";
import { Alert, Box, Chip, CircularProgress, Divider, IconButton, Paper, Stack, Tooltip, Typography } from "@mui/material";
import { useNavigate, useParams } from "react-router-dom";

import {
  ForecastVsActualStrip,
  PostTransitionMinutesTable,
  PreTransitionWindowsTable,
  TRANSITION_TYPE_LABELS,
  magnitudeTierColor,
  transitionTypeColor,
} from "../components/market-transition/CasWindowedDetailTables";
import { useCasIntelligence } from "../hooks/useCasIntelligence";
import { useCasWindowedDetail } from "../hooks/useCasWindowedDetail";

function fmtPoints(v: number | null): string {
  if (v === null) return "N/A";
  return v > 0 ? `+${v.toFixed(0)}` : v.toFixed(0);
}

// Dedicated full-page view for one historical day's CAS pre/post-3pm
// windowed detail -- replaces the old cramped inline table-row expansion
// (nested inside the daily table's own maxHeight-capped scroll container,
// itself wrapping two more maxHeight-capped tables). Per the user's own
// suggestion: "if you think we cannot adjust within the same page...then
// we can have a separate page only for these." No inner height caps here
// -- the page itself scrolls, so the whole pre+post detail is readable in
// one continuous view instead of scroll-within-scroll-within-scroll.
export function CasDayDetailPage() {
  const { symbol = "", date = "" } = useParams<{ symbol: string; date: string }>();
  const navigate = useNavigate();

  const { data: dailyData, isLoading: dailyLoading } = useCasIntelligence(symbol);
  const day = dailyData?.daily_results.find((d) => d.session_date === date);

  const { data, isLoading, isError } = useCasWindowedDetail(symbol, date, Boolean(symbol && date));

  return (
    <Box sx={{ width: "100%" }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center", mb: 1.5 }}>
        <IconButton size="small" onClick={() => navigate(-1)}>
          <ArrowBack fontSize="small" />
        </IconButton>
        <Typography variant="h6" sx={{ fontWeight: 700 }}>
          CAS Transition Detail — {symbol} — {date}
        </Typography>
      </Stack>

      {dailyLoading && (
        <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
          <CircularProgress size={20} />
        </Box>
      )}

      {day && (
        <Paper sx={{ p: 1.5, mb: 1.5 }}>
          <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 1, alignItems: "center" }}>
            <Chip label={TRANSITION_TYPE_LABELS[day.transition_type]} color={transitionTypeColor(day.transition_type)} />
            {day.magnitude_tier !== null ? (
              <Tooltip
                title={`${day.magnitude_pct_return !== null ? day.magnitude_pct_return.toFixed(2) : "N/A"}% return, ${
                  day.magnitude_atr_normalized !== null ? day.magnitude_atr_normalized.toFixed(2) : "N/A"
                }x prior day's 14-day ATR`}
              >
                <Chip label={day.magnitude_tier} color={magnitudeTierColor(day.magnitude_tier)} variant="outlined" />
              </Tooltip>
            ) : (
              <Chip label="Magnitude: N/A" variant="outlined" />
            )}
            <Typography variant="body2" sx={{ textTransform: "capitalize" }}>
              Pre: {day.pre_direction ?? "N/A"} ({fmtPoints(day.pre_window_points_move)} pts)
            </Typography>
            <Typography variant="body2" sx={{ textTransform: "capitalize" }}>
              Post: {day.post_direction ?? "N/A"} ({fmtPoints(day.post_window_points_move)} pts)
            </Typography>
            {day.expiry_type && <Chip size="small" label={day.expiry_type} variant="outlined" />}
          </Stack>
        </Paper>
      )}

      <Paper sx={{ p: 1.5 }}>
        {isLoading && (
          <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
            <CircularProgress size={20} />
          </Box>
        )}
        {isError && <Alert severity="error">Failed to load windowed detail for {date}.</Alert>}

        {data && data.pre_transition_windows.length === 0 && data.post_transition_minutes.length === 0 && (
          <Alert severity="info">No windowed detail yet for {date} -- run scripts/run_cas_windowed_analysis.py.</Alert>
        )}

        {data && (data.pre_transition_windows.length > 0 || data.post_transition_minutes.length > 0) && (
          <Stack spacing={1}>
            <Chip
              label="2:30-2:59 PRE-TRANSITION — FORECAST INFORMATION"
              sx={{ alignSelf: "flex-start", bgcolor: "info.dark", color: "info.contrastText", fontWeight: 700 }}
            />
            <PreTransitionWindowsTable windows={data.pre_transition_windows} maxTableHeight={520} />

            <Divider sx={{ "&::before, &::after": { borderColor: "warning.main" } }}>
              <Chip label="⬇ 3 PM TRANSITION ⬇" color="warning" sx={{ fontWeight: 700 }} />
            </Divider>

            <Chip
              label="3:00-3:15 + 3:30 CLOSE — ACTUAL OUTCOME"
              sx={{ alignSelf: "flex-start", bgcolor: "success.dark", color: "success.contrastText", fontWeight: 700 }}
            />
            <PostTransitionMinutesTable minutes={data.post_transition_minutes} maxTableHeight={520} />

            {day && <ForecastVsActualStrip forecast={data.forecasts.find((f) => f.checkpoint_time === "14:59")} day={day} />}
          </Stack>
        )}
      </Paper>
    </Box>
  );
}
