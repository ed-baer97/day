import type {
  BatchTrail,
  DiscrepancyEvent,
  MapOverview,
  StationDetail,
  TruckDetail,
} from "../types";
import { expireSession, readSession, type AdminSession } from "../session";

const API_BASE = import.meta.env?.VITE_API_BASE ?? "/api/v1";

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
  online?: boolean;
}

export interface PublicStation {
  code: string;
  name: string;
  address?: string | null;
  lat?: number;
  lon?: number;
  tanks: PublicTank[];
}

export interface TankDevice {
  id: string;
  station_id: string;
  code: string;
  capacity_liters: number;
  ingest_token: string;
  level_path: string;
  ingest_url?: string;
  shelly: ShellyLink | null;
}

export interface LevelReading {
  id: string;
  tank_id: string;
  volts: number | null;
  remainder_liters: number;
  fill_percent: number | null;
  recorded_at: string;
  delta_liters?: number | null;
}

export interface TankIngestState {
  station_id: string;
  tank_id: string;
  opening_liters: number | null;
  receipts_liters: number;
  dispense_liters: number;
  pending_dispense_liters: number;
  calculated_remainder_liters: number | null;
  actual_remainder_liters: number | null;
  delta_liters: number | null;
  balance_status: string;
  calibrated: boolean;
  last_volts: number | null;
  last_measured_at: string | null;
}

export interface IngestAck {
  accepted: boolean;
  message: string;
  entity_id?: string | null;
  duplicate: boolean;
  actual_remainder_liters?: number | null;
  calculated_remainder_liters?: number | null;
  delta_liters?: number | null;
  balance_status?: string | null;
}

export interface BatchRecord {
  id: string;
  trail_code: string;
  supplier_id?: string | null;
  factory_id?: string | null;
  product_grade?: string | null;
  density_kg_per_liter?: number | null;
  volume_liters: number;
  mass_kg?: number | null;
  status: string;
  formed_at?: string | null;
  notes?: string | null;
  created_at: string;
}

export interface BalanceSnapshot {
  id: string;
  station_id: string;
  tank_id: string;
  period_start: string;
  period_end: string;
  previous_remainder_liters: number;
  receipts_liters: number;
  dispense_liters: number;
  calculated_remainder_liters: number;
  actual_remainder_liters: number | null;
  delta_liters: number | null;
  status: string;
  created_at: string;
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

export interface CabinetPump {
  pump_id: string;
  name: string;
  delivered_ml: number;
  amount_kzt: number;
  sales: number;
}

export interface CabinetSale {
  sale_id: string;
  number: string;
  pump_name: string;
  delivered_ml: number;
  amount_kzt: number;
  price_kzt_per_liter: number;
  finished_at: string;
}

export interface CabinetFace {
  station_id: string;
  price_kzt_per_liter: number;
  delivered_ml: number;
  amount_kzt: number;
  sales: number;
  pumps: CabinetPump[];
  recent: CabinetSale[];
}

export interface StationUser {
  id: string;
  station_id: string;
  username: string;
  kind?: string;
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

function authHeader(extraHeaders?: Record<string, string>): Record<string, string> {
  const token = readSession()?.token;
  const base: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
  return extraHeaders ? { ...base, ...extraHeaders } : base;
}

async function readError(res: Response, path: string): Promise<Error> {
  if (res.status === 401 && !path.startsWith("/auth/") && !path.startsWith("/ingest/")) {
    expireSession();
    return new Error("Сессия закончилась");
  }
  const text = await res.text();
  if (res.status === 401) return new Error("Неверный логин или пароль");
  return new Error(text || res.statusText);
}

async function getJson<T>(path: string, extraHeaders?: Record<string, string>): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeader(extraHeaders) });
  if (!res.ok) throw await readError(res, path);
  return res.json() as Promise<T>;
}

