import { Box, Chip, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";

import type { DecisionOutcomeDTO, PaperAccountDTO, PaperPositionDTO } from "../../types/paperTrading";
import { pnlColor, rupees } from "./PaperHeader";

function fmtTime(iso: string | null): string {
  if (!iso) return "--";
  return new Date(iso).toLocaleTimeString("en-IN", {
    timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false,
  });
}

function qualityColor(q: string): "success" | "error" | "warning" | "default" {
  if (q === "GOOD") return "success";
  if (q === "BAD TRADE") return "error";
  if (q.startsWith("DIRECTION RIGHT") || q.startsWith("PROFITABLE BUT")) return "warning";
  return "default";
}

export function PerformancePanel({ account }: { account: PaperAccountDTO }) {
  const rows: [string, string][] = [
    ["Trades", `${account.trade_count}`],
    ["Wins", `${account.win_count}`],
    ["Losses", `${account.loss_count}`],
    ["Win Rate", account.win_rate === null ? "--" : `${(account.win_rate * 100).toFixed(0)}%`],
    ["Today's P&L", rupees(account.daily_pnl)],
    ["Total P&L", rupees(account.total_pnl)],
    ["Balance", rupees(account.current_capital)],
    ["Max Drawdown", `${account.max_drawdown_pct.toFixed(1)}%`],
    ["Average Win", rupees(account.average_win)],
    ["Average Loss", rupees(account.average_loss)],
    ["Profit Factor", account.profit_factor === null ? "--" : account.profit_factor.toFixed(2)],
    ["Consecutive Losses", `${account.consecutive_losses}`],
  ];
  return (
    <Paper sx={{ p: 1.5, flex: 1, minWidth: 320 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 0.5 }}>
        Paper Experiment Metrics
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
        Deliberately NOT labelled strategy performance. Five sessions is far too small a sample to characterise a
        strategy, and all figures are pre-cost.
      </Typography>
      <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap" }}>
        {rows.map(([label, value]) => (
          <Box key={label} sx={{ minWidth: 118 }}>
            <Typography variant="caption" color="text.secondary">
              {label}
            </Typography>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>
              {value}
            </Typography>
          </Box>
        ))}
      </Stack>
    </Paper>
  );
}

export function OutcomePanel({ outcomes }: { outcomes: DecisionOutcomeDTO[] }) {
  return (
    <Paper sx={{ p: 1.5, flex: 1, minWidth: 340 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 0.5 }}>
        Decision vs Outcome
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 1 }}>
        Direction correctness and option profitability are tracked separately: a correct call that lost money is not a
        good trade, and a wrong call that made money is not evidence of skill.
      </Typography>
      {outcomes.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No decisions recorded yet today.
        </Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Symbol</TableCell>
              <TableCell>Decision</TableCell>
              <TableCell>Forecast</TableCell>
              <TableCell>Actual</TableCell>
              <TableCell>Direction</TableCell>
              <TableCell align="right">P&L</TableCell>
              <TableCell>Quality</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {outcomes.map((o) => (
              <TableRow key={`${o.symbol}-${o.session_date}`}>
                <TableCell>{o.symbol}</TableCell>
                <TableCell>{o.decision.replace(/_/g, " ")}</TableCell>
                <TableCell>{o.forecast_direction ?? "--"}</TableCell>
                <TableCell>{o.actual_direction ?? "--"}</TableCell>
                <TableCell>
                  {o.direction_correct === null ? "--" : o.direction_correct ? "CORRECT" : "WRONG"}
                </TableCell>
                <TableCell align="right" sx={{ color: pnlColor(o.net_pnl) }}>
                  {rupees(o.net_pnl)}
                </TableCell>
                <TableCell>
                  <Chip label={o.decision_quality} size="small" color={qualityColor(o.decision_quality)} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Paper>
  );
}

export function JournalTable({ trades }: { trades: PaperPositionDTO[] }) {
  return (
    <Paper sx={{ p: 1.5 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
        Paper Trade Journal
      </Typography>
      {trades.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No completed paper trades yet. Every 14:59 decision -- including NO TRADE -- is still journaled above.
        </Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Date</TableCell>
              <TableCell>Symbol</TableCell>
              <TableCell>Option</TableCell>
              <TableCell>Entry</TableCell>
              <TableCell>SL</TableCell>
              <TableCell>Target</TableCell>
              <TableCell>Exit</TableCell>
              <TableCell>Exit Reason</TableCell>
              <TableCell align="right">P&L</TableCell>
              <TableCell align="right">Return</TableCell>
              <TableCell>Direction</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {trades.map((t) => (
              <TableRow key={t.id}>
                <TableCell>{t.session_date}</TableCell>
                <TableCell>{t.symbol}</TableCell>
                <TableCell>{`${t.strike.toFixed(0)} ${t.option_type}`}</TableCell>
                <TableCell>{`${t.entry_price.toFixed(2)} @ ${fmtTime(t.entry_timestamp)}`}</TableCell>
                <TableCell>{t.initial_stop.toFixed(2)}</TableCell>
                <TableCell>{t.initial_target.toFixed(2)}</TableCell>
                <TableCell>{t.exit_price === null ? "--" : `${t.exit_price.toFixed(2)} @ ${fmtTime(t.exit_timestamp)}`}</TableCell>
                <TableCell>{t.exit_reason?.replace(/_/g, " ") ?? "--"}</TableCell>
                <TableCell align="right" sx={{ color: pnlColor(t.net_pnl) }}>
                  {rupees(t.net_pnl)}
                </TableCell>
                <TableCell align="right">{t.return_pct === null ? "--" : `${t.return_pct.toFixed(1)}%`}</TableCell>
                <TableCell>
                  {t.direction_correct === null ? "--" : t.direction_correct ? "CORRECT" : "WRONG"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
        Entry fills at the ASK and exits at the BID -- never LTP or midpoint. P&L is pre-cost.
      </Typography>
    </Paper>
  );
}
