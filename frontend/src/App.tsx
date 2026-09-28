import { useEffect, useMemo, useRef, useState } from "react";
import Dashboard from "./components/Dashboard";
import Logo from "./components/Logo";
import MapPopup from "./components/MapPopup";
import MapView from "./components/MapView";
import SupplyPage from "./components/SupplyPage";
import { useToast } from "./components/Toast";
import { IDS } from "./sim/seed";
import { useSim } from "./sim/SimContext";
import { useTheme } from "./theme";
import type { MapPoint } from "./types";

type Page = "map" | "dashboard" | "supply";

type Selection =
  | { kind: "truck"; id: string }
  | { kind: "station"; id: string }
  | { kind: "factory"; id: string }
  | null;

export default function App() {
  const { theme, toggle } = useTheme();
  const toast = useToast();
  const { overview, routes, state } = useSim();
  const [page, setPage] = useState<Page>("map");
  const [selection, setSelection] = useState<Selection>(null);
  const [dashStationId, setDashStationId] = useState<string | null>(null);
  const [supplyId, setSupplyId] = useState<string | null>(IDS.supplyDemo);
  const dashRef = useRef<HTMLElement>(null);

  useEffect(() => {
    dashRef.current?.scrollTo(0, 0);
  }, [dashStationId, page, supplyId]);

  function openSupply(id: string) {
    setSupplyId(id);
    setPage("supply");
  }

  function openStationPage(id: string) {
    setDashStationId(id);
    setPage("dashboard");
  }
  const seenEvents = useRef<Set<string>>(new Set());

  useEffect(() => {
    for (const ev of state.events) {
      if (!seenEvents.current.has(ev.id)) {
        seenEvents.current.add(ev.id);
        toast.err(`${ev.title}: ${ev.delta_liters ?? ""} л`);
      }
    }
  }, [state.events, toast]);

  const truck = useMemo(() => {
    if (selection?.kind !== "truck") return null;
    return state.trucks.find((t) => t.detail.id === selection.id)?.detail ?? null;
  }, [selection, state.trucks]);

  const station = useMemo(() => {
    if (selection?.kind !== "station") return null;
    return state.stations.find((s) => s.detail.id === selection.id)?.detail ?? null;
  }, [selection, state.stations]);

  const factoryName = useMemo(() => {
    if (selection?.kind !== "factory") return null;
    return state.factories.find((f) => f.id === selection.id)?.name ?? null;
  }, [selection, state.factories]);

  function onSelect(point: MapPoint) {
    if (point.id.startsWith("alert-")) {
      setSelection({ kind: "station", id: IDS.stationN });
      toast.err("Расхождение на АГЗС Актау · 12 мкр");
      return;
    }
    if (point.kind === "truck" || point.kind === "station" || point.kind === "factory") {
      setSelection({ kind: point.kind, id: point.id });
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <Logo size={32} className="mark" alt="Цифровой след LPG" />
          <h1>Цифровой след LPG</h1>
          <span>мок · Мангыстау</span>
        </div>

        <nav className="nav-pages" aria-label="Разделы">
          <button
            type="button"
            className={`nav-page${page === "map" ? " active" : ""}`}
            onClick={() => setPage("map")}
          >
            Карта
          </button>
          <button
            type="button"
            className={`nav-page${page === "dashboard" ? " active" : ""}`}
            onClick={() => {
              setDashStationId(null);
              setPage("dashboard");
            }}
          >
            Дашборд
          </button>
          <button
            type="button"
            className={`nav-page${page === "supply" ? " active" : ""}`}
            onClick={() => setPage("supply")}
          >
            Поставка
          </button>
        </nav>

        <div className="topbar-actions">
          <div className="stats-chip">
            <span>
              рейсы <strong>{overview.active_trips}</strong>
            </span>
            <span>
              события{" "}
              <strong className={overview.open_events ? "text-danger" : ""}>
                {overview.open_events}
              </strong>
            </span>
          </div>
          <button
            className="btn secondary small"
            type="button"
            onClick={toggle}
            aria-label={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
          >
            {theme === "dark" ? "Светлая" : "Тёмная"}
          </button>
        </div>
      </header>

      {page === "map" ? (
        <main className="page land">
          <div className="map-stage">
            <MapView
              points={overview.points}
              routes={routes}
              selectedId={selection?.id}
              onSelect={onSelect}
            />
          </div>

          {selection && (
            <div className="map-hud">
              <MapPopup
                truck={truck}
                station={station}
                factoryName={factoryName}
                onClose={() => setSelection(null)}
                onOpenStation={openStationPage}
                onOpenSupply={openSupply}
              />
            </div>
          )}
        </main>
      ) : page === "supply" ? (
        <main className="page dash-page" ref={dashRef}>
          <SupplyPage supplyId={supplyId} onSelect={setSupplyId} />
        </main>
      ) : (
        <main className="page dash-page" ref={dashRef}>
          <Dashboard stationId={dashStationId} onOpenStation={setDashStationId} />
        </main>
      )}
    </div>
  );
}
