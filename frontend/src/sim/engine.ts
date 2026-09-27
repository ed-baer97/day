/**
 * Движение газовозов — копия рабочей схемы GazTrail (pitch) + LogHub:
 * 1) погрузка  2) полный OSRM-маршрут на карте  3) along(progress) по длине линии
 */
import type {
  BatchTrailEvent,
  FiscalCheck,
  FiscalStatus,
  PumpFiscalCheck,
  MapOverview,
  MapPoint,
  StationBalance,
  StationDetail,
} from "../types";
import { along, alongPrefix, type Coord } from "./geo";
import { createSeed, IDS, type SimState, type SimTruck, type TripPhase } from "./seed";

const DWELL_MS: Record<Exclude<TripPhase, "in_transit">, number> = {
  loading: 4_000,
  routing: 2_500,
  arrived: 2_000,
  unloading: 8_000,
  idle: 10_000,
};

function hasEvent(events: BatchTrailEvent[], id: string) {
  return events.some((e) => e.id === id);
}

function pushTrail(state: SimState, ev: BatchTrailEvent) {
  if (hasEvent(state.batch.events, ev.id)) return;
  state.batch.events = [...state.batch.events, ev];
}

function stationN(state: SimState) {
  return state.stations.find((s) => s.detail.id === IDS.stationN)!;
}

function stationS(state: SimState) {
  return state.stations.find((s) => s.detail.id === IDS.stationS)!;
}

/** opening + доставлено − колонки = книга; факт − книга = Δ */
export function stationBalance(d: StationDetail): StationBalance {
  const delivered = d.receipts_day_liters;
  const through_pumps = d.consumption_day_liters;
  const opening = d.opening_remainder_liters;
  const storage_actual =
    d.tanks[0]?.actual_remainder_liters ?? d.remainder_liters ?? 0;
  const book_remainder = opening + delivered - through_pumps;
  const delta = Math.round((storage_actual - book_remainder) * 10) / 10;
  const abs = Math.abs(delta);
  const status: StationBalance["status"] =
    abs < 40 ? "ok" : abs < 120 ? "warn" : delta < 0 ? "shortage" : "surplus";
  return {
    delivered,
    storage_actual,
    through_pumps,
    opening,
    book_remainder,
    delta,
    status,
  };
}

/** Допуск на округление, л */
const FISCAL_TOLERANCE_L = 1;

/** Счётчик ТРК → чек на ККМ → ОФД → КГД */
export function fiscalCheck(d: StationDetail): FiscalCheck {
  const pumps: PumpFiscalCheck[] = d.pumps.map((p) => {
    const noReceipt = Math.round(p.counter_liters - p.pouring_liters - p.kkm_liters);
    const unreceipted = noReceipt >= FISCAL_TOLERANCE_L ? noReceipt : 0;
    const unsent = Math.round(p.kkm_liters - p.ofd_liters);
    const unsentReceipts = p.kkm_receipts - p.ofd_receipts;
    const status: FiscalStatus = unreceipted
      ? "no_receipt"
      : unsentReceipts > 0
        ? "not_sent"
        : "ok";
    return {
      ...p,
      unreceipted_liters: unreceipted,
      unsent_liters: unsentReceipts > 0 ? unsent : 0,
      unsent_receipts: Math.max(0, unsentReceipts),
      status,
    };
  });
  const sum = (f: (p: PumpFiscalCheck) => number) => pumps.reduce((s, p) => s + f(p), 0);
  const unreceipted = sum((p) => p.unreceipted_liters);
  const unsent = sum((p) => p.unsent_liters);
  const gap = unreceipted + unsent;
  return {
    counter_liters: sum((p) => p.counter_liters),
    fills: sum((p) => p.fills),
    kkm_liters: sum((p) => p.kkm_liters),
    kkm_receipts: sum((p) => p.kkm_receipts),
    ofd_liters: sum((p) => p.ofd_liters),
    ofd_receipts: sum((p) => p.ofd_receipts),
    ofd_amount_kzt: Math.round(sum((p) => p.ofd_liters) * d.price_kzt_per_liter),
    unreceipted_liters: unreceipted,
    unsent_liters: unsent,
    gap_liters: gap,
    gap_kzt: Math.round(gap * d.price_kzt_per_liter),
    status: unreceipted ? "no_receipt" : unsent ? "not_sent" : "ok",
    pumps,
  };
}

