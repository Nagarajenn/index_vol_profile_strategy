import { Stack } from "@mui/material";

import { ScalpDecisionPanel } from "../components/scalp-decision/ScalpDecisionPanel";

// The 12C scalping decision + risk brake on a page of its own, so the call a trader
// watches all session is not buried under the Terminal's analytics panels. The panel
// keeps its own symbol toggle, session picker and position selector, and stays what it
// has always been: advisory, read-only, never an order.
export function ScalpDecisionPage() {
  return (
    <Stack spacing={2} sx={{ width: "100%" }}>
      <ScalpDecisionPanel />
    </Stack>
  );
}
