import { useEffect, useState } from "react";
import { api } from "./api/client";
import BatchTrailPanel from "./components/BatchTrailPanel";
import Logo from "./components/Logo";
import MapView from "./components/MapView";
import StationPanel from "./components/StationPanel";
import { useToast } from "./components/Toast";
import TruckPanel from "./components/TruckPanel";
import { useTheme } from "./theme";
import type { MapOverview, MapPoint, StationDetail, TruckDetail } from "./types";

type Selection =
  | { kind: "truck"; id: string }
  | { kind: "station"; id: string }
  | { kind: "factory"; id: string }
  | null;

export default function App() {
  const { theme, toggle } = useTheme();
  const toast = useToast();
  const [overview, setOverview] = useState<MapOverview | null>(null);
  const [selection, setSelection] = useState<Selection>(null);
  const [truck, setTruck] = useState<TruckDetail | null>(null);
  const [station, setStation] = useState<StationDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void api
      .mapOverview()
      .then((data) => {
        if (!cancelled) setOverview(data);
      })
      .catch((e) => {
        if (!cancelled) toast.err(e instanceof Error ? e.message : "Ошибка карты");
      });
    return () => {
      cancelled = true;
    };
  }, [toast]);

  useEffect(() => {
    if (!selection || selection.kind === "factory") {
      setTruck(null);
      setStation(null);
      return;
    }
    let cancelled = false;
    setLoadingDetail(true);
    const load =
      selection.kind === "truck"
        ? api.truck(selection.id).then((d) => {
            if (!cancelled) {
              setTruck(d);
              setStation(null);
            }
          })
        : api.station(selection.id).then((d) => {
            if (!cancelled) {
              setStation(d);
              setTruck(null);
            }
          });
    void load
      .catch((e) => {
        if (!cancelled) toast.err(e instanceof Error ? e.message : "Ошибка загрузки");
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selection, toast]);

  function onSelect(point: MapPoint) {
    if (point.kind === "truck" || point.kind === "station") {
      setSelection({ kind: point.kind, id: point.id });
    } else {
      setSelection({ kind: "factory", id: point.id });
      toast.ok(`Завод: ${point.name}`);
    }
  }

  const listPoints = (overview?.points ?? []).filter((p) => p.kind !== "factory");

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <Logo size={32} className="mark" alt="Цифровой след LPG" />
          <h1>Цифровой след LPG</h1>
          <span>контроль СУГ · завод → АГЗС → продажа</span>
        </div>
        <div className="topbar-actions">
          {overview && (
            <div className="stats-chip">
              <span>
                рейсы <strong>{overview.active_trips}</strong>
              </span>
              <span>
                события <strong>{overview.open_events}</strong>
              </span>
              <span>
                объектов <strong>{overview.points.length}</strong>
              </span>
            </div>
          )}
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
            points={overview?.points ?? []}
            selectedId={selection?.id}
            onSelect={onSelect}
          />
        </div>

        <aside className="side">
          <section className="panel">
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
            <div className="panel-body" style={{ paddingTop: 0, maxHeight: 160 }}>
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
          </section>

          {selection?.kind === "truck" && (
            <TruckPanel
              truck={truck}
              loading={loadingDetail}
              onClose={() => setSelection(null)}
            />
          )}
          {selection?.kind === "station" && (
            <StationPanel
              station={station}
              loading={loadingDetail}
              onClose={() => setSelection(null)}
            />
          )}
          {selection?.kind !== "truck" && selection?.kind !== "station" && <BatchTrailPanel />}
        </aside>
      </main>
    </div>
  );
}