/** Суточный профиль спроса на колонках, по часам 0..23 */
const HOUR_WEIGHTS = [
  0.2, 0.1, 0.1, 0.1, 0.2, 0.5, 1.2, 1.8, 1.6, 1.3, 1.1, 1.2,
  1.4, 1.3, 1.2, 1.3, 1.6, 1.9, 1.7, 1.3, 1.0, 0.8, 0.5, 0.3,
];

export type StationHour = {
  hour: number;
  pumps: number;
  fills: number;
  delivered: number;
  book: number;
  actual: number;
};

/** Раскладка суточных итогов АГЗС по часам до текущего часа симуляции. */
export function stationHourly(d: StationDetail, nowMs: number): StationHour[] {
  const now = new Date(nowMs);
  const curH = now.getHours();
  const weights = HOUR_WEIGHTS.slice(0, curH + 1);
  const wSum = weights.reduce((s, w) => s + w, 0) || 1;

  const delivered = new Array<number>(curH + 1).fill(0);
  let placed = 0;
  for (const dl of d.recent_deliveries) {
    const t = new Date(dl.occurred_at);
    if (t.toDateString() !== now.toDateString()) continue;
    const h = Math.min(curH, t.getHours());
    delivered[h] += dl.liters;
    placed += dl.liters;
  }
  const rest = d.receipts_day_liters - placed;
  if (rest > 1) delivered[Math.max(0, curH - 1)] += rest;

  const bal = stationBalance(d);
  const out: StationHour[] = [];
  let book = bal.opening;
  for (let h = 0; h <= curH; h++) {
    const pumps = (d.consumption_day_liters * weights[h]) / wSum;
    book += delivered[h] - pumps;
    out.push({
      hour: h,
      pumps,
      fills: Math.round(pumps / Math.max(1, d.avg_fill_liters)),
      delivered: delivered[h],
      book,
      actual: book + (bal.delta * (h + 1)) / (curH + 1),
    });
  }
  return out;
}

function syncStationDerived(st: SimState) {
  for (const s of st.stations) {
    const bal = stationBalance(s.detail);
    const tank = s.detail.tanks[0];
    if (tank) {
      tank.calculated_remainder_liters = bal.book_remainder;
      s.detail.remainder_liters = tank.actual_remainder_liters ?? bal.storage_actual;
      s.detail.tanks = [{ ...tank }];
    } else {
      s.detail.remainder_liters = bal.storage_actual;
    }
    s.detail.calculated_vs_actual_delta = bal.delta;
    s.detail.balance_status =
      bal.status === "ok"
        ? "ok"
        : bal.status === "warn"
          ? "measurement_error"
          : bal.status;
  }
}

function setPhase(truck: SimTruck, phase: TripPhase) {
  truck.phase = phase;
  truck.phaseElapsedMs = 0;
}

function recordDelivery(
  state: SimState,
  station: ReturnType<typeof stationN>,
  truck: SimTruck,
  liters: number,
  now: string
) {
  const vol = Math.round(liters);
  if (vol <= 0) return;
  station.detail.delivery_count_day += 1;
  station.detail.receipts_day_liters += vol;
  station.detail.recent_deliveries = [
    { plate: truck.detail.plate_number, liters: vol, occurred_at: now },
    ...station.detail.recent_deliveries,
  ].slice(0, 8);
  state.stats.delivery_trips_day += 1;
  state.stats.delivered_liters_day += vol;
}

