import { Alert, Box, Chip, CircularProgress, Divider, Paper, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";

import { PostTransitionMinutesTable, PreTransitionWindowsTable } from "./CasWindowedDetailTables";
import { useCasWindowedDetail } from "../../hooks/useCasWindowedDetail";

const TRACKER_START_MIN = 14 * 60 + 15; // 14:15, a little buffer before the first 14:30 window
const TRACKER_END_MIN = 15 * 60 + 20; // 15:20, a little buffer after the last 15:15 minute
const POLL_INTERVAL_MS = 20_000;

function nowInIst(): Date {
  // The browser's own clock, formatted as IST -- good enough for a UI
  // gating window (not used for any leakage-sensitive computation, which
  // all happens server-side against the DB's own IST timestamps).
  return new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
}

function todayIstDateString(): string {
  const d = nowInIst();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function nowIstTimeString(): string {
  const d = nowInIst();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function isWithinTrackingWindow(): boolean {
  const d = nowInIst();
  const minutes = d.getHours() * 60 + d.getMinutes();
  return minutes >= TRACKER_START_MIN && minutes <= TRACKER_END_MIN;
}

export function LiveCasTrackerPanel({ symbol }: { symbol: string }) {
  const [active, setActive] = useState(isWithinTrackingWindow());

  useEffect(() => {
    const id = setInterval(() => setActive(isWithinTrackingWindow()), 30_000);
    return () => clearInterval(id);
  }, []);

  const today = todayIstDateString();
  const { data, isLoading, isError } = useCasWindowedDetail(symbol, today, active, POLL_INTERVAL_MS);

  if (!active) return null; // outside the tracking window -- no empty placeholder taking up space

  const nowTime = nowIstTimeString();
  const hasPreData = data && data.pre_transition_windows.some((w) => w.volume > 0);
  const hasPostData = data && data.post_transition_minutes.length > 0;

  return (
    <Paper sx={{ p: 1.5 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center", mb: 0.5 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          Live CAS Transition Tracker -- {symbol}
        </Typography>
        <Chip size="small" label="LIVE" color="error" sx={{ fontWeight: 700 }} />
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
        Today's 14:30-14:59 pre-transition windows and 15:00-15:15 post-transition minutes, updating as the session
        happens -- the same dual-resolution view as CAS Intelligence's per-day detail below, just live for today
        instead of a closed historical day. Today won't appear in the CAS Intelligence table itself until after
        tonight's post-market batch run.
      </Typography>

      {isLoading && (
        <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
          <CircularProgress size={20} />
        </Box>
      )}
      {isError && <Alert severity="error">Live tracker failed to load.</Alert>}

      {data && !hasPreData && !hasPostData && (
        <Alert severity="info">No data yet -- the first 14:30-14:34 window is still filling in.</Alert>
      )}

      {data && (hasPreData || hasPostData) && (
        <Stack spacing={1}>
          {hasPreData && (
            <>
              <Chip
                size="small"
                label="2:30-2:59 PRE-TRANSITION — FORECAST INFORMATION"
                sx={{ alignSelf: "flex-start", bgcolor: "info.dark", color: "info.contrastText", fontWeight: 700 }}
              />
              <PreTransitionWindowsTable windows={data.pre_transition_windows} nowTime={nowTime} />
            </>
          )}

          {hasPostData && (
            <>
              <Divider sx={{ "&::before, &::after": { borderColor: "warning.main" } }}>
                <Chip size="small" label="⬇ 3 PM TRANSITION ⬇" color="warning" sx={{ fontWeight: 700 }} />
              </Divider>
              <Chip
                size="small"
                label="3:00-3:15 — ACTUAL OUTCOME (so far)"
                sx={{ alignSelf: "flex-start", bgcolor: "success.dark", color: "success.contrastText", fontWeight: 700 }}
              />
              <PostTransitionMinutesTable minutes={data.post_transition_minutes} />
            </>
          )}
        </Stack>
      )}
    </Paper>
  );
}
