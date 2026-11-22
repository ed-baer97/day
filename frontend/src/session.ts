import { roleOf, type AppRole } from "./access";

const KEY = "lpg.admin.session";

export type AdminSession = {
  token: string;
  username: string;
  role?: AppRole;
  station_id?: string | null;
  station_ids?: string[];
};

export type RawSessionInput = {
  token?: unknown;
  username?: unknown;
  role?: unknown;
  station_id?: unknown;
  station_ids?: unknown;
};

export function normalizeStationIds(stationIds: unknown, stationId?: unknown): string[] {
  const seen = new Set<string>();
  const normalized: string[] = [];
  if (Array.isArray(stationIds)) {
    for (const item of stationIds) {
      if (typeof item === "string" && item.length > 0 && !seen.has(item)) {
        seen.add(item);
        normalized.push(item);
      }
    }
  }
  if (normalized.length === 0 && typeof stationId === "string" && stationId.length > 0) {
    normalized.push(stationId);
  }
  return normalized;
}

export function normalizeSession(raw: RawSessionInput | null | undefined): AdminSession | null {
  if (!raw || typeof raw.token !== "string" || !raw.token || typeof raw.username !== "string" || !raw.username) {
    return null;
  }
  const role = roleOf(raw.role);
  const stationIds = normalizeStationIds(raw.station_ids, raw.station_id);
  return {
    token: raw.token,
    username: raw.username,
    role,
    station_id: stationIds.length === 1 ? stationIds[0] : null,
    station_ids: stationIds,
  };
}

export function readSession(): AdminSession | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    return normalizeSession(JSON.parse(raw) as RawSessionInput);
  } catch {
    return null;
  }
}

export function writeSession(session: AdminSession | null) {
  if (!session) sessionStorage.removeItem(KEY);
  else sessionStorage.setItem(KEY, JSON.stringify(session));
}

type Listener = () => void;
const listeners = new Set<Listener>();

export function onSessionExpired(listener: Listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function expireSession() {
  if (!readSession()) return;
  writeSession(null);
  for (const listener of listeners) listener();
}
