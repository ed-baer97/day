import type { FiscalStatus, LinkQuality, SensorStatus, SupplyStatus } from "./types";

export const REGIONS = [
  "г. Актау",
  "г. Жанаозен",
  "Мунайлинский р-н",
  "Каракиянский р-н",
  "Тупкараганский р-н",
  "Мангистауский р-н",
  "Бейнеуский р-н",
] as const;

export function stationRegion(station: { name?: string | null; address?: string | null; code?: string | null }): string {
  const hay = `${station.name ?? ""} ${station.address ?? ""} ${station.code ?? ""}`.toLowerCase();
  if (hay.includes("актау") || hay.includes("akt")) return "г. Актау";
  if (hay.includes("жанаозен") || hay.includes("рахат") || hay.includes("тенге") || hay.includes("zho")) return "г. Жанаозен";
  if (
    hay.includes("мунайл") ||
    hay.includes("баскудук") ||
    hay.includes("кызылтобе") ||
    hay.includes("мангистау,") ||
    hay.includes("с. мангистау") ||
    hay.includes("mun")
  )
    return "Мунайлинский р-н";
  if (hay.includes("жетыбай") || hay.includes("курык") || hay.includes("караки") || hay.includes("zhb") || hay.includes("kur"))
    return "Каракиянский р-н";
  if (
    hay.includes("форт-шевченко") ||
    hay.includes("акшукур") ||
    hay.includes("тупкараган") ||
    hay.includes("fsh") ||
    hay.includes("tup")
  )
    return "Тупкараганский р-н";
  if (hay.includes("шетпе") || hay.includes("сай-утес") || hay.includes("мангистауский") || hay.includes("shp"))
    return "Мангистауский р-н";
  if (hay.includes("бейнеу") || hay.includes("боранкул") || hay.includes("bey")) return "Бейнеуский р-н";
  return "Мангистауская обл.";
}

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

export function percentLabel(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${Math.round(value)}%`;
}

export function liters(v?: number | null) {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Math.round(v).toLocaleString("ru-RU")} л`;
}

export function signedLiters(v: number) {
  const r = Math.round(v);
  return `${r > 0 ? "+" : ""}${r.toLocaleString("ru-RU")} л`;
}

export function balBadge(status: string) {
  if (status === "ok" || status === "in_band") return "ok";
  if (
    status === "warn" ||
    status === "outside_band" ||
    status === "measurement_error" ||
    status === "unregistered_receipt" ||
    status === "unregistered_dispense"
  ) {
    return "warn";
  }
  if (status === "unknown") return "";
  if (status === "shortage" || status === "surplus") return "danger";
  return "";
}

export function balText(status: string) {
  if (status === "ok" || status === "in_band") return "в полосе датчика";
  if (status === "warn" || status === "outside_band" || status === "measurement_error") {
    return "датчик вне полосы";
  }
  if (status === "unknown") return "датчик недоступен";
  if (status === "unregistered_receipt") return "слив без документа";
  if (status === "unregistered_dispense") return "уход без колонки";
  if (status === "shortage") return "недостача";
  if (status === "surplus") return "излишек";
  return status;
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

export function batchStatusLabel(status?: string | null): string {
  const map: Record<string, string> = {
    formed: "сформирована",
    in_transit: "в пути",
    delivered: "доставлена",
    partially_sold: "частично продана",
    closed: "закрыта",
  };
  return status ? map[status] ?? status : "—";
}

export function eventTypeLabel(eventType?: string | null): string {
  const map: Record<string, string> = {
    shortage: "Недостача",
    surplus: "Излишек",
    unregistered_receipt: "Слив без документа",
    unregistered_dispense: "Уход без колонки",
    measurement_error: "Погрешность датчика",
    outside_band: "Датчик вне полосы",
    sensor_offline: "Нет связи",
    calibration: "Калибровка",
    ok: "Норма",
  };
  return eventType ? map[eventType] ?? eventType : "Событие";
}

export function severityLabel(severity?: string | null): string {
  const map: Record<string, string> = {
    critical: "критично",
    warning: "внимание",
    warn: "внимание",
    info: "инфо",
  };
  return severity ? map[severity] ?? severity : "—";
}

export function trailNodeLabel(nodeType?: string | null): string {
  const map: Record<string, string> = {
    supplier: "Поставщик",
    factory: "Завод",
    batch: "Партия",
    truck: "Газовоз",
    route: "Маршрут",
    station: "АГЗС",
    tank: "Резервуар",
    dispense: "ТРК",
    sale: "Продажа",
  };
  return nodeType ? map[nodeType] ?? nodeType : "Этап";
}

export function columnsModeLabel(mode?: string | null): string {
  if (mode === "virtual") return "Виртуальные";
  if (mode === "edge") return "Реальные (Edge)";
  return "Отключены";
}
