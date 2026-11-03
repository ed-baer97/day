import { useEffect, useState } from "react";
import { api, type LevelReading } from "./api/client";

export type SensorDay = {
  /** Газ, который уже был на первом замере дня. Это не поставка. */
  opening: number | null;
  closing: number | null;
  /** Поставок нет — приход не считаем из остатка, который уже был. */
  inflow: number;
  /** Падение уровня датчика. */
  outflow: number;
  /** Последний известный остаток в часе. До первого замера — пусто. */
  hourlyLevel: (number | null)[];
  points: LevelReading[];
};

const EMPTY = (): SensorDay => ({
  opening: null,
  closing: null,
  inflow: 0,
  outflow: 0,
  hourlyLevel: Array(24).fill(null),
  points: [],
});

function startOfTodayIso() {
  const stamp = new Date();
  stamp.setHours(0, 0, 0, 0);
  return stamp.toISOString();
}

function dayOf(rows: LevelReading[]): SensorDay {
  const ordered = [...rows].sort(
    (a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime()
  );
  if (ordered.length === 0) return EMPTY();
  const hourlyLevel: (number | null)[] = Array(24).fill(null);
  let outflow = 0;
  for (const row of ordered) {
    const hour = new Date(row.recorded_at).getHours();
    if (hour >= 0 && hour <= 23) hourlyLevel[hour] = row.remainder_liters;
    if (row.delta_liters != null && row.delta_liters < 0) outflow += -row.delta_liters;
  }
  const now = new Date().getHours();
  let carry: number | null = null;
  for (let hour = 0; hour <= now; hour++) {
    if (hourlyLevel[hour] != null) carry = hourlyLevel[hour];
    else if (carry != null) hourlyLevel[hour] = carry;
  }
  return {
    opening: ordered[0].remainder_liters,
    closing: ordered[ordered.length - 1].remainder_liters,
    inflow: 0,
    outflow,
    hourlyLevel,
    points: ordered,
  };
}

async function loadStation(stationId: string, since: string): Promise<SensorDay> {
  const devices = await api.tankDevices(stationId);
  if (devices.length === 0) return EMPTY();
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
  perTank.forEach((rows, index) => {
    const part = dayOf(rows);
    if (part.opening == null || part.closing == null) return;
    any = true;
    opening += part.opening;
    closing += part.closing;
    outflow += part.outflow;
    part.hourlyLevel.forEach((value, hour) => {
      if (value == null) return;
      hourlyLevel[hour] = (hourlyLevel[hour] ?? 0) + value;
    });
    if (index === 0) points.push(...part.points);
  });
  if (!any) return { ...EMPTY(), inflow };
  return { opening, closing, inflow, outflow, hourlyLevel, points };
}

export function useSensorDay(stationIds: string[]) {
  const [byStation, setByStation] = useState<Map<string, SensorDay>>(new Map());
  const key = [...stationIds].sort().join("|");

  useEffect(() => {
    const ids = key ? key.split("|") : [];
    if (ids.length === 0) {
      setByStation(new Map());
      return;
    }
    let live = true;
    async function load() {
      const since = startOfTodayIso();
      const pairs = await Promise.all(
        ids.map(async (id) => {
          try {
            return [id, await loadStation(id, since)] as const;
          } catch {
            return [id, EMPTY()] as const;
          }
        })
      );
      if (!live) return;
      setByStation(new Map(pairs));
    }
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [key]);

  return byStation;
}

export function hoursToday() {
  const hour = new Date().getHours();
  return Array.from({ length: hour + 1 }, (_, index) => index);
}