function recordSaleDrip(
  station: ReturnType<typeof stationN>,
  liters: number,
  now: string,
  fillSize = 28
) {
  if (liters <= 0) return;
  const d = station.detail;
  d.consumption_day_liters += liters;
  station.saleAcc += liters;
  const pumpAt = () => d.pumps[d.sales_day_count % Math.max(1, d.pumps.length)];
  const pouring = pumpAt();
  if (pouring) {
    pouring.counter_liters += liters;
    pouring.pouring_liters += liters;
  }
  while (station.saleAcc >= fillSize) {
    station.saleAcc -= fillSize;
    const pump = pumpAt();
    if (pump) {
      // сверх объёма заправки — это уже следующий клиент на следующей ТРК
      const carry = Math.max(0, pump.pouring_liters - fillSize);
      pump.pouring_liters = 0;
      pump.counter_liters -= carry;
      const next = d.pumps[(d.sales_day_count + 1) % d.pumps.length];
      next.counter_liters += carry;
      next.pouring_liters += carry;
      pump.fills += 1;
      const idx = d.pumps.indexOf(pump);
      const skip =
        station.unfiscal?.pump === idx && pump.fills % station.unfiscal.every === 0;
      if (!skip) {
        pump.kkm_liters += fillSize;
        pump.kkm_receipts += 1;
        pump.kkm_amount_kzt += Math.round(fillSize * d.price_kzt_per_liter);
        if (pump.kkm_online) {
          pump.ofd_liters += fillSize;
          pump.ofd_receipts += 1;
          pump.ofd_last_at = now;
        }
      }
    }
    station.detail.sales_day_count += 1;
    station.detail.recent_fills = [
      { liters: fillSize, occurred_at: now },
      ...station.detail.recent_fills,
    ].slice(0, 10);
    const fills = station.detail.recent_fills;
    station.detail.avg_fill_liters = Math.round(
      fills.reduce((s, f) => s + f.liters, 0) / fills.length
    );
  }
}

function applyUnload(
  state: SimState,
  station: ReturnType<typeof stationN>,
  truck: SimTruck,
  simDtMs: number,
  fullCargo: number,
  now: string
) {
  const rate = fullCargo / DWELL_MS.unloading;
  let take = Math.min(truck.cargo, rate * simDtMs);
  if (truck.phaseElapsedMs >= DWELL_MS.unloading) {
    take = truck.cargo;
  }
  if (take > 0) {
    truck.cargo -= take;
    const tank = station.detail.tanks[0];
    if (tank) {
      tank.calculated_remainder_liters = (tank.calculated_remainder_liters ?? 0) + take;
      tank.actual_remainder_liters = (tank.actual_remainder_liters ?? 0) + take;
      tank.last_measured_at = now;
    } else {
      station.detail.remainder_liters = (station.detail.remainder_liters ?? 0) + take;
    }
    station.detail.active_trucks = [{ plate: truck.detail.plate_number, status: "unloading" }];
  }
  if (truck.phaseElapsedMs >= DWELL_MS.unloading) {
    truck.cargo = 0;
    station.detail.active_trucks = [];
    recordDelivery(state, station, truck, fullCargo, now);
    setPhase(truck, "idle");
  }
}

function applyLngLat(truck: SimTruck, lon: number, lat: number, now: string, phase: TripPhase) {
  truck.detail = {
    ...truck.detail,
    lon,
    lat,
    status: phase,
    trip_status: phase,
    cargo_volume_liters: truck.cargo,
    recorded_at: now,
    recent_positions: [
      ...(truck.detail.recent_positions ?? []).slice(-30),
      { lat, lon, recorded_at: now },
    ],
  };
}

function snapToRoute(truck: SimTruck, now: string) {
  const [lon, lat] = along(truck.route, truck.routeProgress);
  applyLngLat(truck, lon, lat, now, truck.phase);
}

/** GazTrail: dProg = (speedKmh * 1000 * dtH) / distanceM */
function driveAlongRoad(truck: SimTruck, simDtMs: number): boolean {
  const dtH = simDtMs / 3_600_000;
  const distM = truck.routeDistanceM || 1;
  const dProg = (truck.speedKmh * 1000 * dtH) / distM;
  truck.routeProgress = Math.min(1, truck.routeProgress + dProg);
  return truck.routeProgress >= 0.995;
}

