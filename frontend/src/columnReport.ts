import type { ColumnsMode, DispenseReading, LevelReading } from "./api/client";
import type { TimeRange } from "./period";

/** Базовое число колонок по умолчанию, если в паспорте АГЗС оно не задано явно. */
export const CONNECTED_COLUMNS = 2;

export type { ColumnsMode };

export type ColumnSeries = {
  number: number;
  code: string;
  name: string;
  liters: number[];
  total: number;
  opsCount: number;
  lastLiters: number | null;
  lastAt: string | null;
};

export type ColumnReport = {
  columnCount: number;
  columns: ColumnSeries[];
  totals: number[];
  total: number;
  tankOutflowLiters: number | null;
  opsTotal: number;
  discrepancyLiters: number | null;
  status: "ok" | "warn";
  source: "edge" | "level";
  labels: string[];
};

export type LiveTankSample = {
  tankId: string;
  remainder: number;
  measuredAt: string | null;
};

export function buildLiveTankSamples(
  live: { tanks: { code: string; remainder_liters: number | null; measured_at: string | null }[] } | null,
  devices: { id: string; code: string }[],
  points: LevelReading[],
  includesNow: boolean,
): LiveTankSample[] {
  if (!includesNow || !live) return [];
  const samples: LiveTankSample[] = [];
  for (const tank of live.tanks) {
    const device = devices.find((item) => item.code === tank.code);
    const tankId = device?.id ?? (live.tanks.length === 1 ? points[0]?.tank_id : undefined);
    if (!tankId || tank.remainder_liters == null) continue;
    samples.push({
      tankId,
      remainder: tank.remainder_liters,
      measuredAt: tank.measured_at,
    });
  }
  return samples;
}

export function isColumnReportStation(station: {
  code?: string | null;
  name?: string | null;
  columns_mode?: ColumnsMode | null;
}): boolean {
  if (station.columns_mode === "none") return false;
  if (station.columns_mode === "virtual" || station.columns_mode === "edge") return true;
  const code = (station.code ?? "").trim().toLowerCase();
  const name = (station.name ?? "").trim().toLowerCase();
  return name.includes("rekon") || code === "agzs-akt-12" || code === "akt-12mkr";
}

export function stationColumnCount(station: { columns_count?: number | null }): number {
  const n = station.columns_count;
  if (typeof n === "number" && Number.isFinite(n) && n >= 1) {
    return Math.min(8, Math.round(n));
  }
  return CONNECTED_COLUMNS;
}

export function bucketCaption(range: TimeRange, label: string): string {
  if (range.preset === "today" || range.preset === "day") return `${label}:00`;
  return label;
}

/**
 * Отпуск колонок — только фактические наливы ТРК.
 * Снижение уровня резервуара в литры колонок не раскладывается:
 * оно остаётся отдельно, как уход по датчику.
 */
export function columnDispenseReport(
  _points: LevelReading[],
  range: TimeRange,
  _liveTanks: LiveTankSample[] = [],
  _now = new Date(),
  fallbackOutflow = 0,
  realDispenses: DispenseReading[] = [],
  options?: { columnCount?: number; mode?: ColumnsMode; sensorOutflowLiters?: number | null },
): ColumnReport {
  const colCount = Math.max(1, Math.min(8, Math.round(options?.columnCount ?? CONNECTED_COLUMNS)));

  const columns: ColumnSeries[] = Array.from({ length: colCount }, (_, index) => ({
    number: index + 1,
    code: `ТРК-${index + 1}`,
    name: `Колонка ${index + 1}`,
    liters: Array(range.labels.length).fill(0),
    total: 0,
    opsCount: 0,
    lastLiters: null,
    lastAt: null,
  }));

  const inRangeDispenses = realDispenses
    .map((item) => {
      const stamp = item.finished_at ?? item.started_at;
      const atMs = new Date(stamp).getTime();
      return { item, atMs, bucket: range.indexAt(atMs) };
    })
    .filter((entry) => entry.bucket >= 0 && entry.item.volume_liters > 0)
    .sort((a, b) => a.atMs - b.atMs);

  const source: "edge" | "level" = "edge";

  inRangeDispenses.forEach(({ item, atMs, bucket }, index) => {
    const addr = item.pump_address;
    const colIdx =
      addr != null && addr >= 1 ? (addr - 1) % colCount : index % colCount;
    const column = columns[colIdx];
    const vol = Math.round(item.volume_liters * 1000) / 1000;
    column.liters[bucket] = Math.round((column.liters[bucket] + vol) * 1000) / 1000;
    column.total = Math.round((column.total + vol) * 1000) / 1000;
    column.opsCount += 1;
    column.lastLiters = vol;
    column.lastAt = new Date(atMs).toISOString();
  });

  const totals = range.labels.map((_, index) =>
    Math.round(columns.reduce((sum, column) => sum + column.liters[index], 0) * 1000) / 1000,
  );
  const total = Math.round(columns.reduce((sum, column) => sum + column.total, 0) * 1000) / 1000;
  const opsTotal = columns.reduce((sum, column) => sum + column.opsCount, 0);

  let tankOutflowLiters: number | null;
  let discrepancyLiters: number | null;
  let status: "ok" | "warn";

  if (source === "edge") {
    const rawSensorOutflow =
      options?.sensorOutflowLiters !== undefined ? options.sensorOutflowLiters : fallbackOutflow;
    if (rawSensorOutflow == null || !Number.isFinite(rawSensorOutflow)) {
      tankOutflowLiters = null;
      discrepancyLiters = null;
      status = total > 0 ? "warn" : "ok";
    } else {
      const normalizedOutflow = Math.round(rawSensorOutflow * 1000) / 1000;
      tankOutflowLiters = normalizedOutflow === 0 ? 0 : normalizedOutflow;
      const diff = Math.round(total - tankOutflowLiters);
      discrepancyLiters = diff === 0 ? 0 : diff;
      status =
        (tankOutflowLiters === 0 && total > 0) || Math.abs(discrepancyLiters) > 50
          ? "warn"
          : "ok";
    }
  } else {
    tankOutflowLiters = total;
    discrepancyLiters = 0;
    status = "ok";
  }

  return {
    columnCount: colCount,
    columns,
    totals,
    total,
    tankOutflowLiters,
    opsTotal,
    discrepancyLiters,
    status,
    source,
    labels: range.labels,
  };
}

