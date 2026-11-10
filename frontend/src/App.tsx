import { useEffect, useMemo, useRef, useState } from "react";
import { isAdmin } from "./access";
import { api, type BatchRecord } from "./api/client";
import { useAuth } from "./auth";
import { useCatalog } from "./catalog";
import AdminPage from "./components/AdminPage";
import Dashboard from "./components/Dashboard";
import Landing from "./components/Landing";
import Logo from "./components/Logo";
import MapPopup from "./components/MapPopup";
import MapView from "./components/MapView";
import { dateTime, liters, phaseLabel, REGIONS, stationRegion } from "./format";
import { isLowFill, LOW_FILL_PERCENT, SensorStatus, sensorLabel, usePublicLevels } from "./liveLevels";
import { useTheme } from "./theme";
import type { MapPoint } from "./types";

type Page = "landing" | "map" | "dashboard" | "admin" | "supply";
type Selection = { kind: "truck"; id: string } | { kind: "station"; id: string } | null;
type QuickFilter = "all" | "low" | "offline" | "online";

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
  const [adminTruckId, setAdminTruckId] = useState<string | null>(null);
  const dashRef = useRef<HTMLElement>(null);

  const [quickOpen, setQuickOpen] = useState(false);
  const [quickQuery, setQuickQuery] = useState("");
  const [quickFilter, setQuickFilter] = useState<QuickFilter>("all");
  const quickRef = useRef<HTMLDivElement>(null);

  const [mapHudOpen, setMapHudOpen] = useState(true);
  const [mapHudTab, setMapHudTab] = useState<"stations" | "trucks">("stations");
  const [mapSearch, setMapSearch] = useState("");
  const [mapRegion, setMapRegion] = useState("all");
  const [mapStatus, setMapStatus] = useState<"all" | "low" | "offline">("all");
  const [batches, setBatches] = useState<BatchRecord[]>([]);

  useEffect(() => {
    dashRef.current?.scrollTo(0, 0);
  }, [dashStationId, page, adminStationId, adminTruckId]);

  useEffect(() => {
    function onDocClick(event: MouseEvent) {
      if (quickRef.current && !quickRef.current.contains(event.target as Node)) setQuickOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setQuickOpen((prev) => !prev);
      } else if (event.key === "Escape") {
        setQuickOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  useEffect(() => {
    if (!admin || page !== "supply") return;
    let alive = true;
    api
      .batches()
      .then((rows) => {
        if (alive) setBatches(rows);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [admin, page]);

  function openStationPage(id: string) {
    setDashStationId(id);
    setPage("dashboard");
    setQuickOpen(false);
  }

  function openStationOnMap(id: string) {
    setSelection({ kind: "station", id });
    setMapHudTab("stations");
    setPage("map");
    setQuickOpen(false);
  }

  function openTruckOnMap(id: string) {
    setSelection({ kind: "truck", id });
    setMapHudTab("trucks");
    setPage("map");
    setQuickOpen(false);
  }

  function openAdminStation(id: string) {
    setAdminTruckId(null);
    setAdminStationId(id);
    setPage("admin");
    setQuickOpen(false);
  }

  function openAdminTruck(id: string) {
    setAdminStationId(null);
    setAdminTruckId(id);
    setPage("admin");
    setQuickOpen(false);
  }

  const isOwner = session?.role === "owner" || session?.role === "station";
  const isStationSide = isOwner;
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

  const networkStats = useMemo(() => {
    let litersSum = 0;
    let capSum = 0;
    let online = 0;
    let offline = 0;
    let low = 0;
    for (const row of stations) {
      const live = byCode.get(row.code);
      const hasTanks = !!live && live.tanks.length > 0;
      const fill = hasTanks && live?.fill != null ? Math.round(live.fill) : null;
      const isOnline =
        !!live && live.tanks.some((tank) => tank.online === true && tank.remainder_liters != null);
      if (hasTanks && live) {
        capSum += live.capacity;
        if (live.remainder != null) litersSum += live.remainder;
        if (isOnline) online++;
        else offline++;
      } else {
        offline++;
      }
      if (isLowFill(fill)) low++;
    }
    return {
      litersSum,
      capSum,
      freeSum: Math.max(0, capSum - litersSum),
      online,
      offline,
      low,
    };
  }, [stations, byCode]);

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
      if (q) {
        const hit = [row.name, row.code, row.address, stationRegion(row)].some((part) =>
          part?.toLowerCase().includes(q)
        );
        if (!hit) return false;
      }
      const live = byCode.get(row.code);
      const hasLive = !!live && live.tanks.length > 0;
      const fill = hasLive && live?.fill != null ? Math.round(live.fill) : null;
      const online = !!live?.tanks.some((t) => t.online && t.remainder_liters != null);
      if (quickFilter === "low" && !isLowFill(fill)) return false;
      if (quickFilter === "offline" && online) return false;
      if (quickFilter === "online" && !online) return false;
      return true;
    });
  }, [stations, quickQuery, quickFilter, byCode]);

  const filteredMapStations = useMemo(() => {
    const q = mapSearch.trim().toLowerCase();
    return stations.filter((row) => {
      if (
        q &&
        ![row.name, row.code, row.address, stationRegion(row)].some((part) =>
          part?.toLowerCase().includes(q)
        )
      )
        return false;
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
    selection?.kind === "truck"
      ? (catalog.trucks.find((row) => row.id === selection.id) ?? null)
      : null;

  const screen = !admin && (page === "admin" || page === "supply") ? "dashboard" : page;
  const showTrucks = admin && mapHudTab === "trucks";

  // Определяем текущую активную станцию для сквозных хлебных крошек и быстрого переключения режимов
  const activeContextStation = useMemo(() => {
    const id =
      screen === "dashboard"
        ? dashStationId
        : screen === "admin"
          ? adminStationId
          : screen === "map" && selection?.kind === "station"
            ? selection.id
            : null;
    if (!id) return null;
    return catalog.stations.find((row) => row.id === id) ?? null;
  }, [screen, dashStationId, adminStationId, selection, catalog.stations]);

  function onSelect(point: MapPoint) {
    if (point.kind === "truck" || point.kind === "station")
      setSelection({ kind: point.kind, id: point.id });
  }

  function goHomeDashboard() {
    setDashStationId(isStationSide && stations.length === 1 ? stations[0].id : null);
    setAdminStationId(null);
    setAdminTruckId(null);
    setPage("dashboard");
  }

  if (page === "landing" || !session) {
    return <Landing onEnter={() => setPage("dashboard")} />;
  }

  return (
    <div className="app">
      <header className="topbar">
        <div
          className="brand"
          onClick={goHomeDashboard}
          style={{ cursor: "pointer" }}
          title="Перейти на главную сводку"
        >
          <Logo size={32} className="mark" alt="Цифровой след LPG" />
          <div>
            <h1>Цифровой след LPG</h1>
            <span>
              {isOwner
                ? `Владелец · ${stations.length === 1 ? (stations[0]?.name ?? "своя заправка") : `${stations.length} АГЗС`}`
                : `Диспетчерская платформы · ${stations.length} АГЗС`}
            </span>
          </div>
        </div>

        <nav className="nav-pages" aria-label="Разделы">
          <button
            type="button"
            className={`nav-page${screen === "dashboard" ? " active" : ""}`}
            onClick={goHomeDashboard}
          >
            {isStationSide
              ? stations.length > 1
                ? `Мои АГЗС (${stations.length})`
                : "Моя АГЗС"
              : `Дашборд (${stations.length})`}
          </button>
          {isStationSide ? null : (
            <button
              type="button"
              className={`nav-page${screen === "map" ? " active" : ""}`}
              onClick={() => setPage("map")}
            >
              Карта ({mapPoints.length})
            </button>
          )}
          {admin ? (
            <button
              type="button"
              className={`nav-page${screen === "supply" ? " active" : ""}`}
              onClick={() => setPage("supply")}
            >
              Поставки ({catalog.trucks.length})
            </button>
          ) : null}
          {admin ? (
            <button
              type="button"
              className={`nav-page${screen === "admin" ? " active" : ""}`}
              onClick={() => {
                setAdminStationId(null);
                setAdminTruckId(null);
                setPage("admin");
              }}
            >
              Администратор
            </button>
          ) : null}
        </nav>

        {!isStationSide ? (
          <div className="stats-chip" aria-label="Сводка по сети">
            <span>
              Газ: <strong>{liters(networkStats.litersSum)}</strong>
            </span>
            <span>
              Онлайн:{" "}
              <strong>
                {networkStats.online}/{stations.length}
              </strong>
            </span>
            {networkStats.low > 0 ? (
              <button
                type="button"
                className="stats-chip-btn text-danger"
                onClick={() => {
                  setQuickFilter("low");
                  setQuickOpen(true);
                }}
                title="Показать АГЗС с малым остатком газа"
              >
                Мало газа: <strong>{networkStats.low}</strong>
              </button>
            ) : null}
          </div>
        ) : null}

        <div className="quick-jumper" ref={quickRef}>
          <button
            type="button"
            className="quick-jumper-btn"
            onClick={() => setQuickOpen((value) => !value)}
            title="Быстрый поиск и переход к любой АГЗС (Ctrl+K)"
          >
            <span>Быстрый переход к АГЗС…</span>
            <kbd>Ctrl+K · {stations.length}</kbd>
          </button>
          {quickOpen ? (
            <div className="quick-jumper-popover">
              <div className="quick-jumper-head">
                <input
                  type="search"
                  autoFocus
                  value={quickQuery}
                  placeholder="Найти АГЗС по названию, коду, адресу или району…"
                  onChange={(event) => setQuickQuery(event.target.value)}
                />
                <div className="st-status-pills" style={{ marginTop: 8 }}>
                  <button
                    type="button"
                    className={`filter-pill${quickFilter === "all" ? " active" : ""}`}
                    onClick={() => setQuickFilter("all")}
                  >
                    Все ({stations.length})
                  </button>
                  <button
                    type="button"
                    className={`filter-pill${quickFilter === "low" ? " active" : ""}`}
                    onClick={() => setQuickFilter("low")}
                  >
                    Мало газа ({networkStats.low})
                  </button>
                  <button
                    type="button"
                    className={`filter-pill${quickFilter === "offline" ? " active" : ""}`}
                    onClick={() => setQuickFilter("offline")}
                  >
                    Нет связи ({networkStats.offline})
                  </button>
                  <button
                    type="button"
                    className={`filter-pill${quickFilter === "online" ? " active" : ""}`}
                    onClick={() => setQuickFilter("online")}
                  >
                    Онлайн ({networkStats.online})
                  </button>
                </div>
              </div>
              <ul className="quick-jumper-list">
                {quickStations.map((row) => {
                  const live = byCode.get(row.code);
                  const hasLive = !!live && live.tanks.length > 0;
                  const fill = hasLive && live?.fill != null ? Math.round(live.fill) : null;
                  return (
                    <li key={row.id} className="quick-jumper-item">
                      <div className="quick-jumper-main" onClick={() => openStationPage(row.id)}>
                        <div>
                          <strong>
                            {row.name}{" "}
                            {fill != null ? (
                              <span className={isLowFill(fill) ? "text-danger" : ""}>
                                ({fill}%)
                              </span>
                            ) : null}
                          </strong>
                          <span className="dash-muted">
                            {row.code} · {stationRegion(row)} ·{" "}
                            {hasLive && live?.remainder != null
                              ? `${liters(live.remainder)} из ${liters(live.capacity)}`
                              : "замера нет"}
                          </span>
                        </div>
                        <div className="quick-jumper-badges">
                          {hasLive && live ? (
                            <SensorStatus level={live} />
                          ) : (
                            <span className="badge warn">нет датчика</span>
                          )}
                        </div>
                      </div>
                      <div className="quick-jumper-actions">
                        <button
                          type="button"
                          className="btn secondary small"
                          onClick={() => openStationPage(row.id)}
                        >
                          Сводка
                        </button>
                        {!isStationSide ? (
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() => openStationOnMap(row.id)}
                          >
                            На карте
                          </button>
                        ) : null}
                        {admin ? (
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() => openAdminStation(row.id)}
                          >
                            Админка
                          </button>
                        ) : null}
                      </div>
                    </li>
                  );
                })}
                {quickStations.length === 0 ? (
                  <li className="quick-jumper-empty">АГЗС по заданному фильтру не найдена</li>
                ) : null}
              </ul>
            </div>
          ) : null}
        </div>

        <div className="topbar-actions">
          <span className="who">
            {isOwner
              ? `владелец ${session.username}`
              : `админ ${session.username}`}
          </span>
          <button type="button" className="btn secondary small" onClick={() => setPage("landing")}>
            Публичная витрина
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

      <div className="breadcrumb-bar" role="navigation" aria-label="Путь по разделу">
        <div className="breadcrumb-trail">
          <button type="button" className="breadcrumb-link" onClick={goHomeDashboard}>
            {isStationSide ? "Кабинет АГЗС" : "Диспетчерская"}
          </button>
          <span className="breadcrumb-sep">/</span>
          <button
            type="button"
            className={`breadcrumb-link${!activeContextStation ? " current" : ""}`}
            onClick={() => {
              if (screen === "dashboard") setDashStationId(null);
              if (screen === "admin") {
                setAdminStationId(null);
                setAdminTruckId(null);
              }
            }}
          >
            {screen === "dashboard"
              ? "Мониторинг сети АГЗС"
              : screen === "map"
                ? "Интерактивная карта"
                : screen === "supply"
                  ? "Контур поставок и газовозов"
                  : "Панель администратора"}
          </button>
          {activeContextStation ? (
            <>
              <span className="breadcrumb-sep">/</span>
              <span className="dash-muted">{stationRegion(activeContextStation)}</span>
              <span className="breadcrumb-sep">/</span>
              <strong className="breadcrumb-current">
                {activeContextStation.name} ({activeContextStation.code})
              </strong>
            </>
          ) : null}
        </div>

        {activeContextStation ? (
          <div className="breadcrumb-actions">
            <span className="dash-muted">Режим просмотра станции:</span>
            <button
              type="button"
              className={`filter-pill${screen === "dashboard" && dashStationId === activeContextStation.id ? " active" : ""}`}
              onClick={() => openStationPage(activeContextStation.id)}
            >
              Сводка и графики
            </button>
            {!isStationSide ? (
              <button
                type="button"
                className={`filter-pill${screen === "map" && selection?.id === activeContextStation.id ? " active" : ""}`}
                onClick={() => openStationOnMap(activeContextStation.id)}
              >
                На карте
              </button>
            ) : null}
            {admin ? (
              <button
                type="button"
                className={`filter-pill${screen === "admin" && adminStationId === activeContextStation.id ? " active" : ""}`}
                onClick={() => openAdminStation(activeContextStation.id)}
              >
                Настройки в админке
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      {screen === "map" ? (
        <main className="page land">
          <div className="map-stage">
            <MapView points={mapPoints} selectedId={selection?.id} onSelect={onSelect} />
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
                    {catalog.trucks.length === 0 ? (
                      <li className="dash-muted">Газовозы не заведены.</li>
                    ) : null}
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
                onClose={() => setSelection(null)}
                onOpenStation={openStationPage}
                onOpenAdminStation={admin ? openAdminStation : undefined}
                onOpenAdminTruck={admin ? openAdminTruck : undefined}
              />
            </div>
          ) : null}
        </main>
      ) : screen === "supply" ? (
        <main className="page dash-page" ref={dashRef}>
          <div className="dash">
            <header className="dash-hero">
              <div>
                <p className="kicker">Логистический контур · Мангистауская область</p>
                <h2>Планирование поставок, газовозы и партии LPG</h2>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  className="btn secondary small"
                  onClick={() => {
                    setMapHudTab("trucks");
                    setPage("map");
                  }}
                >
                  Газовозы на карте ({catalog.trucks.length})
                </button>
                <button
                  type="button"
                  className="btn small"
                  onClick={() => {
                    setAdminStationId(null);
                    setAdminTruckId("new");
                    setPage("admin");
                  }}
                >
                  + Добавить газовоз
                </button>
              </div>
            </header>

            <div className="dash-kpis">
              <div className="dash-kpi">
                <span>Парк газовозов</span>
                <strong>{catalog.trucks.length}</strong>
                <em>
                  общая вместимость:{" "}
                  {liters(catalog.trucks.reduce((s, t) => s + (t.capacity_liters || 0), 0))}
                </em>
              </div>
              <div className="dash-kpi">
                <span>АГЗС требуют подвоза (&lt; {LOW_FILL_PERCENT}%)</span>
                <strong className={networkStats.low > 0 ? "text-danger" : ""}>
                  {networkStats.low}
                </strong>
                <em>приоритетные станции</em>
              </div>
              <div className="dash-kpi">
                <span>Свободная ёмкость сети</span>
                <strong>{liters(networkStats.freeSum)}</strong>
                <em>доступно под слив по всем АГЗС</em>
              </div>
              <div className="dash-kpi">
                <span>Партий в реестре</span>
                <strong>{batches.length}</strong>
                <em>цифровой след партий LPG</em>
              </div>
            </div>

            <section className="dash-section">
              <div className="card-head-inline">
                <h3>Приоритет подвоза газа по АГЗС (по остатку в резервуарах)</h3>
              </div>
              <div className="dash-table-wrap">
                <table className="dash-table">
                  <thead>
                    <tr>
                      <th>АГЗС и район</th>
                      <th>Уровень %</th>
                      <th>Фактический остаток</th>
                      <th>Полная ёмкость</th>
                      <th>Рекомендуемый слив (до 85%)</th>
                      <th>Макс. свободно (до 100%)</th>
                      <th>Датчик</th>
                      <th>Переход</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...stations]
                      .map((st) => {
                        const live = byCode.get(st.code) ?? null;
                        const hasLive = !!live && live.tanks.length > 0;
                        const fill = hasLive && live?.fill != null ? Math.round(live.fill) : null;
                        const rem = hasLive ? (live?.remainder ?? null) : null;
                        const cap = hasLive ? (live?.capacity ?? 0) : 0;
                        const free = rem != null && cap > 0 ? Math.max(0, cap - rem) : null;
                        const safe =
                          rem != null && cap > 0
                            ? Math.max(0, Math.round(cap * 0.85) - rem)
                            : null;
                        return { st, live, hasLive, fill, rem, cap, free, safe };
                      })
                      .sort((a, b) => (a.fill ?? 101) - (b.fill ?? 101))
                      .map(({ st, live, hasLive, fill, rem, cap, free, safe }) => (
                        <tr key={st.id} className="dash-row-link" onClick={() => openStationPage(st.id)}>
                          <td>
                            <strong>{st.name}</strong>
                            <div className="dash-muted">
                              {st.code} · {stationRegion(st)}
                            </div>
                          </td>
                          <td>
                            <strong className={isLowFill(fill) ? "text-danger" : ""}>
                              {fill == null ? "—" : `${fill}%`}
                            </strong>
                          </td>
                          <td>{rem == null ? "замера нет" : liters(rem)}</td>
                          <td>{liters(cap)}</td>
                          <td>
                            <strong>{safe == null ? "—" : liters(safe)}</strong>
                          </td>
                          <td>{free == null ? "—" : liters(free)}</td>
                          <td>
                            {hasLive && live ? (
                              <SensorStatus level={live} />
                            ) : (
                              <span className="badge warn">не подключён</span>
                            )}
                          </td>
                          <td onClick={(e) => e.stopPropagation()}>
                            <div style={{ display: "flex", gap: 4 }}>
                              <button
                                type="button"
                                className="btn secondary small"
                                onClick={() => openStationPage(st.id)}
                              >
                                Сводка
                              </button>
                              <button
                                type="button"
                                className="btn secondary small"
                                onClick={() => openStationOnMap(st.id)}
                              >
                                Карта
                              </button>
                              <button
                                type="button"
                                className="btn secondary small"
                                onClick={() => openAdminStation(st.id)}
                              >
                                Принять слив
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="dash-section">
              <h3>Автопарк газовозов ({catalog.trucks.length})</h3>
              {catalog.trucks.length === 0 ? (
                <p className="empty">Газовозы ещё не добавлены в каталог.</p>
              ) : (
                <div className="dash-table-wrap">
                  <table className="dash-table">
                    <thead>
                      <tr>
                        <th>Госномер</th>
                        <th>Перевозчик</th>
                        <th>Объём цистерны</th>
                        <th>Статус рейса</th>
                        <th>Координаты GPS</th>
                        <th>Действия</th>
                      </tr>
                    </thead>
                    <tbody>
                      {catalog.trucks.map((tr) => (
                        <tr key={tr.id}>
                          <td>
                            <strong>{tr.plate_number}</strong>
                          </td>
                          <td>{tr.carrier_name || "—"}</td>
                          <td>{liters(tr.capacity_liters)}</td>
                          <td>
                            <span className="badge ok">{phaseLabel(tr.status)}</span>
                          </td>
                          <td>
                            {tr.lat != null && tr.lon != null
                              ? `${tr.lat.toFixed(4)}, ${tr.lon.toFixed(4)}`
                              : "нет координат"}
                          </td>
                          <td>
                            <div style={{ display: "flex", gap: 6 }}>
                              {tr.lat != null && tr.lon != null ? (
                                <button
                                  type="button"
                                  className="btn secondary small"
                                  onClick={() => openTruckOnMap(tr.id)}
                                >
                                  На карте
                                </button>
                              ) : null}
                              <button
                                type="button"
                                className="btn secondary small"
                                onClick={() => openAdminTruck(tr.id)}
                              >
                                Редактировать
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {batches.length > 0 ? (
              <section className="dash-section">
                <h3>Зарегистрированные партии газа ({batches.length})</h3>
                <div className="dash-table-wrap">
                  <table className="dash-table">
                    <thead>
                      <tr>
                        <th>Код партии</th>
                        <th>Марка</th>
                        <th>Объём</th>
                        <th>Статус</th>
                        <th>Дата регистрации</th>
                        <th>Примечание</th>
                      </tr>
                    </thead>
                    <tbody>
                      {batches.map((b) => (
                        <tr key={b.id}>
                          <td>
                            <strong>{b.trail_code}</strong>
                          </td>
                          <td>{b.product_grade || "ПБТ"}</td>
                          <td>{liters(b.volume_liters)}</td>
                          <td>
                            <span className="badge ok">{b.status}</span>
                          </td>
                          <td>{dateTime(b.created_at)}</td>
                          <td className="dash-muted">{b.notes || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            ) : null}
          </div>
        </main>
      ) : screen === "admin" ? (
        <main className="page dash-page" ref={dashRef}>
          <AdminPage
            initialStationId={adminStationId}
            initialTruckId={adminTruckId}
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
            showOverviewCharts={isOwner}
          />
        </main>
      )}
    </div>
  );
}
