import { create } from "zustand";

interface AlertSoundState {
  enabled: boolean;
  toggle: () => void;
}

export const useAlertSoundStore = create<AlertSoundState>((set) => ({
  enabled: true,
  toggle: () => set((s) => ({ enabled: !s.enabled })),
}));
