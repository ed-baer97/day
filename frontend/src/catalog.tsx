import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, type CatalogStation, type CatalogTruck, type StationDraft, type TruckDraft } from "./api/client";
import { useAuth } from "./auth";

type CatalogApi = {
  stations: CatalogStation[];
  trucks: CatalogTruck[];
  ready: boolean;
  error: string | null;
  reload: () => Promise<void>;
  saveStation: (id: string | null, body: StationDraft) => Promise<CatalogStation>;
  saveTruck: (id: string | null, body: TruckDraft) => Promise<CatalogTruck>;
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

  const reload = useCallback(async () => {
    try {
      const [nextStations, nextTrucks] = await Promise.all([api.stations(), api.trucks()]);
      setStations(nextStations);
      setTrucks(nextTrucks);
      setError(null);
      setReady(true);
    } catch (err) {
      setError(messageOf(err));
      setReady(false);
    }
  }, []);

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
    setStations((current) => {
      const index = current.findIndex((row) => row.id === saved.id);
      if (index < 0) return [...current, saved];
      return current.map((row) => (row.id === saved.id ? saved : row));
    });
    setReady(true);
    return saved;
  }, []);

  const saveTruck = useCallback(async (id: string | null, body: TruckDraft) => {
    const saved = id ? await api.updateTruck(id, body) : await api.createTruck(body);
    setTrucks((current) => {
      const index = current.findIndex((row) => row.id === saved.id);
      if (index < 0) return [...current, saved];
      return current.map((row) => (row.id === saved.id ? saved : row));
    });
    setReady(true);
    return saved;
  }, []);

  const value = useMemo(
    () => ({ stations, trucks, ready, error, reload, saveStation, saveTruck }),
    [stations, trucks, ready, error, reload, saveStation, saveTruck]
  );

  return <CatalogContext.Provider value={value}>{children}</CatalogContext.Provider>;
}

export function useCatalog(): CatalogApi {
  const ctx = useContext(CatalogContext);
  if (!ctx) throw new Error("useCatalog outside CatalogProvider");
  return ctx;
}
