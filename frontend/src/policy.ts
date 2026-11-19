import policy from "../../backend/app/domain/level_policy.json";

/** Те же числа, что в backend/app/domain/level_policy.json. */
export const LOW_FILL_PERCENT = policy.low_fill_percent;
export const SAFE_FILL_PERCENT = policy.safe_fill_percent;
export const POLL_MS = policy.poll_seconds * 1000;
export const SENSOR_STALE_SECONDS = policy.sensor_stale_seconds;
export const DIAL_MIN_PERCENT = policy.dial_min_percent;
export const DIAL_MAX_PERCENT = policy.dial_max_percent;

/** Свободный объём до полной ёмкости резервуара. */
export function freeVolumeLiters(
  capacity: number,
  remainder: number | null | undefined,
): number | null {
  if (remainder == null || capacity <= 0) return null;
  return Math.max(0, capacity - remainder);
}

/** Свободный объём безопасного слива до предельного уровня заполнения (из level_policy.json). */
export function safeRefillLiters(
  capacity: number,
  remainder: number | null | undefined,
  maxFillPercent: number = SAFE_FILL_PERCENT,
): number | null {
  if (remainder == null || capacity <= 0) return null;
  return Math.max(0, Math.round((capacity * maxFillPercent) / 100) - remainder);
}
