import { useEffect, useMemo, useState, type FormEvent } from "react";
import { isAdmin } from "../access";
import { useAuth } from "../auth";
import { dateTime, liters, REGIONS, stationRegion } from "../format";
import {
  isLowFill,
  LOW_FILL_PERCENT,
  SensorStatus,
  summarizeLevel,
  tankSensorLabel,
  usePublicLevels,
} from "../liveLevels";
import { useTheme } from "../theme";
import type { MapPoint } from "../types";
import PublicStationModal from "../pages/landing/PublicStationModal";
import Logo from "./Logo";
import MapView from "./MapView";

type AvailFilter = "all" | "plenty" | "low" | "online" | "no_reading";
type PublicSort = "region" | "liters_desc" | "fill_desc" | "fill_asc" | "name_asc";
type PublicViewMode = "grid" | "table";

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
  const [availFilter, setAvailFilter] = useState<AvailFilter>("all");
  const [sortBy, setSortBy] = useState<PublicSort>("region");
  const [viewMode, setViewMode] = useState<PublicViewMode>("grid");
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
    let capacitySum = 0;
    let plenty = 0;
    let low = 0;
    let online = 0;
    let noReading = 0;
    let tanksCount = 0;
    for (const item of enrichedStations) {
      tanksCount += item.station.tanks.length;
      capacitySum += item.live.capacity;
      if (item.live.remainder != null) litersSum += item.live.remainder;
      if (!item.hasReading) noReading++;
      else if (isLowFill(item.live.fill)) low++;
      else plenty++;
      if (item.online) online++;
    }
    const avgFill = capacitySum > 0 ? Math.round((litersSum / capacitySum) * 100) : 0;
    return {
      all: enrichedStations.length,
      litersSum,
      capacitySum,
      freeSum: Math.max(0, capacitySum - litersSum),
      avgFill,
      plenty,
      low,
      online,
      noReading,
      tanksCount,
    };
  }, [enrichedStations]);

  const regionStats = useMemo(() => {
    return REGIONS.map((region) => {
      const items = enrichedStations.filter((item) => item.region === region);
      const gas = items.reduce((sum, item) => sum + (item.live.remainder ?? 0), 0);
      const cap = items.reduce((sum, item) => sum + item.live.capacity, 0);
      const fill = cap > 0 ? Math.round((gas / cap) * 100) : null;
      const onlineCount = items.filter((item) => item.online).length;
      const plentyCount = items.filter(
        (item) => item.hasReading && !isLowFill(item.live.fill)
      ).length;
      return {
        region,
        count: items.length,
        gas,
        cap,
        fill,
        onlineCount,
        plentyCount,
      };
    }).filter((row) => row.count > 0);
  }, [enrichedStations]);

  const visibleStations = useMemo(() => {
    const query = stationQuery.trim().toLowerCase();
    const filtered = enrichedStations.filter(({ station, live, region, online, hasReading }) => {
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
      if (availFilter === "online" && !online) return false;
      if (availFilter === "no_reading" && hasReading) return false;
      return true;
    });

    return [...filtered].sort((a, b) => {
      if (sortBy === "liters_desc") return (b.live.remainder ?? -1) - (a.live.remainder ?? -1);
      if (sortBy === "fill_desc") return (b.live.fill ?? -1) - (a.live.fill ?? -1);
      if (sortBy === "fill_asc") return (a.live.fill ?? 101) - (b.live.fill ?? 101);
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

  function selectQuickFilter(nextAvail: AvailFilter, nextRegion = regionFilter) {
    setAvailFilter(nextAvail);
    setRegionFilter(nextRegion);
    jump("levels");
  }

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
          <div className="landing-brand" onClick={() => jump("hero")} style={{ cursor: "pointer" }}>
            <Logo size={36} alt="Цифровой след LPG" />
            <div>
              <p className="kicker">Мангистауская область</p>
              <strong>Цифровой след LPG</strong>
            </div>
          </div>
          <nav className="landing-links" aria-label="Навигация по странице">
            <button type="button" onClick={() => jump("summary")}>
              Сводка по области
            </button>
            <button type="button" onClick={() => jump("regions")}>
              По районам ({regionStats.length})
            </button>
            <button type="button" onClick={() => jump("levels")}>
              Карточки АГЗС ({levels.length})
            </button>
            <button type="button" onClick={() => jump("project")}>
              О системе
            </button>
          </nav>
          <div className="landing-nav-actions">
            <span className="badge ok" title="Суммарный публичный остаток на всех АГЗС">
              В наличии: {liters(publicTotals.litersSum)}
            </span>
            <button type="button" className="btn secondary small" onClick={toggle}>
              {theme === "dark" ? "Светлая тема" : "Тёмная тема"}
            </button>
            {session ? (
              <>
                <button type="button" className="btn small" onClick={onEnter}>
                  {isAdmin(session) ? "Диспетчерская" : "Мой кабинет"}
                </button>
                <button type="button" className="btn secondary small" onClick={logout}>
                  Выйти
                </button>
              </>
            ) : (
              <button type="button" className="btn small" onClick={() => setAuthOpen(true)}>
                Войти в систему
              </button>
            )}
          </div>
        </header>

        <section className="landing-hero" id="hero">
          <div className="landing-copy">
            <p className="kicker">Открытая информационная витрина · Региональный мониторинг</p>
            <h1>Наличие сжиженного газа на АГЗС</h1>
            <p className="landing-prose">
              Актуальная информация об остатках сжиженного нефтяного газа (LPG) в резервуарах
              автогазозаправочных станций Мангистауской области. Выберите район или конкретную
              заправку, чтобы посмотреть точный объём в литрах, процент заполнения каждого
              резервуара и время последнего замера датчика.
            </p>
            <div className="landing-hero-actions">
              <button type="button" className="btn" onClick={() => jump("levels")}>
                Найти АГЗС и проверить остатки ({levels.length})
              </button>
              <button type="button" className="btn secondary" onClick={() => jump("regions")}>
                Сводка по районам ({regionStats.length})
              </button>
              {session ? (
                <button type="button" className="btn secondary" onClick={onEnter}>
                  Перейти в рабочий кабинет
                </button>
              ) : (
                <button type="button" className="btn secondary" onClick={() => setAuthOpen(true)}>
                  Вход для операторов и владельцев
                </button>
              )}
            </div>
          </div>
        </section>

        <section className="landing-section" id="summary">
          <div className="level-head">
            <div>
              <p className="kicker">Оперативная сводка по региону</p>
              <h2>Показатели сети АГЗС в реальном времени</h2>
            </div>
            {updatedAt ? (
              <p className="public-fresh">
                Данные обновлены: <strong>{dateTime(updatedAt.toISOString())}</strong>
              </p>
            ) : null}
          </div>

          <div className="dash-kpis" style={{ marginTop: 18 }}>
            <div
              className={`dash-kpi${availFilter === "all" && regionFilter === "all" ? " active-kpi" : ""}`}
              onClick={() => selectQuickFilter("all", "all")}
              style={{ cursor: "pointer" }}
            >
              <span>Работающих АГЗС в витрине</span>
              <strong>{publicTotals.all}</strong>
              <em>всего резервуаров: {publicTotals.tanksCount}</em>
            </div>
            <div
              className="dash-kpi"
              onClick={() => selectQuickFilter("all", "all")}
              style={{ cursor: "pointer" }}
            >
              <span>Суммарный объём газа</span>
              <strong>{liters(publicTotals.litersSum)}</strong>
              <em>
                из {liters(publicTotals.capacitySum)} ёмкости ({publicTotals.avgFill}%)
              </em>
            </div>
            <div
              className={`dash-kpi${availFilter === "plenty" ? " active-kpi" : ""}`}
              onClick={() => selectQuickFilter("plenty")}
              style={{ cursor: "pointer" }}
            >
              <span>Достаточный запас (≥ {LOW_FILL_PERCENT}%)</span>
              <strong style={{ color: "var(--sea)" }}>{publicTotals.plenty}</strong>
              <em>нажмите, чтобы показать список</em>
            </div>
            <div
              className={`dash-kpi${availFilter === "low" ? " active-kpi" : ""}`}
              onClick={() => selectQuickFilter("low")}
              style={{ cursor: "pointer" }}
            >
              <span>Малый остаток (&lt; {LOW_FILL_PERCENT}%)</span>
              <strong className={publicTotals.low > 0 ? "text-danger" : ""}>{publicTotals.low}</strong>
              <em>заправки с низким уровнем</em>
            </div>
            <div
              className={`dash-kpi${availFilter === "online" ? " active-kpi" : ""}`}
              onClick={() => selectQuickFilter("online")}
              style={{ cursor: "pointer" }}
            >
              <span>Датчики на связи</span>
              <strong>{publicTotals.online}</strong>
              <em>актуальная телеметрия уровня</em>
            </div>
          </div>
        </section>

        <section className="landing-section" id="regions">
          <div className="level-head">
            <div>
              <p className="kicker">География покрытия · {regionStats.length} районов и городов</p>
              <h2>Распределение запасов по районам</h2>
            </div>
            {regionFilter !== "all" ? (
              <button
                type="button"
                className="btn secondary small"
                onClick={() => setRegionFilter("all")}
              >
                Показать все районы
              </button>
            ) : null}
          </div>

          <div className="st-card-grid" style={{ marginTop: 18 }}>
            {regionStats.map((row) => {
              const isSelected = regionFilter === row.region;
              return (
                <article
                  key={row.region}
                  className={`dash-card st-grid-card${isSelected ? " active-kpi" : ""}`}
                  onClick={() => {
                    setRegionFilter(isSelected ? "all" : row.region);
                    jump("levels");
                  }}
                >
                  <div className="st-grid-card-head">
                    <div>
                      <span className="badge">{row.count} АГЗС</span>
                      <h4>{row.region}</h4>
                    </div>
                    <strong className={`st-grid-pct${isLowFill(row.fill) ? " text-danger" : ""}`}>
                      {row.fill == null ? "—" : `${row.fill}%`}
                    </strong>
                  </div>
                  <div className="fill-bar" style={{ margin: "10px 0 8px" }}>
                    <i
                      style={{
                        width: `${row.fill ?? 0}%`,
                        background: isLowFill(row.fill) ? "var(--coral)" : "var(--sea)",
                      }}
                    />
                  </div>
                  <div className="st-grid-metrics">
                    <div>
                      <span>Объём в наличии</span>
                      <strong>{liters(row.gas)}</strong>
                    </div>
                    <div>
                      <span>Общая ёмкость</span>
                      <strong>{liters(row.cap)}</strong>
                    </div>
                    <div>
                      <span>Достаточно газа</span>
                      <strong>{row.plentyCount} АГЗС</strong>
                    </div>
                    <div>
                      <span>Датчики онлайн</span>
                      <strong>
                        {row.onlineCount} из {row.count}
                      </strong>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        <section className="landing-section" id="levels">
          <div className="level-head">
            <div>
              <p className="kicker">
                Публичный каталог · показано {visibleStations.length} из {levels.length} АГЗС · всего{" "}
                {liters(publicTotals.litersSum)}
              </p>
              <h2>Наличие газа на АГЗС</h2>
              {updatedAt ? (
                <p className="public-fresh">
                  Обновлено {dateTime(updatedAt.toISOString())} · Нажмите на любую карточку АГЗС для просмотра подробного паспорта
                </p>
              ) : null}
            </div>
            <div className="level-controls">
              <input
                className="level-search"
                type="search"
                value={stationQuery}
                placeholder="Поиск по названию, коду, адресу, району…"
                aria-label="Найти заправку"
                onChange={(event) => setStationQuery(event.target.value)}
              />
              <select
                className="level-select"
                value={availFilter}
                aria-label="Фильтр наличия газа"
                onChange={(e) => setAvailFilter(e.target.value as AvailFilter)}
              >
                <option value="all">Все станции ({publicTotals.all})</option>
                <option value="plenty">
                  Достаточно газа ≥ {LOW_FILL_PERCENT}% ({publicTotals.plenty})
                </option>
                <option value="low">
                  Мало газа &lt; {LOW_FILL_PERCENT}% ({publicTotals.low})
                </option>
                <option value="online">Датчики онлайн ({publicTotals.online})</option>
                <option value="no_reading">Ожидание замера ({publicTotals.noReading})</option>
              </select>
              <select
                className="level-select"
                value={sortBy}
                aria-label="Сортировка"
                onChange={(e) => setSortBy(e.target.value as PublicSort)}
              >
                <option value="region">Сортировка: по району</option>
                <option value="liters_desc">Сначала больше газа (л)</option>
                <option value="fill_desc">Сначала полные (%)</option>
                <option value="fill_asc">Сначала малый остаток (%)</option>
                <option value="name_asc">По алфавиту (А–Я)</option>
              </select>
              <div className="mini-tabs" role="group" aria-label="Вид списка">
                <button
                  type="button"
                  className={viewMode === "grid" ? "active" : ""}
                  onClick={() => setViewMode("grid")}
                >
                  Плитка
                </button>
                <button
                  type="button"
                  className={viewMode === "table" ? "active" : ""}
                  onClick={() => setViewMode("table")}
                >
                  Таблица
                </button>
              </div>
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
              const count = enrichedStations.filter((s) => s.region === reg).length;
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
            {stationQuery || regionFilter !== "all" || availFilter !== "all" ? (
              <button
                type="button"
                className="btn secondary small"
                onClick={() => {
                  setStationQuery("");
                  setRegionFilter("all");
                  setAvailFilter("all");
                }}
              >
                Сбросить фильтры
              </button>
            ) : null}
          </div>

          {viewMode === "grid" ? (
            <div className="level-grid">
              {visibleStations.map(({ station, live, region, freeLiters }) => (
                <article
                  className="level-card level-card-clickable"
                  key={station.code}
                  onClick={() => setDetailCode(station.code)}
                >
                  <header>
                    <div className="level-card-meta">
                      <span className="badge">{region}</span>
                      <span className="dash-muted">{station.code}</span>
                    </div>
                    <h3>{station.name}</h3>
                    <p title={station.address ?? station.code}>
                      {station.address || "Адрес не указан"}
                    </p>
                  </header>

                  <div className="public-station-summary">
                    <div>
                      <span>Всего на АГЗС</span>
                      <strong>
                        {live.remainder == null ? "замера нет" : liters(live.remainder)}
                      </strong>
                    </div>
                    <div>
                      <span>Ёмкость / свободно</span>
                      <strong>
                        {liters(live.capacity)}
                        {freeLiters != null ? ` (своб. ${liters(freeLiters)})` : ""}
                      </strong>
                    </div>
                  </div>

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
                            <span>
                              Резервуар {tank.code} ·{" "}
                              <em style={{ fontStyle: "normal" }}>{tankSensorLabel(tank)}</em>
                            </span>
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
                            {tank.measured_at ? ` · ${dateTime(tank.measured_at)}` : ""}
                          </p>
                        </div>
                      );
                    })
                  )}

                  <footer className="level-card-footer">
                    {station.tanks.length > 0 ? (
                      <SensorStatus level={live} />
                    ) : (
                      <span className="badge warn">нет резервуаров</span>
                    )}
                    <span className="level-card-more">Подробнее →</span>
                  </footer>
                </article>
              ))}
            </div>
          ) : (
            <div className="dash-table-wrap" style={{ marginTop: 20 }}>
              <table className="dash-table">
                <thead>
                  <tr>
                    <th>Код и район</th>
                    <th>Название и адрес АГЗС</th>
                    <th>Заполненность</th>
                    <th>Остаток / Ёмкость</th>
                    <th>Свободно</th>
                    <th>Резервуары и связь</th>
                    <th>Последний замер</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {visibleStations.map(({ station, live, region, freeLiters }) => (
                    <tr
                      key={station.code}
                      className="dash-row-link"
                      onClick={() => setDetailCode(station.code)}
                    >
                      <td>
                        <strong>{station.code}</strong>
                        <div className="dash-muted">{region}</div>
                      </td>
                      <td>
                        <strong>{station.name}</strong>
                        <div className="dash-muted">{station.address || "—"}</div>
                      </td>
                      <td>
                        <strong className={isLowFill(live.fill) ? "text-danger" : ""}>
                          {live.fill == null ? "—" : `${live.fill}%`}
                        </strong>
                      </td>
                      <td>
                        <strong>
                          {live.remainder == null ? "замера нет" : liters(live.remainder)}
                        </strong>
                        <div className="dash-muted">из {liters(live.capacity)}</div>
                      </td>
                      <td>{freeLiters == null ? "—" : liters(freeLiters)}</td>
                      <td>
                        {station.tanks.length > 0 ? (
                          <SensorStatus level={live} />
                        ) : (
                          <span className="badge warn">нет резервуаров</span>
                        )}
                        <div className="dash-muted">емкостей: {station.tanks.length}</div>
                      </td>
                      <td>{live.measuredAt ? dateTime(live.measuredAt) : "—"}</td>
                      <td>
                        <button
                          type="button"
                          className="btn secondary small"
                          onClick={(e) => {
                            e.stopPropagation();
                            setDetailCode(station.code);
                          }}
                        >
                          Паспорт →
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {levelsLoading && levels.length === 0 ? <p className="dash-muted">Загрузка…</p> : null}
          {!levelsLoading && levels.length > 0 && visibleStations.length === 0 ? (
            <p className="dash-muted">По выбранному фильтру заправок не найдено.</p>
          ) : null}
        </section>

        <section className="landing-section" id="project">
          <p className="kicker">О системе и архитектуре учёта</p>
          <h2>Открытый остаток для жителей · закрытый контур учёта для операторов</h2>
          <p className="landing-prose">
            На публичной странице публикуется исключительно актуальное количество сжиженного газа в
            резервуарах АГЗС Мангистауской области, чтобы водители видели наличие топлива и время
            последнего замера. Все данные о поставках, маршрутах газовозов, книжных остатках,
            расхождениях, колонках ККМ/КГД и датчиках защищены и доступны только авторизованным
            операторам, владельцам заправок и администраторам платформы.
          </p>
          <div className="st-card-grid" style={{ marginTop: 22 }}>
            <div className="dash-card">
              <h3>1. Телеметрия резервуаров</h3>
              <p className="dash-muted">
                Датчики уровня передают напряжение через контроллеры Shelly Plus Uni. Сервер
                автоматически пересчитывает вольты в проценты и литры с учётом калибровки и
                отсекает шумовые колебания менее 0,02 В.
              </p>
            </div>
            <div className="dash-card">
              <h3>2. Кабинет владельца и пульт ТРК</h3>
              <p className="dash-muted">
                Владелец АГЗС управляет розничной ценой газа (₸/л), контролирует выручку и отпуск по
                каждой колонке, а также назначает операторов кассового пульта своей станции.
              </p>
            </div>
            <div className="dash-card">
              <h3>3. Диспетчерский контроль региона</h3>
              <p className="dash-muted">
                Администратор платформы отслеживает баланс по всем районам Мангистауской области,
                планирует подвоз газа газовозами, сверяет книжные и фактические остатки.
              </p>
            </div>
          </div>
        </section>
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
            <p>
              Доступ для администраторов платформы, владельцев АГЗС и операторов кассового пульта.
            </p>
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
