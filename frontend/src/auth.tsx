import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { roleOf } from "./access";
import { api } from "./api/client";
import { onSessionExpired, readSession, writeSession, type AdminSession } from "./session";

type AuthApi = {
  session: AdminSession | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthApi | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AdminSession | null>(() => readSession());

  const login = useCallback(async (username: string, password: string) => {
    const next = await api.login(username, password);
    writeSession(next);
    setSession(next);
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
        const next: AdminSession = {
          token: current.token,
          username: me.username,
          role: roleOf(me.role),
          station_id: me.station_id,
        };
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
