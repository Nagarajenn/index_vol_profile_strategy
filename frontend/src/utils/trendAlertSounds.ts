// Synthesized (not sampled) so the alert needs no audio asset files -- two
// short sine-wave beeps for a plain Bullish/Bearish 2-candle streak, a
// louder double-beep at a higher pitch for Strong Bullish/Strong Bearish so
// the two are clearly distinguishable by ear alone.

let audioCtx: AudioContext | null = null;

function getAudioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (!audioCtx) audioCtx = new AudioContext();
  return audioCtx;
}

function beep(ctx: AudioContext, frequency: number, durationMs: number, startDelayMs: number, volume: number): void {
  const startTime = ctx.currentTime + startDelayMs / 1000;
  const oscillator = ctx.createOscillator();
  const gain = ctx.createGain();
  oscillator.type = "sine";
  oscillator.frequency.value = frequency;
  gain.gain.setValueAtTime(volume, startTime);
  gain.gain.exponentialRampToValueAtTime(0.001, startTime + durationMs / 1000);
  oscillator.connect(gain);
  gain.connect(ctx.destination);
  oscillator.start(startTime);
  oscillator.stop(startTime + durationMs / 1000);
}

// Best-effort unlock for the browser autoplay policy -- a no-op if the
// context is already running, safe to call from any user gesture (e.g. the
// mute toggle) or opportunistically before playing.
export function unlockTrendAlertAudio(): void {
  const ctx = getAudioContext();
  if (ctx && ctx.state === "suspended") {
    void ctx.resume();
  }
}

export function playTrendAlert(strength: "normal" | "strong"): void {
  const ctx = getAudioContext();
  if (!ctx) return;
  unlockTrendAlertAudio();
  if (strength === "normal") {
    beep(ctx, 660, 180, 0, 0.2);
  } else {
    beep(ctx, 880, 150, 0, 0.28);
    beep(ctx, 880, 150, 220, 0.28);
  }
}
