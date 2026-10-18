import type {
  BatchTrail,
  DiscrepancyEvent,
  MapOverview,
  StationDetail,
  TruckDetail,
} from "../types";
import { expireSession, readSession, type AdminSession } from "../session";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

export interface ShellyLink {
  host: string;
  online: boolean;
  mac: string | null;
  model: string | null;
  firmware: string | null;
  rssi: number | null;
  sensor_ready: boolean;
  volts: number | null;
  applied: boolean;
  last_polled_at: string | null;
  last_error: string | null;
}

export interface PublicTank {
  code: string;
  capacity_liters: number;
  remainder_liters: number | null;
  fill_percent: number | null;
  measured_at: string | null;
}

export interface PublicStation {
  code: string;
  name: string;
  address?: string | null;
  tanks: PublicTank[];
}

export interface TankDevice {
  id: string;
  station_id: string;
  code: string;
  capacity_liters: number;
  ingest_token: string;
  level_path: string;
  shelly: ShellyLink | null;
}

export interface CatalogStation {
  id: string;
  code: string;
  name: string;
  address?: string | null;
  lat: number;
  lon: number;
  is_active: boolean;
}

export interface CatalogTruck {
  id: string;
  plate_number: string;
  capacity_liters: number;
  carrier_name?: string | null;
  status: string;
  lat?: number | null;
  lon?: number | null;
}

export type StationDraft = {
  code: string;
  name: string;
  address?: string | null;
  lat: number;
  lon: number;
  is_active: boolean;
};

export type TruckDraft = {
  plate_number: string;
  capacity_liters: number;
  carrier_name?: string | null;
  status: string;
  lat?: number | null;
  lon?: number | null;
};

function authHeader(): Record<string, string> {
  const token = readSession()?.token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function readError(res: Response, path: string): Promise<Error> {
  if (res.status === 401 && !path.startsWith("/auth/")) {
    expireSession();
    return new Error("Сессия закончилась");
  }
  const text = await res.text();
  if (res.status === 401) return new Error("Неверный логин или пароль");
  return new Error(text || res.statusText);
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeader() });
  if (!res.ok) throw await readError(res, path);
  return res.json() as Promise<T>;
}

async function sendJson<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { ...authHeader() };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw await readError(res, path);
  return res.json() as Promise<T>;
}

export const api = {
  login: async (username: string, password: string): Promise<AdminSession> => {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
    } catch {
      throw new Error("Сервер не ответил");
    }
    if (res.status === 401) throw new Error("Неверный логин или пароль");
    if (!res.ok) throw new Error("Сервер не ответил");
    return res.json() as Promise<AdminSession>;
  },
  mapOverview: () => getJson<MapOverview>("/map/overview"),
  stations: () => getJson<CatalogStation[]>("/stations"),
  createStation: (body: StationDraft) => sendJson<CatalogStation>("POST", "/stations", body),
  updateStation: (id: string, body: StationDraft) =>
    sendJson<CatalogStation>("PATCH", `/stations/${id}`, body),
  trucks: () => getJson<CatalogTruck[]>("/trucks"),
  createTruck: (body: TruckDraft) => sendJson<CatalogTruck>("POST", "/trucks", body),
  updateTruck: (id: string, body: TruckDraft) => sendJson<CatalogTruck>("PATCH", `/trucks/${id}`, body),
  tankDevices: (stationId: string) => getJson<TankDevice[]>(`/stations/${stationId}/devices`),
  createTankDevice: (stationId: string, body: { code: string; capacity_liters: number }) =>
    sendJson<TankDevice>("POST", `/stations/${stationId}/devices`, body),
  updateTankDevice: (
    stationId: string,
    tankId: string,
    body: { code: string; capacity_liters: number }
  ) => sendJson<TankDevice>("PATCH", `/stations/${stationId}/devices/${tankId}`, body),
  connectShelly: (stationId: string, tankId: string, host: string) =>
    sendJson<TankDevice>("PUT", `/stations/${stationId}/devices/${tankId}/shelly`, { host }),
  disconnectShelly: (stationId: string, tankId: string) =>
    sendJson<TankDevice>("DELETE", `/stations/${stationId}/devices/${tankId}/shelly`),
  truck: (id: string) => getJson<TruckDetail>(`/trucks/${id}`),
  station: (id: string) => getJson<StationDetail>(`/stations/${id}`),
  trailByCode: (code: string) =>
    getJson<BatchTrail>(`/batches/by-code/${encodeURIComponent(code)}/trail`),
  events: () => getJson<DiscrepancyEvent[]>("/events?unresolved_only=true"),
  publicLevels: () => getJson<PublicStation[]>("/public/levels"),
};
