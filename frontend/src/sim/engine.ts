import type { BatchTrailEvent, DiscrepancyEvent, MapOverview, MapPoint } from "../types";
import { createSeed, IDS, type RoutePoint, type SimState, type SimTruck, type TripPhase } from "./seed";

const PHASE_ENDS = {
  loading: 0.08,
  in_transit: 0.62,
  arrived: 0.7,
  unloading: 0.82,
  // remainder: idle / dispense at station while truck waits, then loop
} as const;

/** Wall-clock ms per full truck-A cycle at 1x */
export const CYCLE_MS_1X = 90_000;

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

export function pointOnRoute(route: RoutePoint[], t: number): RoutePoint {
  if (route.length === 0) return { lon: 0, lat: 0 };
  if (route.length === 1) return route[0];
  const clamped = Math.min(1, Math.max(0, t));
  const seg = clamped * (route.length - 1);
  const i = Math.min(route.length - 2, Math.floor(seg));
  const local = seg - i;
  return {
    lon: lerp(route[i].lon, route[i + 1].lon, local),
    lat: lerp(route[i].lat, route[i + 1].lat, local),
  };
}

function phaseFor(progress: number): TripPhase {
  if (progress < PHASE_ENDS.loading) return "loading";
  if (progress < PHASE_ENDS.in_transit) return "in_transit";
  if (progress < PHASE_ENDS.arrived) return "arrived";
  if (progress < PHASE_ENDS.unloading) return "unloading";
  return "idle";
}

function transitT(progress: number): number {
  const a = PHASE_ENDS.loading;
  const b = PHASE_ENDS.in_transit;
  if (progress <= a) return 0;
  if (progress >= b) return 1;
  return (progress - a) / (b - a);
}

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

function syncStationDerived(st: SimState) {
  for (const s of st.stations) {
    const tank = s.detail.tanks[0];
    if (!tank) continue;
    const actual = tank.actual_remainder_liters ?? 0;
    const calc = tank.calculated_remainder_liters ?? 0;
    const delta = actual - calc;
    s.detail.remainder_liters = actual;
    s.detail.calculated_vs_actual_delta = Math.round(delta * 10) / 10;
    const abs = Math.abs(delta);
    s.detail.balance_status = abs < 40 ? "ok" : abs < 120 ? "measurement_error" : delta < 0 ? "shortage" : "surplus";
    s.detail.tanks = [{ ...tank }];
  }
}

