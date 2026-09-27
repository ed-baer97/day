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
};

const SimContext = createContext<SimApi | null>(null);

const TICK_MS = 200;

export function SimProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SimState>(() => resetState());
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState<SimSpeed>(5);
  const playingRef = useRef(playing);
  const speedRef = useRef(speed);
  playingRef.current = playing;
  speedRef.current = speed;

  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    let acc = 0;

    const loop = (now: number) => {
      const wall = now - last;
      last = now;
      if (playingRef.current) {
        acc += wall;
        if (acc >= TICK_MS) {
          const step = acc;
          acc = 0;
          setState((prev) => tick(prev, step, speedRef.current));
        }
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  const play = useCallback(() => setPlaying(true), []);
  const pause = useCallback(() => setPlaying(false), []);
  const toggle = useCallback(() => setPlaying((p) => !p), []);
  const reset = useCallback(() => {
    setState(resetState());
    setPlaying(true);
  }, []);

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
    }),
    [state, overview, routes, playing, speed, play, pause, toggle, reset]
  );

  return <SimContext.Provider value={value}>{children}</SimContext.Provider>;
}

export function useSim(): SimApi {
  const ctx = useContext(SimContext);
  if (!ctx) throw new Error("useSim outside SimProvider");
  return ctx;
}
