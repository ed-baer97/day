import { useMemo, useState } from "react";
import type { CatalogStation } from "../api/client";
import { useCatalog } from "../catalog";
import { liters, REGIONS, shortStationName, stationRegion } from "../format";
import { isLowFill, LOW_FILL_PERCENT, SensorStatus, usePublicLevels, useSensorDay, useViewPeriod, type LiveLevel } from "../liveLevels";
import { chartOf } from "../sensorDay";
import { BarChart, LineChart } from "./Charts";
import PeriodSwitch from "./PeriodSwitch";
import StationDetailPage from "./StationDetailPage";

type StatusFilter = "all" | "low" | "offline" | "no_sensor" | "ok";
type SortBy = "attention" | "fill_asc" | "change_desc" | "name_asc";
type ViewMode = "list" | "grid" | "regions";
type ChartMode = "remainder" | "change" | "by_region";

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
  const catalog = useCatalog();
  const { byCode } = usePublicLevels();
  const { range, historyLoading } = useViewPeriod();
  const stations = useMemo(
    () => catalog.stations.filter((row) => row.is_active),
    [catalog.stations]
  );
  const day = useSensorDay(stations.map((row) => row.id));

  const [query, setQuery] = useState("");
  const [regionFilter, setRegionFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sortBy, setSortBy] = useState<SortBy>("attention");
  const [viewMode, setViewMode] = useState<ViewMode>("list");
  const [chartMode, setChartMode] = useState<ChartMode>("remainder");
  const [pageSize, setPageSize] = useState(10);
  const [currentPage, setCurrentPage] = useState(1);

  const rows = useMemo(() => {
    return stations.map((station) => {
      const live = byCode.get(station.code) ?? null;
      const hasTanks = !!live && live.tanks.length > 0;
      const fill = hasTanks && live.fill != null ? Math.round(live.fill) : null;
      const online = !!live && live.tanks.some((tank) => tank.online === true && tank.remainder_liters != null);
      const spent = day.get(station.id)?.outflow ?? null;
      const hasJournal = (day.get(station.id)?.points.length ?? 0) > 0;
      const attention = (!hasTanks ? 2 : !online ? 3 : 0) + (isLowFill(fill) ? 2 : 0);
      return {
        station,
        live,
        hasTanks,
        fill,
        online,
        spent: hasJournal ? spent : null,
        region: stationRegion(station),
        gas: hasTanks ? live?.remainder ?? null : null,
        cap: hasTanks ? live?.capacity ?? 0 : 0,
        attention,
      };
    });
  }, [stations, byCode, day]);

  const totals = useMemo(() => {
    let litersSum = 0;
    let online = 0;
    let offline = 0;
    let noSensor = 0;
    let low = 0;
    let spent = 0;
    let spentKnown = false;
    let inflow = 0;
    for (const row of rows) {
      if (!row.hasTanks) noSensor++;
      else if (row.online) online++;
      else offline++;
      if (isLowFill(row.fill)) low++;
      if (row.gas != null) litersSum += row.gas;
      if (row.spent != null) {
        spent += row.spent;
        spentKnown = true;
      }
      inflow += day.get(row.station.id)?.inflow ?? 0;
    }
    return { litersSum, online, offline, noSensor, low, spent, spentKnown, inflow, all: rows.length, ok: online };
  }, [rows]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = rows.filter((row) => {
      if (q) {
        const hit = [row.station.name, row.station.code, row.station.address, row.region].some((part) =>
          part?.toLowerCase().includes(q)
        );
        if (!hit) return false;
      }
      if (regionFilter !== "all" && row.region !== regionFilter) return false;
      if (statusFilter === "low" && !isLowFill(row.fill)) return false;
      if (statusFilter === "offline" && !(row.hasTanks && !row.online)) return false;
      if (statusFilter === "no_sensor" && row.hasTanks) return false;
      if (statusFilter === "ok" && !row.online) return false;
      return true;
    });
    return [...list].sort((a, b) => {
      if (sortBy === "attention") return b.attention - a.attention || a.station.name.localeCompare(b.station.name, "ru");
      if (sortBy === "fill_asc") return (a.fill ?? 101) - (b.fill ?? 101);
      if (sortBy === "change_desc") return (b.spent ?? 0) - (a.spent ?? 0);
      return a.station.name.localeCompare(b.station.name, "ru");
    });
  }, [rows, query, regionFilter, statusFilter, sortBy]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(currentPage, totalPages);
  const paged = useMemo(() => {
    const start = (safePage - 1) * pageSize;
    return filtered.slice(start, start + pageSize);
  }, [filtered, safePage, pageSize]);

  const grouped = useMemo(() => {
    const map = new Map<string, typeof filtered>();
    for (const region of REGIONS) map.set(region, []);
    for (const row of filtered) {
      const bucket = map.get(row.region) ?? [];
      bucket.push(row);
      map.set(row.region, bucket);
    }
    return Array.from(map.entries()).filter(([, items]) => items.length > 0);
  }, [filtered]);

  const chartData = useMemo(() => {
    if (chartMode === "by_region") {
      const regs = REGIONS.filter((region) => rows.some((row) => row.region === region && row.gas != null));
      return {
        labels: regs.map((region) => region.replace(" р-н", "").replace("г. ", "")),
        series: [
          {
            name: "Остаток датчика",
            color: "var(--sea)",
            values: regs.map((region) =>
              rows.filter((row) => row.region === region).reduce((sum, row) => sum + (row.gas ?? 0), 0)
            ),
          },
        ],
      };
    }
    if (chartMode === "change") {
      const top = [...rows]
        .filter((row) => row.spent != null)
        .sort((a, b) => (b.spent ?? 0) - (a.spent ?? 0))
        .slice(0, 10);
      return {
        labels: top.map((row) => shortStationName(row.station.name)),
        series: [
          {
            name: "Расход",
            color: "var(--coral)",
            values: top.map((row) => row.spent ?? 0),
          },
        ],
      };
    }
    const top = [...rows]
      .filter((row) => row.gas != null)
      .sort((a, b) => (b.gas ?? 0) - (a.gas ?? 0))
      .slice(0, 10);
    return {
      labels: top.map((row) => shortStationName(row.station.name)),
      series: [{ name: "Остаток датчика", color: "var(--sea)", values: top.map((row) => row.gas ?? 0) }],
    };
  }, [chartMode, rows]);

  const levelChart = useMemo(() => {
    const summed = range.labels.map((_, index) => {
      let sum = 0;
      let known = false;
      for (const row of rows) {
        const level = day.get(row.station.id)?.series[index];
        if (level == null) continue;
        sum += level;
        known = true;
      }
      return known ? sum : null;
    });
    const chart = chartOf(summed, range.labels);
    if (chart.labels.length > 0) return chart;
    if (!range.includesNow || !rows.some((row) => row.gas != null)) return chart;
    const nowIndex = range.indexAt(Date.now());
    const gas = rows.reduce((sum, row) => sum + (row.gas ?? 0), 0);
    return {
      labels: [range.labels[nowIndex] ?? range.labels[range.labels.length - 1] ?? "сейчас"],
      values: [gas],
    };
  }, [rows, day, range]);

  function pickFilter(next: StatusFilter) {
    setStatusFilter(next);
    setCurrentPage(1);
  }

  return (
    <div className="dash">
      <header className="dash-hero">
        <div>
          <p className="kicker">Внутренний диспетчерский контур</p>
          <h2>Контроль сети АГЗС по датчикам ({totals.all})</h2>
        </div>
        <PeriodSwitch />
      </header>

      <div className="dash-kpis">
        <div className={`dash-kpi${statusFilter === "all" ? " active-kpi" : ""}`} onClick={() => pickFilter("all")} style={{ cursor: "pointer" }}>
          <span>Газ в резервуарах</span>
          <strong>{liters(totals.litersSum)}</strong>
          <em>по последним замерам</em>
        </div>
        <div className={`dash-kpi${statusFilter === "ok" ? " active-kpi" : ""}`} onClick={() => pickFilter("ok")} style={{ cursor: "pointer" }}>
          <span>Датчик на связи</span>
          <strong>{totals.online}</strong>
          <em>замер свежий</em>
        </div>
        <div
          className={`dash-kpi${statusFilter === "offline" ? " active-kpi" : ""}`}
          onClick={() => pickFilter("offline")}
          style={{ cursor: "pointer" }}
        >
          <span>Нет связи</span>
          <strong className={totals.offline ? "text-danger" : ""}>{totals.offline}</strong>
          <em>резервуар есть, замер устарел</em>
        </div>
        <div
          className={`dash-kpi${statusFilter === "no_sensor" ? " active-kpi" : ""}`}
          onClick={() => pickFilter("no_sensor")}
          style={{ cursor: "pointer" }}
        >
          <span>Датчик не подключён</span>
          <strong>{totals.noSensor}</strong>
          <em>резервуара в кабинете нет</em>
        </div>
        <div className="dash-kpi">
          <span>{range.inflowTitle}</span>
          <strong>{range.countsReceipts ? liters(totals.inflow) : "—"}</strong>
          <em>
            {range.countsReceipts
              ? totals.inflow > 0
                ? "принятые поставки"
                : "поставок не было, газ уже был в резервуаре"
              : "поставки в книге без даты, за этот срок не считаем"}
          </em>
        </div>
        <div className="dash-kpi">
          <span>{range.expenseTitle}</span>
          <strong>{totals.spentKnown ? liters(totals.spent) : "—"}</strong>
          <em>на сколько уровень ниже первого замера за срок</em>
        </div>
      </div>

      <div className="dash-charts">
        <section className="dash-card">
          <div className="card-head-inline">
            <h3>Сравнение АГЗС</h3>
            <div className="mini-tabs">
              <button type="button" className={chartMode === "remainder" ? "active" : ""} onClick={() => setChartMode("remainder")}>
                Остаток
              </button>
              <button type="button" className={chartMode === "change" ? "active" : ""} onClick={() => setChartMode("change")}>
                Расход
              </button>
              <button type="button" className={chartMode === "by_region" ? "active" : ""} onClick={() => setChartMode("by_region")}>
                По районам
              </button>
            </div>
          </div>
          {chartData.labels.length === 0 ? (
            <p className="dash-muted">
              {chartMode === "change"
                ? "Расхода нет: уровень не падал. Приход 0 л — поставки не было."
                : "На диаграмме появятся станции, у которых есть замер датчика."}
            </p>
          ) : (
            <BarChart labels={chartData.labels} series={chartData.series} />
          )}
        </section>
        <section className="dash-card">
          <h3>{range.chartTitle}</h3>
          <p className="dash-muted">
            {range.countsReceipts ? (
              <>
                Приход {liters(totals.inflow)}
                {totals.inflow > 0 ? " — это поставки." : ": поставки не было."}{" "}
              </>
            ) : null}
            Линия — газ, который уже был, по замерам датчика.
          </p>
          {historyLoading && levelChart.labels.length === 0 ? (
            <p className="dash-muted">Загрузка замеров…</p>
          ) : levelChart.labels.length === 0 ? (
            <p className="dash-muted">Замера датчика за этот срок ещё нет.</p>
          ) : levelChart.labels.length === 1 ? (
            <BarChart
              labels={levelChart.labels}
              series={[{ name: "Остаток", color: "var(--sea)", values: levelChart.values }]}
            />
          ) : (
            <LineChart
              labels={levelChart.labels}
              series={[{ name: "Остаток", color: "var(--sea)", values: levelChart.values }]}
            />
          )}
        </section>
      </div>

      <section className="dash-section">
        <div className="st-nav-toolbar">
          <div className="st-nav-top">
            <h3>
              Навигатор АГЗС{" "}
              <span className="dash-muted">
                (показано {filtered.length} из {totals.all})
              </span>
            </h3>
            <div className="st-view-controls">
              <div className="mini-tabs" role="group" aria-label="Режим отображения">
                <button type="button" className={viewMode === "list" ? "active" : ""} onClick={() => setViewMode("list")}>
                  Список
                </button>
                <button type="button" className={viewMode === "grid" ? "active" : ""} onClick={() => setViewMode("grid")}>
                  Плитка
                </button>
                <button type="button" className={viewMode === "regions" ? "active" : ""} onClick={() => setViewMode("regions")}>
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
              onChange={(event) => {
                setQuery(event.target.value);
                setCurrentPage(1);
              }}
            />
            <select
              className="st-select"
              value={regionFilter}
              aria-label="Район"
              onChange={(event) => {
                setRegionFilter(event.target.value);
                setCurrentPage(1);
              }}
            >
              <option value="all">Все районы ({totals.all})</option>
              {REGIONS.map((region) => {
                const count = rows.filter((row) => row.region === region).length;
                if (!count) return null;
                return (
                  <option key={region} value={region}>
                    {region} ({count})
                  </option>
                );
              })}
            </select>
            <select
              className="st-select"
              value={sortBy}
              aria-label="Сортировка"
              onChange={(event) => setSortBy(event.target.value as SortBy)}
            >
              <option value="attention">Сначала без связи и мало газа</option>
              <option value="fill_asc">По остатку газа (сначала мало)</option>
              <option value="change_desc">По расходу за выбранный срок</option>
              <option value="name_asc">По алфавиту (А–Я)</option>
            </select>
            {viewMode !== "regions" ? (
              <select
                className="st-select"
                value={pageSize}
                aria-label="Показывать по"
                onChange={(event) => {
                  setPageSize(Number(event.target.value));
                  setCurrentPage(1);
                }}
              >
                <option value={8}>По 8 на стр.</option>
                <option value={10}>По 10 на стр.</option>
                <option value={20}>По 20 на стр.</option>
                <option value={100}>Все ({filtered.length})</option>
              </select>
            ) : null}
          </div>

          <div className="st-status-pills" role="group" aria-label="Фильтр по статусу">
            <button type="button" className={`filter-pill${statusFilter === "all" ? " active" : ""}`} onClick={() => pickFilter("all")}>
              Все АГЗС ({totals.all})
            </button>
            <button type="button" className={`filter-pill${statusFilter === "low" ? " active" : ""}`} onClick={() => pickFilter("low")}>
              Мало газа &lt; {LOW_FILL_PERCENT}% ({totals.low})
            </button>
            <button type="button" className={`filter-pill${statusFilter === "offline" ? " active" : ""}`} onClick={() => pickFilter("offline")}>
              Нет связи ({totals.offline})
            </button>
            <button
              type="button"
              className={`filter-pill${statusFilter === "no_sensor" ? " active" : ""}`}
              onClick={() => pickFilter("no_sensor")}
            >
              Без датчика ({totals.noSensor})
            </button>
            <button type="button" className={`filter-pill${statusFilter === "ok" ? " active" : ""}`} onClick={() => pickFilter("ok")}>
              На связи ({totals.ok})
            </button>
            {query || regionFilter !== "all" || statusFilter !== "all" ? (
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
            ) : null}
          </div>
        </div>

        {catalog.error ? <p className="tank-error">{catalog.error}</p> : null}
        {!catalog.ready ? <p className="dash-muted">Загрузка станций…</p> : null}
        {catalog.ready && filtered.length === 0 ? (
          <div className="empty">
            <strong>По заданным условиям АГЗС не найдены</strong>
            <p>Измените поиск или сбросьте фильтр района и статуса.</p>
          </div>
        ) : viewMode === "list" ? (
          <ul className="st-list">
            {paged.map((row) => (
              <StationListRow
                key={row.station.id}
                {...row}
                spentCaption={range.spentCaption}
                onOpen={() => onOpenStation(row.station.id)}
                onMap={onOpenMapStation ? () => onOpenMapStation(row.station.id) : undefined}
                onAdmin={onOpenAdminStation ? () => onOpenAdminStation(row.station.id) : undefined}
              />
            ))}
          </ul>
        ) : viewMode === "grid" ? (
          <div className="st-card-grid">
            {paged.map((row) => (
              <article key={row.station.id} className="dash-card st-grid-card" onClick={() => onOpenStation(row.station.id)}>
                <div className="st-grid-card-head">
                  <div>
                    <span className="badge">{row.region}</span>
                    <h4>{row.station.name}</h4>
                    <span className="dash-muted">
                      {row.station.code} · {row.station.address || "адрес не указан"}
                    </span>
                  </div>
                  <strong className={`st-grid-pct${isLowFill(row.fill) ? " text-danger" : ""}`}>
                    {row.fill == null ? "—" : `${row.fill}%`}
                  </strong>
                </div>
                <div className="fill-bar" style={{ margin: "10px 0 6px" }}>
                  <i
                    style={{
                      width: `${row.fill ?? 0}%`,
                      background: isLowFill(row.fill) ? "var(--coral)" : "var(--sea)",
                    }}
                  />
                </div>
                <div className="st-grid-metrics">
                  <div>
                    <span>Факт / ёмкость</span>
                    <strong>
                      {row.gas == null ? "замера нет" : liters(row.gas)} / {liters(row.cap)}
                    </strong>
                  </div>
                  <div>
                    <span>{range.spentCaption}</span>
                    <strong>{row.spent == null ? "—" : liters(row.spent)}</strong>
                  </div>
                  <div>
                    <span>Резервуаров</span>
                    <strong>{row.live?.tanks.length ?? 0}</strong>
                  </div>
                  <div>
                    <span>Датчик</span>
                    <strong>{row.hasTanks && row.live ? (row.online ? "на связи" : "нет связи") : "не подключён"}</strong>
                  </div>
                </div>
                <div className="st-grid-footer">
                  {row.hasTanks && row.live ? <SensorStatus level={row.live} /> : <span className="badge warn">датчик не подключён</span>}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="st-regions-group">
            {grouped.map(([region, items]) => (
              <div key={region} className="region-group-block">
                <header className="region-group-head">
                  <h4>{region}</h4>
                  <span>
                    {items.length} АГЗС · остаток {liters(items.reduce((sum, row) => sum + (row.gas ?? 0), 0))}
                  </span>
                </header>
                <ul className="st-list">
                  {items.map((row) => (
                    <li key={row.station.id}>
                      <button type="button" className="st-row" onClick={() => onOpenStation(row.station.id)}>
                        <div className="st-row-main">
                          <strong>{row.station.name}</strong>
                          <span>
                            {row.station.code} · {row.station.address || "адрес не указан"}
                          </span>
                        </div>
                        <FillCell fill={row.fill} gas={row.gas} cap={row.cap} live={row.hasTanks ? row.live : null} />
                        <div className="st-row-num">
                          <strong>{row.spent == null ? "—" : liters(row.spent)}</strong>
                          <span>{range.spentCaption}</span>
                        </div>
                        <div className="st-row-num">
                          <strong>{row.live?.tanks.length ?? 0}</strong>
                          <span>резервуаров</span>
                        </div>
                        <div className="st-row-badges">
                          {row.hasTanks && row.live ? (
                            <SensorStatus level={row.live} />
                          ) : (
                            <span className="badge warn">не подключён</span>
                          )}
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

        {viewMode !== "regions" && totalPages > 1 ? (
          <div className="pagination-bar">
            <span className="dash-muted">
              Страница {safePage} из {totalPages} ({filtered.length} АГЗС)
            </span>
            <div className="pagination-buttons">
              <button
                type="button"
                className="btn secondary small"
                disabled={safePage <= 1}
                onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
              >
                ← Пред.
              </button>
              {Array.from({ length: totalPages }, (_, index) => index + 1).map((page) => (
                <button
                  key={page}
                  type="button"
                  className={`btn small${page === safePage ? "" : " secondary"}`}
                  onClick={() => setCurrentPage(page)}
                >
                  {page}
                </button>
              ))}
              <button
                type="button"
                className="btn secondary small"
                disabled={safePage >= totalPages}
                onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
              >
                След. →
              </button>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function FillCell({
  fill,
  gas,
  cap,
  live,
}: {
  fill: number | null;
  gas: number | null;
  cap: number;
  live: LiveLevel | null;
}) {
  return (
    <div className="st-row-fill">
      <div className="fill-bar">
        <i
          style={{
            width: `${fill ?? 0}%`,
            background: isLowFill(fill) ? "var(--coral)" : "var(--sea)",
          }}
        />
      </div>
      <span>
        {gas == null ? "замера нет" : `${liters(gas)} из ${liters(cap)}`} ·{" "}
        <strong className={isLowFill(fill) ? "text-danger" : ""}>{fill == null ? "—" : `${fill}%`}</strong>
      </span>
      {live && live.tanks.length > 0 ? <SensorStatus level={live} /> : null}
    </div>
  );
}

function StationListRow({
  station,
  region,
  fill,
  gas,
  cap,
  live,
  hasTanks,
  spent,
  spentCaption,
  onOpen,
  onMap,
  onAdmin,
}: {
  station: CatalogStation;
  region: string;
  fill: number | null;
  gas: number | null;
  cap: number;
  live: LiveLevel | null;
  hasTanks: boolean;
  spent: number | null;
  spentCaption: string;
  onOpen: () => void;
  onMap?: () => void;
  onAdmin?: () => void;
}) {
  return (
    <li className="st-list-item">
      <div className="st-row" onClick={onOpen}>
        <div className="st-row-main">
          <strong>{station.name}</strong>
          <span>
            {station.code} · {region}
          </span>
        </div>
        <FillCell fill={fill} gas={gas} cap={cap} live={hasTanks ? live : null} />
        <div className="st-row-num">
          <strong>{spent == null ? "—" : liters(spent)}</strong>
          <span>{spentCaption}</span>
        </div>
        <div className="st-row-num">
          <strong>{live?.tanks.length ?? 0}</strong>
          <span>резервуаров</span>
        </div>
        <div className="st-row-badges">
          {hasTanks && live ? <SensorStatus level={live} /> : <span className="badge warn">не подключён</span>}
        </div>
        <div className="st-row-actions" onClick={(event) => event.stopPropagation()}>
          {onMap ? (
            <button type="button" className="btn secondary small" onClick={onMap}>
              Карта
            </button>
          ) : null}
          {onAdmin ? (
            <button type="button" className="btn secondary small" onClick={onAdmin}>
              Администратор
            </button>
          ) : null}
        </div>
      </div>
    </li>
  );
}
