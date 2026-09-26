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
import { primaryRoute, resetState, tick, toMapOverview } from "./engine";
import type { SimState } from "./seed";
import type { MapOverview } from "../types";
import type { RoutePoint } from "./seed";

export type SimSpeed = 1 | 5 | 20;

type SimApi = {
  state: SimState;
  overview: MapOverview;
  route: RoutePoint[];
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
  const route = useMemo(() => primaryRoute(state), [state]);

  const value = useMemo(
    () => ({
      state,
      overview,
      route,
      playing,
      speed,
      play,
      pause,
      toggle,
      setSpeed,
      reset,
    }),
    [state, overview, route, playing, speed, play, pause, toggle, reset]
  );

  return <SimContext.Provider value={value}>{children}</SimContext.Provider>;
}

export function useSim(): SimApi {
  const ctx = useContext(SimContext);
  if (!ctx) throw new Error("useSim outside SimProvider");
  return ctx;
}
