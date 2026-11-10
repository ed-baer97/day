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

export type AdminTab = "stations" | "trucks" | "supplies" | "reconcile" | "security";

export const ADMIN_SECTIONS: { id: AdminTab; label: string; note: string }[] = [
  { id: "stations", label: "АГЗС", note: "Карточки, резервуары, Shelly" },
  { id: "trucks", label: "Газовозы", note: "Автопарк и GPS-координаты" },
  { id: "supplies", label: "Поставки", note: "План подвоза и партии" },
  { id: "reconcile", label: "Сверка и аудит", note: "Контроль датчиков и события" },
  { id: "security", label: "Доступ и защита", note: "Контур безопасности" },
];
