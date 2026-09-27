import type { BatchTrailEvent, DiscrepancyEvent, StationDetail, TruckDetail } from "../types";
import { along, type Coord } from "./geo";
import { ROUTE_A, ROUTE_B, ROUTE_A_M, ROUTE_B_M } from "./routes";

export type { Coord };
export { ROUTE_A, ROUTE_B };

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
  tankN: "b1111111-1111-1111-1111-111111111101",
  tankS: "b1111111-1111-1111-1111-111111111102",
  truckA: "c1111111-1111-1111-1111-111111111101",
  truckB: "c1111111-1111-1111-1111-111111111102",
  batch: "e1111111-1111-1111-1111-111111111101",
} as const;

function iso(ms: number) {
  return new Date(ms).toISOString();
}

function stationDetail(partial: StationDetail, saleAcc = 0): SimStation {
  return { detail: partial, saleAcc };
}

function baseStation(
  id: string,
  code: string,
  name: string,
  address: string,
  lat: number,
  lon: number,
  remainder: number,
  capacity: number,
  consumption: { day: number; week: number; month: number },
  sales: number,
  deliveries: number,
  deliveryLiters: number,
  fills: { liters: number; atOffsetMs: number }[],
  recentDeliveries: { plate: string; liters: number; atOffsetMs: number }[],
  tanks: StationDetail["tanks"],
  baseMs: number,
  /** искусственный дисбаланс: недостача (+) в колонках vs хранилище */
  leakLiters = 0
): SimStation {
  const avg =
    fills.length > 0
      ? Math.round(fills.reduce((s, f) => s + f.liters, 0) / fills.length)
      : 28;
  // opening + delivered − pumps = book; actual = remainder (с учётом leak)
  const opening = Math.max(0, Math.round(remainder - deliveryLiters + consumption.day + leakLiters));
  const actual = remainder;
  const book = opening + deliveryLiters - consumption.day;
  const delta = actual - book;
  const abs = Math.abs(delta);
  const balance_status =
    abs < 40 ? "ok" : abs < 120 ? "measurement_error" : delta < 0 ? "shortage" : "surplus";

  const tanksSynced =
    tanks.length > 0
      ? tanks.map((t) => ({
          ...t,
          actual_remainder_liters: actual,
          calculated_remainder_liters: book,
        }))
      : tanks;

  return stationDetail({
    id,
    code,
    name,
    address,
    lat,
    lon,
    is_active: true,
    tanks: tanksSynced,
    opening_remainder_liters: opening,
    remainder_liters: actual,
    capacity_liters: capacity,
    receipts_day_liters: deliveryLiters,
    consumption_day_liters: consumption.day,
    consumption_week_liters: consumption.week,
    consumption_month_liters: consumption.month,
    sales_day_count: sales,
    delivery_count_day: deliveries,
    avg_fill_liters: avg,
    recent_fills: fills.map((f) => ({
      liters: f.liters,
      occurred_at: iso(baseMs - f.atOffsetMs),
    })),
    recent_deliveries: recentDeliveries.map((d) => ({
      plate: d.plate,
      liters: d.liters,
      occurred_at: iso(baseMs - d.atOffsetMs),
    })),
    active_trucks: [],
    balance_status,
    calculated_vs_actual_delta: Math.round(delta * 10) / 10,
  });
}

function pos(route: Coord[], t: number) {
  const [lon, lat] = along(route, t);
  return { lon, lat };
}

