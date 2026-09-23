import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";

import type { LiveControlStatus } from "../types/liveTrading";

// The live control service is deliberately NOT the read-only dashboard backend: that one is
// GET-only by contract. This is a separate local-only app on its own port.
const CONTROL_BASE = import.meta.env.VITE_CONTROL_URL ?? "http://127.0.0.1:8100";

const control = axios.create({ baseURL: CONTROL_BASE, timeout: 20_000 });

export function useLiveStatus(enabled = true) {
  return useQuery<LiveControlStatus>({
    queryKey: ["live-control-status"],
    queryFn: async () => (await control.get<LiveControlStatus>("/api/control/status")).data,
    refetchInterval: 10_000, // this is a live-money page; it should feel current
    enabled,
    retry: 1,
  });
}

export function useLiveControl() {
  const qc = useQueryClient();
  const after = () => qc.invalidateQueries({ queryKey: ["live-control-status"] });

  const arm = useMutation({
    mutationFn: async (symbol: string) =>
      (await control.post(`/api/control/${symbol}/arm`, { confirm: true })).data,
    onSuccess: after,
  });
  const disarm = useMutation({
    mutationFn: async (symbol: string) => (await control.post(`/api/control/${symbol}/disarm`)).data,
    onSuccess: after,
  });
  const kill = useMutation({
    mutationFn: async ({ symbol, on }: { symbol: string; on: boolean }) =>
      (await control.post(`/api/control/${symbol}/kill`, null, { params: { on } })).data,
    onSuccess: after,
  });
  // live=false simulates the exit, so the button can be rehearsed without sending anything.
  const flatten = useMutation({
    mutationFn: async ({ symbol, live }: { symbol: string; live: boolean }) =>
      (await control.post(`/api/control/${symbol}/flatten`, null, { params: { live } })).data,
    onSuccess: after,
  });
  return { arm, disarm, kill, flatten };
}
