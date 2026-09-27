export type MapPointKind = "factory" | "truck" | "station";

export interface MapPoint {
  id: string;
  kind: MapPointKind;
  name: string;
  lat: number;
  lon: number;
  status?: string | null;
  meta?: Record<string, unknown> | null;
}

export interface MapOverview {
  generated_at: string;
  points: MapPoint[];
  active_trips: number;
  open_events: number;
}

export interface TruckDetail {
  id: string;
  plate_number: string;
  capacity_liters: number;
  carrier_name?: string | null;
  status: string;
  lat?: number | null;
  lon?: number | null;
  recorded_at?: string | null;
  supplier_name?: string | null;
  origin_name?: string | null;
  destination_name?: string | null;
  cargo_volume_liters?: number | null;
  departed_at?: string | null;
  arrived_at?: string | null;
  trip_status?: string | null;
  recent_positions?: { lat: number; lon: number; recorded_at: string }[];
}

export interface Tank {
  id: string;
  code: string;
  capacity_liters: number;
  has_electronic_sensor: boolean;
  actual_remainder_liters?: number | null;
  calculated_remainder_liters?: number | null;
  level_source: string;
  last_measured_at?: string | null;
}

export interface StationDetail {
  id: string;
  code: string;
  name: string;
  address?: string | null;
  lat: number;
  lon: number;
  is_active: boolean;
  tanks: Tank[];
  /** Остаток на начало суток (книга) */
  opening_remainder_liters: number;
  remainder_liters?: number | null;
  capacity_liters?: number | null;
  /** Доставлено газовозами за сутки */
  receipts_day_liters: number;
  /** Прошло через колонки (продажи) за сутки */
  consumption_day_liters: number;
  consumption_week_liters: number;
  consumption_month_liters: number;
  sales_day_count: number;
  /** Сколько раз газовоз слил на АГЗС за сутки */
  delivery_count_day: number;
  /** Средний объём одной заправки клиента, л */
  avg_fill_liters: number;
  recent_fills: { liters: number; occurred_at: string }[];
  recent_deliveries: { plate: string; liters: number; occurred_at: string }[];
  active_trucks: { plate: string; status: string }[];
  balance_status: string;
  calculated_vs_actual_delta?: number | null;
  price_kzt_per_liter: number;
  pumps: PumpFiscal[];
}

/**
 * Колонка (ТРК) и её онлайн-ККМ.
 * Цепочка: счётчик ТРК → чек на ККМ → ОФД → КГД.
 */
export interface PumpFiscal {
  id: string;
  code: string;
  kkm_serial: string;
  /** false — ККМ в автономном режиме, чеки копятся и не уходят в ОФД */
  kkm_online: boolean;
  counter_liters: number;
  /** незавершённая заправка: уже на счётчике, чек ещё не пробит */
  pouring_liters: number;
  fills: number;
  /** пробито на ККМ */
  kkm_liters: number;
  kkm_receipts: number;
  kkm_amount_kzt: number;
  /** получено ОФД и передано в КГД */
  ofd_liters: number;
  ofd_receipts: number;
  ofd_last_at: string;
}

export type FiscalStatus = "ok" | "no_receipt" | "not_sent";

export interface PumpFiscalCheck extends PumpFiscal {
  /** счётчик − ККМ: продано без чека */
  unreceipted_liters: number;
  /** ККМ − ОФД: чеки не дошли до ОФД/КГД */
  unsent_liters: number;
  unsent_receipts: number;
  status: FiscalStatus;
}

export interface FiscalCheck {
  counter_liters: number;
  fills: number;
  kkm_liters: number;
  kkm_receipts: number;
  ofd_liters: number;
  ofd_receipts: number;
  ofd_amount_kzt: number;
  unreceipted_liters: number;
  unsent_liters: number;
  /** всё, чего не видит КГД: без чека + не передано */
  gap_liters: number;
  gap_kzt: number;
  status: FiscalStatus;
  pumps: PumpFiscalCheck[];
}

/** Сверка АГЗС: доставка ↔ хранилище ↔ колонки */
export interface StationBalance {
  delivered: number;
  storage_actual: number;
  through_pumps: number;
  opening: number;
  /** opening + delivered − pumps */
  book_remainder: number;
  /** actual − book */
  delta: number;
  status: "ok" | "warn" | "shortage" | "surplus";
}

export interface FleetStats {
  delivered_liters_day: number;
  delivery_trips_day: number;
  sold_liters_day: number;
  fills_day: number;
  trucks_in_transit: number;
  stations_active: number;
}

export interface BatchTrailEvent {
  id: string;
  node_type: string;
  occurred_at: string;
  title: string;
  description?: string | null;
  volume_liters?: number | null;
}

export interface BatchTrail {
  batch: {
    id: string;
    trail_code: string;
    status: string;
    volume_liters: number;
  };
  chain: string[];
  events: BatchTrailEvent[];
}

export interface DiscrepancyEvent {
  id: string;
  station_id: string;
  event_type: string;
  severity: string;
  delta_liters?: number | null;
  title: string;
  description?: string | null;
  is_resolved: boolean;
  detected_at: string;
}
