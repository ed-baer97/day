import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, type CatalogStation, type CatalogTruck, type StationDraft, type TruckDraft } from "./api/client";
import { useAuth } from "./auth";
import { useSim } from "./sim/SimContext";

type CatalogApi = {
  stations: CatalogStation[];
  trucks: CatalogTruck[];
  ready: boolean;
  error: string | null;
  reload: () => Promise<void>;
  saveStation: (id: string | null, body: StationDraft) => Promise<CatalogStation>;
  deleteStation: (id: string) => Promise<void>;
  saveTruck: (id: string | null, body: TruckDraft) => Promise<CatalogTruck>;
  deleteTruck: (id: string) => Promise<void>;
};

const CatalogContext = createContext<CatalogApi | null>(null);

export function messageOf(err: unknown): string {
  if (!(err instanceof Error) || !err.message) return "Сервер не ответил";
  try {
    const parsed = JSON.parse(err.message) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    /* ответ не JSON */
  }
  return err.message;
}

export function CatalogProvider({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const { state } = useSim();
  const [stations, setStations] = useState<CatalogStation[]>([]);
  const [trucks, setTrucks] = useState<CatalogTruck[]>([]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const removedStationIds = useRef<Set<string>>(new Set());
  const removedTruckIds = useRef<Set<string>>(new Set());

  const seedStations = useMemo<CatalogStation[]>(
    () =>
      state.stations.map((s) => ({
        id: s.detail.id,
        code: s.detail.code,
        name: s.detail.name,
        address: s.detail.address,
        lat: s.detail.lat,
        lon: s.detail.lon,
        is_active: s.detail.is_active,
      })),
    [state.stations]
  );

  const seedTrucks = useMemo<CatalogTruck[]>(
    () =>
      state.trucks.map((t) => ({
        id: t.detail.id,
        plate_number: t.detail.plate_number,
        capacity_liters: t.detail.capacity_liters,
        carrier_name: t.detail.carrier_name,
        status: t.detail.status,
        lat: t.detail.lat ?? null,
        lon: t.detail.lon ?? null,
      })),
    [state.trucks]
  );

  const reload = useCallback(async () => {
    try {
      const [apiStations, apiTrucks] = await Promise.all([api.stations(), api.trucks()]);
      setStations((prev) => {
        const merged = new Map<string, CatalogStation>();
        for (const s of apiStations) {
          if (!removedStationIds.current.has(s.id)) merged.set(s.id, s);
        }
        for (const s of prev) {
          if (!removedStationIds.current.has(s.id) && !merged.has(s.id)) merged.set(s.id, s);
        }
        return Array.from(merged.values());
      });
      setTrucks((prev) => {
        const merged = new Map<string, CatalogTruck>();
        for (const t of apiTrucks) {
          if (!removedTruckIds.current.has(t.id)) merged.set(t.id, t);
        }
        for (const t of prev) {
          if (!removedTruckIds.current.has(t.id) && !merged.has(t.id)) merged.set(t.id, t);
        }
        return Array.from(merged.values());
      });
      setError(null);
      setReady(true);
    } catch {
      // Если бэкенд недоступен — на карте остаётся живая АГЗС, без чужих точек.
      setStations((prev) => (prev.length > 0 ? prev : seedStations));
      setTrucks((prev) => (prev.length > 0 ? prev : seedTrucks));
      setError(null);
      setReady(true);
    }
  }, [seedStations, seedTrucks]);

  useEffect(() => {
    if (!session) {
      setStations([]);
      setTrucks([]);
      setReady(false);
      setError(null);
      return;
    }
    void reload();
  }, [session, reload]);

  const saveStation = useCallback(async (id: string | null, body: StationDraft) => {
    let saved: CatalogStation;
    try {
      saved = id ? await api.updateStation(id, body) : await api.createStation(body);
    } catch {
      saved = {
        id: id ?? `st-${Date.now().toString(36)}`,
        code: body.code.trim(),
        name: body.name.trim(),
        address: body.address ? body.address.trim() : null,
        lat: body.lat,
        lon: body.lon,
        is_active: body.is_active,
      };
    }
    removedStationIds.current.delete(saved.id);
    setStations((current) => {
      const index = current.findIndex((row) => row.id === saved.id);
      if (index < 0) return [...current, saved];
      return current.map((row) => (row.id === saved.id ? saved : row));
    });
    setReady(true);
    return saved;
  }, []);

  const deleteStation = useCallback(async (id: string) => {
    try {
      await api.deleteStation(id);
    } catch {
      /* станция могла быть только в локальном каталоге */
    }
    removedStationIds.current.add(id);
    setStations((current) => current.filter((row) => row.id !== id));
    setReady(true);
  }, []);

  const saveTruck = useCallback(async (id: string | null, body: TruckDraft) => {
    let saved: CatalogTruck;
    try {
      saved = id ? await api.updateTruck(id, body) : await api.createTruck(body);
    } catch {
      saved = {
        id: id ?? `tr-${Date.now().toString(36)}`,
        plate_number: body.plate_number.trim(),
        capacity_liters: body.capacity_liters,
        carrier_name: body.carrier_name ? body.carrier_name.trim() : null,
        status: body.status,
        lat: body.lat,
        lon: body.lon,
      };
    }
    removedTruckIds.current.delete(saved.id);
    setTrucks((current) => {
      const index = current.findIndex((row) => row.id === saved.id);
      if (index < 0) return [...current, saved];
      return current.map((row) => (row.id === saved.id ? saved : row));
    });
    setReady(true);
    return saved;
  }, []);

  const deleteTruck = useCallback(async (id: string) => {
    try {
      await api.deleteTruck(id);
    } catch {
      /* газовоз мог быть только в локальном каталоге */
    }
    removedTruckIds.current.add(id);
    setTrucks((current) => current.filter((row) => row.id !== id));
    setReady(true);
  }, []);

  const value = useMemo(
    () => ({
      stations,
      trucks,
      ready,
      error,
      reload,
      saveStation,
      deleteStation,
      saveTruck,
      deleteTruck,
    }),
    [stations, trucks, ready, error, reload, saveStation, deleteStation, saveTruck, deleteTruck]
  );

  return <CatalogContext.Provider value={value}>{children}</CatalogContext.Provider>;
}

export function useCatalog(): CatalogApi {
  const ctx = useContext(CatalogContext);
  if (!ctx) throw new Error("useCatalog outside CatalogProvider");
  return ctx;
}
