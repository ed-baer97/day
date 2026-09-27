import type { StationBalance } from "./types";

export function liters(v?: number | null) {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Math.round(v).toLocaleString("ru-RU")} л`;
}

export function signedLiters(v: number) {
  const r = Math.round(v);
  return `${r > 0 ? "+" : ""}${r.toLocaleString("ru-RU")} л`;
}

export function balBadge(status: StationBalance["status"]) {
  if (status === "ok") return "ok";
  if (status === "warn") return "warn";
  return "danger";
}

export function balText(status: StationBalance["status"]) {
  if (status === "ok") return "сходится";
  if (status === "warn") return "погрешность";
  if (status === "shortage") return "недостача";
  return "излишек";
}

export function phaseLabel(status?: string | null) {
  const map: Record<string, string> = {
    loading: "погрузка",
    routing: "маршрут",
    in_transit: "в пути",
    arrived: "прибыл",
    unloading: "слив",
    idle: "ожидание",
  };
  return status ? map[status] ?? status : "—";
}

export function timeHM(iso: string) {
  return new Date(iso).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

export function shortStationName(name: string) {
  return name.replace(/^АГЗС\s+/, "");
}
