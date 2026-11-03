import { useEffect, useMemo, useState } from "react";
import { api, type PublicStation, type PublicTank } from "./api/client";

export type LiveLevel = {
  code: string;
  tanks: PublicTank[];
  remainder: number | null;
  capacity: number;
  fill: number | null;
  hasReading: boolean;
  measuredAt: string | null;
};

export function summarizeLevel(station: PublicStation): LiveLevel {
  const tanks = station.tanks;
  const capacity = tanks.reduce((sum, tank) => sum + (tank.capacity_liters || 0), 0);
  const known = tanks.filter((tank) => tank.remainder_liters != null);
  const remainder = known.length
    ? known.reduce((sum, tank) => sum + (tank.remainder_liters ?? 0), 0)
    : null;
  const fill =
    remainder != null && capacity > 0 ? Math.round((remainder / capacity) * 1000) / 10 : null;
  const measuredAt =
    tanks
      .map((tank) => tank.measured_at)
      .filter((stamp): stamp is string => !!stamp)
      .sort()
      .at(-1) ?? null;
  return {
    code: station.code,
    tanks,
    remainder,
    capacity,
    fill,
    hasReading: remainder != null,
    measuredAt,
  };
}

export function sensorLabel(level: LiveLevel): string {
  if (!level.hasReading) return "замера нет";
  const known = level.tanks.filter((tank) => tank.remainder_liters != null);
  const online = known.filter((tank) => tank.online === true).length;
  if (online === known.length) return "датчик работает";
  if (online === 0) return "нет связи";
  return "нет связи у части";
}

export function sensorBadge(level: LiveLevel): "ok" | "warn" | "danger" {
  if (!level.hasReading) return "warn";
  const known = level.tanks.filter((tank) => tank.remainder_liters != null);
  const online = known.filter((tank) => tank.online === true).length;
  if (online === known.length) return "ok";
  if (online === 0) return "danger";
  return "warn";
}

export function tankSensorLabel(tank: PublicTank): string {
  if (tank.remainder_liters == null) return "замера нет";
  return tank.online === true ? "датчик работает" : "нет связи";
}

export function tankSensorBadge(tank: PublicTank): "ok" | "warn" | "danger" {
  if (tank.remainder_liters == null) return "warn";
  return tank.online === true ? "ok" : "danger";
}

export function SensorStatus({ level }: { level: LiveLevel }) {
  return <span className={`badge ${sensorBadge(level)}`}>{sensorLabel(level)}</span>;
}

export function usePublicLevels() {
  const [rows, setRows] = useState<PublicStation[]>([]);

  useEffect(() => {
    let live = true;
    async function load() {
      try {
        const next = await api.publicLevels();
        if (live) setRows(next);
      } catch {
        /* оставляем последний удачный срез */
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);

  const byCode = useMemo(() => {
    const map = new Map<string, LiveLevel>();
    for (const row of rows) map.set(row.code, summarizeLevel(row));
    return map;
  }, [rows]);

  return { byCode };
}
