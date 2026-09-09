import { Alert, Box, CircularProgress, Paper, Stack, Typography } from "@mui/material";

import { DecisionCard } from "../components/paper-trading/DecisionCard";
import { JournalTable, OutcomePanel, PerformancePanel } from "../components/paper-trading/JournalPanel";
import { OpenPositionPanel } from "../components/paper-trading/OpenPositionPanel";
import { PaperHeader } from "../components/paper-trading/PaperHeader";
import { usePaperToday, usePaperTrades } from "../hooks/usePaperTrading";

function DataHealth({ heartbeat, agentState, dbOk }: { heartbeat: string | null; agentState: string; dbOk: boolean }) {
  const age = heartbeat ? Math.round((Date.now() - new Date(heartbeat).getTime()) / 1000) : null;
  return (
    <Paper sx={{ p: 1.5, minWidth: 260, flex: 1 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
        Data Health
      </Typography>
      <Stack spacing={0.5}>
        <Typography variant="body2">
          Agent state: <b>{agentState.replace(/_/g, " ")}</b>
        </Typography>
        <Typography variant="body2">
          Last heartbeat: <b>{age === null ? "never" : `${age}s ago`}</b>
        </Typography>
        <Typography variant="body2">
          Database: <b>{dbOk ? "OK" : "ERROR"}</b>
        </Typography>
        <Typography variant="caption" color="text.secondary">
          The agent ticks once a minute from the live pipeline. A stale heartbeat during market hours means the pipeline
          is not running.
        </Typography>
      </Stack>
    </Paper>
  );
}

export function PaperTradingPage() {
  const { data, isLoading, isError, error } = usePaperToday();
  const { data: trades } = usePaperTrades();

  if (isLoading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", mt: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (isError || !data) {
    return (
      <Alert severity="error" sx={{ mt: 2 }}>
        Failed to load paper trading data: {error instanceof Error ? error.message : "unknown error"}
      </Alert>
    );
  }

  return (
    <Stack spacing={2} sx={{ width: "100%" }}>
      <PaperHeader status={data.status} account={data.account} />

      {data.status.kill_switch_active && (
        <Alert severity="warning">
          Paper engine kill switch is ACTIVE. No new paper entries will be taken. Existing records are untouched. Release
          it with: <code>venv/Scripts/python.exe scripts/run_paper_agent.py --kill-switch off</code>
        </Alert>
      )}

      <Stack direction={{ xs: "column", lg: "row" }} spacing={2}>
        {data.decisions.length === 0 ? (
          <Paper sx={{ p: 2, flex: 1 }}>
            <Typography variant="body2" color="text.secondary">
              No 14:59 decision has been frozen yet today. The agent monitors the market from 09:15 and freezes its
              decision for each symbol at 14:59 IST.
            </Typography>
          </Paper>
        ) : (
          data.decisions.map((d) => <DecisionCard key={d.symbol} decision={d} />)
        )}
      </Stack>

      {data.open_position && <OpenPositionPanel position={data.open_position} />}

      <Stack direction={{ xs: "column", lg: "row" }} spacing={2}>
        <PerformancePanel account={data.account} />
        <OutcomePanel outcomes={data.outcomes} />
        <DataHealth
          heartbeat={data.status.last_heartbeat}
          agentState={data.status.agent_state}
          dbOk={data.status.database_ok}
        />
      </Stack>

      <JournalTable trades={trades ?? data.closed_today} />

      <Typography variant="caption" color="text.secondary">
        This is an instrumented research experiment on virtual capital, not a live trading system and not evidence that
        the strategy is profitable. Milestones 11A-11C found no validated directional edge and no validated
        option-expression rule; the paper agent exists to test whether the platform reads the market coherently, knows
        when NOT to trade, and manages risk sensibly.
      </Typography>
    </Stack>
  );
}
