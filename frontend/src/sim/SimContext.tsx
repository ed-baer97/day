import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { mapRoutes, resetState, stationBalance, tick, toMapOverview, type MapRouteLayer } from "./engine";
import { applyFleet, type FleetStation, type FleetTruck } from "./fleet";
import type { SimState } from "./seed";
import type { DiscrepancyEvent, LpgSupply, MapOverview } from "../types";

export type SimSpeed = 1 | 5 | 20;

type SimApi = {
  state: SimState;
  overview: MapOverview;
  routes: MapRouteLayer[];
  playing: boolean;
  speed: SimSpeed;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  setSpeed: (s: SimSpeed) => void;
  reset: () => void;
  applyFleetCards: (
    stations: FleetStation[],
    trucks: FleetTruck[],
    removedStationIds?: Set<string>,
    removedTruckIds?: Set<string>
  ) => void;
  updateStationTankLevel: (
    stationId: string,
    tankCode: string,
    actualLiters: number,
    capacityLiters?: number
  ) => void;
  recordStationReceipt: (stationId: string, volumeLiters: number, plate?: string) => void;
  resolveSimEvent: (eventId: string, note?: string) => void;
  addSimEvent: (ev: Omit<DiscrepancyEvent, "id" | "detected_at" | "is_resolved">) => void;
  createSimSupply: (params: {
    waybill: string;
    stationId: string;
    truckId: string;
    volumeLiters: number;
  }) => LpgSupply | null;
};

const SimContext = createContext<SimApi | null>(null);

