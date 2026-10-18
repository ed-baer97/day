import { useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "./auth";
import { useCatalog } from "./catalog";
import AdminPage from "./components/AdminPage";
import Dashboard from "./components/Dashboard";
import Landing from "./components/Landing";
import Logo from "./components/Logo";
import MapPopup from "./components/MapPopup";
import MapView from "./components/MapView";
import SupplyPage from "./components/SupplyPage";
import { useToast } from "./components/Toast";
import { IDS } from "./sim/seed";
import { useSim } from "./sim/SimContext";
import { useTheme } from "./theme";
import type { MapPoint } from "./types";

type Page = "landing" | "map" | "dashboard" | "supply" | "admin";

type Selection =
  | { kind: "truck"; id: string }
  | { kind: "station"; id: string }
  | { kind: "factory"; id: string }
  | null;

export default function App() {
  const { theme, toggle } = useTheme();
  const toast = useToast();
  const { session, logout } = useAuth();
  const { overview, state, applyFleetCards } = useSim();
  const catalog = useCatalog();
  const [page, setPage] = useState<Page>("landing");
  const [selection, setSelection] = useState<Selection>(null);
  const [dashStationId, setDashStationId] = useState<string | null>(null);
  const [supplyId, setSupplyId] = useState<string | null>(IDS.supplyDemo);
  const dashRef = useRef<HTMLElement>(null);

  useEffect(() => {
    dashRef.current?.scrollTo(0, 0);
  }, [dashStationId, page, supplyId]);

  useEffect(() => {
    if (catalog.ready) applyFleetCards(catalog.stations, catalog.trucks);
  }, [catalog.ready, catalog.stations, catalog.trucks, applyFleetCards]);

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
    const inside = page !== "landing" && session;
    for (const ev of state.events) {
      if (seenEvents.current.has(ev.id)) continue;
      seenEvents.current.add(ev.id);
      if (inside) toast.err(`${ev.title}: ${ev.delta_liters ?? ""} л`);
    }
  }, [state.events, toast, page, session]);

  const mapPoints = useMemo(() => {
    const hidden = new Set(catalog.stations.filter((row) => !row.is_active).map((row) => row.id));
    const listed = new Set(catalog.stations.map((row) => row.id));
    const points = overview.points.filter(
      (point) =>
        point.kind !== "truck" &&
        !point.id.startsWith("alert-") &&
        (point.kind !== "station" || !catalog.ready || listed.has(point.id))
    );
    return points.filter((point) => !hidden.has(point.id));
  }, [overview.points, catalog.stations, catalog.ready]);

  const truck = useMemo(() => {
    if (selection?.kind !== "truck") return null;
    const live = state.trucks.find((t) => t.detail.id === selection.id)?.detail;
    if (live) return live;
    const row = catalog.trucks.find((item) => item.id === selection.id);
    if (!row) return null;
    return {
      id: row.id,
      plate_number: row.plate_number,
      capacity_liters: row.capacity_liters,
      carrier_name: row.carrier_name,
      status: row.status,
      lat: row.lat,
      lon: row.lon,
    };
  }, [selection, state.trucks, catalog.trucks]);

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

  if (page === "landing" || !session) {
    return <Landing onEnter={() => setPage("map")} />;
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
          <button
            type="button"
            className={`nav-page${page === "admin" ? " active" : ""}`}
            onClick={() => setPage("admin")}
          >
            Админка
          </button>
        </nav>

        <div className="topbar-actions">
          <div className="stats-chip">
            <span>
              события{" "}
              <strong className={overview.open_events ? "text-danger" : ""}>
                {overview.open_events}
              </strong>
            </span>
          </div>
          <span className="who">{session.username}</span>
          <button type="button" className="btn secondary small" onClick={() => setPage("landing")}>
            На сайт
          </button>
          <button
            type="button"
            className="btn secondary small"
            onClick={() => {
              logout();
              setPage("landing");
            }}
          >
            Выйти
          </button>
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
              points={mapPoints}
              routes={[]}
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
      ) : page === "admin" ? (
        <main className="page dash-page" ref={dashRef}>
          <AdminPage />
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