function updateTruckA(state: SimState, truck: SimTruck, simDtMs: number) {
  const now = new Date(state.simTimeMs).toISOString();
  const loop = truck.loop;
  const north = stationN(state);
  truck.phaseElapsedMs += simDtMs;

  if (truck.phase === "loading") {
    truck.routeProgress = 0;
    snapToRoute(truck, now);
    state.batch.status = "formed";
    if (truck.phaseElapsedMs >= DWELL_MS.loading) {
      setPhase(truck, "routing");
      state.batch.status = "routed";
      pushTrail(state, {
        id: `ev-${loop}-route-built`,
        node_type: "route",
        occurred_at: now,
        title: "Маршрут построен",
        description: `${truck.detail.origin_name} → ${truck.detail.destination_name}`,
        volume_liters: truck.cargo,
      });
    }
    return;
  }

  if (truck.phase === "routing") {
    truck.routeProgress = 0;
    snapToRoute(truck, now);
    if (truck.phaseElapsedMs >= DWELL_MS.routing) {
      setPhase(truck, "in_transit");
      truck.detail.departed_at = now;
      truck.detail.arrived_at = null;
      state.batch.status = "in_transit";
      pushTrail(state, {
        id: `ev-${loop}-truck`,
        node_type: "truck",
        occurred_at: now,
        title: "Газовоз выехал",
        description: truck.detail.plate_number,
        volume_liters: truck.cargo,
      });
    }
    return;
  }

  if (truck.phase === "in_transit") {
    const done = driveAlongRoad(truck, simDtMs);
    snapToRoute(truck, now);
    const bucket = Math.floor(truck.routeProgress * 8);
    pushTrail(state, {
      id: `ev-${loop}-gps-${bucket}`,
      node_type: "route",
      occurred_at: now,
      title: "В пути",
      description: `GPS ${truck.detail.lat!.toFixed(4)}, ${truck.detail.lon!.toFixed(4)}`,
      volume_liters: truck.cargo,
    });
    if (done) {
      truck.routeProgress = 1;
      snapToRoute(truck, now);
      setPhase(truck, "arrived");
      truck.detail.arrived_at = now;
      state.batch.status = "delivered";
      pushTrail(state, {
        id: `ev-${loop}-station`,
        node_type: "station",
        occurred_at: now,
        title: "Прибытие на АГЗС",
        description: "АГЗС Актау · 12 мкр",
        volume_liters: truck.cargo,
      });
    }
    return;
  }

  if (truck.phase === "arrived") {
    truck.routeProgress = 1;
    snapToRoute(truck, now);
    if (truck.phaseElapsedMs >= DWELL_MS.arrived) setPhase(truck, "unloading");
    return;
  }

  if (truck.phase === "unloading") {
    truck.routeProgress = 1;
    snapToRoute(truck, now);
    applyUnload(state, north, truck, simDtMs, 16500, now);
    return;
  }

  // idle
  truck.routeProgress = 1;
  snapToRoute(truck, now);
  const tank = north.detail.tanks[0];
  const saleStep = 0.01 * simDtMs;
  if ((tank.calculated_remainder_liters ?? 0) > 500) {
    tank.calculated_remainder_liters! -= saleStep;
    tank.actual_remainder_liters = (tank.actual_remainder_liters ?? 0) - saleStep * 0.97;
    recordSaleDrip(north, saleStep, now, 30);
  }

  if (
    truck.phaseElapsedMs > DWELL_MS.idle * 0.5 &&
    truck.phaseElapsedMs - simDtMs <= DWELL_MS.idle * 0.5 &&
    !state.events.some((e) => e.id === `disc-${loop}-shortage`)
  ) {
    const leak = 180 + Math.random() * 80;
    tank.actual_remainder_liters = Math.max(0, (tank.actual_remainder_liters ?? 0) - leak);
    const delta = (tank.actual_remainder_liters ?? 0) - (tank.calculated_remainder_liters ?? 0);
    state.events = [
      {
        id: `disc-${loop}-shortage`,
        station_id: IDS.stationN,
        event_type: "shortage",
        severity: "critical",
        delta_liters: Math.round(delta),
        title: "Недостача",
        description: `Факт ниже расчёта на ${Math.abs(Math.round(delta))} л`,
        is_resolved: false,
        detected_at: now,
      },
      ...state.events,
    ].slice(0, 12);
  }

  if (truck.phaseElapsedMs >= DWELL_MS.idle) {
    truck.loop += 1;
    truck.cargo = 16500;
    truck.routeProgress = 0;
    const code = `LPG-2026-${String(41 + truck.loop).padStart(5, "0")}`;
    state.batch = {
      id: IDS.batch,
      trail_code: code,
      status: "formed",
      volume_liters: 16500,
      events: [
        {
          id: `ev-${truck.loop}-supplier`,
          node_type: "supplier",
          occurred_at: now,
          title: "Поставщик подтвердил партию",
          description: "ТОО КазГаз",
          volume_liters: 16500,
        },
        {
          id: `ev-${truck.loop}-factory`,
          node_type: "factory",
          occurred_at: now,
          title: "Отгрузка с завода",
          description: "КазГаз · Жанаозен",
          volume_liters: 16500,
        },
        {
          id: `ev-${truck.loop}-batch`,
          node_type: "batch",
          occurred_at: now,
          title: "Партия сформирована",
          description: code,
          volume_liters: 16500,
        },
      ],
    };
    setPhase(truck, "loading");
    snapToRoute(truck, now);
  }
}

