import { useEffect, useRef } from "react";

import { playTrendAlert } from "../utils/trendAlertSounds";

type Family = "bullish" | "bearish" | null;

function familyOf(label: string | null): Family {
  if (!label) return null;
  if (label.includes("Bullish")) return "bullish";
  if (label.includes("Bearish")) return "bearish";
  return null;
}

function isStrong(label: string | null): boolean {
  return label?.startsWith("Strong") ?? false;
}

interface StreakState {
  family: Family;
  count: number;
  // 0 = nothing played yet this streak, 1 = the plain Bullish/Bearish sound
  // played, 2 = the Strong sound played. Only escalation (1 -> 2) plays a
  // second sound within the same streak -- a de-escalation back to plain
  // Bullish/Bearish, or the streak just continuing at the same strength,
  // never repeats a sound that already fired.
  alertedRank: 0 | 1 | 2;
}

const EMPTY_STREAK: StreakState = { family: null, count: 0, alertedRank: 0 };

// Watches trend_label across consecutive dashboard polls (each poll reflects
// the live pipeline's latest 1-min snapshot -- the closest thing to "the
// next candle" the frontend can observe) and plays an alarm once the trend
// has read Bullish/Bearish (same family) for 2 polls in a row, with a
// louder, distinct sound if that 2nd reading is Strong Bullish/Strong
// Bearish. `dataUpdatedAt` (not just `trendLabel`) must be in the effect's
// trigger set -- if the label is unchanged between polls (the common case:
// several minutes of "Bullish" in a row), a dependency on trendLabel alone
// would never re-fire the effect, so the streak would never advance past 1.
export function useTrendAlert(symbol: string, trendLabel: string | null, dataUpdatedAt: number, soundEnabled: boolean): void {
  const streakRef = useRef<StreakState>({ ...EMPTY_STREAK });
  const symbolRef = useRef(symbol);
  const enabledRef = useRef(soundEnabled);

  useEffect(() => {
    enabledRef.current = soundEnabled;
  }, [soundEnabled]);

  useEffect(() => {
    if (dataUpdatedAt === 0) return; // no successful fetch yet

    if (symbolRef.current !== symbol) {
      symbolRef.current = symbol;
      streakRef.current = { ...EMPTY_STREAK };
    }

    const streak = streakRef.current;
    const family = familyOf(trendLabel);

    if (family === null) {
      streakRef.current = { ...EMPTY_STREAK };
      return;
    }

    if (family === streak.family) {
      streak.count += 1;
    } else {
      streak.family = family;
      streak.count = 1;
      streak.alertedRank = 0;
    }

    if (streak.count < 2) return;

    const targetRank: 1 | 2 = isStrong(trendLabel) ? 2 : 1;
    if (targetRank > streak.alertedRank) {
      streak.alertedRank = targetRank;
      if (enabledRef.current) playTrendAlert(targetRank === 2 ? "strong" : "normal");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, trendLabel, dataUpdatedAt]);
}
