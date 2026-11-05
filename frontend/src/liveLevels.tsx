import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type PublicStation, type PublicTank } from "./api/client";
import { useAuth } from "./auth";
import { useCatalog } from "./catalog";
import { periodFromKey, periodKey, resolveRange, todayPeriod, type TimeRange, type ViewPeriod } from "./period";
import { emptySensorDay, loadStationSpan, withLiveRemainder, type SensorDay } from "./sensorDay";

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
  historyLoading: boolean;
  dayById: Map<string, SensorDay>;
  period: ViewPeriod;
  setPeriod: (period: ViewPeriod) => void;
  range: TimeRange;
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
  const [historyLoading, setHistoryLoading] = useState(false);
  const [rawDay, setRawDay] = useState<Map<string, SensorDay>>(new Map());
  const [period, setPeriodState] = useState<ViewPeriod>(() => todayPeriod());
  const [now, setNow] = useState(() => new Date());
  const stationKey = session ? catalog.stations.map((row) => row.id).sort().join("|") : "";
  const selectedKey = periodKey(period);
  const range = useMemo(() => resolveRange(periodFromKey(selectedKey, now), now), [selectedKey, now]);

  const setPeriod = useCallback((next: ViewPeriod) => {
    const today = todayPeriod();
    if (next.preset === "today") {
      setPeriodState(today);
      return;
    }
    setPeriodState({
      preset: next.preset,
      day: next.day > today.day ? today.day : next.day,
    });
  }, []);

  useEffect(() => {
    let live = true;
    async function load() {
      try {
        const rows = await api.publicLevels();
        if (!live) return;
        setStations(rows);
        setUpdatedAt(new Date());
        setNow(new Date());
        setError(null);
      } catch {
        if (!live) return;
        setError("Не удалось обновить уровни");
      } finally {
        if (live) setLoading(false);
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const ids = stationKey ? stationKey.split("|") : [];
    const span = resolveRange(periodFromKey(selectedKey), new Date());
    let live = true;
    let first = true;

    async function load() {
      if (first) {
        setRawDay(new Map());
        setHistoryLoading(ids.length > 0);
        first = false;
      }
      if (ids.length === 0) {
        if (!live) return;
        setRawDay(new Map());
        setHistoryLoading(false);
        return;
      }
      const pairs = await Promise.all(
        ids.map(async (id) => {
          try {
            return [id, await loadStationSpan(id, span)] as const;
          } catch {
            return [id, emptySensorDay(span)] as const;
          }
        })
      );
      if (!live) return;
      setNow(new Date());
      setRawDay(new Map(pairs));
      setHistoryLoading(false);
    }

    void load();
    if (!span.includesNow) {
      return () => {
        live = false;
      };
    }
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [stationKey, selectedKey]);

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
      next.set(id, withLiveRemainder(day, live?.remainder ?? null, now));
    }
    if (!session || !range.includesNow) return next;
    for (const station of catalog.stations) {
      if (next.has(station.id)) continue;
      const live = byCode.get(station.code);
      if (live?.remainder == null) continue;
      next.set(station.id, withLiveRemainder(emptySensorDay(range), live.remainder, now));
    }
    return next;
  }, [rawDay, byCode, catalog.stations, session, now, range]);

  const value = useMemo(
    () => ({ byCode, stations, updatedAt, loading, error, historyLoading, dayById, period, setPeriod, range }),
    [byCode, stations, updatedAt, loading, error, historyLoading, dayById, period, setPeriod, range]
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

export function useViewPeriod() {
  const { period, setPeriod, range, historyLoading } = useLevels();
  return { period, setPeriod, range, historyLoading };
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
