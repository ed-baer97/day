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
import { mapRoutes, resetState, tick, toMapOverview, type MapRouteLayer } from "./engine";
import { applyFleet, type FleetStation, type FleetTruck } from "./fleet";
import type { SimState } from "./seed";
import type { MapOverview } from "../types";

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
  applyFleetCards: (stations: FleetStation[], trucks: FleetTruck[]) => void;
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
  const applyFleetCards = useCallback((stations: FleetStation[], trucks: FleetTruck[]) => {
    setState((prev) => applyFleet(prev, stations, trucks));
  }, []);

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

  useEffect(() => {
    (window as unknown as { __lpgDebug?: unknown }).__lpgDebug = {
      phases: state.trucks.map((t) => ({
        plate: t.detail.plate_number,
        phase: t.phase,
        progress: t.routeProgress,
        routePts: t.route.length,
        lat: t.detail.lat,
        lon: t.detail.lon,
      })),
      routeLayers: routes.map((r) => ({
        id: r.id,
        planned: r.planned.length,
        traveled: r.traveled.length,
        plannedSample: r.planned.filter((_, i) => i % 40 === 0).slice(0, 8),
      })),
    };
  }, [state, routes]);

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
    }),
    [state, overview, routes, playing, speed, play, pause, toggle, reset, applyFleetCards]
  );

  return <SimContext.Provider value={value}>{children}</SimContext.Provider>;
}

export function useSim(): SimApi {
  const ctx = useContext(SimContext);
  if (!ctx) throw new Error("useSim outside SimProvider");
  return ctx;
}
