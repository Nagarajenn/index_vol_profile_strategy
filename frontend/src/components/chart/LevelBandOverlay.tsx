import { Box } from "@mui/material";

export interface LevelBand {
  key: string;
  label: string;
  color: string;
  fill: string;
  top: number;
  bottom: number;
}

/** Absolutely-positioned shaded horizontal band + label, layered over the
 * chart canvas. lightweight-charts has no native "filled region between two
 * prices" primitive, so bands are drawn as plain HTML positioned via
 * series.priceToCoordinate() -- see useCandlestickChart's recomputeBands. */
export function LevelBandOverlay({ band }: { band: LevelBand }) {
  const height = Math.max(1, band.bottom - band.top);
  return (
    <Box
      sx={{
        position: "absolute",
        left: 0,
        right: 56,
        top: band.top,
        height,
        bgcolor: band.fill,
        borderTop: `1px solid ${band.color}`,
        borderBottom: `1px solid ${band.color}`,
        pointerEvents: "none",
      }}
    >
      <Box
        sx={{
          position: "absolute",
          left: 6,
          top: 2,
          fontSize: 12,
          fontWeight: 700,
          color: band.color,
          bgcolor: "rgba(247,246,241,0.85)",
          px: 0.5,
          borderRadius: 0.5,
          lineHeight: 1.4,
        }}
      >
        {band.label}
      </Box>
    </Box>
  );
}
