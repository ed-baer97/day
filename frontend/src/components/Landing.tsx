import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useAuth } from "../auth";
import { dateTime, liters, REGIONS, stationRegion } from "../format";
import { isLowFill, LOW_FILL_PERCENT, usePublicLevels } from "../liveLevels";
import Logo from "./Logo";
import MapView from "./MapView";
import { useTheme } from "../theme";
import type { MapPoint } from "../types";

function percentLabel(value: number) {
  return String(Math.round(value));
}

function jump(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

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
  const [availFilter, setAvailFilter] = useState<"all" | "plenty" | "low">("all");

  useEffect(() => {
    if (!authOpen) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setAuthOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [authOpen]);

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

  const visibleStations = useMemo(() => {
    const query = stationQuery.trim().toLowerCase();
    return levels.filter((station) => {
      if (query) {
        const hit = [station.name, station.address, station.code].some((part) =>
          part?.toLowerCase().includes(query)
        );
        if (!hit) return false;
      }
      if (regionFilter !== "all" && stationRegion(station) !== regionFilter) {
        return false;
      }
      if (availFilter !== "all") {
        const fill = byCode.get(station.code)?.fill ?? null;
        if (availFilter === "plenty" && (fill == null || isLowFill(fill))) return false;
        if (availFilter === "low" && !isLowFill(fill)) return false;
      }
      return true;
    });
  }, [levels, byCode, stationQuery, regionFilter, availFilter]);

  const totalPublicLiters = useMemo(
    () => levels.reduce((sum, station) => sum + (byCode.get(station.code)?.remainder ?? 0), 0),
    [levels, byCode]
  );

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
            <Logo size={36} alt="Цифровой след LPG" />
            <div>
              <p className="kicker">Мангыстау</p>
              <strong>Цифровой след LPG</strong>
            </div>
          </div>
          <nav className="landing-links" aria-label="Страница">
            <button type="button" onClick={() => jump("levels")}>
              Наличие газа на АГЗС ({levels.length})
            </button>
            <button type="button" onClick={() => jump("project")}>
              О проекте
            </button>
          </nav>
          <div className="landing-nav-actions">
            <button type="button" className="btn secondary small" onClick={toggle}>
              {theme === "dark" ? "Светлая" : "Тёмная"}
            </button>
            {session ? (
              <>
                <button type="button" className="btn small" onClick={onEnter}>
                  Администратор
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

        <section className="landing-hero">
          <div className="landing-copy">
            <p className="kicker">Открытая витрина · Мангистауская область</p>
            <h1>Наличие сжиженного газа на АГЗС</h1>
            <p className="landing-prose">
              Публичный мониторинг остатков газа на автогазозаправочных станциях региона в реальном
              времени. Логистика, сверка баланса и диспетчерский контроль доступны только внутри
              защищённой панели администратора.
            </p>
            <div className="landing-hero-actions">
              <button type="button" className="btn" onClick={() => jump("levels")}>
                Смотреть остатки газа ({levels.length} АГЗС)
              </button>
              {session ? (
                <button type="button" className="btn secondary" onClick={onEnter}>
                  Открыть панель управления
                </button>
              ) : (
                <button type="button" className="btn secondary" onClick={() => setAuthOpen(true)}>
                  Вход в админ-панель
                </button>
              )}
            </div>
          </div>
        </section>

        <section className="landing-section" id="levels">
          <div className="level-head">
            <div>
              <p className="kicker">Публичные данные · {levels.length} АГЗС · всего {liters(totalPublicLiters)}</p>
              <h2>Количество газа на АГЗС</h2>
              {updatedAt ? (
                <p className="public-fresh">Обновлено {dateTime(updatedAt.toISOString())}</p>
              ) : null}
            </div>
            <div className="level-controls">
              <input
                className="level-search"
                type="search"
                value={stationQuery}
                placeholder="Поиск по названию, коду или адресу…"
                aria-label="Найти заправку"
                onChange={(event) => setStationQuery(event.target.value)}
              />
              <select
                className="level-select"
                value={availFilter}
                aria-label="Фильтр наличия газа"
                onChange={(e) => setAvailFilter(e.target.value as "all" | "plenty" | "low")}
              >
                <option value="all">Все станции ({levels.length})</option>
                <option value="plenty">Достаточно газа (≥ {LOW_FILL_PERCENT}%)</option>
                <option value="low">Мало газа (&lt; {LOW_FILL_PERCENT}%)</option>
              </select>
            </div>
          </div>

          <div className="region-pills" role="group" aria-label="Районы">
            <button
              type="button"
              className={`filter-pill${regionFilter === "all" ? " active" : ""}`}
              onClick={() => setRegionFilter("all")}
            >
              Все районы ({levels.length})
            </button>
            {REGIONS.map((reg) => {
              const count = levels.filter((s) => stationRegion(s) === reg).length;
              if (!count) return null;
              return (
                <button
                  key={reg}
                  type="button"
                  className={`filter-pill${regionFilter === reg ? " active" : ""}`}
                  onClick={() => setRegionFilter(reg)}
                >
                  {reg} ({count})
                </button>
              );
            })}
          </div>

          <div className="level-grid">
            {visibleStations.map((station) => {
              const region = stationRegion(station);
              return (
                <article className="level-card" key={station.code}>
                  <header>
                    <div className="level-card-meta">
                      <span className="badge">{region}</span>
                      <span className="dash-muted">{station.code}</span>
                    </div>
                    <h3>{station.name}</h3>
                    <p title={station.address ?? station.code}>{station.address || station.code}</p>
                  </header>
                  {station.tanks.length === 0 ? (
                    <p className="dash-muted">Резервуаров пока нет</p>
                  ) : (
                    station.tanks.map((tank) => {
                      const pct = tank.fill_percent ?? 0;
                      const width = Math.max(0, Math.min(100, pct));
                      const online = tank.online === true;
                      const measured = tank.measured_at
                        ? `Замер ${dateTime(tank.measured_at)}`
                        : "Замера ещё нет";
                      const lowGas = isLowFill(tank.fill_percent);
                      return (
                        <div
                          className={`level-tank${online ? "" : " level-tank-stale"}`}
                          key={tank.code}
                          title={measured}
                        >
                          <div className="level-tank-head">
                            <span>Резервуар {tank.code}</span>
                            <strong className={lowGas ? "text-danger" : ""}>
                              {tank.fill_percent == null ? "—" : `${percentLabel(tank.fill_percent)}%`}
                            </strong>
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
                          <p>
                            {tank.remainder_liters == null
                              ? measured
                              : `${liters(tank.remainder_liters)} из ${liters(tank.capacity_liters)}`}
                            {tank.remainder_liters != null && !online ? " · нет связи" : ""}
                          </p>
                        </div>
                      );
                    })
                  )}
                </article>
              );
            })}
          </div>
          {levelsLoading && levels.length === 0 ? <p className="dash-muted">Загрузка…</p> : null}
          {!levelsLoading && levels.length > 0 && visibleStations.length === 0 ? (
            <p className="dash-muted">По выбранному фильтру заправок не найдено.</p>
          ) : null}
        </section>

        <section className="landing-section" id="project">
          <p className="kicker">О системе</p>
          <h2>Открытый остаток для жителей · закрытый контур учёта для операторов</h2>
          <p className="landing-prose">
            На публичной странице публикуется исключительно актуальное количество сжиженного газа в
            резервуарах АГЗС Мангистауской области, чтобы водители видели наличие топлива. Все
            данные о поставках, маршрутах газовозов, книжных остатках, расхождениях, колонках ККМ/КГД
            и датчиках защищены и доступны только авторизованным администраторам.
          </p>
        </section>
      </div>

      {authOpen && !session ? (
        <div className="login-layer" onClick={() => setAuthOpen(false)}>
          <form
            className="login-card"
            onClick={(event) => event.stopPropagation()}
            onSubmit={onSubmit}
          >
            <h2>Вход для администратора</h2>
            <p>Внутренний учёт, маршруты газовозов, сверка КГД и управление АГЗС требуют авторизации.</p>
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
