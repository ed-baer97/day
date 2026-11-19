import type { AdminStationOverview, CatalogStation } from "../../api/client";
import type { LiveLevel } from "../../liveLevels";

export const TRUCK_STATUS = [
  { value: "idle", label: "ожидание" },
  { value: "loading", label: "погрузка" },
  { value: "in_transit", label: "в пути" },
  { value: "arrived", label: "прибыл" },
  { value: "unloading", label: "слив" },
] as const;

export function statusLabel(value: string) {
  return TRUCK_STATUS.find((row) => row.value === value)?.label ?? value;
}

export function truckStatusBadge(status: string): "ok" | "warn" | "" {
  if (status === "in_transit") return "ok";
  if (status === "loading" || status === "arrived" || status === "unloading") return "warn";
  return "";
}

export type EnrichedStation = {
  row: CatalogStation;
  overview: AdminStationOverview | null;
  cap: number;
  actual: number | null;
  fill: number | null;
  free: number | null;
  safeRefill: number | null;
  online: boolean;
  live: LiveLevel | null;
  region: string;
  tanksCount: number;
  calibratedCount: number;
  bookCalc: number | null;
  bookDelta: number | null;
  balanceStatus: string;
};

export type AdminTab = "stations" | "trucks" | "edge" | "reconcile" | "access";

export const ADMIN_SECTIONS: { id: AdminTab; label: string; note: string }[] = [
  { id: "stations", label: "АГЗС и оборудование", note: "Карточки, резервуары, Shelly, ТРК" },
  { id: "trucks", label: "Автопарк", note: "Газовозы и GPS-координаты" },
  { id: "edge", label: "Edge-узлы и OTA", note: "Станционные узлы и кольца" },
  { id: "reconcile", label: "Сверка и инциденты", note: "Баланс книги и датчиков" },
  { id: "access", label: "Пользователи и доступ", note: "Владельцы и токены устройств" },
];