function updateTruckB(state: SimState, truck: SimTruck, simDtMs: number) {
  const now = new Date(state.simTimeMs).toISOString();
  truck.phaseElapsedMs += simDtMs;
  const south = stationS(state);

  if (truck.phase === "loading" || truck.phase === "routing") {
    truck.routeProgress = 0;
    snapToRoute(truck, now);
    const dwell = truck.phase === "loading" ? DWELL_MS.loading : DWELL_MS.routing;
    if (truck.phaseElapsedMs >= dwell) {
      if (truck.phase === "loading") {
        setPhase(truck, "routing");
      } else {
        setPhase(truck, "in_transit");
        truck.detail.departed_at = now;
      }
    }
    return;
  }

  if (truck.phase === "in_transit") {
    if (driveAlongRoad(truck, simDtMs)) {
      truck.routeProgress = 1;
      setPhase(truck, "arrived");
    }
    snapToRoute(truck, now);
    return;
  }

  if (truck.phase === "arrived") {
    truck.routeProgress = 1;
    snapToRoute(truck, now);
    if (truck.phaseElapsedMs >= DWELL_MS.arrived) setPhase(truck, "unloading");
    return;
  }

  if (truck.phase === "unloading") {
    truck.routeProgress = 1;
    snapToRoute(truck, now);
    applyUnload(state, south, truck, simDtMs, 12000, now);
    return;
  }

  // idle
  truck.routeProgress = 1;
  snapToRoute(truck, now);
  const tank = south.detail.tanks[0];
  if (tank && (tank.calculated_remainder_liters ?? 0) > 800) {
    const step = 0.006 * simDtMs;
    tank.calculated_remainder_liters! -= step;
    tank.actual_remainder_liters! -= step * 1.01;
    recordSaleDrip(south, step, now, 26);
  }

  if (truck.phaseElapsedMs >= DWELL_MS.idle) {
    truck.loop += 1;
    truck.cargo = 12000;
    truck.routeProgress = 0;
    truck.detail.cargo_volume_liters = 12000;
    setPhase(truck, "loading");
    snapToRoute(truck, now);
  }
}

export function tick(state: SimState, wallDtMs: number, speed: number): SimState {
  const next: SimState = structuredClone(state);
  const simDt = wallDtMs * speed;
  next.simTimeMs += simDt;
  next.clockLabel = new Date(next.simTimeMs).toISOString();

  for (const truck of next.trucks) {
    if (truck.detail.id === IDS.truckA) updateTruckA(next, truck, simDt);
    else updateTruckB(next, truck, simDt);
  }

  syncStationDerived(next);
  return next;
}

export function resetState(): SimState {
  return createSeed();
}

