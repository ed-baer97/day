import { useMemo, useState } from "react";
import { useCatalog } from "../catalog";
import { fiscalCheck, fleetStats, stationBalance, stationHourly, withMeasured } from "../sim/engine";
import { useSim } from "../sim/SimContext";
import {
  balBadge,
  balText,
  fiscalBadge,
  fiscalText,
  liters,
  phaseLabel,
  REGIONS,
  shortStationName,
  signedLiters,
  stationRegion,
  tenge,
} from "../format";
import { SensorStatus, usePublicLevels } from "../liveLevels";
import { BarChart } from "./Charts";
import StationDetailPage from "./StationDetailPage";

type StatusFilter = "all" | "balance_issue" | "kgd_issue" | "low_gas" | "ok";
type SortBy = "severity" | "fill_asc" | "sales_desc" | "name_asc";
type ViewMode = "list" | "grid" | "regions";
type ChartMode = "top_volume" | "top_delta" | "by_region";

export default function Dashboard({
  stationId,
  onOpenStation,
  onOpenAdminStation,
  onOpenMapStation,
}: {
  stationId: string | null;
  onOpenStation: (id: string | null) => void;
  onOpenAdminStation?: (id: string) => void;
  onOpenMapStation?: (id: string) => void;
}) {
  if (stationId) {
    return (
      <StationDetailPage
        stationId={stationId}
        onBack={() => onOpenStation(null)}
        onSelectStation={(id) => onOpenStation(id)}
        onOpenAdmin={onOpenAdminStation}
        onOpenMap={onOpenMapStation}
      />
    );
  }
  return (
    <Overview
      onOpenStation={onOpenStation}
      onOpenAdminStation={onOpenAdminStation}
      onOpenMapStation={onOpenMapStation}
    />
  );
}

