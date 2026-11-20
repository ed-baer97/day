import { useEffect, useMemo, useState, type FormEvent } from "react";
import { isAdmin } from "../access";
import { useAuth } from "../auth";
import { dateTime, liters, percentLabel, REGIONS, stationRegion } from "../format";
import {
  isLowFill,
  SensorStatusBadge,
  summarizeLevel,
  usePublicLevels,
} from "../liveLevels";
import PublicStationModal from "../pages/landing/PublicStationModal";
import { useTheme } from "../theme";
import type { MapPoint } from "../types";
import Logo from "./Logo";
import MapView from "./MapView";

type AvailFilter = "all" | "plenty" | "low";
type PublicSort = "region" | "liters_desc" | "fill_desc" | "name_asc";

export default function Landing({ onEnter }: { onEnter: () => void }) {
  const { theme, toggle } = useTheme();
  const { session, login, logout } = useAuth();
  const { stations: levels, byCode, updatedAt, loading: levelsLoading } = usePublicLevels();
  const [authOpen, setAuthOpen] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [stationQuery, setStationQuery] = useState("");
  const [regionFilter, setRegionFilter] = useState<string>("all");
  const [availFilter, setAvailFilter] = useState<AvailFilter>("all");
  const [sortBy, setSortBy] = useState<PublicSort>("region");
  const [detailCode, setDetailCode] = useState<string | null>(null);

  useEffect(() => {
    if (!authOpen && !detailCode) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setAuthOpen(false);
        setDetailCode(null);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [authOpen, detailCode]);

  const publicMapPoints = useMemo<MapPoint[]>(
    () =>
      levels
        .filter((station) => station.lat != null && station.lon != null)
        .map((station) => ({
          id: station.code,
          kind: "station" as const,
          name: station.name,
          lat: station.lat as number,
          lon: station.lon as number,
          status: "active",
        })),
    [levels]
  );

  const enrichedStations = useMemo(() => {
    return levels.map((station) => {
      const live = byCode.get(station.code) ?? summarizeLevel(station);
      const region = stationRegion(station);
      const online = station.tanks.some((t) => t.online === true && t.remainder_liters != null);
      const hasReading = live.remainder != null;
      const freeLiters =
        live.remainder != null && live.capacity > 0
          ? Math.max(0, live.capacity - live.remainder)
          : null;
      return {
        station,
        live,
        region,
        online,
        hasReading,
        freeLiters,
      };
    });
  }, [levels, byCode]);

  const publicTotals = useMemo(() => {
    let litersSum = 0;
    let plenty = 0;
    for (const item of enrichedStations) {
      if (item.live.remainder != null) litersSum += item.live.remainder;
      if (item.hasReading && !isLowFill(item.live.fill)) plenty++;
    }
    return {
      all: enrichedStations.length,
      litersSum,
      plenty,
    };
  }, [enrichedStations]);

  const regionStats = useMemo(() => {
    return REGIONS.map((region) => ({
      region,
      count: enrichedStations.filter((item) => item.region === region).length,
    })).filter((row) => row.count > 0);
  }, [enrichedStations]);

  const visibleStations = useMemo(() => {
    const query = stationQuery.trim().toLowerCase();
    const filtered = enrichedStations.filter(({ station, live, region, hasReading }) => {
      if (query) {
        const hit = [station.name, station.address, station.code, region].some((part) =>
          part?.toLowerCase().includes(query)
        );
        if (!hit) return false;
      }
      if (regionFilter !== "all" && region !== regionFilter) {
        return false;
      }
      if (availFilter === "plenty" && (!hasReading || isLowFill(live.fill))) return false;
      if (availFilter === "low" && !isLowFill(live.fill)) return false;
      return true;
    });

    return [...filtered].sort((a, b) => {
      if (sortBy === "liters_desc") return (b.live.remainder ?? -1) - (a.live.remainder ?? -1);
      if (sortBy === "fill_desc") return (b.live.fill ?? -1) - (a.live.fill ?? -1);
      if (sortBy === "name_asc") return a.station.name.localeCompare(b.station.name, "ru");
      return (
        a.region.localeCompare(b.region, "ru") ||
        a.station.name.localeCompare(b.station.name, "ru")
      );
    });
  }, [enrichedStations, stationQuery, regionFilter, availFilter, sortBy]);

  const activeDetailIndex = useMemo(
    () => (detailCode ? visibleStations.findIndex((item) => item.station.code === detailCode) : -1),
    [detailCode, visibleStations]
  );
  const activeDetail =
    activeDetailIndex >= 0
      ? visibleStations[activeDetailIndex]
      : detailCode
        ? enrichedStations.find((item) => item.station.code === detailCode) ?? null
        : null;

  const hasFilters = Boolean(stationQuery.trim() || regionFilter !== "all" || availFilter !== "all");

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
      onEnter();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось войти");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="landing">
      <div className="landing-map" aria-hidden="true">
        <MapView
          points={publicMapPoints}
          routes={[]}
          interactive={false}
          markerStyle="dot"
          boundsPadding={{ top: 120, right: 70, bottom: 180, left: 70 }}
        />
      </div>
      <div className="landing-veil" />

      <div className="landing-page">
        <header className="landing-nav">
          <div className="landing-brand">
            <Logo size={34} alt="Цифровой след LPG" />
            <div>
              <p className="kicker">Мангистауская область</p>
              <strong>Цифровой след LPG</strong>
            </div>
          </div>
          <div className="landing-nav-actions">
            <button type="button" className="btn secondary small" onClick={toggle}>
              {theme === "dark" ? "Светлая" : "Тёмная"}
            </button>
            {session ? (
              <>
                <button type="button" className="btn small" onClick={onEnter}>
                  {isAdmin(session) ? "Диспетчерская" : "Кабинет"}
                </button>
                <button type="button" className="btn secondary small" onClick={logout}>
                  Выйти
                </button>
              </>
            ) : (
              <button type="button" className="btn small" onClick={() => setAuthOpen(true)}>
                Войти
              </button>
            )}
          </div>
        </header>

        <main className="landing-shell">
          <section className="landing-top">
            <div>
              <h1>Наличие газа на АГЗС</h1>
              <p className="landing-lead">
                Актуальные остатки сжиженного газа по датчикам резервуаров Мангистауской области.
              </p>
            </div>
            <div className="landing-stats" aria-label="Сводка по сети">
              <div>
                <span>С запасом</span>
                <strong>
                  {publicTotals.plenty} из {publicTotals.all}
                </strong>
              </div>
              <div>
                <span>Всего в наличии</span>
                <strong>{liters(publicTotals.litersSum)}</strong>
              </div>
              <div>
                <span>Обновлено</span>
                <strong>{updatedAt ? dateTime(updatedAt.toISOString()) : "—"}</strong>
              </div>
            </div>
          </section>

          {regionStats.length > 1 ? (
            <div className="landing-region-chips" role="group" aria-label="Фильтр по району">
              <button
                type="button"
                className={`landing-chip${regionFilter === "all" ? " active" : ""}`}
                onClick={() => setRegionFilter("all")}
              >
                Все ({levels.length})
              </button>
              {regionStats.map((row) => {
                const active = regionFilter === row.region;
                return (
                  <button
                    key={row.region}
                    type="button"
                    className={`landing-chip${active ? " active" : ""}`}
                    onClick={() => setRegionFilter(active ? "all" : row.region)}
                  >
                    {row.region} · {row.count}
                  </button>
                );
              })}
            </div>
          ) : null}

          <div className="landing-toolbar">
            <input
              className="level-search"
              type="search"
              value={stationQuery}
              placeholder="Поиск по названию или адресу…"
              aria-label="Найти заправку"
              onChange={(event) => setStationQuery(event.target.value)}
            />
            <div className="mini-tabs" role="group" aria-label="Наличие газа">
              <button
                type="button"
                className={availFilter === "all" ? "active" : ""}
                onClick={() => setAvailFilter("all")}
              >
                Все
              </button>
              <button
                type="button"
                className={availFilter === "plenty" ? "active" : ""}
                onClick={() => setAvailFilter("plenty")}
              >
                Есть газ
              </button>
              <button
                type="button"
                className={availFilter === "low" ? "active" : ""}
                onClick={() => setAvailFilter("low")}
              >
                Мало
              </button>
            </div>
            <select
              className="level-select"
              value={sortBy}
              aria-label="Сортировка"
              onChange={(e) => setSortBy(e.target.value as PublicSort)}
            >
              <option value="region">По району</option>
              <option value="liters_desc">Больше газа (л)</option>
              <option value="fill_desc">Больше запас (%)</option>
              <option value="name_asc">По алфавиту</option>
            </select>
            {hasFilters ? (
              <button
                type="button"
                className="btn secondary small"
                onClick={() => {
                  setStationQuery("");
                  setRegionFilter("all");
                  setAvailFilter("all");
                }}
              >
                Сбросить
              </button>
            ) : null}
          </div>

          <section id="levels" aria-label="Список АГЗС">
            <div className="level-grid">
              {visibleStations.map(({ station, live, region, online }) => {
                const width = Math.max(0, Math.min(100, live.fill ?? 0));
                const lowGas = isLowFill(live.fill);
                return (
                  <article
                    className="level-card level-card-clickable"
                    key={station.code}
                    onClick={() => setDetailCode(station.code)}
                  >
                    <div className="level-card-meta">
                      <span className="landing-card-region">{region}</span>
                      {station.tanks.length > 0 ? (
                        <SensorStatusBadge level={live} />
                      ) : (
                        <span className="badge warn">нет резервуаров</span>
                      )}
                    </div>
                    <header>
                      <h3>{station.name}</h3>
                      <p title={station.address ?? region}>{station.address || region}</p>
                    </header>

                    <div className="landing-card-reading">
                      <strong className={lowGas ? "text-danger" : ""}>
                        {percentLabel(live.fill)}
                      </strong>
                      <span className="landing-card-liters">
                        {live.remainder == null ? "замера нет" : liters(live.remainder)}
                      </span>
                    </div>

                    <div className="public-track" aria-hidden="true">
                      <i
                        style={{
                          width: `${width}%`,
                          background: lowGas
                            ? "var(--coral)"
                            : "linear-gradient(90deg, var(--sea-2), var(--sea))",
                          opacity: online ? 1 : 0.45,
                        }}
                      />
                    </div>

                    <footer className="level-card-footer">
                      <span className="dash-muted">
                        {live.measuredAt ? dateTime(live.measuredAt) : "ожидание замера"}
                        {station.tanks.length > 1 ? ` · ${station.tanks.length} рез.` : ""}
                      </span>
                      <span className="level-card-more">Подробнее →</span>
                    </footer>
                  </article>
                );
              })}
            </div>

            {levelsLoading && levels.length === 0 ? (
              <p className="dash-muted" style={{ marginTop: 18 }}>
                Загрузка…
              </p>
            ) : null}
            {!levelsLoading && levels.length > 0 && visibleStations.length === 0 ? (
              <p className="dash-muted" style={{ marginTop: 18 }}>
                По выбранному фильтру заправок не найдено.
              </p>
            ) : null}
          </section>

          <footer className="landing-footer">
            <p>
              Публикуются только текущие остатки газа на АГЗС. Учёт поставок и колонок доступен
              авторизованным пользователям.
            </p>
            {!session ? (
              <button
                type="button"
                className="btn secondary small"
                onClick={() => setAuthOpen(true)}
              >
                Войти в кабинет
              </button>
            ) : null}
          </footer>
        </main>
      </div>

      {activeDetail ? (
        <PublicStationModal
          station={activeDetail.station}
          live={activeDetail.live}
          region={activeDetail.region}
          freeLiters={activeDetail.freeLiters}
          onClose={() => setDetailCode(null)}
          onPrev={
            visibleStations.length > 1
              ? () => {
                  const idx =
                    activeDetailIndex > 0 ? activeDetailIndex - 1 : visibleStations.length - 1;
                  setDetailCode(visibleStations[idx].station.code);
                }
              : undefined
          }
          onNext={
            visibleStations.length > 1
              ? () => {
                  const idx =
                    activeDetailIndex >= 0 && activeDetailIndex < visibleStations.length - 1
                      ? activeDetailIndex + 1
                      : 0;
                  setDetailCode(visibleStations[idx].station.code);
                }
              : undefined
          }
        />
      ) : null}

      {authOpen && !session ? (
        <div className="login-layer" onClick={() => setAuthOpen(false)}>
          <form
            className="login-card"
            onClick={(event) => event.stopPropagation()}
            onSubmit={onSubmit}
          >
            <h2>Вход в систему</h2>
            <p>Доступ для администраторов платформы и владельцев АГЗС.</p>
            <label>
              Логин
              <input
                name="username"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
              />
            </label>
            <label>
              Пароль
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </label>
            {error ? (
              <p className="tank-error" role="alert">
                {error}
              </p>
            ) : null}
            <div className="login-actions">
              <button className="btn secondary" type="button" onClick={() => setAuthOpen(false)}>
                Закрыть
              </button>
              <button className="btn" type="submit" disabled={busy}>
                {busy ? "Проверяем…" : "Войти"}
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}
