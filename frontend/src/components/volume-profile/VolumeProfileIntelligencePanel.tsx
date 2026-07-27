import { Box, Chip, Paper, Stack, Typography } from "@mui/material";

import { useVolumeProfileIntelligence } from "../../hooks/useVolumeProfileIntelligence";
import type {
  InitialBalanceDTO,
  LevelTestDTO,
  OpeningTypeDTO,
  ProfileShapeDTO,
  RotationFactorDTO,
  ValueMigrationDTO,
  VolumeNodeDTO,
  VolumePaceDTO,
} from "../../types/volumeProfile";

function fmt(v: number): string {
  return Math.round(v).toLocaleString();
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Box sx={{ minWidth: 130 }}>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body1" sx={{ fontWeight: 600 }}>
        {value}
      </Typography>
      {sub && (
        <Typography variant="caption" color="text.secondary">
          {sub}
        </Typography>
      )}
    </Box>
  );
}

function outcomeColor(outcome: LevelTestDTO["outcome"]): "success" | "error" | "default" {
  if (outcome === "accepted") return "success";
  if (outcome === "rejected") return "error";
  return "default";
}

function shapeLabel(shape: ProfileShapeDTO["shape"]): string {
  return { P: "P — Short-Covering Rally", b: "b — Long Liquidation", D: "D — Balanced", B: "B — Double Distribution" }[shape];
}

function ShapeSection({ shape }: { shape: ProfileShapeDTO | null }) {
  if (!shape) return <Stat label="Profile Shape" value="N/A" />;
  return <Stat label="Profile Shape" value={shapeLabel(shape.shape)} sub={shape.description} />;
}

function OpeningSection({ opening }: { opening: OpeningTypeDTO | null }) {
  if (!opening) return <Stat label="Opening Type" value="N/A" />;
  return <Stat label="Opening Type" value={opening.type} sub={opening.description} />;
}

function RotationSection({ rotation }: { rotation: RotationFactorDTO | null }) {
  if (!rotation) return <Stat label="Rotation Factor" value="N/A" />;
  return (
    <Stat
      label="Rotation Factor"
      value={`${rotation.label} (${rotation.value})`}
      sub={`${rotation.periods} periods observed`}
    />
  );
}

function PaceSection({ pace }: { pace: VolumePaceDTO | null }) {
  if (!pace) return <Stat label="Volume Pace" value="N/A" />;
  return (
    <Stat
      label="Volume Pace"
      value={`${pace.label} (${pace.pace_pct.toFixed(0)}%)`}
      sub={`${fmt(pace.today_cumulative)} vs avg ${fmt(pace.average_cumulative)}`}
    />
  );
}

function InitialBalanceSection({ ib }: { ib: InitialBalanceDTO | null }) {
  if (!ib) return <Stat label="Initial Balance" value="N/A" />;
  return (
    <Stat
      label={`Initial Balance${ib.is_complete ? "" : " (forming)"}`}
      value={`${fmt(ib.ib_low)} – ${fmt(ib.ib_high)}`}
      sub={`Range ${fmt(ib.ib_range)}`}
    />
  );
}

function MigrationSection({ migration }: { migration: ValueMigrationDTO | null }) {
  if (!migration) {
    return <Stat label="Value Migration" value="N/A — no prior session" />;
  }
  const arrow = migration.direction === "up" ? "▲" : migration.direction === "down" ? "▼" : "→";
  const color = migration.direction === "up" ? "success.main" : migration.direction === "down" ? "error.main" : "text.secondary";
  return (
    <Box sx={{ minWidth: 200 }}>
      <Typography variant="body2" color="text.secondary">
        Value Migration (vs. prior session)
      </Typography>
      <Typography variant="body1" sx={{ fontWeight: 600, color }}>
        {arrow} POC {migration.poc_shift >= 0 ? "+" : ""}
        {fmt(migration.poc_shift)} ({migration.poc_shift_pct.toFixed(2)}%)
      </Typography>
      <Typography variant="caption" color="text.secondary">
        VAH {migration.vah_shift >= 0 ? "+" : ""}
        {fmt(migration.vah_shift)} · VAL {migration.val_shift >= 0 ? "+" : ""}
        {fmt(migration.val_shift)} · Intraday drift {migration.intraday_poc_drift >= 0 ? "+" : ""}
        {fmt(migration.intraday_poc_drift)}
      </Typography>
    </Box>
  );
}

function NodeList({ title, nodes, color }: { title: string; nodes: VolumeNodeDTO[]; color: string }) {
  return (
    <Box sx={{ minWidth: 160 }}>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
        {title}
      </Typography>
      {nodes.length === 0 ? (
        <Typography variant="caption" color="text.secondary">
          None detected
        </Typography>
      ) : (
        <Stack spacing={0.25}>
          {nodes.map((n) => (
            <Typography key={n.price} variant="body2" sx={{ color, fontWeight: 600 }}>
              {fmt(n.price)}
            </Typography>
          ))}
        </Stack>
      )}
    </Box>
  );
}

function LevelTestsSection({ tests }: { tests: LevelTestDTO[] }) {
  if (tests.length === 0) return null;
  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
        Acceptance / Rejection
      </Typography>
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 1 }}>
        {tests.map((t) => (
          <Chip
            key={t.level_name}
            size="small"
            variant="outlined"
            color={outcomeColor(t.outcome)}
            label={`${t.level_name} ${fmt(t.price)} · ${t.outcome}${t.touches > 0 ? ` (${t.touches})` : ""}`}
          />
        ))}
      </Stack>
    </Box>
  );
}

export function VolumeProfileIntelligencePanel({ symbol }: { symbol: string }) {
  const { data, isLoading, isError } = useVolumeProfileIntelligence(symbol);

  return (
    <Paper sx={{ p: 1.5 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
        Volume Profile Intelligence
      </Typography>

      {isLoading && (
        <Typography variant="body2" color="text.secondary">
          Loading...
        </Typography>
      )}
      {isError && !isLoading && (
        <Typography variant="body2" color="text.secondary">
          Not enough data yet for this symbol.
        </Typography>
      )}

      {data && (
        <Stack spacing={1.5}>
          <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 1.5 }}>
            <ShapeSection shape={data.profile_shape} />
            <OpeningSection opening={data.opening_type} />
            <RotationSection rotation={data.rotation_factor} />
            <PaceSection pace={data.volume_pace} />
            <InitialBalanceSection ib={data.initial_balance} />
          </Stack>

          <MigrationSection migration={data.migration} />

          <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap", rowGap: 1.5 }}>
            <NodeList title="High Volume Nodes" nodes={data.hvns} color="success.main" />
            <NodeList title="Low Volume Nodes" nodes={data.lvns} color="warning.main" />
          </Stack>

          <LevelTestsSection tests={data.level_tests} />

          {data.developing.length > 0 && (
            <Typography variant="caption" color="text.secondary">
              Developing POC as of {new Date(data.developing[data.developing.length - 1].timestamp).toLocaleTimeString()}:{" "}
              {fmt(data.developing[data.developing.length - 1].poc)} (VA {fmt(data.developing[data.developing.length - 1].val)}–
              {fmt(data.developing[data.developing.length - 1].vah)})
            </Typography>
          )}
        </Stack>
      )}
    </Paper>
  );
}
