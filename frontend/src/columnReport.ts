import type { LevelReading } from "./api/client";
import type { TimeRange } from "./period";

/** На REKON в отчёте две колонки. Через колонку газ только уходит. */
export const CONNECTED_COLUMNS = 2;

/** Сдвиг меньше литра в отпуск не пишем: это шум шкалы, не заправка. */
const MIN_DROP_LITERS = 1;

export type ColumnSeries = {
  number: number;
  name: string;
  liters: number[];
  total: number;
};

export type ColumnReport = {
  columnCount: number;
  columns: ColumnSeries[];
  totals: number[];
  total: number;
  labels: string[];
};

export type LiveTankSample = {
  tankId: string;
  remainder: number;
  measuredAt: string | null;
};

type Drop = { atMs: number; liters: number };

export function isColumnReportStation(station: { code?: string | null; name?: string | null }): boolean {
  const code = (station.code ?? "").trim().toLowerCase();
  const name = (station.name ?? "").trim().toLowerCase();
  return name.includes("rekon") || code === "agzs-akt-12" || code === "akt-12mkr";
}

export function bucketCaption(range: TimeRange, label: string): string {
  if (range.preset === "today" || range.preset === "day") return `${label}:00`;
  return label;
}

/**
 * Отпуск для отчёта: каждое снижение остатка в резервуаре — литры через колонку.
 * Рост остатка — приход в резервуар, в колонки он не попадает.
 * Снижения по очереди разносятся на две колонки, сумма колонок равна снижению.
 */
export function columnDispenseReport(
  points: LevelReading[],
  range: TimeRange,
  liveTanks: LiveTankSample[] = [],
  now = new Date(),
): ColumnReport {
  const drops: Drop[] = [];
  const byTank = new Map<string, LevelReading[]>();
  for (const point of points) {
    const list = byTank.get(point.tank_id) ?? [];
    list.push(point);
    byTank.set(point.tank_id, list);
  }

  for (const [tankId, rows] of byTank) {
    const ordered = [...rows].sort(
      (a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime(),
    );
    let previous: number | null = null;
    for (const row of ordered) {
      const atMs = new Date(row.recorded_at).getTime();
      if (row.delta_liters != null) {
        pushDrop(drops, atMs, -row.delta_liters, range);
      } else if (previous != null) {
        pushDrop(drops, atMs, previous - row.remainder_liters, range);
      }
      previous = row.remainder_liters;
    }
    const live = liveTanks.find((item) => item.tankId === tankId);
    const last = ordered[ordered.length - 1];
    if (range.includesNow && live && previous != null && last) {
      const atMs = live.measuredAt ? new Date(live.measuredAt).getTime() : now.getTime();
      const lastAt = new Date(last.recorded_at).getTime();
      if (atMs >= lastAt) pushDrop(drops, atMs, previous - live.remainder, range);
    }
  }

  drops.sort((a, b) => a.atMs - b.atMs || a.liters - b.liters);
  const columns: ColumnSeries[] = Array.from({ length: CONNECTED_COLUMNS }, (_, index) => ({
    number: index + 1,
    name: `Колонка ${index + 1}`,
    liters: Array(range.labels.length).fill(0),
    total: 0,
  }));
  drops.forEach((drop, index) => {
    const bucket = range.indexAt(drop.atMs);
    if (bucket < 0) return;
    const column = columns[index % CONNECTED_COLUMNS];
    column.liters[bucket] += drop.liters;
    column.total += drop.liters;
  });
  const totals = range.labels.map((_, index) =>
    columns.reduce((sum, column) => sum + column.liters[index], 0),
  );
  return {
    columnCount: CONNECTED_COLUMNS,
    columns,
    totals,
    total: columns.reduce((sum, column) => sum + column.total, 0),
    labels: range.labels,
  };
}

function pushDrop(drops: Drop[], atMs: number, raw: number, range: TimeRange) {
  if (!(raw >= MIN_DROP_LITERS)) return;
  const liters = Math.round(raw);
  if (liters < 1) return;
  if (range.indexAt(atMs) < 0) return;
  drops.push({ atMs, liters });
}
