import policy from "../../backend/app/domain/level_policy.json";

/** Те же числа, что в backend/app/domain/level_policy.json. */
export const LOW_FILL_PERCENT = policy.low_fill_percent;
export const POLL_MS = policy.poll_seconds * 1000;
export const DIAL_MIN_PERCENT = policy.dial_min_percent;
export const DIAL_MAX_PERCENT = policy.dial_max_percent;
