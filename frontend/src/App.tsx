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
import { balBadge, fiscalBadge, liters, phaseLabel, REGIONS, signedLiters, stationRegion } from "./format";
import { fiscalCheck, stationBalance } from "./sim/engine";
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
  const { overview, routes, state, playing, speed, play, pause, setSpeed, reset, applyFleetCards } = useSim();
  const catalog = useCatalog();
  const [page, setPage] = useState<Page>("landing");
  const [selection, setSelection] = useState<Selection>(null);
  const [dashStationId, setDashStationId] = useState<string | null>(null);
  const [adminStationId, setAdminStationId] = useState<string | null>(null);
  const [supplyId, setSupplyId] = useState<string | null>(IDS.supplyDemo);
  const dashRef = useRef<HTMLElement>(null);

  // Глобальный быстрый переключатель АГЗС в шапке
  const [quickOpen, setQuickOpen] = useState(false);
  const [quickQuery, setQuickQuery] = useState("");
  const quickRef = useRef<HTMLDivElement>(null);

  // Боковой навигатор на карте для большого числа АГЗС
  const [mapHudOpen, setMapHudOpen] = useState(true);
  const [mapHudTab, setMapHudTab] = useState<"stations" | "trucks" | "events">("stations");
  const [mapSearch, setMapSearch] = useState("");
  const [mapRegion, setMapRegion] = useState<string>("all");
  const [mapStatus, setMapStatus] = useState<"all" | "issue" | "kgd" | "low">("all");

  useEffect(() => {
    dashRef.current?.scrollTo(0, 0);
  }, [dashStationId, page, supplyId, adminStationId]);

  useEffect(() => {
    if (catalog.ready) applyFleetCards(catalog.stations, catalog.trucks);
  }, [catalog.ready, catalog.stations, catalog.trucks, applyFleetCards]);

  useEffect(() => {
    function onDocClick(ev: MouseEvent) {
      if (quickRef.current && !quickRef.current.contains(ev.target as Node)) {
        setQuickOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  function openSupply(id: string) {
    setSupplyId(id);
    setPage("supply");
  }

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

  const seenEvents = useRef<Set<string>>(new Set());

  useEffect(() => {
    const inside = page !== "landing" && session;
    for (const ev of state.events) {
      if (seenEvents.current.has(ev.id)) continue;
      seenEvents.current.add(ev.id);
      if (inside && !ev.is_resolved) {
        toast.err(`${ev.title}${ev.delta_liters != null ? `: ${ev.delta_liters} л` : ""}`);
      }
    }
  }, [state.events, toast, page, session]);

  const activeStations = useMemo(() => {
    const hidden = new Set(catalog.stations.filter((row) => !row.is_active).map((row) => row.id));
    return state.stations.filter((s) => !hidden.has(s.detail.id) && s.detail.is_active);
  }, [state.stations, catalog.stations]);

  const mapPoints = useMemo(() => {
    const hidden = new Set(catalog.stations.filter((row) => !row.is_active).map((row) => row.id));
    return overview.points.filter((point) => !hidden.has(point.id));
  }, [overview.points, catalog.stations]);

  const quickStations = useMemo(() => {
    const q = quickQuery.trim().toLowerCase();
    return state.stations.filter((s) => {
      if (!q) return true;
      const d = s.detail;
      return [d.name, d.code, d.address, stationRegion(d)].some((part) =>
        part?.toLowerCase().includes(q)
      );
    });
  }, [state.stations, quickQuery]);

  const filteredMapStations = useMemo(() => {
    const q = mapSearch.trim().toLowerCase();
    return activeStations.filter(({ detail }) => {
      if (q) {
        const hit = [detail.name, detail.code, detail.address].some((p) =>
          p?.toLowerCase().includes(q)
        );
        if (!hit) return false;
      }
      if (mapRegion !== "all" && stationRegion(detail) !== mapRegion) {
        return false;
      }
      if (mapStatus !== "all") {
        const bal = stationBalance(detail);
        const fc = fiscalCheck(detail);
        const fill = detail.capacity_liters
          ? Math.round((bal.storage_actual / detail.capacity_liters) * 100)
          : 0;
        if (mapStatus === "issue" && bal.status === "ok") return false;
        if (mapStatus === "kgd" && fc.status === "ok") return false;
        if (mapStatus === "low" && fill >= 25) return false;
      }
      return true;
    });
  }, [activeStations, mapSearch, mapRegion, mapStatus]);

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
      const evId = point.id.replace("alert-", "");
      const ev = state.events.find((e) => e.id === evId);
      const stId = ev?.station_id ?? IDS.stationN;
      setSelection({ kind: "station", id: stId });
      return;
    }
    if (point.kind === "truck" || point.kind === "station" || point.kind === "factory") {
      setSelection({ kind: point.kind, id: point.id });
    }
  }

  if (page === "landing" || !session) {
    return <Landing onEnter={() => setPage("dashboard")} />;
  }

  const openEventsCount = state.events.filter((e) => !e.is_resolved).length;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <Logo size={32} className="mark" alt="Цифровой след LPG" />
          <div>
            <h1>Цифровой след LPG</h1>
            <span>Диспетчерская · Мангыстау ({activeStations.length} АГЗС)</span>
          </div>
        </div>

        <nav className="nav-pages" aria-label="Разделы">
          <button
            type="button"
            className={`nav-page${page === "dashboard" ? " active" : ""}`}
            onClick={() => {
              setDashStationId(null);
              setPage("dashboard");
            }}
          >
            Дашборд ({activeStations.length})
          </button>
          <button
            type="button"
            className={`nav-page${page === "map" ? " active" : ""}`}
            onClick={() => setPage("map")}
          >
            Карта
          </button>
          <button
            type="button"
            className={`nav-page${page === "supply" ? " active" : ""}`}
            onClick={() => setPage("supply")}
          >
            Поставки ({state.supplies.length})
          </button>
          <button
            type="button"
            className={`nav-page${page === "admin" ? " active" : ""}`}
            onClick={() => setPage("admin")}
          >
            Админка
          </button>
        </nav>

        <div className="quick-jumper" ref={quickRef}>
          <button
            type="button"
            className="quick-jumper-btn"
            onClick={() => setQuickOpen((v) => !v)}
            title="Быстрый поиск и переход к любой АГЗС"
          >
            <span>Быстрый переход к АГЗС…</span>
            <kbd>{state.stations.length}</kbd>
          </button>
          {quickOpen && (
            <div className="quick-jumper-popover">
              <div className="quick-jumper-head">
                <input
                  type="search"
                  autoFocus
                  value={quickQuery}
                  placeholder="Найти АГЗС по названию, коду, району…"
                  onChange={(e) => setQuickQuery(e.target.value)}
                />
              </div>
              <ul className="quick-jumper-list">
                {quickStations.map(({ detail }) => {
                  const bal = stationBalance(detail);
                  const fc = fiscalCheck(detail);
                  const fill = detail.capacity_liters
                    ? Math.round((bal.storage_actual / detail.capacity_liters) * 100)
                    : 0;
                  return (
                    <li key={detail.id} className="quick-jumper-item">
                      <div
                        className="quick-jumper-main"
                        onClick={() => openStationPage(detail.id)}
                      >
                        <div>
                          <strong>{detail.name}</strong>
                          <span className="dash-muted">
                            {detail.code} · {stationRegion(detail)} · {fill}% ({liters(bal.storage_actual)})
                          </span>
                        </div>
                        <div className="quick-jumper-badges">
                          <span className={`badge ${balBadge(bal.status)}`}>
                            {bal.status === "ok" ? "Баланс ОК" : signedLiters(bal.delta)}
                          </span>
                          {fc.status !== "ok" && (
                            <span className={`badge ${fiscalBadge(fc.status)}`}>КГД</span>
                          )}
                        </div>
                      </div>
                      <div className="quick-jumper-actions">
                        <button
                          type="button"
                          className="btn secondary small"
                          onClick={() => openStationPage(detail.id)}
                        >
                          Сводка
                        </button>
                        <button
                          type="button"
                          className="btn secondary small"
                          onClick={() => openStationOnMap(detail.id)}
                        >
                          Карта
                        </button>
                        <button
                          type="button"
                          className="btn secondary small"
                          onClick={() => openAdminStation(detail.id)}
                        >
                          Настроить
                        </button>
                      </div>
                    </li>
                  );
                })}
                {quickStations.length === 0 && (
                  <li className="quick-jumper-empty">АГЗС не найдена</li>
                )}
              </ul>
            </div>
          )}
        </div>

        <div className="topbar-actions">
          <button
            type="button"
            className="stats-chip stats-chip-btn"
            onClick={() => {
              setPage("admin");
            }}
            title="Перейти к инцидентам"
          >
            <span>
              инциденты{" "}
              <strong className={openEventsCount ? "text-danger" : ""}>
                {openEventsCount}
              </strong>
            </span>
          </button>
          <span className="who">{session.username}</span>
          <button type="button" className="btn secondary small" onClick={() => setPage("landing")}>
            Публичный сайт
          </button>
          <button
            className="btn secondary small"
            type="button"
            onClick={toggle}
            aria-label={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
          >
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

      {page === "map" ? (
        <main className="page land">
          <div className="map-stage">
            <MapView
              points={mapPoints}
              routes={routes}
              selectedId={selection?.id}
              onSelect={onSelect}
            />
          </div>

          <aside className={`map-nav-drawer${mapHudOpen ? " open" : " collapsed"}`}>
            <div className="map-nav-header">
              <div className="map-sim-bar">
                <button
                  type="button"
                  className="btn small"
                  onClick={() => (playing ? pause() : play())}
                >
                  {playing ? "Пауза" : "Старт рейсов"}
                </button>
                <div className="sim-speeds">
                  {[1, 5, 20].map((s) => (
                    <button
                      key={s}
                      type="button"
                      className={`filter-pill${speed === s ? " active" : ""}`}
                      onClick={() => setSpeed(s as 1 | 5 | 20)}
                    >
                      {s}×
                    </button>
                  ))}
                </div>
                <button type="button" className="btn secondary small" onClick={reset}>
                  Сброс
                </button>
                <button
                  type="button"
                  className="btn secondary small"
                  onClick={() => setMapHudOpen((v) => !v)}
                  title={mapHudOpen ? "Свернуть список" : "Развернуть список"}
                >
                  {mapHudOpen ? "Свернуть" : `Список (${activeStations.length})`}
                </button>
              </div>

              {mapHudOpen && (
                <>
                  <div className="tabs hud-tabs" style={{ padding: "8px 0 0" }}>
                    <button
                      type="button"
                      className={`tab${mapHudTab === "stations" ? " active" : ""}`}
                      onClick={() => setMapHudTab("stations")}
                    >
                      АГЗС ({filteredMapStations.length})
                    </button>
                    <button
                      type="button"
                      className={`tab${mapHudTab === "trucks" ? " active" : ""}`}
                      onClick={() => setMapHudTab("trucks")}
                    >
                      Газовозы ({state.trucks.length})
                    </button>
                    <button
                      type="button"
                      className={`tab${mapHudTab === "events" ? " active" : ""}`}
                      onClick={() => setMapHudTab("events")}
                    >
                      Инциденты ({openEventsCount})
                    </button>
                  </div>

                  {mapHudTab === "stations" && (
                    <div className="map-nav-filters">
                      <input
                        type="search"
                        value={mapSearch}
                        placeholder="Поиск АГЗС на карте…"
                        onChange={(e) => setMapSearch(e.target.value)}
                      />
                      <select
                        value={mapRegion}
                        onChange={(e) => setMapRegion(e.target.value)}
                        aria-label="Фильтр района"
                      >
                        <option value="all">Все районы ({activeStations.length})</option>
                        {REGIONS.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </select>
                      <div className="map-status-chips">
                        <button
                          type="button"
                          className={`filter-pill${mapStatus === "all" ? " active" : ""}`}
                          onClick={() => setMapStatus("all")}
                        >
                          Все
                        </button>
                        <button
                          type="button"
                          className={`filter-pill${mapStatus === "issue" ? " active" : ""}`}
                          onClick={() => setMapStatus("issue")}
                        >
                          Расхождения
                        </button>
                        <button
                          type="button"
                          className={`filter-pill${mapStatus === "kgd" ? " active" : ""}`}
                          onClick={() => setMapStatus("kgd")}
                        >
                          КГД
                        </button>
                        <button
                          type="button"
                          className={`filter-pill${mapStatus === "low" ? " active" : ""}`}
                          onClick={() => setMapStatus("low")}
                        >
                          Мало газа
                        </button>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>

            {mapHudOpen && (
              <div className="map-nav-body">
                {mapHudTab === "stations" && (
                  <ul className="object-list">
                    {filteredMapStations.map(({ detail }) => {
                      const bal = stationBalance(detail);
                      const fill = detail.capacity_liters
                        ? Math.round((bal.storage_actual / detail.capacity_liters) * 100)
                        : 0;
                      const isSel = selection?.kind === "station" && selection.id === detail.id;
                      return (
                        <li key={detail.id}>
                          <button
                            type="button"
                            className={`object-row${isSel ? " active" : ""}`}
                            onClick={() => setSelection({ kind: "station", id: detail.id })}
                          >
                            <span
                              className="dot station"
                              style={{
                                background:
                                  bal.status === "shortage"
                                    ? "var(--coral)"
                                    : bal.status === "surplus"
                                      ? "var(--dust)"
                                      : "var(--sea)",
                              }}
                            />
                            <div className="object-row-info">
                              <strong>{detail.name}</strong>
                              <span>
                                {detail.code} · {stationRegion(detail)}
                              </span>
                            </div>
                            <em>
                              {fill}% · {liters(bal.storage_actual)}
                            </em>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}

                {mapHudTab === "trucks" && (
                  <ul className="object-list">
                    {state.trucks.map((t) => {
                      const isSel = selection?.kind === "truck" && selection.id === t.detail.id;
                      return (
                        <li key={t.detail.id}>
                          <button
                            type="button"
                            className={`object-row${isSel ? " active" : ""}`}
                            onClick={() => setSelection({ kind: "truck", id: t.detail.id })}
                          >
                            <span className="dot truck" />
                            <div className="object-row-info">
                              <strong>{t.detail.plate_number}</strong>
                              <span>
                                {t.detail.origin_name} → {t.detail.destination_name}
                              </span>
                            </div>
                            <em>
                              {phaseLabel(t.phase)} · {liters(t.cargo)}
                            </em>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}

                {mapHudTab === "events" && (
                  <ul className="object-list">
                    {state.events.map((ev) => (
                      <li key={ev.id}>
                        <button
                          type="button"
                          className="object-row"
                          onClick={() => {
                            if (ev.station_id) {
                              setSelection({ kind: "station", id: ev.station_id });
                            }
                          }}
                        >
                          <span className="dot alert" />
                          <div className="object-row-info">
                            <strong>{ev.title}</strong>
                            <span>{ev.description}</span>
                          </div>
                          <em>{ev.is_resolved ? "Закрыт" : "Открыт"}</em>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </aside>

          {selection && (
            <div className="map-hud map-hud-right">
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
          <AdminPage
            initialStationId={adminStationId}
            onOpenStationDashboard={openStationPage}
            onOpenStationMap={openStationOnMap}
          />
        </main>
      ) : page === "supply" ? (
        <main className="page dash-page" ref={dashRef}>
          <SupplyPage supplyId={supplyId} onSelect={setSupplyId} />
        </main>
      ) : (
        <main className="page dash-page" ref={dashRef}>
          <Dashboard
            stationId={dashStationId}
            onOpenStation={setDashStationId}
            onOpenAdminStation={openAdminStation}
            onOpenMapStation={openStationOnMap}
          />
        </main>
      )}
    </div>
  );
}
