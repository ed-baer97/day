import { useMemo, useState } from "react";
import type { CatalogStation, CatalogTruck } from "../api/client";
import MapPopup from "../components/MapPopup";
import MapView from "../components/MapView";
import { liters, phaseLabel, REGIONS, stationRegion } from "../format";
import type { NetworkStats } from "../layout/Topbar";
import { isLowFill, type LiveLevel, sensorLabel } from "../liveLevels";
import type { MapPoint } from "../types";

export type MapSelection =
  | { kind: "truck"; id: string }
  | { kind: "station"; id: string }
  | null;

export default function MapScreen({
  admin,
  stations,
  trucks,
  byCode,
  mapPoints,
  networkStats,
  selection,
  mapHudTab,
  onSetMapHudTab,
  onSelect,
  onOpenStationPage,
  onOpenAdminStation,
  onOpenAdminTruck,
}: {
  admin: boolean;
  stations: CatalogStation[];
  trucks: CatalogTruck[];
  byCode: Map<string, LiveLevel>;
  mapPoints: MapPoint[];
  networkStats: NetworkStats;
  selection: MapSelection;
  mapHudTab: "stations" | "trucks";
  onSetMapHudTab: (tab: "stations" | "trucks") => void;
  onSelect: (selection: MapSelection) => void;
  onOpenStationPage: (id: string) => void;
  onOpenAdminStation?: (id: string) => void;
  onOpenAdminTruck?: (id: string) => void;
}) {
  const [mapHudOpen, setMapHudOpen] = useState(true);
  const [mapSearch, setMapSearch] = useState("");
  const [mapRegion, setMapRegion] = useState("all");
  const [mapStatus, setMapStatus] = useState<"all" | "low" | "offline">("all");

  const filteredMapStations = useMemo(() => {
    const q = mapSearch.trim().toLowerCase();
    return stations.filter((row) => {
      if (
        q &&
        ![row.name, row.code, row.address, stationRegion(row)].some((part) =>
          part?.toLowerCase().includes(q)
        )
      ) {
        return false;
      }
      if (mapRegion !== "all" && stationRegion(row) !== mapRegion) return false;
      const live = byCode.get(row.code);
      const fill = live && live.tanks.length > 0 && live.fill != null ? Math.round(live.fill) : null;
      const online = !!live?.tanks.some((tank) => tank.online && tank.remainder_liters != null);
      if (mapStatus === "low" && !isLowFill(fill)) return false;
      if (mapStatus === "offline" && online) return false;
      return true;
    });
  }, [stations, mapSearch, mapRegion, mapStatus, byCode]);

  const selectedStation =
    selection?.kind === "station" ? (stations.find((row) => row.id === selection.id) ?? null) : null;
  const selectedTruck =
    selection?.kind === "truck" ? (trucks.find((row) => row.id === selection.id) ?? null) : null;
  const showTrucks = admin && mapHudTab === "trucks";

  return (
    <main className="page land">
      <div className="map-stage">
        <MapView
          points={mapPoints}
          selectedId={selection?.id}
          onSelect={(point) => {
            if (point.kind === "truck" || point.kind === "station") {
              onSelect({ kind: point.kind, id: point.id });
            }
          }}
        />
      </div>
      <aside className={`map-nav-drawer${mapHudOpen ? " open" : " collapsed"}`}>
        <div className="map-nav-header">
          <div className="map-sim-bar">
            <button
              type="button"
              className="btn secondary small"
              onClick={() => setMapHudOpen((value) => !value)}
            >
              {mapHudOpen ? "Свернуть панель" : `Объекты на карте (${mapPoints.length})`}
            </button>
            {mapHudOpen ? (
              <span className="dash-muted" style={{ marginLeft: "auto" }}>
                Всего: {liters(networkStats.litersSum)}
              </span>
            ) : null}
          </div>
          {mapHudOpen ? (
            <>
              <div className="tabs hud-tabs" style={{ padding: "8px 0 0" }}>
                <button
                  type="button"
                  className={`tab${mapHudTab === "stations" ? " active" : ""}`}
                  onClick={() => onSetMapHudTab("stations")}
                >
                  АГЗС ({filteredMapStations.length})
                </button>
                {admin ? (
                  <button
                    type="button"
                    className={`tab${mapHudTab === "trucks" ? " active" : ""}`}
                    onClick={() => onSetMapHudTab("trucks")}
                  >
                    Газовозы ({trucks.length})
                  </button>
                ) : null}
              </div>
              {!showTrucks ? (
                <div className="map-nav-filters">
                  <input
                    type="search"
                    value={mapSearch}
                    placeholder="Поиск АГЗС на карте…"
                    onChange={(event) => setMapSearch(event.target.value)}
                  />
                  <select
                    value={mapRegion}
                    onChange={(event) => setMapRegion(event.target.value)}
                    aria-label="Район"
                  >
                    <option value="all">Все районы ({stations.length})</option>
                    {REGIONS.map((region) => (
                      <option key={region} value={region}>
                        {region}
                      </option>
                    ))}
                  </select>
                  <div className="map-status-chips">
                    <button
                      type="button"
                      className={`filter-pill${mapStatus === "all" ? " active" : ""}`}
                      onClick={() => setMapStatus("all")}
                    >
                      Все ({stations.length})
                    </button>
                    <button
                      type="button"
                      className={`filter-pill${mapStatus === "low" ? " active" : ""}`}
                      onClick={() => setMapStatus("low")}
                    >
                      Мало газа ({networkStats.low})
                    </button>
                    <button
                      type="button"
                      className={`filter-pill${mapStatus === "offline" ? " active" : ""}`}
                      onClick={() => setMapStatus("offline")}
                    >
                      Нет связи ({networkStats.offline})
                    </button>
                  </div>
                </div>
              ) : null}
            </>
          ) : null}
        </div>
        {mapHudOpen ? (
          <div className="map-nav-body">
            {!showTrucks ? (
              <ul className="object-list">
                {filteredMapStations.map((row) => {
                  const live = byCode.get(row.code);
                  const hasLive = !!live && live.tanks.length > 0;
                  const fill = hasLive && live.fill != null ? Math.round(live.fill) : null;
                  return (
                    <li key={row.id}>
                      <button
                        type="button"
                        className={`object-row${selection?.kind === "station" && selection.id === row.id ? " active" : ""}`}
                        onClick={() => onSelect({ kind: "station", id: row.id })}
                      >
                        <span className="dot station" />
                        <div className="object-row-info">
                          <strong>{row.name}</strong>
                          <span>
                            {row.code} · {stationRegion(row)}
                          </span>
                        </div>
                        <em>
                          {hasLive && live ? `${sensorLabel(live)} · ` : "нет датчика · "}
                          <strong className={isLowFill(fill) ? "text-danger" : ""}>
                            {fill == null ? "—" : `${fill}%`}
                          </strong>{" "}
                          ·{" "}
                          {hasLive && live?.remainder != null
                            ? liters(live.remainder)
                            : "замера нет"}
                        </em>
                      </button>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <ul className="object-list">
                {trucks.length === 0 ? (
                  <li className="dash-muted">Газовозы не заведены.</li>
                ) : null}
                {trucks.map((row) => (
                  <li key={row.id}>
                    <button
                      type="button"
                      className={`object-row${selection?.kind === "truck" && selection.id === row.id ? " active" : ""}`}
                      onClick={() => onSelect({ kind: "truck", id: row.id })}
                    >
                      <span className="dot truck" />
                      <div className="object-row-info">
                        <strong>{row.plate_number}</strong>
                        <span>
                          {row.carrier_name || "перевозчик не указан"} ·{" "}
                          {liters(row.capacity_liters)}
                        </span>
                      </div>
                      <em>
                        {phaseLabel(row.status)}
                        {row.lat == null || row.lon == null ? " · координат нет" : ""}
                      </em>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </aside>
      {selection ? (
        <div className="map-hud map-hud-right">
          <MapPopup
            truck={selectedTruck}
            station={selectedStation}
            onClose={() => onSelect(null)}
            onOpenStation={onOpenStationPage}
            onOpenAdminStation={onOpenAdminStation}
            onOpenAdminTruck={onOpenAdminTruck}
          />
        </div>
      ) : null}
    </main>
  );
}
