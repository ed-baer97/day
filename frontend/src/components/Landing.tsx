import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api, type PublicStation } from "../api/client";
import { useAuth } from "../auth";
import { dateTime, liters } from "../format";
import Logo from "./Logo";
import MapView from "./MapView";
import { useSim } from "../sim/SimContext";
import { useTheme } from "../theme";

function percentLabel(value: number) {
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toLocaleString("ru-RU", { maximumFractionDigits: 1 });
}

function jump(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

export default function Landing({ onEnter }: { onEnter: () => void }) {
  const { theme, toggle } = useTheme();
  const { session, login, logout } = useAuth();
  const { overview, routes, play, pause, setSpeed } = useSim();
  const [levels, setLevels] = useState<PublicStation[]>([]);
  const [levelsError, setLevelsError] = useState<string | null>(null);
  const [levelsLoading, setLevelsLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [authOpen, setAuthOpen] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stationQuery, setStationQuery] = useState("");

  useEffect(() => {
    setSpeed(20);
    play();
    return () => pause();
  }, [play, pause, setSpeed]);

  useEffect(() => {
    if (!authOpen) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setAuthOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [authOpen]);

  useEffect(() => {
    let live = true;
    async function load() {
      try {
        const rows = await api.publicLevels();
        if (!live) return;
        setLevels(rows);
        setUpdatedAt(new Date());
        setLevelsError(null);
      } catch {
        if (!live) return;
        setLevelsError("Не удалось обновить уровни");
      } finally {
        if (live) setLevelsLoading(false);
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);

  const points = useMemo(
    () => overview.points.filter((point) => !point.id.startsWith("alert-")),
    [overview.points]
  );
  const visibleStations = useMemo(() => {
    const query = stationQuery.trim().toLowerCase();
    if (!query) return levels;
    return levels.filter((station) =>
      [station.name, station.address, station.code].some((part) => part?.toLowerCase().includes(query))
    );
  }, [levels, stationQuery]);

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
          points={points}
          routes={routes}
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
            <button type="button" onClick={() => jump("project")}>
              О проекте
            </button>
            <button type="button" onClick={() => jump("levels")}>
              Заполненность
            </button>
          </nav>
          <div className="landing-nav-actions">
            <button type="button" className="btn secondary small" onClick={toggle}>
              {theme === "dark" ? "Светлая" : "Тёмная"}
            </button>
            {session ? (
              <>
                <button type="button" className="btn small" onClick={onEnter}>
                  В систему
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
            <p className="kicker">Мангыстау</p>
            <h1>Цифровой след сжиженного газа</h1>
            <div className="landing-hero-actions">
              <button type="button" className="btn" onClick={() => jump("levels")}>
                Заполненность заправок
              </button>
              {session ? (
                <button type="button" className="btn secondary" onClick={onEnter}>
                  В систему
                </button>
              ) : (
                <button type="button" className="btn secondary" onClick={() => setAuthOpen(true)}>
                  Вход для администратора
                </button>
              )}
            </div>
          </div>
        </section>

        <section className="landing-section" id="project">
          <p className="kicker">О проекте</p>
          <h2>От отгрузки до продажи на колонке</h2>
          <p className="landing-prose">
            Цифровой след LPG собирает путь сжиженного газа в одну цепочку. Видно, какой завод отгрузил партию, какой
            газовоз её вёз, какая заправка приняла газ и сколько сейчас в резервуаре. Расхождение между книгой и
            замером не теряется между участками.
          </p>
        </section>

        <section className="landing-section" id="levels">
          <div className="level-head">
            <div>
              <p className="kicker">Открытые данные</p>
              <h2>Заполненность заправок</h2>
              {updatedAt ? <p className="public-fresh">Обновлено {dateTime(updatedAt.toISOString())}</p> : null}
            </div>
            {levels.length > 1 ? (
              <input
                className="level-search"
                type="search"
                value={stationQuery}
                placeholder="Найти заправку"
                aria-label="Найти заправку"
                onChange={(event) => setStationQuery(event.target.value)}
              />
            ) : null}
          </div>
          {levelsError ? <p className="tank-error">{levelsError}</p> : null}

          <div className="level-grid">
            {visibleStations.map((station) => (
              <article className="level-card" key={station.code}>
                <header>
                  <h3>{station.name}</h3>
                  <p>{station.address || station.code}</p>
                </header>
                {station.tanks.length === 0 ? (
                  <p className="dash-muted">Резервуаров пока нет</p>
                ) : (
                  station.tanks.map((tank) => {
                    const width = tank.fill_percent == null ? 0 : Math.max(0, Math.min(100, tank.fill_percent));
                    const measured = tank.measured_at ? `Замер ${dateTime(tank.measured_at)}` : "Замера ещё нет";
                    return (
                      <div className="level-tank" key={tank.code} title={measured}>
                        <div className="level-tank-head">
                          <span>{tank.code}</span>
                          <strong>{tank.fill_percent == null ? "—" : `${percentLabel(tank.fill_percent)}%`}</strong>
                        </div>
                        <div className="public-track" aria-hidden="true">
                          <i style={{ width: `${width}%` }} />
                        </div>
                        <p>
                          {tank.remainder_liters == null
                            ? measured
                            : `${liters(tank.remainder_liters)} из ${liters(tank.capacity_liters)}`}
                        </p>
                      </div>
                    );
                  })
                )}
              </article>
            ))}
          </div>
          {levelsLoading && levels.length === 0 ? <p className="dash-muted">Загрузка…</p> : null}
          {!levelsLoading && levels.length === 0 && !levelsError ? (
            <p className="dash-muted">Заправки появятся здесь.</p>
          ) : null}
          {!levelsLoading && levels.length > 0 && visibleStations.length === 0 ? (
            <p className="dash-muted">Такой заправки нет.</p>
          ) : null}
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
            <p>Карта, поставки и сверка остатков открываются после входа.</p>
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