export function createSeed(baseMs = Date.UTC(2026, 8, 26, 8, 0, 0)): SimState {
  const factory: SimFactory = {
    id: IDS.factory,
    name: "КазГаз",
    lat: 43.3685,
    lon: 52.793,
  };

  const aProg = 0.12;
  const a0 = pos(ROUTE_A, aProg);
  const truckA: SimTruck = {
    phase: "in_transit",
    cargo: 16500,
    loop: 0,
    route: ROUTE_A,
    routeDistanceM: ROUTE_A_M,
    routeProgress: aProg,
    speedKmh: 120,
    phaseElapsedMs: 0,
    detail: {
      id: IDS.truckA,
      plate_number: "705 ABA 12",
      capacity_liters: 18000,
      carrier_name: "ГазТранс Мангыстау",
      status: "in_transit",
      lat: a0.lat,
      lon: a0.lon,
      recorded_at: iso(baseMs),
      supplier_name: "ТОО КазГаз",
      origin_name: "КазГаз",
      destination_name: "АГЗС Актау · 12 мкр",
      cargo_volume_liters: 16500,
      departed_at: iso(baseMs - 600_000),
      arrived_at: null,
      trip_status: "in_transit",
      recent_positions: [],
    },
  };

  const bProg = 0.35;
  const bPos = pos(ROUTE_B, bProg);
  const truckB: SimTruck = {
    phase: "in_transit",
    cargo: 12000,
    loop: 0,
    route: ROUTE_B,
    routeDistanceM: ROUTE_B_M,
    routeProgress: bProg,
    speedKmh: 110,
    phaseElapsedMs: 0,
    detail: {
      id: IDS.truckB,
      plate_number: "701 ABA 12",
      capacity_liters: 20000,
      carrier_name: "ЛПГ Мангыстау",
      status: "in_transit",
      lat: bPos.lat,
      lon: bPos.lon,
      recorded_at: iso(baseMs),
      supplier_name: "ТОО КазГаз",
      origin_name: "КазГаз",
      destination_name: "АГЗС Жетыбай",
      cargo_volume_liters: 12000,
      departed_at: iso(baseMs - 3_600_000),
      arrived_at: null,
      trip_status: "in_transit",
      recent_positions: [],
    },
  };

  const stations: SimStation[] = [
    baseStation(
      IDS.stationN,
      "AGZS-AKT-12",
      "АГЗС Актау · 12 мкр",
      "Актау, 12 микрорайон",
      43.6479,
      51.248,
      8200,
      25000,
      { day: 420, week: 18200, month: 74000 },
      18,
      1,
      6000,
      [
        { liters: 32, atOffsetMs: 120_000 },
        { liters: 28, atOffsetMs: 480_000 },
        { liters: 40, atOffsetMs: 900_000 },
        { liters: 25, atOffsetMs: 1_400_000 },
      ],
      [{ plate: "705 ABA 12", liters: 6000, atOffsetMs: 8_400_000 }],
      [
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
      baseMs,
      220
    ),
    baseStation(
      IDS.stationS,
      "AGZS-ZHB-01",
      "АГЗС Жетыбай",
      "Жетыбай, Мангистауская обл.",
      43.592,
      52.078,
      6200,
      20000,
      { day: 310, week: 15100, month: 62000 },
      12,
      1,
      4000,
      [
        { liters: 30, atOffsetMs: 200_000 },
        { liters: 22, atOffsetMs: 700_000 },
        { liters: 35, atOffsetMs: 1_100_000 },
      ],
      [{ plate: "701 ABA 12", liters: 4000, atOffsetMs: 10_800_000 }],
      [
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
      baseMs
    ),
    baseStation(
      IDS.stationZhanaozen,
      "AGZS-ZHO-01",
      "АГЗС Жанаозен · центр",
      "Жанаозен",
      43.3427,
      52.8431,
      6400,
      18000,
      { day: 280, week: 9800, month: 41000 },
      9,
      0,
      0,
      [
        { liters: 27, atOffsetMs: 300_000 },
        { liters: 33, atOffsetMs: 800_000 },
      ],
      [],
      [],
      baseMs
    ),
    baseStation(
      IDS.stationKuryk,
      "AGZS-KUR-01",
      "АГЗС Курык",
      "Курык",
      43.1862,
      51.6966,
      5100,
      15000,
      { day: 190, week: 7200, month: 29000 },
      6,
      0,
      0,
      [{ liters: 24, atOffsetMs: 400_000 }],
      [],
      [],
      baseMs
    ),
    baseStation(
      IDS.stationFort,
      "AGZS-FSH-01",
      "АГЗС Форт-Шевченко",
      "Форт-Шевченко",
      44.5244,
      50.3254,
      8700,
      22000,
      { day: 240, week: 11000, month: 45000 },
      8,
      0,
      0,
      [
        { liters: 29, atOffsetMs: 250_000 },
        { liters: 31, atOffsetMs: 950_000 },
      ],
      [],
      [],
      baseMs
    ),
    baseStation(
      IDS.stationAktau28,
      "AGZS-AKT-28",
      "АГЗС Актау · 28 мкр",
      "Актау, 28 микрорайон",
      43.662,
      51.205,
      7200,
      20000,
      { day: 350, week: 14000, month: 56000 },
      14,
      0,
      0,
      [
        { liters: 36, atOffsetMs: 180_000 },
        { liters: 28, atOffsetMs: 620_000 },
        { liters: 30, atOffsetMs: 1_200_000 },
      ],
      [],
      [],
      baseMs
    ),
    baseStation(
      IDS.stationShetpe,
      "AGZS-SHP-01",
      "АГЗС Шетпе",
      "Шетпе",
      44.1385,
      52.164,
      4300,
      12000,
      { day: 160, week: 6100, month: 24000 },
      5,
      0,
      0,
      [{ liters: 26, atOffsetMs: 500_000 }],
      [],
      [],
      baseMs
    ),
  ];

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
        description: "ТОО КазГаз",
        volume_liters: 16500,
      },
      {
        id: "ev-seed-factory",
        node_type: "factory",
        occurred_at: iso(baseMs - 3_600_000),
        title: "Отгрузка с завода",
        description: "КазГаз · Жанаозен",
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
    stations,
    batch,
    events: [],
    clockLabel: iso(baseMs),
    stats: {
      delivered_liters_day: 10000,
      delivery_trips_day: 2,
    },
  };
}