function Overview({
  onOpenStation,
  onOpenAdminStation,
  onOpenMapStation,
}: {
  onOpenStation: (id: string) => void;
  onOpenAdminStation?: (id: string) => void;
  onOpenMapStation?: (id: string) => void;
}) {
  const { state } = useSim();
  const catalog = useCatalog();
  const { byCode } = usePublicLevels();

  const [query, setQuery] = useState("");
  const [regionFilter, setRegionFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sortBy, setSortBy] = useState<SortBy>("severity");
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [chartMode, setChartMode] = useState<ChartMode>("top_volume");
  const [pageSize, setPageSize] = useState<number>(10);
  const [currentPage, setCurrentPage] = useState<number>(1);

  const liveStations = useMemo(() => {
    if (!catalog.ready) return state.stations;
    const activeIds = new Set(
      catalog.stations.filter((row) => row.is_active).map((row) => row.id)
    );
    return state.stations.filter((station) => activeIds.has(station.detail.id));
  }, [catalog.ready, catalog.stations, state.stations]);

  const stats = useMemo(
    () => fleetStats({ ...state, stations: liveStations }),
    [state, liveStations]
  );

  const enrichedStations = useMemo(
    () =>
      liveStations.map((s) => {
        const d = s.detail;
        const fc = fiscalCheck(d);
        const live = byCode.get(d.code) ?? null;
        const hasLive = !!live && live.tanks.length > 0;
        const bal = withMeasured(stationBalance(d), hasLive ? live.remainder : null);
        const simFill = d.capacity_liters
          ? Math.min(100, Math.round((bal.storage_actual / d.capacity_liters) * 100))
          : 0;
        const fill = hasLive ? (live.fill == null ? null : Math.round(live.fill)) : simFill;
        const gasLiters = hasLive ? live.remainder : bal.storage_actual;
        const gasCap = hasLive && live.capacity > 0 ? live.capacity : (d.capacity_liters ?? 0);
        const region = stationRegion(d);
        const severity =
          Math.abs(bal.delta) + fc.gap_liters + (fill != null && fill < 25 ? 800 : 0);
        return { d, bal, fc, fill, gasLiters, gasCap, live, region, severity };
      }),
    [liveStations, byCode]
  );

  // Счётчики для быстрых фильтров
  const counts = useMemo(() => {
    let balanceIssue = 0;
    let kgdIssue = 0;
    let lowGas = 0;
    let ok = 0;
    for (const item of enrichedStations) {
      if (item.bal.status !== "ok") balanceIssue++;
      if (item.fc.status !== "ok") kgdIssue++;
      if (item.fill != null && item.fill < 25) lowGas++;
      if (item.bal.status === "ok" && item.fc.status === "ok" && item.fill != null && item.fill >= 25) ok++;
    }
    return {
      all: enrichedStations.length,
      balanceIssue,
      kgdIssue,
      lowGas,
      ok,
    };
  }, [enrichedStations]);

  const filteredStations = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = enrichedStations.filter((item) => {
      if (q) {
        const hit = [item.d.name, item.d.code, item.d.address, item.region].some((p) =>
          p?.toLowerCase().includes(q)
        );
        if (!hit) return false;
      }
      if (regionFilter !== "all" && item.region !== regionFilter) {
        return false;
      }
      if (statusFilter === "balance_issue" && item.bal.status === "ok") return false;
      if (statusFilter === "kgd_issue" && item.fc.status === "ok") return false;
      if (statusFilter === "low_gas" && (item.fill == null || item.fill >= 25)) return false;
      if (
        statusFilter === "ok" &&
        (item.bal.status !== "ok" || item.fc.status !== "ok" || item.fill == null || item.fill < 25)
      )
        return false;
      return true;
    });

    return [...list].sort((a, b) => {
      if (sortBy === "severity") return b.severity - a.severity;
      if (sortBy === "fill_asc") return (a.fill ?? 101) - (b.fill ?? 101);
      if (sortBy === "sales_desc") return b.bal.through_pumps - a.bal.through_pumps;
      return a.d.name.localeCompare(b.d.name, "ru");
    });
  }, [enrichedStations, query, regionFilter, statusFilter, sortBy]);

  const totalPages = Math.max(1, Math.ceil(filteredStations.length / pageSize));
  const safePage = Math.min(currentPage, totalPages);
  const pagedStations = useMemo(() => {
    const start = (safePage - 1) * pageSize;
    return filteredStations.slice(start, start + pageSize);
  }, [filteredStations, safePage, pageSize]);

  const groupedByRegion = useMemo(() => {
    const map = new Map<string, typeof filteredStations>();
    for (const reg of REGIONS) map.set(reg, []);
    for (const item of filteredStations) {
      const arr = map.get(item.region) ?? [];
      arr.push(item);
      map.set(item.region, arr);
    }
    return Array.from(map.entries()).filter(([, items]) => items.length > 0);
  }, [filteredStations]);

  const chartData = useMemo(() => {
    if (chartMode === "by_region") {
      const regs = REGIONS.filter((r) => enrichedStations.some((s) => s.region === r));
      return {
        labels: regs.map((r) => r.replace(" р-н", "").replace("г. ", "")),
        series: [
          {
            name: "Доставлено",
            color: "var(--dust)",
            values: regs.map((r) =>
              enrichedStations
                .filter((s) => s.region === r)
                .reduce((sum, s) => sum + s.bal.delivered, 0)
            ),
          },
          {
            name: "Через колонки",
            color: "var(--sea)",
            values: regs.map((r) =>
              enrichedStations
                .filter((s) => s.region === r)
                .reduce((sum, s) => sum + s.bal.through_pumps, 0)
            ),
          },
        ],
      };
    }
    if (chartMode === "top_delta") {
      const top = [...enrichedStations]
        .sort((a, b) => Math.abs(b.bal.delta) + b.fc.gap_liters - (Math.abs(a.bal.delta) + a.fc.gap_liters))
        .slice(0, 10);
      return {
        labels: top.map((s) => shortStationName(s.d.name)),
        series: [
          {
            name: "Расхождение ёмкости |Δ|",
            color: "var(--coral)",
            values: top.map((s) => Math.abs(s.bal.delta)),
          },
          {
            name: "Не видит КГД",
            color: "var(--dust)",
            values: top.map((s) => s.fc.gap_liters),
          },
        ],
      };
    }
    const top = [...enrichedStations]
      .sort((a, b) => b.bal.through_pumps + b.bal.delivered - (a.bal.through_pumps + a.bal.delivered))
      .slice(0, 10);
    return {
      labels: top.map((s) => shortStationName(s.d.name)),
      series: [
        { name: "Доставлено", color: "var(--dust)", values: top.map((s) => s.bal.delivered) },
        { name: "Через колонки", color: "var(--sea)", values: top.map((s) => s.bal.through_pumps) },
      ],
    };
  }, [chartMode, enrichedStations]);

  const hourlyTotal = useMemo(() => {
    const perStation = liveStations.map((s) => stationHourly(s.detail, state.simTimeMs));
    const hours = perStation[0]?.length ?? 0;
    return Array.from({ length: hours }, (_, h) =>
      perStation.reduce((sum, rows) => sum + (rows[h]?.pumps ?? 0), 0)
    );
  }, [liveStations, state.simTimeMs]);

  return (
    <div className="dash">
      <header className="dash-hero dash-hero-row">
        <div>
          <p className="kicker">Внутренний диспетчерский контур · суточная сводка</p>
          <h2>Контроль сети АГЗС и сверка баланса ({counts.all} станций)</h2>
        </div>
      </header>

      <div className="dash-kpis">
        <div className="dash-kpi" onClick={() => setStatusFilter("all")} style={{ cursor: "pointer" }}>
          <span>Доставлено за сутки</span>
          <strong>{liters(stats.delivered_liters_day)}</strong>
          <em>{stats.delivery_trips_day} рейсов</em>
        </div>
        <div className="dash-kpi">
          <span>Через колонки</span>
          <strong>{liters(stats.sold_liters_day)}</strong>
          <em>{stats.fills_day} заправок</em>
        </div>
        <div className="dash-kpi">
          <span>Газовозов в рейсе</span>
          <strong>{stats.trucks_in_transit}</strong>
          <em>из {state.trucks.length} машин в парке</em>
        </div>
        <div
          className={`dash-kpi${statusFilter === "balance_issue" ? " active-kpi" : ""}`}
          onClick={() => {
            setStatusFilter(statusFilter === "balance_issue" ? "all" : "balance_issue");
            setCurrentPage(1);
          }}
          style={{ cursor: "pointer" }}
          title="Нажмите для фильтрации станций с расхождением"
        >
          <span>Расхождения в хранилище</span>
          <strong className={counts.balanceIssue ? "text-danger" : ""}>{counts.balanceIssue}</strong>
          <em>из {stats.stations_active} АГЗС (нажмите для фильтра)</em>
        </div>
        <div
          className={`dash-kpi${statusFilter === "kgd_issue" ? " active-kpi" : ""}`}
          onClick={() => {
            setStatusFilter(statusFilter === "kgd_issue" ? "all" : "kgd_issue");
            setCurrentPage(1);
          }}
          style={{ cursor: "pointer" }}
          title="Нажмите для фильтрации станций с расхождением КГД"
        >
          <span>КГД не видит</span>
          <strong className={stats.gap_liters ? "text-danger" : ""}>{liters(stats.gap_liters)}</strong>
          <em>
            {tenge(stats.gap_kzt)} · без чека {liters(stats.unreceipted_liters)} · ККМ офлайн{" "}
            {stats.kkm_offline}
          </em>
        </div>
      </div>

      <div className="dash-charts">
        <section className="dash-card">
          <div className="card-head-inline">
            <h3>Сравнение АГЗС</h3>
            <div className="mini-tabs">
              <button
                type="button"
                className={chartMode === "top_volume" ? "active" : ""}
                onClick={() => setChartMode("top_volume")}
              >
                Топ-10 объём
              </button>
              <button
                type="button"
                className={chartMode === "top_delta" ? "active" : ""}
                onClick={() => setChartMode("top_delta")}
              >
                Топ-10 расхождения
              </button>
              <button
                type="button"
                className={chartMode === "by_region" ? "active" : ""}
                onClick={() => setChartMode("by_region")}
              >
                По районам
              </button>
            </div>
          </div>
          <BarChart labels={chartData.labels} series={chartData.series} />
        </section>
        <section className="dash-card">
          <h3>Отпуск через колонки по часам · вся сеть АГЗС</h3>
          <BarChart
            labels={hourlyTotal.map((_, h) => `${String(h).padStart(2, "0")}`)}
            series={[{ name: "Колонки", color: "var(--sea)", values: hourlyTotal }]}
          />
        </section>
      </div>

      <section className="dash-section">
        <div className="st-nav-toolbar">
          <div className="st-nav-top">
            <h3>
              Навигатор АГЗС{" "}
              <span className="dash-muted">
                (показано {filteredStations.length} из {counts.all})
              </span>
            </h3>
            <div className="st-view-controls">
              <div className="mini-tabs" role="group" aria-label="Режим отображения">
                <button
                  type="button"
                  className={viewMode === "list" ? "active" : ""}
                  onClick={() => setViewMode("list")}
                >
                  Список
                </button>
                <button
                  type="button"
                  className={viewMode === "grid" ? "active" : ""}
                  onClick={() => setViewMode("grid")}
                >
                  Плитка
                </button>
                <button
                  type="button"
                  className={viewMode === "regions" ? "active" : ""}
                  onClick={() => setViewMode("regions")}
                >
                  По районам
                </button>
              </div>
            </div>
          </div>

          <div className="st-filter-bar">
            <input
              type="search"
              className="st-search-input"
              value={query}
              placeholder="Поиск АГЗС по названию, коду, адресу или району…"
              onChange={(e) => {
                setQuery(e.target.value);
                setCurrentPage(1);
              }}
            />
            <select
              className="st-select"
              value={regionFilter}
              aria-label="Район"
              onChange={(e) => {
                setRegionFilter(e.target.value);
                setCurrentPage(1);
              }}
            >
              <option value="all">Все районы ({counts.all})</option>
              {REGIONS.map((reg) => {
                const cnt = enrichedStations.filter((s) => s.region === reg).length;
                if (!cnt) return null;
                return (
                  <option key={reg} value={reg}>
                    {reg} ({cnt})
                  </option>
                );
              })}
            </select>
            <select
              className="st-select"
              value={sortBy}
              aria-label="Сортировка"
              onChange={(e) => setSortBy(e.target.value as SortBy)}
            >
              <option value="severity">По критичности (расхождения сверху)</option>
              <option value="fill_asc">По остатку газа (сначала мало)</option>
              <option value="sales_desc">По объёму продаж за сутки</option>
              <option value="name_asc">По алфавиту (А–Я)</option>
            </select>
            {viewMode !== "regions" && (
              <select
                className="st-select"
                value={pageSize}
                aria-label="Показывать по"
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setCurrentPage(1);
                }}
              >
                <option value={8}>По 8 на стр.</option>
                <option value={10}>По 10 на стр.</option>
                <option value={20}>По 20 на стр.</option>
                <option value={100}>Все ({filteredStations.length})</option>
              </select>
            )}
          </div>

          <div className="st-status-pills" role="group" aria-label="Фильтр по статусу">
            <button
              type="button"
              className={`filter-pill${statusFilter === "all" ? " active" : ""}`}
              onClick={() => {
                setStatusFilter("all");
                setCurrentPage(1);
              }}
            >
              Все АГЗС ({counts.all})
            </button>
            <button
              type="button"
              className={`filter-pill${statusFilter === "balance_issue" ? " active" : ""}`}
              onClick={() => {
                setStatusFilter("balance_issue");
                setCurrentPage(1);
              }}
            >
              Расхождение баланса ({counts.balanceIssue})
            </button>
            <button
              type="button"
              className={`filter-pill${statusFilter === "kgd_issue" ? " active" : ""}`}
              onClick={() => {
                setStatusFilter("kgd_issue");
                setCurrentPage(1);
              }}
            >
              Проблемы КГД / ККМ ({counts.kgdIssue})
            </button>
            <button
              type="button"
              className={`filter-pill${statusFilter === "low_gas" ? " active" : ""}`}
              onClick={() => {
                setStatusFilter("low_gas");
                setCurrentPage(1);
              }}
            >
              Мало газа &lt; 25% ({counts.lowGas})
            </button>
            <button
              type="button"
              className={`filter-pill${statusFilter === "ok" ? " active" : ""}`}
              onClick={() => {
                setStatusFilter("ok");
                setCurrentPage(1);
              }}
            >
              В норме ({counts.ok})
            </button>
            {(query || regionFilter !== "all" || statusFilter !== "all") && (
              <button
                type="button"
                className="btn secondary small"
                onClick={() => {
                  setQuery("");
                  setRegionFilter("all");
                  setStatusFilter("all");
                  setCurrentPage(1);
                }}
              >
                Сбросить фильтры
              </button>
            )}
          </div>
        </div>

        {filteredStations.length === 0 ? (
          <div className="empty">
            <strong>По заданным условиям АГЗС не найдены</strong>
            <p>Попробуйте изменить поисковый запрос или сбросить фильтр района/статуса.</p>
          </div>
        ) : viewMode === "list" ? (
          <ul className="st-list">
            {pagedStations.map(({ d, bal, fc, fill, gasLiters, gasCap, live, region }) => (
              <li key={d.id} className="st-list-item">
                <div className="st-row" onClick={() => onOpenStation(d.id)}>
                  <div className="st-row-main">
                    <strong>{d.name}</strong>
                    <span>
                      {d.code} · {region}
                    </span>
                  </div>
                  <div className="st-row-fill">
                    <div className="fill-bar">
                      <i
                        style={{
                          width: `${fill ?? 0}%`,
                          background: fill != null && fill < 25 ? "var(--coral)" : "var(--sea)",
                        }}
                      />
                    </div>
                    <span>
                      {gasLiters == null ? "замера ещё нет" : `${liters(gasLiters)} из ${liters(gasCap)}`} ·{" "}
                      <strong className={fill != null && fill < 25 ? "text-danger" : ""}>
                        {fill == null ? "—" : `${fill}%`}
                      </strong>
                    </span>
                    {live && live.tanks.length > 0 ? <SensorStatus level={live} /> : null}
                  </div>
                  <div className="st-row-num">
                    <strong>{liters(bal.delivered)}</strong>
                    <span>доставлено · {d.delivery_count_day} рейс.</span>
                  </div>
                  <div className="st-row-num">
                    <strong>{liters(bal.through_pumps)}</strong>
                    <span>колонки · {d.sales_day_count} запр.</span>
                  </div>
                  <div className="st-row-badges">
                    <span className={`badge ${balBadge(bal.status)}`}>
                      ёмкость {bal.status === "ok" ? balText(bal.status) : signedLiters(bal.delta)}
                    </span>
                    <span className={`badge ${fiscalBadge(fc.status)}`}>
                      КГД {fc.status === "ok" ? "сходится" : `−${liters(fc.gap_liters)}`}
                    </span>
                  </div>
                  <div
                    className="st-row-actions"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {onOpenMapStation && (
                      <button
                        type="button"
                        className="btn secondary small"
                        onClick={() => onOpenMapStation(d.id)}
                        title="Показать на карте"
                      >
                        Карта
                      </button>
                    )}
                    {onOpenAdminStation && (
                      <button
                        type="button"
                        className="btn secondary small"
                        onClick={() => onOpenAdminStation(d.id)}
                        title="Редактировать в админке"
                      >
                        Админка
                      </button>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ) : viewMode === "grid" ? (
          <div className="st-card-grid">
            {pagedStations.map(({ d, bal, fc, fill, gasLiters, gasCap, live, region }) => (
              <article
                key={d.id}
                className="dash-card st-grid-card"
                onClick={() => onOpenStation(d.id)}
              >
                <div className="st-grid-card-head">
                  <div>
                    <span className="badge">{region}</span>
                    <h4>{d.name}</h4>
                    <span className="dash-muted">
                      {d.code} · {d.address}
                    </span>
                  </div>
                  <strong className={`st-grid-pct${fill != null && fill < 25 ? " text-danger" : ""}`}>
                    {fill == null ? "—" : `${fill}%`}
                  </strong>
                </div>
                <div className="fill-bar" style={{ margin: "10px 0 6px" }}>
                  <i
                    style={{
                      width: `${fill ?? 0}%`,
                      background: fill != null && fill < 25 ? "var(--coral)" : "var(--sea)",
                    }}
                  />
                </div>
                <div className="st-grid-metrics">
                  <div>
                    <span>Факт / Ёмкость</span>
                    <strong>
                      {gasLiters == null ? "замера нет" : liters(gasLiters)} / {liters(gasCap)}
                    </strong>
                  </div>
                  <div>
                    <span>Книжный остаток</span>
                    <strong>{liters(bal.book_remainder)}</strong>
                  </div>
                  <div>
                    <span>Через колонки</span>
                    <strong>{liters(bal.through_pumps)}</strong>
                  </div>
                  <div>
                    <span>Колонок ТРК</span>
                    <strong>{d.pumps.length} шт.</strong>
                  </div>
                </div>
                <div className="st-grid-footer">
                  {live && live.tanks.length > 0 ? <SensorStatus level={live} /> : null}
                  <span className={`badge ${balBadge(bal.status)}`}>
                    {bal.status === "ok" ? "Баланс ОК" : `Δ ${signedLiters(bal.delta)}`}
                  </span>
                  <span className={`badge ${fiscalBadge(fc.status)}`}>
                    КГД: {fc.status === "ok" ? "ОК" : `−${liters(fc.gap_liters)}`}
                  </span>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="st-regions-group">
            {groupedByRegion.map(([region, items]) => (
              <div key={region} className="region-group-block">
                <header className="region-group-head">
                  <h4>{region}</h4>
                  <span>
                    {items.length} АГЗС · остаток{" "}
                    {liters(items.reduce((s, x) => s + (x.gasLiters ?? 0), 0))}
                  </span>
                </header>
                <ul className="st-list">
                  {items.map(({ d, bal, fc, fill, gasLiters, live }) => (
                    <li key={d.id}>
                      <button
                        type="button"
                        className="st-row"
                        onClick={() => onOpenStation(d.id)}
                      >
                        <div className="st-row-main">
                          <strong>{d.name}</strong>
                          <span>
                            {d.code} · {d.address}
                          </span>
                        </div>
                        <div className="st-row-fill">
                          <div className="fill-bar">
                            <i
                              style={{
                                width: `${fill ?? 0}%`,
                                background: fill != null && fill < 25 ? "var(--coral)" : "var(--sea)",
                              }}
                            />
                          </div>
                          <span>
                            {gasLiters == null ? "замера нет" : liters(gasLiters)} ·{" "}
                            {fill == null ? "—" : `${fill}%`}
                          </span>
                          {live && live.tanks.length > 0 ? <SensorStatus level={live} /> : null}
                        </div>
                        <div className="st-row-num">
                          <strong>{liters(bal.delivered)}</strong>
                          <span>доставлено</span>
                        </div>
                        <div className="st-row-num">
                          <strong>{liters(bal.through_pumps)}</strong>
                          <span>через колонки</span>
                        </div>
                        <div className="st-row-badges">
                          <span className={`badge ${balBadge(bal.status)}`}>
                            {bal.status === "ok" ? balText(bal.status) : signedLiters(bal.delta)}
                          </span>
                          <span className={`badge ${fiscalBadge(fc.status)}`}>
                            КГД {fc.status === "ok" ? "сходится" : `−${liters(fc.gap_liters)}`}
                          </span>
                        </div>
                        <span className="st-row-chevron" aria-hidden>
                          ›
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}

        {viewMode !== "regions" && totalPages > 1 && (
          <div className="pagination-bar">
            <span className="dash-muted">
              Страница {safePage} из {totalPages} ({filteredStations.length} АГЗС)
            </span>
            <div className="pagination-buttons">
              <button
                type="button"
                className="btn secondary small"
                disabled={safePage <= 1}
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              >
                ← Пред.
              </button>
              {Array.from({ length: totalPages }, (_, idx) => idx + 1).map((p) => (
                <button
                  key={p}
                  type="button"
                  className={`btn small${p === safePage ? "" : " secondary"}`}
                  onClick={() => setCurrentPage(p)}
                >
                  {p}
                </button>
              ))}
              <button
                type="button"
                className="btn secondary small"
                disabled={safePage >= totalPages}
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              >
                След. →
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="dash-section">
        <h3>Фискальная сверка колонок с ОФД и КГД</h3>
        <div className="dash-table-wrap">
          <table className="dash-table">
            <thead>
              <tr>
                <th>АГЗС</th>
                <th>Район</th>
                <th>Счётчики ТРК</th>
                <th>Чеки ККМ</th>
                <th>ОФД → КГД</th>
                <th>Статус КГД</th>
              </tr>
            </thead>
            <tbody>
              {pagedStations.map(({ d, fc, region }) => (
                <tr key={d.id} className="dash-row-link" onClick={() => onOpenStation(d.id)}>
                  <td>
                    <strong>{d.name}</strong>
                    <div className="dash-muted">
                      {d.code} · {d.pumps.length} ТРК
                    </div>
                  </td>
                  <td className="dash-muted">{region}</td>
                  <td>
                    {liters(fc.counter_liters)}
                    <div className="dash-muted">{fc.fills} заправок</div>
                  </td>
                  <td>
                    {liters(fc.kkm_liters)}
                    <div className="dash-muted">{fc.kkm_receipts} чеков</div>
                  </td>
                  <td>
                    {liters(fc.ofd_liters)}
                    <div className="dash-muted">{tenge(fc.ofd_amount_kzt)}</div>
                  </td>
                  <td>
                    <span className={`badge ${fiscalBadge(fc.status)}`}>
                      {fc.status === "ok"
                        ? fiscalText(fc.status)
                        : `${fiscalText(fc.status)} · ${liters(fc.gap_liters)}`}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="dash-section">
        <h3>Парк газовозов и активные рейсы</h3>
        <div className="dash-table-wrap">
          <table className="dash-table">
            <thead>
              <tr>
                <th>Госномер</th>
                <th>Статус</th>
                <th>Груз в цистерне</th>
                <th>Маршрут</th>
                <th>Перевозчик</th>
              </tr>
            </thead>
            <tbody>
              {state.trucks.map((t) => (
                <tr key={t.detail.id}>
                  <td>
                    <strong>{t.detail.plate_number}</strong>
                  </td>
                  <td>
                    <span className="badge ok">{phaseLabel(t.phase)}</span>
                  </td>
                  <td>{liters(t.cargo)}</td>
                  <td className="dash-muted">
                    {t.detail.origin_name} → {t.detail.destination_name}
                  </td>
                  <td className="dash-muted">{t.detail.carrier_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