export function toMapOverview(state: SimState): MapOverview {
  const points: MapPoint[] = [
    ...state.factories.map((f) => ({
      id: f.id,
      kind: "factory" as const,
      name: f.name,
      lat: f.lat,
      lon: f.lon,
      status: "online",
    })),
    ...state.stations.map((s) => ({
      id: s.detail.id,
      kind: "station" as const,
      name: s.detail.name,
      lat: s.detail.lat,
      lon: s.detail.lon,
      status: s.detail.balance_status === "ok" ? "active" : s.detail.balance_status,
      meta: { code: s.detail.code, balance: s.detail.balance_status },
    })),
    ...state.trucks.map((t) => {
      // всегда с линии маршрута — совпадает с концом traveled
      const [lon, lat] = along(t.route, t.routeProgress);
      return {
        id: t.detail.id,
        kind: "truck" as const,
        name: t.detail.plate_number,
        lat,
        lon,
        status: t.phase,
        meta: { destination: t.detail.destination_name },
      };
    }),
  ];

  for (const ev of state.events.filter((e) => !e.is_resolved).slice(0, 2)) {
    const st = state.stations.find((s) => s.detail.id === ev.station_id);
    if (!st) continue;
    points.push({
      id: `alert-${ev.id}`,
      kind: "station",
      name: `⚠ ${ev.title}`,
      lat: st.detail.lat + 0.012,
      lon: st.detail.lon + 0.012,
      status: "alert",
      meta: { event_type: ev.event_type },
    });
  }

  return {
    generated_at: state.clockLabel,
    points,
    active_trips: state.trucks.filter((t) => t.phase === "in_transit" || t.phase === "routing").length,
    open_events: state.events.filter((e) => !e.is_resolved).length,
  };
}

export type MapRouteLayer = {
  id: string;
  planned: Coord[];
  traveled: Coord[];
};

/** Полный маршрут + пройденный хвост. Если focusId — только этот газовоз. */
export function mapRoutes(state: SimState, focusId?: string | null): MapRouteLayer[] {
  return state.trucks
    .filter((t) => t.phase !== "loading")
    .filter((t) => !focusId || t.detail.id === focusId)
    .map((t) => ({
      id: t.detail.id,
      planned: t.route,
      traveled:
        t.phase === "routing"
          ? []
          : alongPrefix(t.route, t.phase === "in_transit" ? t.routeProgress : 1),
    }));
}

export function fleetStats(state: SimState) {
  const sold = state.stations.reduce((s, st) => s + st.detail.consumption_day_liters, 0);
  const fills = state.stations.reduce((s, st) => s + st.detail.sales_day_count, 0);
  const fiscal = state.stations.map((s) => fiscalCheck(s.detail));
  return {
    unreceipted_liters: fiscal.reduce((s, f) => s + f.unreceipted_liters, 0),
    unsent_liters: fiscal.reduce((s, f) => s + f.unsent_liters, 0),
    gap_liters: fiscal.reduce((s, f) => s + f.gap_liters, 0),
    gap_kzt: fiscal.reduce((s, f) => s + f.gap_kzt, 0),
    fiscal_mismatch_stations: fiscal.filter((f) => f.status !== "ok").length,
    kkm_offline: state.stations.reduce(
      (s, st) => s + st.detail.pumps.filter((p) => !p.kkm_online).length,
      0
    ),
    delivered_liters_day: Math.round(state.stats.delivered_liters_day),
    delivery_trips_day: state.stats.delivery_trips_day,
    sold_liters_day: Math.round(sold),
    fills_day: fills,
    trucks_in_transit: state.trucks.filter(
      (t) => t.phase === "in_transit" || t.phase === "routing" || t.phase === "unloading"
    ).length,
    stations_active: state.stations.filter((s) => s.detail.is_active).length,
  };
}

export function primaryRoute(state: SimState): { lon: number; lat: number }[] {
  const layer = mapRoutes(state).find((l) => l.id === IDS.truckA) ?? mapRoutes(state)[0];
  if (!layer) return [];
  return layer.planned.map(([lon, lat]) => ({ lon, lat }));
}
