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
  remainder_liters?: number | null;
  capacity_liters?: number | null;
  receipts_day_liters: number;
  consumption_day_liters: number;
  consumption_week_liters: number;
  consumption_month_liters: number;
  sales_day_count: number;
  active_trucks: { plate: string; status: string }[];
  balance_status: string;
  calculated_vs_actual_delta?: number | null;
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
