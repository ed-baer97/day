import { useEffect, useMemo, useRef, useState } from "react";
import type { CatalogStation } from "../api/client";
import Logo from "../components/Logo";
import { liters, stationRegion } from "../format";
import { isLowFill, type LiveLevel, SensorStatus } from "../liveLevels";
import type { AdminSession } from "../session";

export type AppScreen = "landing" | "map" | "dashboard" | "admin" | "supply";

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
  theme,
  onToggleTheme,
  onGoHomeDashboard,
  onSelectPage,
  onOpenStationPage,
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
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onGoHomeDashboard: () => void;
  onSelectPage: (page: AppScreen) => void;
  onOpenStationPage: (id: string) => void;
  onOpenAdminRoot: () => void;
  onLogout: () => void;
}) {
  const [quickOpen, setQuickOpen] = useState(false);
  const [quickQuery, setQuickQuery] = useState("");
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
      if (!q) return true;
      return [row.name, row.code, row.address, stationRegion(row)].some((part) =>
        part?.toLowerCase().includes(q)
      );
    });
  }, [stations, quickQuery]);

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
              ? "Мои АГЗС"
              : "Моя АГЗС"
            : "Дашборд"}
        </button>
        {isStationSide ? null : (
          <button
            type="button"
            className={`nav-page${screen === "map" ? " active" : ""}`}
            onClick={() => onSelectPage("map")}
          >
            Карта
          </button>
        )}
        {admin ? (
          <button
            type="button"
            className={`nav-page${screen === "supply" ? " active" : ""}`}
            onClick={() => onSelectPage("supply")}
          >
            Поставки
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
                  </li>
                );
              })}
              {quickStations.length === 0 ? (
                <li className="quick-jumper-empty">АГЗС не найдена</li>
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
