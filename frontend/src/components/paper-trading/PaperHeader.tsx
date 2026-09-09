import { Box, Chip, Paper, Stack, Typography } from "@mui/material";

import type { PaperAccountDTO, PaperStatusDTO } from "../../types/paperTrading";

function Metric({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <Box sx={{ minWidth: 130 }}>
      <Typography variant="caption" color="text.secondary" sx={{ textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </Typography>
      <Typography variant="h6" sx={{ fontWeight: 700, color: color ?? "text.primary", lineHeight: 1.3 }}>
        {value}
      </Typography>
    </Box>
  );
}

export function rupees(value: number | null | undefined): string {
  if (value === null || value === undefined) return "--";
  const sign = value < 0 ? "-" : "";
  return `${sign}Rs ${Math.abs(value).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

export function pnlColor(value: number | null | undefined): string | undefined {
  if (value === null || value === undefined || value === 0) return undefined;
  return value > 0 ? "success.main" : "error.main";
}

export function PaperHeader({ status, account }: { status: PaperStatusDTO; account: PaperAccountDTO }) {
  return (
    <Paper sx={{ p: 1.75 }}>
      <Stack direction="row" spacing={2} sx={{ mb: 1.5, alignItems: "center", flexWrap: "wrap" }}>
        <Typography variant="h6" sx={{ fontWeight: 700 }}>
          Paper Trading Command Center
        </Typography>
        <Chip label="PAPER MODE - NO REAL ORDERS" color="warning" size="small" sx={{ fontWeight: 700 }} />
        {status.kill_switch_active && <Chip label="KILL SWITCH ACTIVE" color="error" size="small" sx={{ fontWeight: 700 }} />}
        <Chip label={status.agent_state.replace(/_/g, " ")} size="small" variant="outlined" />
        <Box sx={{ ml: "auto" }}>
          <Typography variant="caption" color="text.secondary">
            {status.strategy_version} - config {status.configuration_hash} - Day {status.experiment_day ?? "?"} of{" "}
            {status.experiment_total_days}
          </Typography>
        </Box>
      </Stack>

      <Stack direction="row" spacing={3} sx={{ flexWrap: "wrap" }}>
        <Metric label="Virtual Capital" value={rupees(account.starting_capital)} />
        <Metric label="Current Balance" value={rupees(account.current_capital)} color={pnlColor(account.total_pnl)} />
        <Metric label="Today's P&L" value={rupees(account.daily_pnl)} color={pnlColor(account.daily_pnl)} />
        <Metric label="Total P&L" value={rupees(account.total_pnl)} color={pnlColor(account.total_pnl)} />
        <Metric label="Max Drawdown" value={`${account.max_drawdown_pct.toFixed(1)}%`} />
        <Metric label="Trades" value={`${account.trade_count}`} />
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
        Simulated experiment on virtual capital. All P&L is {account.pnl_basis.replace("_", "-")} (no brokerage or tax
        model exists in this project, so none is assumed). Results are not evidence that the strategy is profitable.
      </Typography>
    </Paper>
  );
}
