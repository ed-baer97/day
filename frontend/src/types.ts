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

export type LinkQuality = "good" | "fair" | "weak";
export type SensorStatus = "ok" | "warn" | "offline";

export interface Tank {
  id: string;
  code: string;
  capacity_liters: number;
  has_electronic_sensor: boolean;
  actual_remainder_liters?: number | null;
  calculated_remainder_liters?: number | null;
  /** Цифровой уровень: Rochester Junior снимает SRG-1-WAVE */
  level_source: string;
  last_measured_at?: string | null;
  temperature_c: number;
  /** Смартфон АГЗС, через который уходит замер */
  phone_label: string;
  link_quality: LinkQuality;
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
  recent_fills: FillEvent[];
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
export interface FillEvent {
  liters: number;
  occurred_at: string;
  pump_code: string;
  price_kzt_per_liter: number;
}

export interface PumpFiscal {
  id: string;
  code: string;
  kkm_serial: string;
  /** false — ККМ в автономном режиме, чеки копятся и не уходят в ОФД */
  kkm_online: boolean;
  /** Связь Topaz-119-28M → RS-232 → LTE-шлюз */
  link_status: SensorStatus;
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

export type SupplyStatus = "loading" | "in_transit" | "unloading" | "accepted" | "selling";

/** Одна поставка LPG: все объёмы цепочки ссылаются на supply_id. */
export interface LpgSupply {
  supply_id: string;
  /** Живой рейс симуляции — объёмы на газовозе обновляются */
  live: boolean;
  status: SupplyStatus;
  factory_id: string;
  factory_name: string;
  truck_id: string;
  plate: string;
  station_id: string;
  station_name: string;
  tank_id: string;
  tank_code: string;
  shipped_at: string;
  waybill: string;
  shipped_liters: number;
  shipped_temp_c: number;
  route_name: string;
  departed_at: string | null;
  arrived_at: string | null;
  delivered_liters: number | null;
  truck_temp_c: number | null;
  gps_lat: number | null;
  gps_lon: number | null;
  gps_at: string | null;
  gps_status: SensorStatus;
  quantity_sensor: SensorStatus;
  temp_sensor: SensorStatus;
  accepted_liters: number | null;
  accepted_at: string | null;
  dispensed_liters: number;
  fiscal_liters: number;
  fiscal_receipts: number;
  fiscal_amount_kzt: number;
  fiscal_period: string;
  fiscal_updated_at: string | null;
  operations: SupplyOperation[];
}

export interface SupplyOperation {
  id: string;
  pump_code: string;
  volume_liters: number;
  price_kzt_per_liter: number;
  amount_kzt: number;
  occurred_at: string;
  state: "done" | "pouring";
  link_status: SensorStatus;
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
