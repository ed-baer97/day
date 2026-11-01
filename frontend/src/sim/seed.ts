import type {
  BatchTrailEvent,
  DiscrepancyEvent,
  LpgSupply,
  StationDetail,
  TruckDetail,
} from "../types";
import type { Coord } from "./geo";

export type { Coord };

/** @deprecated alias — предпочтительнее Coord */
export type RoutePoint = { lon: number; lat: number };

export type TripPhase = "loading" | "routing" | "in_transit" | "arrived" | "unloading" | "idle";

export interface SimTruck {
  detail: TruckDetail;
  /** OSRM [lon, lat][] */
  route: Coord[];
  routeDistanceM: number;
  /** 0..1 доля длины дороги (как GazTrail) */
  routeProgress: number;
  phase: TripPhase;
  cargo: number;
  loop: number;
  /** км/ч по дороге при 1× — GazTrail ~45–50, LogHub demo 420 */
  speedKmh: number;
  phaseElapsedMs: number;
}

export interface SimStation {
  detail: StationDetail;
  /** накопление продаж до одной «заправки» клиента */
  saleAcc: number;
  /** демо: каждая N-я заправка на этой ТРК уходит без чека */
  unfiscal?: { pump: number; every: number };
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
  supplies: LpgSupply[];
  batch: SimBatch;
  events: DiscrepancyEvent[];
  clockLabel: string;
  stats: {
    delivered_liters_day: number;
    delivery_trips_day: number;
  };
}

export const IDS = {
  factory: "f1111111-1111-1111-1111-111111111101",
  stationN: "a1111111-1111-1111-1111-111111111101",
  stationS: "a1111111-1111-1111-1111-111111111102",
  stationZhanaozen: "a1111111-1111-1111-1111-111111111103",
  stationKuryk: "a1111111-1111-1111-1111-111111111104",
  stationFort: "a1111111-1111-1111-1111-111111111105",
  stationAktau28: "a1111111-1111-1111-1111-111111111106",
  stationShetpe: "a1111111-1111-1111-1111-111111111107",
  stationAktau33: "a1111111-1111-1111-1111-111111111108",
  stationAktauProm: "a1111111-1111-1111-1111-111111111109",
  stationZhanaozenRakhat: "a1111111-1111-1111-1111-111111111110",
  stationTenge: "a1111111-1111-1111-1111-111111111111",
  stationMunaily: "a1111111-1111-1111-1111-111111111112",
  stationBaskuduk: "a1111111-1111-1111-1111-111111111113",
  stationKyzyltobe: "a1111111-1111-1111-1111-111111111114",
  stationAkshukur: "a1111111-1111-1111-1111-111111111115",
  stationBeyneu: "a1111111-1111-1111-1111-111111111116",
  tankN: "b1111111-1111-1111-1111-111111111101",
  tankS: "b1111111-1111-1111-1111-111111111102",
  truckA: "c1111111-1111-1111-1111-111111111101",
  truckB: "c1111111-1111-1111-1111-111111111102",
  batch: "e1111111-1111-1111-1111-111111111101",
  supplyDemo: "SUP-2026-0040",
} as const;

/** Розничная цена LPG, ₸/л */
export const PRICE_KZT = 115;

function stationDetail(partial: StationDetail): SimStation {
  return { detail: partial, saleAcc: 0 };
}

/** Живая АГЗС с датчиком. Остатки приходят с прибора, не из симуляции. */
export function createSeed(baseMs = Date.now()): SimState {
  const station = stationDetail({
    id: IDS.stationN,
    code: "AGZS-AKT-12",
    name: "АГЗС Актау · 12 мкр",
    address: "г. Актау, 12 микрорайон",
    lat: 43.6479,
    lon: 51.248,
    is_active: true,
    tanks: [],
    opening_remainder_liters: 0,
    remainder_liters: null,
    capacity_liters: 0,
    receipts_day_liters: 0,
    consumption_day_liters: 0,
    consumption_week_liters: 0,
    consumption_month_liters: 0,
    sales_day_count: 0,
    delivery_count_day: 0,
    avg_fill_liters: 0,
    recent_fills: [],
    recent_deliveries: [],
    active_trucks: [],
    balance_status: "unknown",
    calculated_vs_actual_delta: null,
    price_kzt_per_liter: PRICE_KZT,
    pumps: [],
  });

  return {
    simTimeMs: baseMs,
    factories: [],
    trucks: [],
    stations: [station],
    supplies: [],
    batch: {
      id: IDS.batch,
      trail_code: "",
      status: "idle",
      volume_liters: 0,
      events: [],
    },
    events: [],
    clockLabel: new Date(baseMs).toISOString(),
    stats: {
      delivered_liters_day: 0,
      delivery_trips_day: 0,
    },
  };
}
