import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, type CatalogStation, type CatalogTruck, type StationDraft, type TruckDraft } from "./api/client";
import { useAuth } from "./auth";

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
  const [stations, setStations] = useState<CatalogStation[]>([]);
  const [trucks, setTrucks] = useState<CatalogTruck[]>([]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const removedStationIds = useRef<Set<string>>(new Set());
  const removedTruckIds = useRef<Set<string>>(new Set());

  const reload = useCallback(async () => {
    try {
      const owner = session?.role === "owner" || session?.role === "station" || session?.role === "console";
      const [apiStations, apiTrucks] = owner
        ? [await api.stations(), [] as CatalogTruck[]]
        : await Promise.all([api.stations(), api.trucks()]);
      setStations(apiStations.filter((row) => !removedStationIds.current.has(row.id)));
      setTrucks(apiTrucks.filter((row) => !removedTruckIds.current.has(row.id)));
      setError(null);
    } catch (err) {
      setStations([]);
      setTrucks([]);
      setError(messageOf(err));
    } finally {
      setReady(true);
    }
  }, [session?.role]);

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
    const saved = id ? await api.updateStation(id, body) : await api.createStation(body);
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
    await api.deleteStation(id);
    removedStationIds.current.add(id);
    setStations((current) => current.filter((row) => row.id !== id));
    setReady(true);
  }, []);

  const saveTruck = useCallback(async (id: string | null, body: TruckDraft) => {
    const saved = id ? await api.updateTruck(id, body) : await api.createTruck(body);
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
    await api.deleteTruck(id);
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
