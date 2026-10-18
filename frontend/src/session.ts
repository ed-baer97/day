const KEY = "lpg.admin.session";

export type AdminSession = {
  token: string;
  username: string;
};

export function readSession(): AdminSession | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<AdminSession>;
    if (!parsed.token || !parsed.username) return null;
    return { token: parsed.token, username: parsed.username };
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
