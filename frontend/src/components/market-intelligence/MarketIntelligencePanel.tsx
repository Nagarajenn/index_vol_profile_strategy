import { Box, Chip, Divider, Paper, Stack, Typography } from "@mui/material";
import { useMemo } from "react";

import { useMarketIntelligence } from "../../hooks/useMarketIntelligence";
import type { MarketIntelligenceEventDTO } from "../../types/marketIntelligence";
import { formatTime, riskColor, sentimentColor } from "../../utils/marketIntelligenceFormat";

interface SectorHeat {
  sector: string;
  score: number; // signed: positive = net bullish pressure, negative = net bearish
}

function computeSectorHeatMap(events: MarketIntelligenceEventDTO[]): SectorHeat[] {
  const totals = new Map<string, number>();
  for (const e of events) {
    const sign = e.sentiment === "Bullish" ? 1 : e.sentiment === "Bearish" ? -1 : 0;
    const weight = e.severity * e.confidence * sign;
    for (const sector of e.affected_sectors) {
      totals.set(sector, (totals.get(sector) ?? 0) + weight);
    }
  }
  return Array.from(totals.entries())
    .map(([sector, score]) => ({ sector, score }))
    .sort((a, b) => Math.abs(b.score) - Math.abs(a.score))
    .slice(0, 8);
}

// One cell in the top placeholder strip (Current Sentiment / News Risk
// Score / Latest Update / High-Impact Events) -- a fixed slot other future
// widgets (Correlation Engine read, Alert Engine status, ...) can extend
// into without reshaping the grid.
function StatCard({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Box sx={{ p: 1, border: "1px solid", borderColor: "divider", borderRadius: 1, bgcolor: "background.default" }}>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", lineHeight: 1.2, fontSize: "0.68rem" }}>
        {label}
      </Typography>
      <Box sx={{ mt: 0.5 }}>{children}</Box>
    </Box>
  );
}

function SectorHeatMap({ events }: { events: MarketIntelligenceEventDTO[] }) {
  const heat = useMemo(() => computeSectorHeatMap(events), [events]);
  if (heat.length === 0) return null;
  const maxAbs = Math.max(...heat.map((h) => Math.abs(h.score)), 1);

  return (
    <Box>
      <Typography variant="caption" sx={{ color: "text.secondary", letterSpacing: 0.5, fontSize: "0.65rem" }}>
        SECTOR HEAT MAP
      </Typography>
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 1, mt: 0.5 }}>
        {heat.map((h) => {
          const intensity = Math.min(Math.abs(h.score) / maxAbs, 1);
          const bg = h.score > 0 ? `rgba(76,175,80,${0.15 + intensity * 0.45})` : h.score < 0 ? `rgba(244,67,54,${0.15 + intensity * 0.45})` : "action.selected";
          return (
            <Box key={h.sector} sx={{ px: 1, py: 0.375, borderRadius: 1, bgcolor: bg, border: "1px solid", borderColor: "divider" }}>
              <Typography variant="caption" sx={{ fontWeight: 600 }}>
                {h.sector}
              </Typography>
            </Box>
          );
        })}
      </Stack>
    </Box>
  );
}

function EventCard({ event }: { event: MarketIntelligenceEventDTO }) {
  return (
    <Paper variant="outlined" sx={{ p: 1, bgcolor: "background.default" }}>
      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 0.75 }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="body2" sx={{ fontWeight: 600, lineHeight: 1.3 }}>
            {event.title}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {event.source} · {formatTime(event.published_at)}
          </Typography>
        </Box>
        <Stack direction="row" spacing={0.5}>
          <Chip size="small" label={`Sev ${event.severity}`} variant="outlined" />
          <Chip size="small" label={event.sentiment} color={sentimentColor(event.sentiment)} />
        </Stack>
      </Stack>

      <Stack direction="row" spacing={1.5} sx={{ flexWrap: "wrap", rowGap: 0.25, mt: 0.75 }}>
        <Typography variant="caption" color="text.secondary">
          {event.category}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Duration: {event.expected_duration}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Volatility: {event.volatility_impact}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Reversal risk: {Math.round(event.reversal_probability * 100)}%
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Confidence: {Math.round(event.confidence * 100)}%
        </Typography>
      </Stack>

      <Typography variant="body2" sx={{ mt: 0.75 }}>
        {event.rationale}
      </Typography>

      <Box sx={{ mt: 0.75, p: 0.75, borderLeft: "3px solid", borderColor: "primary.main", bgcolor: "rgba(77,163,255,0.06)" }}>
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", fontSize: "0.65rem" }}>
          Trading Recommendation
        </Typography>
        <Typography variant="body2">{event.recommended_action}</Typography>
      </Box>

      <Stack direction="row" spacing={1.5} sx={{ flexWrap: "wrap", rowGap: 0.25, mt: 0.75 }}>
        <Typography variant="caption" color="text.secondary">
          NIFTY: {event.expected_direction_nifty}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          SENSEX: {event.expected_direction_sensex}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          BANKNIFTY: {event.expected_direction_banknifty}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Risk: {event.risk_level}
        </Typography>
      </Stack>
    </Paper>
  );
}

export function MarketIntelligencePanel() {
  const { data, isLoading, isError } = useMarketIntelligence();

  return (
    <Paper sx={{ p: 1.5 }}>
      <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center", mb: 1 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          Market Intelligence &amp; Sentiment
        </Typography>
        {data && (
          <Typography variant="caption" color="text.secondary">
            Last updated: {formatTime(data.last_updated)}
          </Typography>
        )}
      </Stack>

      {isLoading && (
        <Typography variant="body2" color="text.secondary">
          Loading...
        </Typography>
      )}
      {isError && !isLoading && (
        <Typography variant="body2" color="text.secondary">
          Market intelligence unavailable.
        </Typography>
      )}

      {data && (
        <Stack spacing={1.5}>
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(4, 1fr)" }, gap: 1.5 }}>
            <StatCard label="Current Sentiment">
              <Chip size="small" label={data.overall_sentiment} color={sentimentColor(data.overall_sentiment)} />
            </StatCard>
            <StatCard label="News Risk Score">
              <Typography variant="body1" sx={{ fontWeight: 700, color: riskColor(data.news_risk_score) }}>
                {data.news_risk_score}/100
              </Typography>
            </StatCard>
            <StatCard label="Latest Update">
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {formatTime(data.last_updated)}
              </Typography>
            </StatCard>
            <StatCard label="High Impact Events">
              <Typography variant="body1" sx={{ fontWeight: 700 }}>
                {data.events.length}
              </Typography>
            </StatCard>
          </Box>

          <SectorHeatMap events={data.events} />

          <Divider />

          <Box>
            <Typography variant="caption" sx={{ color: "text.secondary", letterSpacing: 0.5, fontSize: "0.65rem" }}>
              CURRENT HIGH-IMPACT EVENTS
            </Typography>
            {data.events.length === 0 ? (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                No market-moving events detected yet.
              </Typography>
            ) : (
              <Stack spacing={1} sx={{ mt: 0.75 }}>
                {data.events.map((event) => (
                  <EventCard key={event.link} event={event} />
                ))}
              </Stack>
            )}
          </Box>
        </Stack>
      )}
    </Paper>
  );
}
