import policy from "../../backend/app/domain/level_policy.json";
import type { AppRoute, AppScreen } from "./route";

/** Имена ролей из level_policy.json — те же, что проверяет сервер. */
export const ROLE_ADMIN = policy.role_admin;
export const ROLE_STATION = policy.role_station;
export const ROLE_OWNER = policy.role_owner;
export const ROLE_CASHIER = policy.role_cashier;

export type AppRole =
  | typeof ROLE_ADMIN
  | typeof ROLE_STATION
  | typeof ROLE_OWNER
  | typeof ROLE_CASHIER;

export type SessionLike = { role?: string | null } | null | undefined;

export type SessionCapabilities = {
  admin: boolean;
  owner: boolean;
  cashier: boolean;
  stationSide: boolean;
  knownRole: boolean;
  homeScreen: AppScreen;
};

export function roleOf(value: unknown): AppRole | undefined {
  if (
    value === ROLE_ADMIN ||
    value === ROLE_STATION ||
    value === ROLE_OWNER ||
    value === ROLE_CASHIER
  ) {
    return value;
  }
  return undefined;
}

export function isAdmin(session: SessionLike): boolean {
  return session?.role === ROLE_ADMIN;
}

export function isOwner(session: SessionLike): boolean {
  return session?.role === ROLE_OWNER || session?.role === ROLE_STATION;
}

export function isCashier(session: SessionLike): boolean {
  return session?.role === ROLE_CASHIER;
}

export function sessionCapabilities(session: SessionLike): SessionCapabilities {
  const admin = isAdmin(session);
  const owner = isOwner(session);
  const cashier = isCashier(session);
  const stationSide = owner || cashier;
  const knownRole = admin || stationSide;
  const homeScreen: AppScreen = cashier ? "cashier" : admin || owner ? "dashboard" : "landing";
  return { admin, owner, cashier, stationSide, knownRole, homeScreen };
}

export function screenFor(
  session: SessionLike,
  route: Pick<AppRoute, "screen"> | AppScreen
): AppScreen {
  const requested: AppScreen = typeof route === "string" ? route : route.screen;
  const caps = sessionCapabilities(session);
  if (!session || !caps.knownRole) return "landing";
  if (requested === "landing") return "landing";
  if (caps.cashier) return "cashier";
  if (caps.owner) return "dashboard";
  if (requested === "cashier") return caps.homeScreen;
  return requested;
}

export function entryLabelFor(session: SessionLike): string {
  const caps = sessionCapabilities(session);
  if (caps.admin) return "Диспетчерская";
  if (caps.cashier) return "Рабочее место кассира";
  if (caps.owner) return "Кабинет";
  return "Проверка…";
}
