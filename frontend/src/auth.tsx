import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api/client";
import {
  normalizeSession,
  onSessionExpired,
  readSession,
  writeSession,
  type AdminSession,
} from "./session";

type AuthApi = {
  session: AdminSession | null;
  login: (username: string, password: string) => Promise<AdminSession>;
  logout: () => void;
};

const AuthContext = createContext<AuthApi | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AdminSession | null>(() => readSession());

  const login = useCallback(async (username: string, password: string) => {
    const raw = await api.login(username, password);
    const next = normalizeSession(raw);
    if (!next) throw new Error("Некорректный ответ авторизации");
    writeSession(next);
    setSession(next);
    return next;
  }, []);

  const logout = useCallback(() => {
    void api.logout();
    writeSession(null);
    setSession(null);
  }, []);

  useEffect(() => onSessionExpired(() => setSession(null)), []);

  useEffect(() => {
    const current = readSession();
    if (!current) return;
    let live = true;
    api
      .me()
      .then((me) => {
        if (!live) return;
        const next = normalizeSession({
          token: current.token,
          username: me.username,
          role: me.role,
          station_id: me.station_id,
          station_ids: me.station_ids,
        });
        if (!next) return;
        writeSession(next);
        setSession(next);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);

  const value = useMemo(() => ({ session, login, logout }), [session, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthApi {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
