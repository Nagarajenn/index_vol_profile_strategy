import { Box, Paper, Typography } from "@mui/material";

import type { OptionChainSummaryDTO } from "../../types/dashboard";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", lineHeight: 1.2 }}>
        {label}
      </Typography>
      <Typography variant="body1" sx={{ fontWeight: 600, lineHeight: 1.3 }}>
        {value}
      </Typography>
    </Box>
  );
}

export function OptionChainPanel({ data }: { data: OptionChainSummaryDTO | null }) {
  return (
    <Paper sx={{ p: 1.5 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
        Option Chain
      </Typography>
      {!data ? (
        <Typography variant="body2" color="text.secondary">
          Option chain data unavailable (live snapshots only).
        </Typography>
      ) : (
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "repeat(2, 1fr)", sm: "repeat(4, 1fr)" }, gap: 1.5 }}>
          <Stat label="PCR" value={data.pcr !== null ? data.pcr.toFixed(2) : "N/A"} />
          <Stat label="ATM Strike" value={data.atm_strike !== null ? data.atm_strike.toLocaleString() : "N/A"} />
          <Stat label="ATM IV (Call)" value={data.atm_iv_call !== null ? `${data.atm_iv_call.toFixed(1)}%` : "N/A"} />
          <Stat label="ATM IV (Put)" value={data.atm_iv_put !== null ? `${data.atm_iv_put.toFixed(1)}%` : "N/A"} />
        </Box>
      )}
    </Paper>
  );
}
