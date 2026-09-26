import { useEffect, useMemo, useRef, useState } from "react";
import BatchTrailPanel from "./components/BatchTrailPanel";
import EventsPanel from "./components/EventsPanel";
import Logo from "./components/Logo";
import MapView from "./components/MapView";
import SimControls from "./components/SimControls";
import StationPanel from "./components/StationPanel";
import { useToast } from "./components/Toast";
import TruckPanel from "./components/TruckPanel";
import { IDS } from "./sim/seed";
import { useSim } from "./sim/SimContext";
import { useTheme } from "./theme";
import type { MapPoint } from "./types";

type Tab = "objects" | "trail" | "detail";

type Selection =
  | { kind: "truck"; id: string }
  | { kind: "station"; id: string }
  | { kind: "factory"; id: string }
  | null;

export default function App() {
  const { theme, toggle } = useTheme();
  const toast = useToast();
  const { overview, route, state } = useSim();
  const [selection, setSelection] = useState<Selection>({ kind: "truck", id: IDS.truckA });
  const [tab, setTab] = useState<Tab>("detail");

  const truck = useMemo(() => {
    if (selection?.kind !== "truck") return null;
    return state.trucks.find((t) => t.detail.id === selection.id)?.detail ?? null;
  }, [selection, state.trucks]);

  const station = useMemo(() => {
    if (selection?.kind !== "station") return null;
    if (selection.id.startsWith("alert-")) return null;
    return state.stations.find((s) => s.detail.id === selection.id)?.detail ?? null;
  }, [selection, state.stations]);

  function onSelect(point: MapPoint) {
    if (point.id.startsWith("alert-")) {
      setSelection({ kind: "station", id: IDS.stationN });
      setTab("detail");
      toast.err("Расхождение на АГЗС Север");
      return;
    }
    if (point.kind === "truck" || point.kind === "station") {
      setSelection({ kind: point.kind, id: point.id });
      setTab("detail");
    } else {
      setSelection({ kind: "factory", id: point.id });
      setTab("trail");
      toast.ok(`Завод: ${point.name}`);
    }
  }

  const listPoints = overview.points.filter(
    (p) => p.kind !== "factory" && !p.id.startsWith("alert-")
  );

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <Logo size={32} className="mark" alt="Цифровой след LPG" />
          <h1>Цифровой след LPG</h1>
          <span>мок симуляции · завод → АГЗС → продажа</span>
        </div>
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
            <span>
              след <strong>{state.batch.events.length}</strong>
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

      <main className="page land">
        <div className="map-stage">
          <MapView
            points={overview.points}
            route={route}
            selectedId={selection?.id}
            onSelect={onSelect}
          />
        </div>

        <aside className="side">
          <SimControls />

          <section className="panel">
            <div className="tabs hud-tabs">
              <button
                type="button"
                className={`tab${tab === "objects" ? " active" : ""}`}
                onClick={() => setTab("objects")}
              >
                Объекты
              </button>
              <button
                type="button"
                className={`tab${tab === "detail" ? " active" : ""}`}
                onClick={() => setTab("detail")}
              >
                Карточка
              </button>
              <button
                type="button"
                className={`tab${tab === "trail" ? " active" : ""}`}
                onClick={() => setTab("trail")}
              >
                След
              </button>
            </div>

            {tab === "objects" && (
              <>
                <div className="legend">
                  <span className="legend-item">
                    <i className="dot factory" /> завод
                  </span>
                  <span className="legend-item">
                    <i className="dot station" /> АГЗС
                  </span>
                  <span className="legend-item">
                    <i className="dot truck" /> газовоз
                  </span>
                  <span className="legend-item">
                    <i className="dot alert" /> расхождение
                  </span>
                </div>
                <div className="panel-body" style={{ paddingTop: 0, maxHeight: 280 }}>
                  <ul className="object-list">
                    {listPoints.map((p) => (
                      <li key={p.id}>
                        <button
                          type="button"
                          className={`object-row${selection?.id === p.id ? " active" : ""}`}
                          onClick={() => onSelect(p)}
                        >
                          <i className={`dot ${p.kind}`} />
                          <span>{p.name}</span>
                          <em>{p.status}</em>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              </>
            )}

            {tab === "detail" && selection?.kind === "truck" && (
              <TruckPanel truck={truck} onClose={() => setTab("objects")} />
            )}
            {tab === "detail" && selection?.kind === "station" && (
              <StationPanel station={station} onClose={() => setTab("objects")} />
            )}
            {tab === "detail" && selection?.kind !== "truck" && selection?.kind !== "station" && (
              <div className="panel-body">
                <p className="empty">Выберите газовоз или АГЗС на карте / в списке объектов</p>
              </div>
            )}

            {tab === "trail" && <BatchTrailPanel />}
          </section>

          <EventsPanel />
        </aside>
      </main>
    </div>
  );
}
