import { api, type LevelReading } from "./api/client";

export type SensorDay = {
  /** Газ, который уже был на первом замере дня. Это не поставка. */
  opening: number | null;
  closing: number | null;
  /** Поставок нет — приход не считаем из остатка, который уже был. */
  inflow: number;
  /** На сколько текущий остаток ниже первого замера дня. Скачки датчика туда-обратно не складываются. */
  outflow: number;
  /** Последний известный остаток в часе. Текущий час — тот же остаток, что и на остальных экранах. */
  hourlyLevel: (number | null)[];
  points: LevelReading[];
};

export function emptySensorDay(): SensorDay {
  return {
    opening: null,
    closing: null,
    inflow: 0,
    outflow: 0,
    hourlyLevel: Array(24).fill(null),
    points: [],
  };
}

function startOfTodayIso() {
  const stamp = new Date();
  stamp.setHours(0, 0, 0, 0);
  return stamp.toISOString();
}

export function sensorDayFromReadings(rows: LevelReading[], now = new Date()): SensorDay {
  const ordered = [...rows].sort(
    (a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime()
  );
  if (ordered.length === 0) return emptySensorDay();
  const hourlyLevel: (number | null)[] = Array(24).fill(null);
  for (const row of ordered) {
    const hour = new Date(row.recorded_at).getHours();
    if (hour >= 0 && hour <= 23) hourlyLevel[hour] = row.remainder_liters;
  }
  const openingLiters = ordered[0].remainder_liters;
  const closingLiters = ordered[ordered.length - 1].remainder_liters;
  const outflow = Math.max(0, openingLiters - closingLiters);
  const nowHour = now.getHours();
  let carry: number | null = null;
  for (let hour = 0; hour <= nowHour; hour++) {
    if (hourlyLevel[hour] != null) carry = hourlyLevel[hour];
    else if (carry != null) hourlyLevel[hour] = carry;
  }
  return {
    opening: openingLiters,
    closing: closingLiters,
    inflow: 0,
    outflow,
    hourlyLevel,
    points: ordered,
  };
}

/** Текущий час и расход берутся из того же остатка, что карточки и карта. */
export function withLiveRemainder(day: SensorDay, remainder: number | null, hour = new Date().getHours()): SensorDay {
  if (remainder == null || hour < 0 || hour > 23) return day;
  const hourlyLevel = day.hourlyLevel.slice();
  hourlyLevel[hour] = remainder;
  const outflow = day.opening == null ? day.outflow : Math.max(0, day.opening - remainder);
  return {
    ...day,
    closing: remainder,
    outflow,
    hourlyLevel,
  };
}

export async function loadStationDay(stationId: string): Promise<SensorDay> {
  const since = startOfTodayIso();
  const devices = await api.tankDevices(stationId);
  if (devices.length === 0) return emptySensorDay();
  const receipts = await Promise.all(
    devices.map((device) =>
      api
        .tankIngestState(device.id)
        .then((state) => state.receipts_liters || 0)
        .catch(() => 0)
    )
  );
  const inflow = receipts.reduce((sum, value) => sum + value, 0);
  const perTank = await Promise.all(
    devices.map((device) => api.tankLevels(stationId, device.id, since).catch(() => [] as LevelReading[]))
  );
  const hourlyLevel: (number | null)[] = Array(24).fill(null);
  let outflow = 0;
  let opening = 0;
  let closing = 0;
  let any = false;
  const points: LevelReading[] = [];
  perTank.forEach((rows) => {
    const part = sensorDayFromReadings(rows);
    if (part.opening == null || part.closing == null) return;
    any = true;
    opening += part.opening;
    closing += part.closing;
    outflow += part.outflow;
    part.hourlyLevel.forEach((value, hour) => {
      if (value == null) return;
      hourlyLevel[hour] = (hourlyLevel[hour] ?? 0) + value;
    });
    points.push(...part.points);
  });
  if (!any) return { ...emptySensorDay(), inflow };
  return { opening, closing, inflow, outflow, hourlyLevel, points };
}

export function hoursToday() {
  const hour = new Date().getHours();
  return Array.from({ length: hour + 1 }, (_, index) => index);
}
