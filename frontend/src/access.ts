import policy from "../../backend/app/domain/level_policy.json";

/** Имена ролей из level_policy.json — те же, что проверяет сервер. */
export const ROLE_ADMIN = policy.role_admin;
export const ROLE_STATION = policy.role_station;

export type AppRole = typeof ROLE_ADMIN | typeof ROLE_STATION;

export function roleOf(value: unknown): AppRole | undefined {
  if (value === ROLE_ADMIN || value === ROLE_STATION) return value;
  return undefined;
}

export function isAdmin(session: { role?: string | null } | null | undefined): boolean {
  return session?.role === ROLE_ADMIN;
}
