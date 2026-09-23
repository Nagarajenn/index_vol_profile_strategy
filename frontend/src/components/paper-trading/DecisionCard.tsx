import { Box, Chip, Divider, Paper, Stack, Tooltip, Typography } from "@mui/material";

import type { PaperDecisionDTO } from "../../types/paperTrading";

// The paper agent's frozen 14:59 decision, presented in the same reading order as the 12C
// Scalping Decision panel: header strip -> the decision itself -> WHY? -> supporting /
// conflicting / risk -> evidence chips -> the contract. Nothing about what the agent decides
// changes here; this is how the decision is read, not how it is made.

const UP = "#2e7d32";
const DOWN = "#c62828";

type ChipColor = "success" | "warning" | "error" | "default" | "info";

function num(v: number | null | undefined, digits = 0): string {
  return v === null || v === undefined ? "–" : v.toLocaleString("en-IN", { maximumFractionDigits: digits });
}

function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "–" : `${(v * 100).toFixed(0)}%`;
}

function decisionStyle(d: string): { bg: string; fg: string; label: string } {
  if (d === "TRADE_CALL") return { bg: "rgba(46,125,50,0.16)", fg: UP, label: "TRADE CALL" };
  if (d === "TRADE_PUT") return { bg: "rgba(198,40,40,0.16)", fg: DOWN, label: "TRADE PUT" };
  return { bg: "rgba(120,120,120,0.14)", fg: "text.primary", label: "NO TRADE" };
}

function stateColor(v: string): ChipColor {
  if (/BULLISH|STRONG_UP|UP|GOOD|OK|LOW/.test(v)) return "success";
  if (/BEARISH|STRONG_DOWN|DOWN|POOR|MISSING|EXTREME/.test(v)) return "error";
  if (/MIXED|WEAK|NEUTRAL|DEGRADED|UNCERTAIN|MODERATE|LARGE/.test(v)) return "warning";
  return "default";
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <Box sx={{ minWidth: 104 }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
      <Typography variant="body2" sx={{ fontWeight: 600, color }}>{value}</Typography>
    </Box>
  );
}

/** The one-sentence answer to "why this decision", built from what the agent actually recorded. */
function why(d: PaperDecisionDTO): string {
  if (d.decision === "NO_TRADE") {
    const reason = d.no_trade_reason ? d.no_trade_reason.replace(/_/g, " ").toLowerCase() : "no qualifying setup";
    return `NO TRADE — ${reason}. A NO TRADE day is a valid outcome, not a missed one; the market state the agent saw is shown below regardless.`;
  }
  const side = d.decision === "TRADE_CALL" ? "call" : "put";
  const tail = d.n_analogs === null ? "" : ` Based on N=${d.n_analogs} historical analogs.`;
  return `${d.trend_assessment.replace(/_/g, " ").toLowerCase()} into the close, expressed as a ${side} at ${num(d.strike)}.${tail}`;
}

function FactorColumn({ title, items, color, mark }: { title: string; items: string[]; color: string; mark: string }) {
  if (!items.length) return null;
  return (
    <Box sx={{ flex: 1, minWidth: 230 }}>
      <Typography variant="caption" sx={{ fontWeight: 700 }}>{title}</Typography>
      {items.map((f) => (
        <Typography key={f} variant="caption" component="div" sx={{ color }}>
          {mark} {f}
        </Typography>
      ))}
    </Box>
  );
}

/** Label + chip pairs, the same shape as the 12C evidence row. */
function EvidenceGrid({ d }: { d: PaperDecisionDTO }) {
  const row: [string, string, string][] = [
    ["TREND", d.trend_assessment.replace(/_/g, " "), "The agent's trend read at the decision minute."],
    ["TRANSITION RISK", d.transition_risk_tier ?? "INSUFFICIENT DATA", "Expected move magnitude tier, ATR-normalised."],
    ["DATA", d.data_quality, "Completeness of the inputs behind this decision."],
    [
      "VWAP",
      d.spot === null || d.vwap === null ? "UNKNOWN" : d.spot > d.vwap ? "ABOVE" : d.spot < d.vwap ? "BELOW" : "AT",
      `Spot ${num(d.spot)} vs VWAP ${num(d.vwap)}.`,
    ],
    [
      "POC",
      d.spot === null || d.poc === null ? "UNKNOWN" : d.spot > d.poc ? "ABOVE" : d.spot < d.poc ? "BELOW" : "AT",
      `Spot ${num(d.spot)} vs today's POC ${num(d.poc)}.`,
    ],
    [
      "ANALOGS",
      d.n_analogs === null ? "NONE" : `N=${d.n_analogs}`,
      "How many historical days the forecast was matched against.",
    ],
  ];
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>EVIDENCE</Typography>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(3, minmax(0, 1fr))" }, gap: 0.75 }}>
        {row.map(([k, v, note]) => (
          <Tooltip key={k} title={note} placement="top">
            <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 1 }}>
              <Typography variant="caption" color="text.secondary">{k}</Typography>
              <Chip size="small" color={stateColor(v)} label={v} sx={{ maxWidth: "70%" }} />
            </Box>
          </Tooltip>
        ))}
      </Box>
    </Box>
  );
}

