import { useEffect, useMemo, useRef, useState } from "react";
import type { CatalogStation } from "../api/client";
import Logo from "../components/Logo";
import { liters, stationRegion } from "../format";
import { isLowFill, type LiveLevel, SensorStatus } from "../liveLevels";
import type { AdminSession } from "../session";

export type AppScreen = "landing" | "map" | "dashboard" | "admin" | "supply";
export type QuickFilter = "all" | "low" | "offline" | "online";

export interface NetworkStats {
  litersSum: number;
  capSum: number;
  freeSum: number;
  online: number;
  offline: number;
  low: number;
}

export default function Topbar({
  session,
  admin,
  isOwner,
  isStationSide,
  screen,
  stations,
  byCode,
  mapPointsCount,
  trucksCount,
  networkStats,
  theme,
  onToggleTheme,
  onGoHomeDashboard,
  onSelectPage,
  onOpenStationPage,
  onOpenStationOnMap,
  onOpenAdminStation,
  onOpenAdminRoot,
  onLogout,
}: {
  session: AdminSession;
  admin: boolean;
  isOwner: boolean;
  isStationSide: boolean;
  screen: AppScreen;
  stations: CatalogStation[];
  byCode: Map<string, LiveLevel>;
  mapPointsCount: number;
  trucksCount: number;
  networkStats: NetworkStats;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onGoHomeDashboard: () => void;
  onSelectPage: (page: AppScreen) => void;
  onOpenStationPage: (id: string) => void;
  onOpenStationOnMap: (id: string) => void;
  onOpenAdminStation: (id: string) => void;
  onOpenAdminRoot: () => void;
  onLogout: () => void;
}) {
  const [quickOpen, setQuickOpen] = useState(false);
  const [quickQuery, setQuickQuery] = useState("");
  const [quickFilter, setQuickFilter] = useState<QuickFilter>("all");
  const quickRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(event: MouseEvent) {
      if (quickRef.current && !quickRef.current.contains(event.target as Node)) {
        setQuickOpen(false);
      }
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

  return (
    <header className="topbar">
      <div
        className="brand"
        onClick={onGoHomeDashboard}
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
          onClick={onGoHomeDashboard}
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
            onClick={() => onSelectPage("map")}
          >
            Карта ({mapPointsCount})
          </button>
        )}
        {admin ? (
          <button
            type="button"
            className={`nav-page${screen === "supply" ? " active" : ""}`}
            onClick={() => onSelectPage("supply")}
          >
            Поставки ({trucksCount})
          </button>
        ) : null}
        {admin ? (
          <button
            type="button"
            className={`nav-page${screen === "admin" ? " active" : ""}`}
            onClick={onOpenAdminRoot}
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
                    <div
                      className="quick-jumper-main"
                      onClick={() => {
                        setQuickOpen(false);
                        onOpenStationPage(row.id);
                      }}
                    >
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
                        onClick={() => {
                          setQuickOpen(false);
                          onOpenStationPage(row.id);
                        }}
                      >
                        Сводка
                      </button>
                      {!isStationSide ? (
                        <button
                          type="button"
                          className="btn secondary small"
                          onClick={() => {
                            setQuickOpen(false);
                            onOpenStationOnMap(row.id);
                          }}
                        >
                          На карте
                        </button>
                      ) : null}
                      {admin ? (
                        <button
                          type="button"
                          className="btn secondary small"
                          onClick={() => {
                            setQuickOpen(false);
                            onOpenAdminStation(row.id);
                          }}
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
          {isOwner ? `владелец ${session.username}` : `админ ${session.username}`}
        </span>
        <button type="button" className="btn secondary small" onClick={() => onSelectPage("landing")}>
          Публичная витрина
        </button>
        <button className="btn secondary small" type="button" onClick={onToggleTheme}>
          {theme === "dark" ? "Светлая" : "Тёмная"}
        </button>
        <button type="button" className="btn secondary small" onClick={onLogout}>
          Выйти
        </button>
      </div>
    </header>
  );
}
