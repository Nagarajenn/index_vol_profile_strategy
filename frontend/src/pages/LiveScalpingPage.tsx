import { Stack } from "@mui/material";

import { LiveScalpingPanel } from "../components/live-scalping/LiveScalpingPanel";

// 13A on its own page: the decision a scalper watches, with the risk brake beside it.
// Decision support only — nothing on this page can place an order.
export function LiveScalpingPage() {
  return (
    <Stack spacing={2} sx={{ width: "100%" }}>
      <LiveScalpingPanel />
    </Stack>
  );
}