export function SimProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SimState>(() => resetState());
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<SimSpeed>(5);

  const play = useCallback(() => setPlaying(true), []);
  const pause = useCallback(() => setPlaying(false), []);
  const toggle = useCallback(() => setPlaying((p) => !p), []);
  const reset = useCallback(() => {
    setState(resetState());
    setPlaying(false);
  }, []);
  const applyFleetCards = useCallback(
    (
      stations: FleetStation[],
      trucks: FleetTruck[],
      removedStationIds?: Set<string>,
      removedTruckIds?: Set<string>
    ) => {
      setState((prev) => applyFleet(prev, stations, trucks, removedStationIds, removedTruckIds));
    },
    []
  );

  const updateStationTankLevel = useCallback(
    (stationId: string, tankCode: string, actualLiters: number, capacityLiters?: number) => {
      setState((prev) => {
        const now = new Date().toISOString();
        const nextStations = prev.stations.map((st) => {
          if (st.detail.id !== stationId) return st;
          const d = { ...st.detail };
          const existingIdx = d.tanks.findIndex((t) => t.code === tankCode);
          const nextTanks = [...d.tanks];
          if (existingIdx >= 0) {
            const cur = nextTanks[existingIdx];
            nextTanks[existingIdx] = {
              ...cur,
              actual_remainder_liters: actualLiters,
              capacity_liters: capacityLiters ?? cur.capacity_liters,
              last_measured_at: now,
            };
          } else {
            nextTanks.push({
              id: `${stationId}-${tankCode}`,
              code: tankCode,
              capacity_liters: capacityLiters ?? (d.capacity_liters || 20000),
              has_electronic_sensor: true,
              actual_remainder_liters: actualLiters,
              calculated_remainder_liters: actualLiters,
              level_source: "electronic",
              last_measured_at: now,
              temperature_c: 15.8,
              phone_label: "смартфон АГЗС",
              link_quality: "good",
            });
          }
          d.tanks = nextTanks;
          d.remainder_liters = nextTanks[0]?.actual_remainder_liters ?? actualLiters;
          if (capacityLiters && existingIdx <= 0) {
            d.capacity_liters = capacityLiters;
          }
          const bal = stationBalance(d);
          d.calculated_vs_actual_delta = bal.delta;
          d.balance_status =
            bal.status === "ok"
              ? "ok"
              : bal.status === "warn"
                ? "measurement_error"
                : bal.status;
          return { ...st, detail: d };
        });
        return { ...prev, stations: nextStations };
      });
    },
    []
  );

  const recordStationReceipt = useCallback(
    (stationId: string, volumeLiters: number, plate = "705 ABA 12") => {
      setState((prev) => {
        const now = new Date().toISOString();
        const vol = Math.round(volumeLiters);
        const nextStations = prev.stations.map((st) => {
          if (st.detail.id !== stationId) return st;
          const d = { ...st.detail };
          d.receipts_day_liters += vol;
          d.delivery_count_day += 1;
          d.recent_deliveries = [
            { plate, liters: vol, occurred_at: now },
            ...d.recent_deliveries,
          ].slice(0, 10);
          if (d.tanks.length > 0) {
            const first = { ...d.tanks[0] };
            first.actual_remainder_liters = (first.actual_remainder_liters ?? 0) + vol;
            first.calculated_remainder_liters = (first.calculated_remainder_liters ?? 0) + vol;
            first.last_measured_at = now;
            d.tanks = [first, ...d.tanks.slice(1)];
            d.remainder_liters = first.actual_remainder_liters;
          } else {
            d.remainder_liters = (d.remainder_liters ?? 0) + vol;
          }
          const bal = stationBalance(d);
          d.calculated_vs_actual_delta = bal.delta;
          d.balance_status =
            bal.status === "ok"
              ? "ok"
              : bal.status === "warn"
                ? "measurement_error"
                : bal.status;
          return { ...st, detail: d };
        });
        return {
          ...prev,
          stations: nextStations,
          stats: {
            delivered_liters_day: prev.stats.delivered_liters_day + vol,
            delivery_trips_day: prev.stats.delivery_trips_day + 1,
          },
        };
      });
    },
    []
  );

  const resolveSimEvent = useCallback((eventId: string, note?: string) => {
    setState((prev) => ({
      ...prev,
      events: prev.events.map((ev) =>
        ev.id === eventId
          ? {
              ...ev,
              is_resolved: true,
              description: note ? `${ev.description ?? ""} | Закрыто: ${note}` : ev.description,
            }
          : ev
      ),
    }));
  }, []);

  const addSimEvent = useCallback(
    (ev: Omit<DiscrepancyEvent, "id" | "detected_at" | "is_resolved">) => {
      setState((prev) => ({
        ...prev,
        events: [
          {
            ...ev,
            id: `ev-manual-${Date.now()}`,
            detected_at: new Date().toISOString(),
            is_resolved: false,
          },
          ...prev.events,
        ],
      }));
    },
    []
  );

  const createSimSupply = useCallback(
    (params: { waybill: string; stationId: string; truckId: string; volumeLiters: number }) => {
      let createdSupply: LpgSupply | null = null;
      setState((prev) => {
        const station = prev.stations.find((s) => s.detail.id === params.stationId)?.detail;
        const truck = prev.trucks.find((t) => t.detail.id === params.truckId)?.detail;
        const factory = prev.factories[0];
        if (!station || !truck) return prev;
        const seq = prev.supplies.reduce((max, s) => {
          const n = Number(s.supply_id.split("-").pop());
          return Number.isFinite(n) ? Math.max(max, n) : max;
        }, 42);
        const now = new Date().toISOString();
        const tank = station.tanks[0];
        const supply: LpgSupply = {
          supply_id: `SUP-2026-${String(seq + 1).padStart(4, "0")}`,
          live: true,
          status: "in_transit",
          factory_id: factory?.id ?? "",
          factory_name: factory?.name ?? "КазГаз",
          truck_id: truck.id,
          plate: truck.plate_number,
          station_id: station.id,
          station_name: station.name,
          tank_id: tank?.id ?? `${station.id}-r1`,
          tank_code: tank?.code ?? "R-1",
          shipped_at: now,
          waybill: params.waybill,
          shipped_liters: Math.round(params.volumeLiters),
          shipped_temp_c: 13.2,
          route_name: `${factory?.name ?? "КазГаз"} → ${station.name}`,
          departed_at: now,
          arrived_at: null,
          delivered_liters: Math.round(params.volumeLiters),
          truck_temp_c: 14.5,
          gps_lat: truck.lat ?? 43.5,
          gps_lon: truck.lon ?? 52.1,
          gps_at: now,
          gps_status: "ok",
          quantity_sensor: "ok",
          temp_sensor: "ok",
          accepted_liters: null,
          accepted_at: null,
          dispensed_liters: 0,
          fiscal_liters: 0,
          fiscal_receipts: 0,
          fiscal_amount_kzt: 0,
          fiscal_period: "",
          fiscal_updated_at: null,
          operations: [],
        };
        createdSupply = supply;
        return {
          ...prev,
          supplies: [supply, ...prev.supplies],
        };
      });
      return createdSupply;
    },
    []
  );

  const speedRef = useRef(speed);
  speedRef.current = speed;

  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    let last = performance.now();
    let pending = 0;
    const loop = (now: number) => {
      const dt = Math.min(250, now - last);
      last = now;
      pending += dt;
      if (pending >= 100) {
        const step = pending;
        pending = 0;
        setState((prev) => tick(prev, step, speedRef.current));
      }
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, [playing]);

  const overview = useMemo(() => toMapOverview(state), [state]);
  const routes = useMemo(() => mapRoutes(state), [state]);

  const value = useMemo(
    () => ({
      state,
      overview,
      routes,
      playing,
      speed,
      play,
      pause,
      toggle,
      setSpeed,
      reset,
      applyFleetCards,
      updateStationTankLevel,
      recordStationReceipt,
      resolveSimEvent,
      addSimEvent,
      createSimSupply,
    }),
    [
      state,
      overview,
      routes,
      playing,
      speed,
      play,
      pause,
      toggle,
      reset,
      applyFleetCards,
      updateStationTankLevel,
      recordStationReceipt,
      resolveSimEvent,
      addSimEvent,
      createSimSupply,
    ]
  );

  return <SimContext.Provider value={value}>{children}</SimContext.Provider>;
}

export function useSim(): SimApi {
  const ctx = useContext(SimContext);
  if (!ctx) throw new Error("useSim outside SimProvider");
  return ctx;
}
