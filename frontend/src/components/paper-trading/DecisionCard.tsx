import { Box, Chip, Divider, Paper, Stack, Typography } from "@mui/material";

import type { PaperDecisionDTO } from "../../types/paperTrading";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Box sx={{ minWidth: 110 }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2" sx={{ fontWeight: 600 }}>
        {value}
      </Typography>
    </Box>
  );
}

function num(v: number | null, digits = 0): string {
  return v === null || v === undefined ? "--" : v.toLocaleString("en-IN", { maximumFractionDigits: digits });
}

function pct(v: number | null): string {
  return v === null || v === undefined ? "--" : `${(v * 100).toFixed(0)}%`;
}

function decisionColor(d: string): "success" | "error" | "default" {
  if (d === "TRADE_CALL") return "success";
  if (d === "TRADE_PUT") return "error";
  return "default";
}

function FactorList({ title, items, color }: { title: string; items: string[]; color: string }) {
  if (!items.length) return null;
  return (
    <Box sx={{ minWidth: 230, flex: 1 }}>
      <Typography variant="caption" sx={{ fontWeight: 700, color, textTransform: "uppercase" }}>
        {title}
      </Typography>
      <Box component="ul" sx={{ m: 0, pl: 2.2 }}>
        {items.map((f) => (
          <Typography component="li" variant="caption" key={f} sx={{ display: "list-item" }}>
            {f}
          </Typography>
        ))}
      </Box>
    </Box>
  );
}

export function DecisionCard({ decision }: { decision: PaperDecisionDTO }) {
  const d = decision;
  const isTrade = d.decision !== "NO_TRADE";

  return (
    <Paper sx={{ p: 1.5, flex: 1, minWidth: 380 }}>
      <Stack direction="row" spacing={1} sx={{ mb: 1, alignItems: "center" }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          {d.symbol}
        </Typography>
        <Chip label={d.decision.replace(/_/g, " ")} color={decisionColor(d.decision)} size="small" sx={{ fontWeight: 700 }} />
        <Chip label={d.trend_assessment.replace(/_/g, " ")} size="small" variant="outlined" />
        <Typography variant="caption" color="text.secondary" sx={{ ml: "auto" }}>
          14:59 decision - frozen
        </Typography>
      </Stack>

      {!isTrade && d.no_trade_reason && (
        <Box sx={{ bgcolor: "action.hover", borderRadius: 1, p: 1, mb: 1 }}>
          <Typography variant="body2" sx={{ fontWeight: 700 }}>
            NO TRADE - {d.no_trade_reason.replace(/_/g, " ")}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            A NO TRADE day is a valid outcome. The market state the agent saw is shown below regardless.
          </Typography>
        </Box>
      )}

      <Stack direction="row" spacing={2} sx={{ mb: 1, flexWrap: "wrap" }}>
        <Stat label="Spot" value={num(d.spot)} />
        <Stat label="Confidence" value={`${d.confidence}/100`} />
        <Stat label="P(UP)" value={pct(d.probability_up)} />
        <Stat label="P(DOWN)" value={pct(d.probability_down)} />
        <Stat label="P(NO MOVE)" value={pct(d.probability_no_move)} />
        <Stat
          label="Expected Move"
          value={
            d.expected_move_low === null && d.expected_move_high === null
              ? "--"
              : `${num(d.expected_move_low)} to ${num(d.expected_move_high)} pts`
          }
        />
        <Stat label="Transition Risk" value={d.transition_risk_tier ?? "INSUFFICIENT DATA"} />
        <Stat label="Analogs" value={d.n_analogs === null ? "--" : `N=${d.n_analogs}`} />
      </Stack>

      <Stack direction="row" spacing={2} sx={{ mb: 1, flexWrap: "wrap" }}>
        <Stat label="VWAP" value={num(d.vwap)} />
        <Stat label="POC" value={num(d.poc)} />
        <Stat label="Support" value={`${num(d.support_low)}-${num(d.support_high)}`} />
        <Stat label="Resistance" value={`${num(d.resistance_low)}-${num(d.resistance_high)}`} />
        <Stat label="PCR" value={d.pcr === null ? "--" : d.pcr.toFixed(2)} />
        <Stat label="RVOL" value={d.rvol_pct === null ? "--" : `${d.rvol_pct.toFixed(0)}%`} />
        <Stat label="Data" value={d.data_quality} />
      </Stack>

      {isTrade && (
        <>
          <Divider sx={{ my: 1 }} />
          <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap" }}>
            <Stat label="Option" value={`${num(d.strike)} ${d.option_type}`} />
            <Stat label="Entry (ASK)" value={num(d.entry_ask, 2)} />
            <Stat label="Spread" value={d.entry_spread_pct === null ? "--" : `${d.entry_spread_pct.toFixed(2)}%`} />
            <Stat label="Delta" value={d.option_delta === null ? "--" : d.option_delta.toFixed(2)} />
            <Stat label="Initial SL" value={num(d.dynamic_stop, 2)} />
            <Stat label="Target" value={num(d.dynamic_target, 2)} />
            <Stat label="R:R" value={d.reward_risk === null ? "--" : d.reward_risk.toFixed(2)} />
            <Stat label="Qty" value={`${d.quantity ?? "--"}`} />
          </Stack>
        </>
      )}

      <Divider sx={{ my: 1 }} />
      <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap" }}>
        <FactorList title="Supporting" items={d.supporting_factors} color="success.main" />
        <FactorList title="Conflicting" items={d.conflicting_factors} color="error.main" />
        <FactorList title="Risk" items={d.risk_factors} color="warning.main" />
      </Stack>
    </Paper>
  );
}
