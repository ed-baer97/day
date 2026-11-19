import type { ColumnsMode, DispenseReading, LevelReading } from "./api/client";
import type { TimeRange } from "./period";

/** Базовое число колонок по умолчанию, если в паспорте АГЗС оно не задано явно. */
export const CONNECTED_COLUMNS = 2;

/** Сдвиг меньше литра в отпуск не пишем: это шум шкалы, не заправка. */
const MIN_DROP_LITERS = 1;

export type { ColumnsMode };

export type ColumnSeries = {
  number: number;
  code: string;
  name: string;
  kkmSerial: string;
  liters: number[];
  total: number;
  opsCount: number;
  lastLiters: number | null;
  lastAt: string | null;
  kkmLiters: number;
  ofdLiters: number;
  discrepancyLiters: number;
};

export type ColumnReport = {
  columnCount: number;
  columns: ColumnSeries[];
  totals: number[];
  total: number;
  tankOutflowLiters: number;
  kkmTotalLiters: number;
  ofdTotalLiters: number;
  opsTotal: number;
  discrepancyLiters: number;
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

type Drop = { atMs: number; liters: number };

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
 * Отпуск для отчёта по колонкам:
 * 1) При наличии реальных транзакций `station-edge` за период или при режиме `mode: "edge"` строит отчёт по ним (`source: "edge"`).
 * 2) Иначе (режим `mode: "virtual"`) каждое снижение остатка в резервуаре переводится в отпуск по виртуальным колонкам (`source: "level"`).
 */
export function columnDispenseReport(
  points: LevelReading[],
  range: TimeRange,
  liveTanks: LiveTankSample[] = [],
  now = new Date(),
  fallbackOutflow = 0,
  realDispenses: DispenseReading[] = [],
  options?: { columnCount?: number; mode?: ColumnsMode },
): ColumnReport {
  const colCount = Math.max(1, Math.min(8, Math.round(options?.columnCount ?? CONNECTED_COLUMNS)));
  const mode: ColumnsMode = options?.mode ?? "virtual";

  const columns: ColumnSeries[] = Array.from({ length: colCount }, (_, index) => ({
    number: index + 1,
    code: `ТРК-${index + 1}`,
    name: `Колонка ${index + 1}`,
    kkmSerial: `ККМ-ТРК-0${index + 1}`,
    liters: Array(range.labels.length).fill(0),
    total: 0,
    opsCount: 0,
    lastLiters: null,
    lastAt: null,
    kkmLiters: 0,
    ofdLiters: 0,
    discrepancyLiters: 0,
  }));

  const inRangeDispenses = realDispenses
    .map((item) => {
      const stamp = item.finished_at ?? item.started_at;
      const atMs = new Date(stamp).getTime();
      return { item, atMs, bucket: range.indexAt(atMs) };
    })
    .filter((entry) => entry.bucket >= 0 && entry.item.volume_liters > 0)
    .sort((a, b) => a.atMs - b.atMs);

  let source: "edge" | "level" = "level";

  if (inRangeDispenses.length > 0 || mode === "edge") {
    source = "edge";
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
  } else {
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

    if (drops.length > 0) {
      drops.forEach((drop, index) => {
        const bucket = range.indexAt(drop.atMs);
        if (bucket < 0) return;
        const column = columns[index % colCount];
        column.liters[bucket] += drop.liters;
        column.total += drop.liters;
        column.opsCount += 1;
        column.lastLiters = drop.liters;
        column.lastAt = new Date(drop.atMs).toISOString();
      });
    } else if (fallbackOutflow >= MIN_DROP_LITERS && range.labels.length > 0) {
      const fallbackTotal = Math.round(fallbackOutflow);
      const nowBucket = range.indexAt(now.getTime());
      const bucket = nowBucket >= 0 ? nowBucket : range.labels.length - 1;
      const stamp = range.includesNow
        ? now.toISOString()
        : new Date(range.buckets[bucket].startMs).toISOString();
      const basePart = Math.floor(fallbackTotal / colCount);
      let remainderPart = fallbackTotal - basePart * colCount;
      for (let index = 0; index < colCount; index += 1) {
        const extra = remainderPart > 0 ? 1 : 0;
        if (remainderPart > 0) remainderPart -= 1;
        const litersPart = basePart + extra;
        if (litersPart < 1) continue;
        const column = columns[index];
        column.liters[bucket] += litersPart;
        column.total += litersPart;
        column.opsCount += 1;
        column.lastLiters = litersPart;
        column.lastAt = stamp;
      }
    }
  }

  for (const column of columns) {
    column.kkmLiters = column.total;
    column.ofdLiters = column.total;
    column.discrepancyLiters = 0;
  }

  const totals = range.labels.map((_, index) =>
    Math.round(columns.reduce((sum, column) => sum + column.liters[index], 0) * 1000) / 1000,
  );
  const total = Math.round(columns.reduce((sum, column) => sum + column.total, 0) * 1000) / 1000;
  const opsTotal = columns.reduce((sum, column) => sum + column.opsCount, 0);
  const tankOutflowLiters =
    source === "edge" && fallbackOutflow > 0
      ? Math.round(fallbackOutflow * 1000) / 1000
      : total;
  const discrepancyLiters =
    source === "edge" && fallbackOutflow > 0 ? Math.round(total - tankOutflowLiters) : 0;
  const status: "ok" | "warn" =
    source === "edge" && Math.abs(discrepancyLiters) > 50 ? "warn" : "ok";

  return {
    columnCount: colCount,
    columns,
    totals,
    total,
    tankOutflowLiters,
    kkmTotalLiters: total,
    ofdTotalLiters: total,
    opsTotal,
    discrepancyLiters,
    status,
    source,
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
