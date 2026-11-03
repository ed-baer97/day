import { useEffect, useState } from "react";
import { api, type LevelReading } from "./api/client";

export type SensorDay = {
  delta: number | null;
  hourlyIn: number[];
  hourlyOut: number[];
  points: LevelReading[];
};

const EMPTY = (): SensorDay => ({
  delta: null,
  hourlyIn: Array(24).fill(0),
  hourlyOut: Array(24).fill(0),
  points: [],
});

function startOfTodayIso() {
  const stamp = new Date();
  stamp.setHours(0, 0, 0, 0);
  return stamp.toISOString();
}

function dayOf(rows: LevelReading[]): SensorDay {
  const hourlyIn = Array(24).fill(0);
  const hourlyOut = Array(24).fill(0);
  if (rows.length === 0) return { delta: null, hourlyIn, hourlyOut, points: [] };
  const first = rows[0].remainder_liters;
  const last = rows[rows.length - 1].remainder_liters;
  for (const row of rows) {
    if (row.delta_liters == null) continue;
    const hour = new Date(row.recorded_at).getHours();
    if (hour < 0 || hour > 23) continue;
    if (row.delta_liters >= 0) hourlyIn[hour] += row.delta_liters;
    else hourlyOut[hour] += -row.delta_liters;
  }
  return { delta: last - first, hourlyIn, hourlyOut, points: rows };
}

async function loadStation(stationId: string, since: string): Promise<SensorDay> {
  const devices = await api.tankDevices(stationId);
  if (devices.length === 0) return EMPTY();
  const perTank = await Promise.all(
    devices.map((device) => api.tankLevels(stationId, device.id, since).catch(() => [] as LevelReading[]))
  );
  const hourlyIn = Array(24).fill(0);
  const hourlyOut = Array(24).fill(0);
  let delta = 0;
  let any = false;
  const points: LevelReading[] = [];
  perTank.forEach((rows, index) => {
    const part = dayOf(rows);
    if (part.delta != null) {
      delta += part.delta;
      any = true;
    }
    part.hourlyIn.forEach((value, hour) => {
      hourlyIn[hour] += value;
    });
    part.hourlyOut.forEach((value, hour) => {
      hourlyOut[hour] += value;
    });
    if (index === 0) points.push(...rows);
  });
  return { delta: any ? delta : null, hourlyIn, hourlyOut, points };
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
