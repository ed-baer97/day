import { roleOf, type AppRole } from "./access";

const KEY = "lpg.admin.session";

export type AdminSession = {
  token: string;
  username: string;
  role?: AppRole;
  station_id?: string | null;
  station_ids?: string[];
};

export function readSession(): AdminSession | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<AdminSession>;
    if (!parsed.token || !parsed.username) return null;
    const role = roleOf(parsed.role) ?? "admin";
    const stationIds = Array.isArray(parsed.station_ids)
      ? parsed.station_ids.filter((item): item is string => typeof item === "string" && item.length > 0)
      : [];
    return {
      token: parsed.token,
      username: parsed.username,
      role,
      station_id: parsed.station_id ?? (stationIds.length === 1 ? stationIds[0] : null),
      station_ids: stationIds.length > 0 ? stationIds : parsed.station_id ? [parsed.station_id] : [],
    };
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
