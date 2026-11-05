import { api, type LevelReading } from "./api/client";
import type { TimeRange } from "./period";

export type SensorDay = {
  /** Газ, который уже был на первом замере срока. Это не поставка. */
  opening: number | null;
  closing: number | null;
  /** Поставок нет — приход не считаем из остатка, который уже был. */
  inflow: number;
  /** На сколько последний остаток срока ниже первого. Скачки датчика туда-обратно не складываются. */
  outflow: number;
  /** Последний известный остаток в часе или в дне. Текущий интервал, если срок включает сейчас, — тот же остаток, что и на остальных экранах. */
  series: (number | null)[];
  labels: string[];
  bucketStart: number[];
  bucketEnd: number[];
  points: LevelReading[];
  includesNow: boolean;
};

export function emptySensorDay(range: TimeRange): SensorDay {
  return {
    opening: null,
    closing: null,
    inflow: 0,
    outflow: 0,
    series: Array(range.labels.length).fill(null),
    labels: range.labels,
    bucketStart: range.buckets.map((bucket) => bucket.startMs),
    bucketEnd: range.buckets.map((bucket) => bucket.endMs),
    points: [],
    includesNow: range.includesNow,
  };
}

function inRange(row: LevelReading, range: TimeRange): boolean {
  const time = new Date(row.recorded_at).getTime();
  return time >= range.start.getTime() && time < range.end.getTime();
}

export function spanFromReadings(rows: LevelReading[], range: TimeRange, now = new Date()): SensorDay {
  const ordered = [...rows].filter((row) => inRange(row, range)).sort(
    (a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime()
  );
  const base = emptySensorDay(range);
  if (ordered.length === 0) return base;
  const series = base.series.slice();
  for (const row of ordered) {
    const index = range.indexAt(new Date(row.recorded_at).getTime());
    if (index >= 0) series[index] = row.remainder_liters;
  }
  const current = range.indexAt(now.getTime());
  const lastIndex = range.includesNow && current >= 0 ? current : series.length - 1;
  let carry: number | null = null;
  for (let index = 0; index <= lastIndex && index < series.length; index++) {
    if (series[index] != null) carry = series[index];
    else if (carry != null) series[index] = carry;
  }
  const opening = ordered[0].remainder_liters;
  const closing = ordered[ordered.length - 1].remainder_liters;
  return {
    ...base,
    opening,
    closing,
    outflow: Math.max(0, opening - closing),
    series,
    points: ordered,
  };
}

/** Текущий интервал и расход берутся из того же остатка, что карточки и карта. */
export function withLiveRemainder(day: SensorDay, remainder: number | null, now = new Date()): SensorDay {
  if (!day.includesNow || remainder == null) return day;
  const index = day.bucketStart.findIndex((start, place) => {
    const time = now.getTime();
    return time >= start && time < day.bucketEnd[place];
  });
  if (index < 0) return day;
  const series = day.series.slice();
  series[index] = remainder;
  return {
    ...day,
    closing: remainder,
    outflow: day.opening == null ? day.outflow : Math.max(0, day.opening - remainder),
    series,
  };
}

export function chartOf(series: (number | null)[], labels: string[]) {
  const start = series.findIndex((value) => value != null);
  if (start < 0) return { labels: [] as string[], values: [] as number[] };
  let end = series.length - 1;
  while (end > start && series[end] == null) end -= 1;
  return {
    labels: labels.slice(start, end + 1),
    values: series.slice(start, end + 1).map((value) => value ?? 0),
  };
}

export async function loadStationSpan(stationId: string, range: TimeRange): Promise<SensorDay> {
  const since = range.start.toISOString();
  const devices = await api.tankDevices(stationId);
  if (devices.length === 0) return emptySensorDay(range);
  const receipts = range.countsReceipts
    ? await Promise.all(
        devices.map((device) =>
          api
            .tankIngestState(device.id)
            .then((state) => state.receipts_liters || 0)
            .catch(() => 0)
        )
      )
    : [];
  const inflow = receipts.reduce((sum, value) => sum + value, 0);
  const perTank = await Promise.all(
    devices.map((device) => api.tankLevels(stationId, device.id, since, 5000).catch(() => [] as LevelReading[]))
  );
  const sampledAt = new Date();
  const series: (number | null)[] = Array(range.labels.length).fill(null);
  let outflow = 0;
  let opening = 0;
  let closing = 0;
  let any = false;
  const points: LevelReading[] = [];
  perTank.forEach((rows) => {
    const part = spanFromReadings(rows, range, sampledAt);
    if (part.opening == null || part.closing == null) return;
    any = true;
    opening += part.opening;
    closing += part.closing;
    outflow += part.outflow;
    part.series.forEach((value, index) => {
      if (value == null) return;
      series[index] = (series[index] ?? 0) + value;
    });
    points.push(...part.points);
  });
  if (!any) return { ...emptySensorDay(range), inflow };
  return {
    opening,
    closing,
    inflow,
    outflow,
    series,
    labels: range.labels,
    bucketStart: range.buckets.map((bucket) => bucket.startMs),
    bucketEnd: range.buckets.map((bucket) => bucket.endMs),
    points,
    includesNow: range.includesNow,
  };
}