function updateTruckA(state: SimState, truck: SimTruck, dtProgress: number) {
  const prev = truck.progress;
  let next = prev + dtProgress;
  let looped = false;
  if (next >= 1) {
    next = next - Math.floor(next);
    truck.loop += 1;
    looped = true;
    // new batch cycle
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
          occurred_at: new Date(state.simTimeMs).toISOString(),
          title: "Поставщик подтвердил партию",
          description: "ООО ГазСнаб",
          volume_liters: 16500,
        },
        {
          id: `ev-${truck.loop}-factory`,
          node_type: "factory",
          occurred_at: new Date(state.simTimeMs).toISOString(),
          title: "Отгрузка с завода",
          description: "Завод Тольятти",
          volume_liters: 16500,
        },
        {
          id: `ev-${truck.loop}-batch`,
          node_type: "batch",
          occurred_at: new Date(state.simTimeMs).toISOString(),
          title: "Партия сформирована",
          description: code,
          volume_liters: 16500,
        },
      ],
    };
    truck.cargo = 16500;
  }

  const phase = phaseFor(next);
  const prevPhase = truck.phase;
  truck.progress = next;
  truck.phase = phase;

  const t = transitT(next);
  const pos = pointOnRoute(truck.route, t);
  truck.detail = {
    ...truck.detail,
    lat: pos.lat,
    lon: pos.lon,
    status: phase,
    trip_status: phase,
    cargo_volume_liters: truck.cargo,
    recorded_at: new Date(state.simTimeMs).toISOString(),
    recent_positions: [
      ...truck.detail.recent_positions!.slice(-20),
      { lat: pos.lat, lon: pos.lon, recorded_at: new Date(state.simTimeMs).toISOString() },
    ],
  };

  const loop = truck.loop;
  const now = new Date(state.simTimeMs).toISOString();

  if (phase === "loading" && (prevPhase !== "loading" || looped)) {
    state.batch.status = "formed";
  }

  if (phase === "in_transit" && prevPhase === "loading") {
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

  if (phase === "in_transit") {
    // periodic route breadcrumbs
    const bucket = Math.floor((t * 5));
    pushTrail(state, {
      id: `ev-${loop}-route-${bucket}`,
      node_type: "route",
      occurred_at: now,
      title: "В пути",
      description: `GPS ${pos.lat.toFixed(3)}, ${pos.lon.toFixed(3)}`,
      volume_liters: truck.cargo,
    });
  }

  if (phase === "arrived" && prevPhase === "in_transit") {
    truck.detail.arrived_at = now;
    state.batch.status = "delivered";
    pushTrail(state, {
      id: `ev-${loop}-station`,
      node_type: "station",
      occurred_at: now,
      title: "Прибытие на АГЗС",
      description: "АГЗС Север",
      volume_liters: truck.cargo,
    });
  }

  const north = stationN(state);
  if (phase === "unloading") {
    const unloadSpan = PHASE_ENDS.unloading - PHASE_ENDS.arrived;
    const local = (next - PHASE_ENDS.arrived) / unloadSpan;
    const prevLocal = Math.max(0, (prev - PHASE_ENDS.arrived) / unloadSpan);
    const deltaLocal = Math.max(0, local - prevLocal);
    const unloadVol = 16500 * deltaLocal;
    if (unloadVol > 0 && truck.cargo > 0) {
      const take = Math.min(truck.cargo, unloadVol);
      truck.cargo -= take;
      const tank = north.detail.tanks[0];
      tank.calculated_remainder_liters = (tank.calculated_remainder_liters ?? 0) + take;
      tank.actual_remainder_liters = (tank.actual_remainder_liters ?? 0) + take;
      tank.last_measured_at = now;
      north.detail.receipts_day_liters += take;
      north.detail.active_trucks = [{ plate: truck.detail.plate_number, status: "unloading" }];
      pushTrail(state, {
        id: `ev-${loop}-tank`,
        node_type: "tank",
        occurred_at: now,
        title: "Приёмка в резервуар R-1",
        description: `+${take.toFixed(0)} л`,
        volume_liters: take,
      });
    }
  }

  // Dispense / sales while idle at station (after unload) and lightly during late unload
  if (phase === "idle" || (phase === "unloading" && next > 0.78)) {
    const salesLiters = 18 * (dtProgress * (CYCLE_MS_1X / 1000)); // ~scaled
    const saleStep = Math.max(0.5, salesLiters);
    const tank = north.detail.tanks[0];
    const calc = tank.calculated_remainder_liters ?? 0;
    const act = tank.actual_remainder_liters ?? 0;
    if (calc > 500) {
      tank.calculated_remainder_liters = calc - saleStep;
      // actual drains a bit differently to allow discrepancy later
      tank.actual_remainder_liters = act - saleStep * 0.97;
      tank.last_measured_at = now;
      north.detail.consumption_day_liters += saleStep;
      north.detail.consumption_week_liters += saleStep;
      north.detail.consumption_month_liters += saleStep;
      north.detail.sales_day_count += Math.random() > 0.4 ? 1 : 0;
      pushTrail(state, {
        id: `ev-${loop}-dispense-${Math.floor(next * 40)}`,
        node_type: "dispense",
        occurred_at: now,
        title: "Отпуск ТРК (Topaz/ASKA)",
        description: `−${saleStep.toFixed(1)} л · read-only`,
        volume_liters: saleStep,
      });
      if (Math.random() > 0.55) {
        pushTrail(state, {
          id: `ev-${loop}-sale-${Math.floor(next * 40)}`,
          node_type: "sale",
          occurred_at: now,
          title: "Продажа",
          description: "Чек АГЗС",
          volume_liters: saleStep,
        });
      }
    }
    north.detail.active_trucks =
      phase === "idle" ? [] : [{ plate: truck.detail.plate_number, status: phase }];
  }

  // Inject shortage once per loop near end of idle
  if (phase === "idle" && prev < 0.9 && next >= 0.9) {
    const tank = north.detail.tanks[0];
    const leak = 180 + Math.random() * 80;
    tank.actual_remainder_liters = Math.max(0, (tank.actual_remainder_liters ?? 0) - leak);
    const delta = (tank.actual_remainder_liters ?? 0) - (tank.calculated_remainder_liters ?? 0);
    const ev: DiscrepancyEvent = {
      id: `disc-${loop}-shortage`,
      station_id: IDS.stationN,
      event_type: "shortage",
      severity: "critical",
      delta_liters: Math.round(delta),
      title: "Недостача",
      description: `Факт ниже расчёта на ${Math.abs(Math.round(delta))} л (симуляция)`,
      is_resolved: false,
      detected_at: now,
    };
    if (!state.events.some((e) => e.id === ev.id)) {
      state.events = [ev, ...state.events].slice(0, 12);
    }
  }

  // Occasional surplus on alternate loops
  if (phase === "idle" && truck.loop % 2 === 1 && prev < 0.95 && next >= 0.95) {
    const tank = north.detail.tanks[0];
    tank.actual_remainder_liters = (tank.actual_remainder_liters ?? 0) + 220;
    const delta = (tank.actual_remainder_liters ?? 0) - (tank.calculated_remainder_liters ?? 0);
    const ev: DiscrepancyEvent = {
      id: `disc-${loop}-surplus`,
      station_id: IDS.stationN,
      event_type: "surplus",
      severity: "warning",
      delta_liters: Math.round(delta),
      title: "Излишек",
      description: `Факт выше расчёта (возможна незарегистрированная приёмка)`,
      is_resolved: false,
      detected_at: now,
    };
    if (!state.events.some((e) => e.id === ev.id)) {
      state.events = [ev, ...state.events].slice(0, 12);
    }
  }

  if (phase !== "unloading" && phase !== "arrived") {
    // clear active truck if left
    if (phase === "loading" || phase === "in_transit") {
      north.detail.active_trucks = north.detail.active_trucks.filter(
        (t) => t.plate !== truck.detail.plate_number
      );
    }
  }
}

