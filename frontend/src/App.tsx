import { useEffect, useMemo, useRef, useState } from "react";
import { isAdmin } from "./access";
import { useAuth } from "./auth";
import { useCatalog } from "./catalog";
import AdminPage from "./components/AdminPage";
import Dashboard from "./components/Dashboard";
import Landing from "./components/Landing";
import Logo from "./components/Logo";
import MapPopup from "./components/MapPopup";
import MapView from "./components/MapView";
import { liters, phaseLabel, REGIONS, stationRegion } from "./format";
import { isLowFill, SensorStatus, sensorLabel, usePublicLevels } from "./liveLevels";
import { useTheme } from "./theme";
import type { MapPoint } from "./types";

type Page = "landing" | "map" | "dashboard" | "admin" | "supply";
type Selection = { kind: "truck"; id: string } | { kind: "station"; id: string } | null;

export default function App() {
  const { theme, toggle } = useTheme();
  const { session, logout } = useAuth();
  const admin = isAdmin(session);
  const catalog = useCatalog();
  const { byCode } = usePublicLevels();
  const [page, setPage] = useState<Page>("landing");
  const [selection, setSelection] = useState<Selection>(null);
  const [dashStationId, setDashStationId] = useState<string | null>(null);
  const [adminStationId, setAdminStationId] = useState<string | null>(null);
  const dashRef = useRef<HTMLElement>(null);
  const [quickOpen, setQuickOpen] = useState(false);
  const [quickQuery, setQuickQuery] = useState("");
  const quickRef = useRef<HTMLDivElement>(null);
  const [mapHudOpen, setMapHudOpen] = useState(true);
  const [mapHudTab, setMapHudTab] = useState<"stations" | "trucks">("stations");
  const [mapSearch, setMapSearch] = useState("");
  const [mapRegion, setMapRegion] = useState("all");
  const [mapStatus, setMapStatus] = useState<"all" | "low" | "offline">("all");

  useEffect(() => {
    dashRef.current?.scrollTo(0, 0);
  }, [dashStationId, page, adminStationId]);

  useEffect(() => {
    function onDocClick(event: MouseEvent) {
      if (quickRef.current && !quickRef.current.contains(event.target as Node)) setQuickOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  function openStationPage(id: string) {
    setDashStationId(id);
    setPage("dashboard");
    setQuickOpen(false);
  }

  function openStationOnMap(id: string) {
    setSelection({ kind: "station", id });
    setPage("map");
    setQuickOpen(false);
  }

  function openAdminStation(id: string) {
    setAdminStationId(id);
    setPage("admin");
    setQuickOpen(false);
  }

  const isOwner = session?.role === "owner" || session?.role === "station";
  const isConsole = session?.role === "console";
  const isStationSide = isOwner || isConsole;
  const stations = useMemo(
    () => catalog.stations.filter((row) => row.is_active),
    [catalog.stations]
  );

  useEffect(() => {
    if (isStationSide && page !== "landing" && page !== "dashboard") setPage("dashboard");
  }, [isStationSide, page]);

  useEffect(() => {
    if (isStationSide && stations.length === 1) setDashStationId(stations[0].id);
  }, [isStationSide, stations]);

  const mapPoints = useMemo<MapPoint[]>(() => {
    const stationPoints = stations.map((row) => ({
      id: row.id,
      kind: "station" as const,
      name: row.name,
      lat: row.lat,
      lon: row.lon,
      status: "active",
    }));
    const truckPoints = catalog.trucks
      .filter((row) => row.lat != null && row.lon != null)
      .map((row) => ({
        id: row.id,
        kind: "truck" as const,
        name: row.plate_number,
        lat: row.lat as number,
        lon: row.lon as number,
        status: row.status,
      }));
    return [...stationPoints, ...truckPoints];
  }, [stations, catalog.trucks]);

  const quickStations = useMemo(() => {
    const q = quickQuery.trim().toLowerCase();
    return stations.filter((row) => {
      if (!q) return true;
      return [row.name, row.code, row.address, stationRegion(row)].some((part) =>
        part?.toLowerCase().includes(q)
      );
    });
  }, [stations, quickQuery]);

  const filteredMapStations = useMemo(() => {
    const q = mapSearch.trim().toLowerCase();
    return stations.filter((row) => {
      if (q && ![row.name, row.code, row.address].some((part) => part?.toLowerCase().includes(q))) return false;
      if (mapRegion !== "all" && stationRegion(row) !== mapRegion) return false;
      const live = byCode.get(row.code);
      const fill = live && live.tanks.length > 0 && live.fill != null ? Math.round(live.fill) : null;
      const online = !!live?.tanks.some((tank) => tank.online && tank.remainder_liters != null);
      if (mapStatus === "low" && !isLowFill(fill)) return false;
      if (mapStatus === "offline" && online) return false;
      return true;
    });
  }, [stations, mapSearch, mapRegion, mapStatus, byCode]);

  const selectedStation = selection?.kind === "station" ? stations.find((row) => row.id === selection.id) ?? null : null;
  const selectedTruck = selection?.kind === "truck" ? catalog.trucks.find((row) => row.id === selection.id) ?? null : null;

  function onSelect(point: MapPoint) {
    if (point.kind === "truck" || point.kind === "station") setSelection({ kind: point.kind, id: point.id });
  }

  if (page === "landing" || !session) {
    return <Landing onEnter={() => setPage("dashboard")} />;
  }

  const screen = !admin && (page === "admin" || page === "supply") ? "dashboard" : page;
  const showTrucks = admin && mapHudTab === "trucks";

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <Logo size={32} className="mark" alt="Цифровой след LPG" />
          <div>
            <h1>Цифровой след LPG</h1>
            <span>
              {isOwner
                ? `Владелец · ${stations.length === 1 ? stations[0]?.name ?? "своя заправка" : `${stations.length} АГЗС`}`
                : isConsole
                  ? `Пульт · ${stations[0]?.name ?? "своя заправка"}`
                  : `Диспетчерская платформы · ${stations.length} АГЗС`}
            </span>
          </div>
        </div>
        <nav className="nav-pages" aria-label="Разделы">
          <button
            type="button"
            className={`nav-page${screen === "dashboard" ? " active" : ""}`}
            onClick={() => {
              setDashStationId(isStationSide && stations.length === 1 ? stations[0].id : null);
              setPage("dashboard");
            }}
          >
            {isStationSide ? (stations.length > 1 ? "Мои АГЗС" : "Моя АГЗС") : `Дашборд (${stations.length})`}
          </button>
          {isStationSide ? null : (
            <button type="button" className={`nav-page${screen === "map" ? " active" : ""}`} onClick={() => setPage("map")}>
              Карта
            </button>
          )}
          {admin ? (
            <button type="button" className={`nav-page${screen === "supply" ? " active" : ""}`} onClick={() => setPage("supply")}>
              Поставки
            </button>
          ) : null}
          {admin ? (
            <button type="button" className={`nav-page${screen === "admin" ? " active" : ""}`} onClick={() => setPage("admin")}>
              Администратор
            </button>
          ) : null}
        </nav>
        <div className="quick-jumper" ref={quickRef}>
          <button type="button" className="quick-jumper-btn" onClick={() => setQuickOpen((value) => !value)}>
            <span>Быстрый переход к АГЗС…</span>
            <kbd>{stations.length}</kbd>
          </button>
          {quickOpen ? (
            <div className="quick-jumper-popover">
              <div className="quick-jumper-head">
                <input
                  type="search"
                  autoFocus
                  value={quickQuery}
                  placeholder="Найти АГЗС по названию, коду, району…"
                  onChange={(event) => setQuickQuery(event.target.value)}
                />
              </div>
              <ul className="quick-jumper-list">
                {quickStations.map((row) => {
                  const live = byCode.get(row.code);
                  const hasLive = !!live && live.tanks.length > 0;
                  return (
                    <li key={row.id} className="quick-jumper-item">
                      <div className="quick-jumper-main" onClick={() => openStationPage(row.id)}>
                        <div>
                          <strong>{row.name}</strong>
                          <span className="dash-muted">
                            {row.code} · {stationRegion(row)} ·{" "}
                            {hasLive && live?.remainder != null ? liters(live.remainder) : "замера нет"}
                          </span>
                          {hasLive && live ? <SensorStatus level={live} /> : null}
                        </div>
                      </div>
                    </li>
                  );
                })}
                {quickStations.length === 0 ? <li className="quick-jumper-empty">АГЗС не найдена</li> : null}
              </ul>
            </div>
          ) : null}
        </div>
        <div className="topbar-actions">
          <span className="who">
            {isOwner ? `владелец ${session.username}` : isConsole ? `пульт ${session.username}` : `платформа ${session.username}`}
          </span>
          <button type="button" className="btn secondary small" onClick={() => setPage("landing")}>
            Публичный сайт
          </button>
          <button className="btn secondary small" type="button" onClick={toggle}>
            {theme === "dark" ? "Светлая" : "Тёмная"}
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
        </div>
      </header>

      {screen === "map" ? (
        <main className="page land">
          <div className="map-stage">
            <MapView points={mapPoints} selectedId={selection?.id} onSelect={onSelect} />
          </div>
          <aside className={`map-nav-drawer${mapHudOpen ? " open" : " collapsed"}`}>
            <div className="map-nav-header">
              <div className="map-sim-bar">
                <button type="button" className="btn secondary small" onClick={() => setMapHudOpen((value) => !value)}>
                  {mapHudOpen ? "Свернуть" : `Список (${stations.length})`}
                </button>
              </div>
              {mapHudOpen ? (
                <>
                  <div className="tabs hud-tabs" style={{ padding: "8px 0 0" }}>
                    <button
                      type="button"
                      className={`tab${mapHudTab === "stations" ? " active" : ""}`}
                      onClick={() => setMapHudTab("stations")}
                    >
                      АГЗС ({filteredMapStations.length})
                    </button>
                    {admin ? (
                      <button
                        type="button"
                        className={`tab${mapHudTab === "trucks" ? " active" : ""}`}
                        onClick={() => setMapHudTab("trucks")}
                      >
                        Газовозы ({catalog.trucks.length})
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
                      <select value={mapRegion} onChange={(event) => setMapRegion(event.target.value)} aria-label="Район">
                        <option value="all">Все районы ({stations.length})</option>
                        {REGIONS.map((region) => (
                          <option key={region} value={region}>
                            {region}
                          </option>
                        ))}
                      </select>
                      <div className="map-status-chips">
                        <button type="button" className={`filter-pill${mapStatus === "all" ? " active" : ""}`} onClick={() => setMapStatus("all")}>
                          Все
                        </button>
                        <button type="button" className={`filter-pill${mapStatus === "low" ? " active" : ""}`} onClick={() => setMapStatus("low")}>
                          Мало газа
                        </button>
                        <button type="button" className={`filter-pill${mapStatus === "offline" ? " active" : ""}`} onClick={() => setMapStatus("offline")}>
                          Нет связи
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
                            onClick={() => setSelection({ kind: "station", id: row.id })}
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
                              {fill == null ? "—" : `${fill}%`} ·{" "}
                              {hasLive && live?.remainder != null ? liters(live.remainder) : "замера нет"}
                            </em>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <ul className="object-list">
                    {catalog.trucks.length === 0 ? <li className="dash-muted">Газовозы не заведены.</li> : null}
                    {catalog.trucks.map((row) => (
                      <li key={row.id}>
                        <button
                          type="button"
                          className={`object-row${selection?.kind === "truck" && selection.id === row.id ? " active" : ""}`}
                          onClick={() => setSelection({ kind: "truck", id: row.id })}
                        >
                          <span className="dot truck" />
                          <div className="object-row-info">
                            <strong>{row.plate_number}</strong>
                            <span>{row.carrier_name || "перевозчик не указан"}</span>
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
                onClose={() => setSelection(null)}
                onOpenStation={openStationPage}
              />
            </div>
          ) : null}
        </main>
      ) : screen === "supply" ? (
        <main className="page dash-page" ref={dashRef}>
          <div className="dash">
            <header className="dash-hero">
              <p className="kicker">Контур поставок</p>
              <h2>Партии и рейсы</h2>
            </header>
            <section className="dash-card">
              <h3>Поставки не подключены</h3>
              <p className="dash-muted">
                Рейсов, партий и сливов в кабинете нет. Раздел оставлен в навигации: цифры появятся, когда контур
                будет подключён.
              </p>
            </section>
          </div>
        </main>
      ) : screen === "admin" ? (
        <main className="page dash-page" ref={dashRef}>
          <AdminPage
            initialStationId={adminStationId}
            onOpenStationDashboard={isStationSide ? undefined : openStationPage}
            onOpenStationMap={isStationSide ? undefined : openStationOnMap}
          />
        </main>
      ) : (
        <main className="page dash-page" ref={dashRef}>
          <Dashboard
            stationId={dashStationId}
            onOpenStation={setDashStationId}
            onOpenAdminStation={admin ? openAdminStation : undefined}
            onOpenMapStation={isStationSide ? undefined : openStationOnMap}
          />
        </main>
      )}
    </div>
  );
}
