export function messageOf(err: unknown, fallback = "Сервер не ответил"): string {
  if (!(err instanceof Error) || !err.message) return fallback;
  try {
    const parsed = JSON.parse(err.message) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    /* ответ не JSON */
  }
  return err.message;
}
