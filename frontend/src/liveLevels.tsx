import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type PublicStation, type PublicTank } from "./api/client";
import { useAuth } from "./auth";
import { useCatalog } from "./catalog";
import { emptySensorDay, loadStationDay, withLiveRemainder, type SensorDay } from "./sensorDay";

export const LOW_FILL_PERCENT = 25;

export function isLowFill(fill: number | null | undefined): boolean {
  return fill != null && fill < LOW_FILL_PERCENT;
}

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
    remainder != null && capacity > 0 ? Math.round((remainder / capacity) * 100) : null;
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

type LevelsApi = {
  byCode: Map<string, LiveLevel>;
  stations: PublicStation[];
  updatedAt: Date | null;
  loading: boolean;
  error: string | null;
  dayById: Map<string, SensorDay>;
};

const LevelsContext = createContext<LevelsApi | null>(null);
const POLL_MS = 15000;

export function LevelsProvider({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const catalog = useCatalog();
  const [stations, setStations] = useState<PublicStation[]>([]);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rawDay, setRawDay] = useState<Map<string, SensorDay>>(new Map());
  const stationKey = session ? catalog.stations.map((row) => row.id).sort().join("|") : "";

  useEffect(() => {
    const ids = stationKey ? stationKey.split("|") : [];
    let live = true;

    async function load() {
      const [levelsResult, dayResult] = await Promise.all([
        api.publicLevels().then(
          (rows) => ({ ok: true as const, rows }),
          () => ({ ok: false as const, rows: null })
        ),
        ids.length === 0
          ? Promise.resolve(null)
          : Promise.all(
              ids.map(async (id) => {
                try {
                  return [id, await loadStationDay(id)] as const;
                } catch {
                  return [id, emptySensorDay()] as const;
                }
              })
            ),
      ]);
      if (!live) return;
      if (levelsResult.ok && levelsResult.rows) {
        setStations(levelsResult.rows);
        setUpdatedAt(new Date());
        setError(null);
      } else {
        setError("Не удалось обновить уровни");
      }
      setRawDay(dayResult ? new Map(dayResult) : new Map());
      setLoading(false);
    }

    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [stationKey]);

  const byCode = useMemo(() => {
    const map = new Map<string, LiveLevel>();
    for (const row of stations) map.set(row.code, summarizeLevel(row));
    return map;
  }, [stations]);

  const dayById = useMemo(() => {
    const codeById = new Map(catalog.stations.map((row) => [row.id, row.code]));
    const next = new Map<string, SensorDay>();
    for (const [id, day] of rawDay) {
      const live = byCode.get(codeById.get(id) ?? "");
      next.set(id, withLiveRemainder(day, live?.remainder ?? null));
    }
    if (!session) return next;
    for (const station of catalog.stations) {
      if (next.has(station.id)) continue;
      const live = byCode.get(station.code);
      if (live?.remainder == null) continue;
      next.set(station.id, withLiveRemainder(emptySensorDay(), live.remainder));
    }
    return next;
  }, [rawDay, byCode, catalog.stations, session]);

  const value = useMemo(
    () => ({ byCode, stations, updatedAt, loading, error, dayById }),
    [byCode, stations, updatedAt, loading, error, dayById]
  );

  return <LevelsContext.Provider value={value}>{children}</LevelsContext.Provider>;
}

function useLevels(): LevelsApi {
  const ctx = useContext(LevelsContext);
  if (!ctx) throw new Error("usePublicLevels outside LevelsProvider");
  return ctx;
}

export function usePublicLevels() {
  const { byCode, stations, updatedAt, loading, error } = useLevels();
  return { byCode, stations, updatedAt, loading, error };
}

export function useSensorDay(stationIds: string[]) {
  const { dayById } = useLevels();
  const key = [...stationIds].sort().join("|");
  return useMemo(() => {
    const ids = key ? key.split("|") : [];
    const map = new Map<string, SensorDay>();
    for (const id of ids) {
      const day = dayById.get(id);
      if (day) map.set(id, day);
    }
    return map;
  }, [dayById, key]);
}
