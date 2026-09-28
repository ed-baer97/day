import type { FiscalStatus, LinkQuality, SensorStatus, StationBalance, SupplyStatus } from "./types";

export function fiscalBadge(status: FiscalStatus) {
  if (status === "ok") return "ok";
  if (status === "not_sent") return "warn";
  return "danger";
}

export function fiscalText(status: FiscalStatus) {
  if (status === "ok") return "сходится";
  if (status === "not_sent") return "не передано в ОФД";
  return "продажа без чека";
}

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

export function tenge(v: number) {
  return `${Math.round(v).toLocaleString("ru-RU")} ₸`;
}

export function timeHM(iso: string) {
  return new Date(iso).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

export function shortStationName(name: string) {
  return name.replace(/^АГЗС\s+/, "");
}

export function dateTime(iso?: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function celsius(v?: number | null) {
  if (v == null || Number.isNaN(v)) return "—";
  return `${v.toLocaleString("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} °C`;
}

/** Разница текущего объёма с предыдущим звеном, например «−80 л к отгрузке». */
export function vsBase(current: number, base: number, what: string) {
  const d = Math.round(current - base);
  const text = `${d > 0 ? "+" : ""}${d.toLocaleString("ru-RU")} л`;
  return `${text} к ${what}`;
}

export function columnLabel(code: string) {
  const n = code.match(/(\d+)\s*$/)?.[1];
  return n ? `Колонка №${n}` : code;
}

export function linkText(q: LinkQuality) {
  if (q === "good") return "хорошая";
  if (q === "fair") return "удовлетворительная";
  return "слабая";
}

export function sensorText(s: SensorStatus) {
  if (s === "ok") return "норма";
  if (s === "warn") return "внимание";
  return "нет связи";
}

export function supplyStatusText(status: SupplyStatus) {
  if (status === "loading") return "погрузка";
  if (status === "in_transit") return "в пути";
  if (status === "unloading") return "слив";
  if (status === "accepted") return "принято";
  return "реализация";
}
