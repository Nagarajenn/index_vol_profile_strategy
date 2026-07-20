import { Box, Paper, Stack, Typography } from "@mui/material";

import type { OptionChainSummaryDTO } from "../../types/dashboard";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Box>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body1" sx={{ fontWeight: 600 }}>
        {value}
      </Typography>
    </Box>
  );
}

export function OptionChainPanel({ data }: { data: OptionChainSummaryDTO | null }) {
  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="h6" sx={{ mb: 1.5 }}>
        Option Chain
      </Typography>
      {!data ? (
        <Typography color="text.secondary">Option chain data unavailable (live snapshots only).</Typography>
      ) : (
        <Stack direction="row" spacing={4}>
          <Stat label="PCR" value={data.pcr !== null ? data.pcr.toFixed(2) : "N/A"} />
          <Stat label="ATM Strike" value={data.atm_strike !== null ? data.atm_strike.toLocaleString() : "N/A"} />
          <Stat label="ATM IV (Call)" value={data.atm_iv_call !== null ? `${data.atm_iv_call.toFixed(1)}%` : "N/A"} />
          <Stat label="ATM IV (Put)" value={data.atm_iv_put !== null ? `${data.atm_iv_put.toFixed(1)}%` : "N/A"} />
        </Stack>
      )}
    </Paper>
  );
}
