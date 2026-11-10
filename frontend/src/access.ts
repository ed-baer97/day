import policy from "../../backend/app/domain/level_policy.json";

/** Имена ролей из level_policy.json — те же, что проверяет сервер. */
export const ROLE_ADMIN = policy.role_admin;
export const ROLE_STATION = policy.role_station;
export const ROLE_OWNER = "owner" as const;

export type AppRole =
  | typeof ROLE_ADMIN
  | typeof ROLE_STATION
  | typeof ROLE_OWNER;

export function roleOf(value: unknown): AppRole | undefined {
  if (
    value === ROLE_ADMIN ||
    value === ROLE_STATION ||
    value === ROLE_OWNER
  ) {
    return value;
  }
  return undefined;
}

export function isAdmin(session: { role?: string | null } | null | undefined): boolean {
  return session?.role === ROLE_ADMIN;
}