export function DecisionCard({ decision }: { decision: PaperDecisionDTO }) {
  const d = decision;
  const st = decisionStyle(d.decision);
  const isTrade = d.decision !== "NO_TRADE";

  return (
    <Paper sx={{ p: 1.5, flex: 1, minWidth: 380 }}>
      {/* header strip */}
      <Stack direction="row" spacing={3} sx={{ mb: 1.5, flexWrap: "wrap", alignItems: "flex-start" }}>
        <Stat label="Market" value={d.symbol} />
        <Stat label="Decision" value="14:59 — frozen" />
        <Stat label="Spot" value={num(d.spot)} />
        <Stat label="Confidence" value={`${d.confidence}/100`} />
        <Stat label="Data" value={d.data_quality} />
      </Stack>

      {/* the decision itself, with WHY? beside it */}
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ alignItems: { sm: "center" } }}>
        <Box sx={{ px: 3, py: 1.25, borderRadius: 1, bgcolor: st.bg, minWidth: 190, textAlign: "center" }}>
          <Typography variant="h5" sx={{ fontWeight: 800, color: st.fg, letterSpacing: 1 }}>{st.label}</Typography>
          <Typography variant="caption" color="text.secondary" component="div">
            Confidence: {d.confidence}/100
          </Typography>
        </Box>
        <Box sx={{ flex: 1 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>WHY?</Typography>
          <Typography variant="body2">{why(d)}</Typography>
        </Box>
      </Stack>

      {/* supporting / conflicting / risk, same glyphs and colours as the 12C panel */}
      <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mt: 1 }}>
        <FactorColumn title="Supporting" items={d.supporting_factors} color={UP} mark="✓" />
        <FactorColumn title="Conflicting" items={d.conflicting_factors} color="#ed6c02" mark="⚠" />
        <FactorColumn title="Risk" items={d.risk_factors} color={DOWN} mark="✕" />
      </Stack>

      <Divider sx={{ my: 1.25 }} />
      <EvidenceGrid d={d} />

      {/* the forecast numbers stay, below the narrative rather than above it */}
      <Divider sx={{ my: 1.25 }} />
      <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap" }}>
        <Stat label="P(UP)" value={pct(d.probability_up)} color={UP} />
        <Stat label="P(DOWN)" value={pct(d.probability_down)} color={DOWN} />
        <Stat label="P(NO MOVE)" value={pct(d.probability_no_move)} />
        <Stat
          label="Expected Move"
          value={
            d.expected_move_low === null && d.expected_move_high === null
              ? "–"
              : `${num(d.expected_move_low)} to ${num(d.expected_move_high)} pts`
          }
        />
        <Stat label="Support" value={`${num(d.support_low)}–${num(d.support_high)}`} />
        <Stat label="Resistance" value={`${num(d.resistance_low)}–${num(d.resistance_high)}`} />
        <Stat label="PCR" value={d.pcr === null ? "–" : d.pcr.toFixed(2)} />
        <Stat label="RVOL" value={d.rvol_pct === null ? "–" : `${d.rvol_pct.toFixed(0)}%`} />
      </Stack>

      {isTrade && (
        <>
          <Divider sx={{ my: 1.25 }} />
          <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 0.5 }}>CONTRACT</Typography>
          <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap" }}>
            <Stat label="Option" value={`${num(d.strike)} ${d.option_type}`} />
            <Stat label="Entry (ASK)" value={num(d.entry_ask, 2)} />
            <Stat label="Spread" value={d.entry_spread_pct === null ? "–" : `${d.entry_spread_pct.toFixed(2)}%`} />
            <Stat label="Delta" value={d.option_delta === null ? "–" : d.option_delta.toFixed(2)} />
            <Stat label="Initial SL" value={num(d.dynamic_stop, 2)} />
            <Stat label="Target" value={num(d.dynamic_target, 2)} />
            <Stat label="R:R" value={d.reward_risk === null ? "–" : d.reward_risk.toFixed(2)} />
            <Stat label="Qty" value={`${d.quantity ?? "–"}`} />
          </Stack>
        </>
      )}
    </Paper>
  );
}
