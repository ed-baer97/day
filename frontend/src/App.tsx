import { useEffect, useMemo, useRef, useState } from "react";
import Dashboard from "./components/Dashboard";
import MapChrome from "./components/MapChrome";
import MapPopup from "./components/MapPopup";
import MapView from "./components/MapView";
import SimDock from "./components/SimDock";
import SupplyPage from "./components/SupplyPage";
import TopBar, { type AppPage } from "./components/layout/TopBar";
import { useToast } from "./components/Toast";
import { IDS } from "./sim/seed";
import { useSim } from "./sim/SimContext";
import type { MapPoint } from "./types";

type Selection =
  | { kind: "truck"; id: string }
  | { kind: "station"; id: string }
  | { kind: "factory"; id: string }
  | null;

export default function App() {
  const toast = useToast();
  const { overview, routes, state } = useSim();
  const [page, setPage] = useState<AppPage>("map");
  const [selection, setSelection] = useState<Selection>(null);
  const [dashStationId, setDashStationId] = useState<string | null>(null);
  const [supplyId, setSupplyId] = useState<string | null>(IDS.supplyDemo);
  const dashRef = useRef<HTMLElement>(null);
  const seenEvents = useRef<Set<string>>(new Set());

  useEffect(() => {
    dashRef.current?.scrollTo(0, 0);
  }, [dashStationId, page, supplyId]);

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

  function navigate(next: AppPage) {
    if (next === "dashboard") setDashStationId(null);
    setPage(next);
  }

  function openSupply(id: string) {
    setSupplyId(id);
    setPage("supply");
  }

  function openStationPage(id: string) {
    setDashStationId(id);
    setPage("dashboard");
  }

  return (
    <div className="app">
      <TopBar page={page} onNavigate={navigate} />

      {page === "map" ? (
        <main className="page land">
          <div className="map-stage">
            <div className="map-vignette" aria-hidden />
            <MapView
              points={overview.points}
              routes={routes}
              selectedId={selection?.id}
              onSelect={onSelect}
            />
          </div>

          <MapChrome selectedId={selection?.id} onSelect={onSelect} />

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

          <SimDock />
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