async function sendJson<T>(
  method: string,
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>
): Promise<T> {
  const headers: Record<string, string> = { ...authHeader(extraHeaders) };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw await readError(res, path);
  if (res.status === 204) return undefined as T;
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
    if (res.status === 429) {
      throw new Error("Слишком много неудачных попыток входа. Подождите минуту.");
    }
    if (res.status === 401) throw new Error("Неверный логин или пароль");
    if (!res.ok) throw new Error("Сервер не ответил");
    return res.json() as Promise<AdminSession>;
  },
  logout: async (): Promise<void> => {
    try {
      await sendJson("POST", "/auth/logout");
    } catch {
      /* игнорируем при недоступности сервера */
    }
  },
  mapOverview: () => getJson<MapOverview>("/map/overview"),
  stations: () => getJson<CatalogStation[]>("/stations"),
  stationUsers: (stationId: string) => getJson<StationUser[]>("/stations/" + stationId + "/users"),
  cabinet: (stationId: string) => getJson<CabinetFace>(`/stations/${stationId}/console/cabinet`),
  consoleAdmins: (stationId: string) => getJson<StationUser[]>(`/stations/${stationId}/console/admins`),
  createConsoleAdmin: (stationId: string, body: { username: string; password: string }) =>
    sendJson<StationUser & { password: string }>("POST", `/stations/${stationId}/console/admins`, body),
  setCabinetPrice: (stationId: string, priceKztPerLiter: number) =>
    sendJson<CabinetFace>("PUT", `/stations/${stationId}/console/cabinet/price`, {
      price_kzt_per_liter: priceKztPerLiter,
    }),
  createStationUser: (stationId: string, body: { username: string; password: string }) =>
    sendJson<StationUser & { password: string }>("POST", `/stations/${stationId}/users`, body),
  createStation: (body: StationDraft) => sendJson<CatalogStation>("POST", "/stations", body),
  updateStation: (id: string, body: Partial<StationDraft>) =>
    sendJson<CatalogStation>("PATCH", `/stations/${id}`, body),
  deleteStation: (id: string) => sendJson<void>("DELETE", `/stations/${id}`),
  trucks: () => getJson<CatalogTruck[]>("/trucks"),
  createTruck: (body: TruckDraft) => sendJson<CatalogTruck>("POST", "/trucks", body),
  updateTruck: (id: string, body: Partial<TruckDraft>) =>
    sendJson<CatalogTruck>("PATCH", `/trucks/${id}`, body),
  deleteTruck: (id: string) => sendJson<void>("DELETE", `/trucks/${id}`),
  tankDevices: (stationId: string) => getJson<TankDevice[]>(`/stations/${stationId}/devices`),
  createTankDevice: (stationId: string, body: { code: string; capacity_liters: number }) =>
    sendJson<TankDevice>("POST", `/stations/${stationId}/devices`, body),
  updateTankDevice: (
    stationId: string,
    tankId: string,
    body: { code: string; capacity_liters: number }
  ) => sendJson<TankDevice>("PATCH", `/stations/${stationId}/devices/${tankId}`, body),
  deleteTankDevice: (stationId: string, tankId: string) =>
    sendJson<void>("DELETE", `/stations/${stationId}/devices/${tankId}`),
  connectShelly: (stationId: string, tankId: string, host: string) =>
    sendJson<TankDevice>("PUT", `/stations/${stationId}/devices/${tankId}/shelly`, { host }),
  disconnectShelly: (stationId: string, tankId: string) =>
    sendJson<TankDevice>("DELETE", `/stations/${stationId}/devices/${tankId}/shelly`),
  tankLevels: (stationId: string, tankId: string, since?: string, limit = 2000) => {
    const cap = Math.max(1, Math.min(limit, 5000));
    const query = since
      ? `?since=${encodeURIComponent(since)}&changes_only=true&limit=${cap}`
      : `?changes_only=true&limit=${Math.min(cap, 200)}`;
    return getJson<LevelReading[]>(`/stations/${stationId}/devices/${tankId}/levels${query}`);
  },
  calibrateTank: (
    body: {
      station_id?: string;
      tank_id?: string;
      capacity_liters?: number;
      low_volts: number;
      low_percent: number;
      high_volts: number;
      high_percent: number;
    },
    deviceToken?: string
  ) =>
    sendJson<TankIngestState>(
      "PUT",
      "/ingest/calibration",
      body,
      deviceToken ? { "X-Device-Token": deviceToken } : undefined
    ),
  ingestLevel: (
    body: {
      station_id?: string;
      tank_id?: string;
      actual_remainder_liters?: number;
      volts?: number;
      level_source?: string;
      recorded_at: string;
      source_event_id?: string;
    },
    deviceToken?: string
  ) =>
    sendJson<IngestAck>(
      "POST",
      "/ingest/level",
      body,
      deviceToken ? { "X-Device-Token": deviceToken } : undefined
    ),
  ingestReceipt: (
    body: {
      station_id: string;
      tank_id: string;
      volume_liters: number;
      recorded_at: string;
      source_event_id?: string;
    },
    deviceToken?: string
  ) =>
    sendJson<IngestAck>(
      "POST",
      "/ingest/receipt",
      body,
      deviceToken ? { "X-Device-Token": deviceToken } : undefined
    ),
  tankIngestState: (tankId: string, deviceToken?: string) =>
    getJson<TankIngestState>(
      `/ingest/tanks/${tankId}`,
      deviceToken ? { "X-Device-Token": deviceToken } : undefined
    ),
  batches: () => getJson<BatchRecord[]>("/batches"),
  createBatch: (body: {
    trail_code: string;
    product_grade?: string;
    density_kg_per_liter?: number;
    volume_liters: number;
    mass_kg?: number;
    notes?: string;
  }) => sendJson<BatchRecord>("POST", "/batches", body),
  truck: (id: string) => getJson<TruckDetail>(`/trucks/${id}`),
  station: (id: string) => getJson<StationDetail>(`/stations/${id}`),
  trailByCode: (code: string) =>
    getJson<BatchTrail>(`/batches/by-code/${encodeURIComponent(code)}/trail`),
  events: (stationId?: string, unresolvedOnly = true) => {
    const params = new URLSearchParams();
    if (stationId) params.set("station_id", stationId);
    if (unresolvedOnly) params.set("unresolved_only", "true");
    const q = params.toString();
    return getJson<DiscrepancyEvent[]>(`/events${q ? `?${q}` : ""}`);
  },
  resolveEvent: (eventId: string, note?: string) =>
    sendJson<DiscrepancyEvent>("POST", `/events/${eventId}/resolve`, { note: note ?? null }),
  reconcileBalance: (body: {
    station_id: string;
    tank_id: string;
    period_start: string;
    period_end: string;
    previous_remainder_liters: number;
    receipts_liters: number;
    dispense_liters: number;
    actual_remainder_liters: number | null;
  }) => sendJson<BalanceSnapshot>("POST", "/balance/reconcile", body),
  stationSnapshots: (stationId: string) =>
    getJson<BalanceSnapshot[]>(`/balance/stations/${stationId}/snapshots`),
  publicLevels: () => getJson<PublicStation[]>("/public/levels"),
  me: () => getJson<{ username: string; role: string; station_id: string | null; station_ids?: string[] }>("/auth/me"),
};
