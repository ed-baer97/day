import type { BatchTrailEvent, DiscrepancyEvent, StationDetail, TruckDetail } from "../types";

export type TripPhase = "loading" | "in_transit" | "arrived" | "unloading" | "idle";

export interface RoutePoint {
  lon: number;
  lat: number;
}

export interface SimTruck {
  detail: TruckDetail;
  route: RoutePoint[];
  /** 0..1 progress along full trip cycle */
  progress: number;
  phase: TripPhase;
  cargo: number;
  loop: number;
}

export interface SimStation {
  detail: StationDetail;
}

export interface SimFactory {
  id: string;
  name: string;
  lat: number;
  lon: number;
}

export interface SimBatch {
  id: string;
  trail_code: string;
  status: string;
  volume_liters: number;
  events: BatchTrailEvent[];
}

export interface SimState {
  simTimeMs: number;
  factories: SimFactory[];
  trucks: SimTruck[];
  stations: SimStation[];
  batch: SimBatch;
  events: DiscrepancyEvent[];
  /** meters of route drawn as trail behind truck */
  clockLabel: string;
}

export const IDS = {
  factory: "f1111111-1111-1111-1111-111111111101",
  stationN: "a1111111-1111-1111-1111-111111111101",
  stationS: "a1111111-1111-1111-1111-111111111102",
  tankN: "b1111111-1111-1111-1111-111111111101",
  tankS: "b1111111-1111-1111-1111-111111111102",
  truckA: "c1111111-1111-1111-1111-111111111101",
  truckB: "c1111111-1111-1111-1111-111111111102",
  batch: "e1111111-1111-1111-1111-111111111101",
} as const;

/** Tolyatti → Samara corridor → Moscow AGZS North (simplified) */
export const ROUTE_A: RoutePoint[] = [
  { lon: 49.4204, lat: 53.5078 },
  { lon: 48.5, lat: 53.8 },
  { lon: 46.0, lat: 54.2 },
  { lon: 42.0, lat: 54.8 },
  { lon: 39.5, lat: 55.2 },
  { lon: 38.0, lat: 55.5 },
  { lon: 37.545, lat: 55.8701 },
];

/** Secondary shorter hop toward AGZS South */
export const ROUTE_B: RoutePoint[] = [
  { lon: 37.62, lat: 55.62 },
  { lon: 37.58, lat: 55.7 },
  { lon: 37.545, lat: 55.8701 },
  { lon: 37.62, lat: 55.62 },
];

function iso(ms: number) {
  return new Date(ms).toISOString();
}

export function createSeed(baseMs = Date.UTC(2026, 8, 26, 8, 0, 0)): SimState {
  const factory: SimFactory = {
    id: IDS.factory,
    name: "Завод Тольятти",
    lat: 53.5078,
    lon: 49.4204,
  };

  const truckA: SimTruck = {
    progress: 0.02,
    phase: "loading",
    cargo: 16500,
    loop: 0,
    route: ROUTE_A,
    detail: {
      id: IDS.truckA,
      plate_number: "А123ВС77",
      capacity_liters: 18000,
      carrier_name: "ГазТранс",
      status: "loading",
      lat: ROUTE_A[0].lat,
      lon: ROUTE_A[0].lon,
      recorded_at: iso(baseMs),
      supplier_name: "ООО ГазСнаб",
      origin_name: "Завод Тольятти",
      destination_name: "АГЗС Север",
      cargo_volume_liters: 16500,
      departed_at: null,
      arrived_at: null,
      trip_status: "loading",
      recent_positions: [],
    },
  };

  const truckB: SimTruck = {
    progress: 0.4,
    phase: "in_transit",
    cargo: 0,
    loop: 0,
    route: ROUTE_B,
    detail: {
      id: IDS.truckB,
      plate_number: "В456ОР99",
      capacity_liters: 20000,
      carrier_name: "ЛПГ Логистика",
      status: "in_transit",
      lat: ROUTE_B[1].lat,
      lon: ROUTE_B[1].lon,
      recorded_at: iso(baseMs),
      supplier_name: "ООО ГазСнаб",
      origin_name: "АГЗС Юг",
      destination_name: "АГЗС Север",
      cargo_volume_liters: 0,
      departed_at: iso(baseMs - 3_600_000),
      arrived_at: null,
      trip_status: "in_transit",
      recent_positions: [],
    },
  };

  const stationN: SimStation = {
    detail: {
      id: IDS.stationN,
      code: "AGZS-MSK-01",
      name: "АГЗС Север",
      address: "Москва, Дмитровское ш.",
      lat: 55.8701,
      lon: 37.545,
      is_active: true,
      tanks: [
        {
          id: IDS.tankN,
          code: "R-1",
          capacity_liters: 25000,
          has_electronic_sensor: true,
          actual_remainder_liters: 9800,
          calculated_remainder_liters: 9800,
          level_source: "electronic",
          last_measured_at: iso(baseMs),
        },
      ],
      remainder_liters: 9800,
      capacity_liters: 25000,
      receipts_day_liters: 0,
      consumption_day_liters: 420,
      consumption_week_liters: 18200,
      consumption_month_liters: 74000,
      sales_day_count: 18,
      active_trucks: [],
      balance_status: "ok",
      calculated_vs_actual_delta: 0,
    },
  };

  const stationS: SimStation = {
    detail: {
      id: IDS.stationS,
      code: "AGZS-MSK-02",
      name: "АГЗС Юг",
      address: "Москва, Варшавское ш.",
      lat: 55.62,
      lon: 37.62,
      is_active: true,
      tanks: [
        {
          id: IDS.tankS,
          code: "R-1",
          capacity_liters: 20000,
          has_electronic_sensor: false,
          actual_remainder_liters: 11200,
          calculated_remainder_liters: 11200,
          level_source: "manual",
          last_measured_at: iso(baseMs),
        },
      ],
      remainder_liters: 11200,
      capacity_liters: 20000,
      receipts_day_liters: 0,
      consumption_day_liters: 310,
      consumption_week_liters: 15100,
      consumption_month_liters: 62000,
      sales_day_count: 12,
      active_trucks: [],
      balance_status: "ok",
      calculated_vs_actual_delta: 0,
    },
  };

  const batch: SimBatch = {
    id: IDS.batch,
    trail_code: "LPG-2026-00041",
    status: "formed",
    volume_liters: 16500,
    events: [
      {
        id: "ev-seed-supplier",
        node_type: "supplier",
        occurred_at: iso(baseMs - 7_200_000),
        title: "Поставщик подтвердил партию",
        description: "ООО ГазСнаб",
        volume_liters: 16500,
      },
      {
        id: "ev-seed-factory",
        node_type: "factory",
        occurred_at: iso(baseMs - 3_600_000),
        title: "Отгрузка с завода",
        description: "Завод Тольятти",
        volume_liters: 16500,
      },
      {
        id: "ev-seed-batch",
        node_type: "batch",
        occurred_at: iso(baseMs - 1_800_000),
        title: "Партия сформирована",
        description: "LPG-2026-00041",
        volume_liters: 16500,
      },
    ],
  };

  return {
    simTimeMs: baseMs,
    factories: [factory],
    trucks: [truckA, truckB],
    stations: [stationN, stationS],
    batch,
    events: [],
    clockLabel: iso(baseMs),
  };
}
