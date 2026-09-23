import {
  Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent, DialogContentText,
  DialogTitle, Divider, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from "@mui/material";
import { useState } from "react";

import { ScalpDecisionPanel } from "../components/scalp-decision/ScalpDecisionPanel";
import { useLiveControl, useLiveStatus } from "../hooks/useLiveTrading";
import type { LiveSymbolState } from "../types/liveTrading";

// 13-live-trading-v1. This page arms and disarms the live trader and shows what it is doing.
// It cannot create an ENTRY: entries come only from the trader process, after the guards pass.
// The one order this page can cause is an EXIT -- the trader's own EXIT NOW.

const LIVE = "#b71c1c";
const UP = "#2e7d32";

function rs(v: number | null | undefined, d = 2): string {
  return typeof v === "number"
    ? `₹${v.toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d })}`
    : "–";
}

function StateBar({ s }: { s: LiveSymbolState }) {
  const state = s.kill_switch ? "KILLED" : s.halted ? "HALTED" : s.armed ? "ARMED" : "DISARMED";
  const color = state === "ARMED" ? "error" : state === "DISARMED" ? "default" : "warning";
  return (
    <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", flexWrap: "wrap" }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>{s.symbol}</Typography>
      <Chip size="small" color={color} label={state} sx={{ fontWeight: 700 }} />
      {!s.scheduled_today && <Chip size="small" variant="outlined" label="not scheduled today" />}
      <Typography variant="body2">Entries used: <b>{s.entries_used} of 2</b></Typography>
      <Typography variant="body2" sx={{ color: s.realised_pnl < 0 ? LIVE : UP }}>
        Realised: <b>{rs(s.realised_pnl)}</b>
      </Typography>
      {s.halt_reason && <Typography variant="caption" color="text.secondary">{s.halt_reason}</Typography>}
    </Stack>
  );
}

export function LiveTradingPage() {
  const { data, isLoading, isError, error } = useLiveStatus();
  const { arm, disarm, kill, flatten } = useLiveControl();
  const [confirmArm, setConfirmArm] = useState<string | null>(null);
  const [confirmExit, setConfirmExit] = useState<LiveSymbolState | null>(null);

  if (isLoading) {
    return <Box sx={{ display: "flex", justifyContent: "center", mt: 8 }}><CircularProgress /></Box>;
  }
  if (isError || !data) {
    return (
      <Alert severity="warning" sx={{ mt: 2 }}>
        The live control service is not reachable{error instanceof Error ? ` (${error.message})` : ""}. Start it with:
        <Box component="code" sx={{ display: "block", mt: 1 }}>
          backend/venv/Scripts/python.exe -m uvicorn backend_control.main:app --host 127.0.0.1 --port 8100
        </Box>
        Nothing can be armed or traded while it is down.
      </Alert>
    );
  }

  const c = data.caps;
  return (
    <Stack spacing={2} sx={{ width: "100%" }}>
      <Paper sx={{ p: 1.5, borderLeft: `6px solid ${LIVE}` }}>
        <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", flexWrap: "wrap", mb: 1 }}>
          <Typography variant="h6" sx={{ fontWeight: 800 }}>LIVE TRADING</Typography>
          <Chip label="REAL MONEY" sx={{ bgcolor: LIVE, color: "#fff", fontWeight: 800 }} size="small" />
          <Chip label={`${data.version} · ${data.config_hash}`} size="small" variant="outlined" />
          <Typography variant="body2" color="text.secondary">
            {data.session_date} ({data.weekday}) · scheduled: {data.scheduled.join(", ") || "none"}
          </Typography>
        </Stack>
        <Typography variant="caption" color="text.secondary">
          Caps enforced in code: {c.max_entries} entries/day · {c.lots} lot · halt after the first realised loss ·
          max {rs(c.max_entry_cost, 0)}/entry against {rs(c.capital, 0)} capital · entry window {c.entry_window[0]}–
          {c.entry_window[1]} · {c.min_confirmation} confirmation only · episode ≥ {c.min_episode_minutes} min ·
          force-flat at {c.force_flat_at}.
        </Typography>
      </Paper>

      {data.symbols.filter((s) => s.scheduled_today || s.armed || s.open_position).map((s) => (
        <Paper key={s.symbol} sx={{ p: 1.5 }}>
          <StateBar s={s} />
          <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: "wrap" }}>
            {s.armed ? (
              <Button size="small" variant="outlined" onClick={() => disarm.mutate(s.symbol)}>Disarm</Button>
            ) : (
              <Button size="small" variant="contained" color="error" disabled={!s.scheduled_today || s.kill_switch}
                      onClick={() => setConfirmArm(s.symbol)}>
                Arm for today
              </Button>
            )}
            <Button size="small" variant={s.kill_switch ? "contained" : "outlined"} color="warning"
                    onClick={() => kill.mutate({ symbol: s.symbol, on: !s.kill_switch })}>
              {s.kill_switch ? "Release kill switch" : "Kill switch"}
            </Button>
            {s.open_position && (
              <Button size="small" variant="contained" color="error" onClick={() => setConfirmExit(s)}>
                EXIT NOW
              </Button>
            )}
          </Stack>

          {s.open_position && (
            <>
              <Divider sx={{ my: 1.25 }} />
              <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>LIVE POSITION</Typography>
              <Stack direction="row" spacing={3} sx={{ flexWrap: "wrap" }}>
                {[["Contract", s.open_position.contract_label], ["Qty", String(s.open_position.quantity)],
                  ["Entry", rs(s.open_position.entry_price)], ["Cost", rs(s.open_position.entry_cost, 0)],
                  ["Opened", new Date(s.open_position.entry_at).toLocaleTimeString("en-IN")]].map(([k, v]) => (
                  <Box key={k} sx={{ minWidth: 120 }}>
                    <Typography variant="caption" color="text.secondary">{k}</Typography>
                    <Typography variant="body2" sx={{ fontWeight: 600 }}>{v}</Typography>
                  </Box>
                ))}
              </Stack>
              <Typography variant="caption" color="text.secondary">
                The exit is yours. The only exit the agent takes by itself is the {c.force_flat_at} force-flat, so no
                position is carried into the close.
              </Typography>
            </>
          )}
        </Paper>
      ))}

      <ScalpDecisionPanel />

      <Paper sx={{ p: 1.5 }}>
        <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>
          SESSION JOURNAL — why an order did or did not happen
        </Typography>
        {data.journal.length === 0 ? (
          <Typography variant="body2" color="text.secondary">Nothing journalled yet today.</Typography>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>{["Time", "Symbol", "Minute", "Event", "Detail"].map((h) => (
                <TableCell key={h} sx={{ fontWeight: 700 }}>{h}</TableCell>))}
              </TableRow>
            </TableHead>
            <TableBody>
              {data.journal.map((j, i) => (
                <TableRow key={`${j.at}-${i}`}>
                  <TableCell>{new Date(j.at).toLocaleTimeString("en-IN")}</TableCell>
                  <TableCell>{j.symbol ?? "–"}</TableCell>
                  <TableCell>{j.minute ?? "–"}</TableCell>
                  <TableCell>
                    <Chip size="small" label={j.event} color={j.event === "ORDER" ? "error"
                      : j.event === "REFUSED" ? "default" : "warning"} />
                  </TableCell>
                  <TableCell sx={{ maxWidth: 620 }}>{j.detail}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Paper>

      <Dialog open={confirmArm !== null} onClose={() => setConfirmArm(null)}>
        <DialogTitle>Arm {confirmArm} for real orders?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            While armed, the trader may place up to {c.max_entries} entries of {c.lots} lot today without asking again.
            The day halts after the first realised loss. Exits are yours, apart from the {c.force_flat_at} force-flat.
            <br /><br />
            This only matters if the trader process is running with <b>--live</b>; in dry run nothing is sent.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmArm(null)}>Cancel</Button>
          <Button color="error" variant="contained"
                  onClick={() => { if (confirmArm) arm.mutate(confirmArm); setConfirmArm(null); }}>
            Arm {confirmArm}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={confirmExit !== null} onClose={() => setConfirmExit(null)}>
        <DialogTitle>Exit {confirmExit?.open_position?.contract_label}?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Sells {confirmExit?.open_position?.quantity} at a limit just below the current bid. Choose Simulate to
            rehearse the exit without sending anything.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmExit(null)}>Cancel</Button>
          <Button onClick={() => { if (confirmExit) flatten.mutate({ symbol: confirmExit.symbol, live: false });
                                   setConfirmExit(null); }}>
            Simulate
          </Button>
          <Button color="error" variant="contained"
                  onClick={() => { if (confirmExit) flatten.mutate({ symbol: confirmExit.symbol, live: true });
                                   setConfirmExit(null); }}>
            Exit for real
          </Button>
        </DialogActions>
      </Dialog>

      <Typography variant="caption" color="text.secondary">
        This page arms and disarms the live trader; it cannot create an entry. Entries come only from the trader
        process after every guard passes, and each one is journalled above with the evidence behind it. The caps are
        code, not settings — loosening one fails a test.
      </Typography>
    </Stack>
  );
}
