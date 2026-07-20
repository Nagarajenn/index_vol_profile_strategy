import { create } from "zustand";

interface SymbolState {
  selectedSymbol: string;
  setSelectedSymbol: (symbol: string) => void;
}

export const useSymbolStore = create<SymbolState>((set) => ({
  selectedSymbol: "SENSEX",
  setSelectedSymbol: (symbol) => set({ selectedSymbol: symbol }),
}));