function updateTruckB(state: SimState, truck: SimTruck, dtProgress: number) {
  // slower shuttle loop between south and north
  let next = truck.progress + dtProgress * 1.4;
  if (next >= 1) next -= Math.floor(next);
  truck.progress = next;
  const phase = phaseFor(next);
  truck.phase = phase;
  const pos = pointOnRoute(truck.route, transitT(next));
  truck.detail = {
    ...truck.detail,
    lat: pos.lat,
    lon: pos.lon,
    status: phase === "idle" ? "arrived" : phase,
    trip_status: phase === "idle" ? "arrived" : phase,
    recorded_at: new Date(state.simTimeMs).toISOString(),
  };

  // light consumption at south station
  if (phase === "idle" || phase === "unloading") {
    const south = state.stations.find((s) => s.detail.id === IDS.stationS)!;
    const step = 6 * dtProgress * 10;
    const tank = south.detail.tanks[0];
    if ((tank.calculated_remainder_liters ?? 0) > 800) {
      tank.calculated_remainder_liters! -= step;
      tank.actual_remainder_liters! -= step * 1.01;
      south.detail.consumption_day_liters += step;
      south.detail.sales_day_count += Math.random() > 0.7 ? 1 : 0;
    }
  }
}

/** Advance simulation by wall-clock delta at given speed. Mutates a clone. */
export function tick(state: SimState, wallDtMs: number, speed: number): SimState {
  const next: SimState = structuredClone(state);
  const simDt = wallDtMs * speed;
  next.simTimeMs += simDt;
  next.clockLabel = new Date(next.simTimeMs).toISOString();

  const dtProgress = simDt / CYCLE_MS_1X;

  for (const truck of next.trucks) {
    if (truck.detail.id === IDS.truckA) updateTruckA(next, truck, dtProgress);
    else updateTruckB(next, truck, dtProgress);
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
    ...state.trucks.map((t) => ({
      id: t.detail.id,
      kind: "truck" as const,
      name: t.detail.plate_number,
      lat: t.detail.lat!,
      lon: t.detail.lon!,
      status: t.phase,
      meta: { destination: t.detail.destination_name },
    })),
  ];

  // surface open discrepancy as alert pseudo-point near station
  for (const ev of state.events.filter((e) => !e.is_resolved).slice(0, 2)) {
    const st = state.stations.find((s) => s.detail.id === ev.station_id);
    if (!st) continue;
    points.push({
      id: `alert-${ev.id}`,
      kind: "station",
      name: `⚠ ${ev.title}`,
      lat: st.detail.lat + 0.02,
      lon: st.detail.lon + 0.02,
      status: "alert",
      meta: { event_type: ev.event_type },
    });
  }

  return {
    generated_at: state.clockLabel,
    points,
    active_trips: state.trucks.filter((t) => t.phase !== "idle" && t.phase !== "loading").length,
    open_events: state.events.filter((e) => !e.is_resolved).length,
  };
}

export function primaryRoute(state: SimState): RoutePoint[] {
  const a = state.trucks.find((t) => t.detail.id === IDS.truckA);
  if (!a) return [];
  const t = transitT(a.progress);
  const count = Math.max(2, Math.ceil(t * (a.route.length - 1)) + 1);
  return a.route.slice(0, count);
}
