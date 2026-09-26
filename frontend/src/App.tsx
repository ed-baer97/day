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
    void api
      .mapOverview()
      .then(setOverview)
      .catch((e) => toast.err(e instanceof Error ? e.message : "Ошибка карты"));
  }, [toast]);

  useEffect(() => {
    if (!selection || selection.kind === "factory") {
      setTruck(null);
      setStation(null);
      return;
    }
    setLoadingDetail(true);
    const load =
      selection.kind === "truck"
        ? api.truck(selection.id).then((d) => {
            setTruck(d);
            setStation(null);
          })
        : api.station(selection.id).then((d) => {
            setStation(d);
            setTruck(null);
          });
    void load
      .catch((e) => toast.err(e instanceof Error ? e.message : "Ошибка загрузки"))
      .finally(() => setLoadingDetail(false));
  }, [selection, toast]);

  function onSelect(point: MapPoint) {
    if (point.kind === "truck" || point.kind === "station") {
      setSelection({ kind: point.kind, id: point.id });
    } else {
      setSelection({ kind: "factory", id: point.id });
      toast.ok(`Завод: ${point.name}`);
    }
  }

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
          {!selection && <BatchTrailPanel />}
        </aside>
      </main>
    </div>
  );
}
