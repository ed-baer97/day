import type { Dispatch, SetStateAction } from "react";
import type { CatalogStation, CatalogTruck } from "../../api/client";
import LevelChangesToday from "../../components/LevelChangesToday";
import StationOwnerCard from "../../components/StationOwnerCard";
import TankDeviceRows from "../../components/TankDeviceRows";
import { dateTime, liters, REGIONS } from "../../format";
import { isLowFill, LOW_FILL_PERCENT, SensorStatus } from "../../liveLevels";
import StationForm from "./StationForm";
import type { EnrichedStation } from "./types";

type CatalogSlice = {
  stations: CatalogStation[];
  trucks: CatalogTruck[];
  error: string | null;
};

export default function AdminStationsTab({
  catalog,
  enriched,
  stationId,
  setStationId,
  station,
  stationEnriched,
  prevStation,
  nextStation,
  query,
  setQuery,
  region,
  setRegion,
  filter,
  setFilter,
  pageSize,
  setPageSize,
  setPage,
  filtered,
  paged,
  totalPages,
  safePage,
  onOpenStationDashboard,
  onOpenStationMap,
  toast,
  scrollTop,
}: {
  catalog: CatalogSlice;
  enriched: EnrichedStation[];
  stationId: string | "new" | null;
  setStationId: (id: string | "new" | null) => void;
  station: CatalogStation | null;
  stationEnriched: EnrichedStation | null;
  prevStation: CatalogStation | undefined;
  nextStation: CatalogStation | undefined;
  query: string;
  setQuery: (value: string) => void;
  region: string;
  setRegion: (value: string) => void;
  filter: "all" | "active" | "inactive" | "issue" | "low";
  setFilter: (value: "all" | "active" | "inactive" | "issue" | "low") => void;
  pageSize: number;
  setPageSize: (value: number) => void;
  setPage: Dispatch<SetStateAction<number>>;
  filtered: EnrichedStation[];
  paged: EnrichedStation[];
  totalPages: number;
  safePage: number;
  onOpenStationDashboard?: (id: string) => void;
  onOpenStationMap?: (id: string) => void;
  toast: { ok: (message: string) => void };
  scrollTop: () => void;
}) {
  const stQuery = query;
  const setStQuery = setQuery;
  const stRegion = region;
  const setStRegion = setRegion;
  const stFilter = filter;
  const setStFilter = setFilter;
  const stPageSize = pageSize;
  const setStPageSize = setPageSize;
  const setStPage = setPage;
  const filteredStations = filtered;
  const pagedStations = paged;
  const totalStPages = totalPages;
  const safeStPage = safePage;
  const scrollAdminTop = scrollTop;
  const enrichedCatalogStations = enriched;
  return (
            <>
              {stationId == null && (
                <div className="st-filter-bar" style={{ marginBottom: 14 }}>
                  <input
                    type="search"
                    className="st-search-input"
                    value={stQuery}
                    placeholder="Быстрый фильтр АГЗС по названию, коду, адресу или району…"
                    onChange={(e) => {
                      setStQuery(e.target.value);
                      setStPage(1);
                    }}
                  />
                  <select
                    className="st-select"
                    value={stRegion}
                    aria-label="Фильтр по району"
                    onChange={(e) => {
                      setStRegion(e.target.value);
                      setStPage(1);
                    }}
                  >
                    <option value="all">Все районы ({catalog.stations.length})</option>
                    {REGIONS.map((reg) => {
                      const cnt = enrichedCatalogStations.filter((x) => x.region === reg).length;
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
                    value={stFilter}
                    aria-label="Статус станции"
                    onChange={(e) => {
                      setStFilter(e.target.value as typeof stFilter);
                      setStPage(1);
                    }}
                  >
                    <option value="all">Все статусы ({catalog.stations.length})</option>
                    <option value="active">Работают</option>
                    <option value="inactive">Скрыты</option>
                    <option value="issue">Нет связи с датчиком</option>
                    <option value="low">Мало газа (&lt; {LOW_FILL_PERCENT}%)</option>
                  </select>
                  <select
                    className="st-select"
                    value={stPageSize}
                    aria-label="На странице"
                    onChange={(e) => {
                      setStPageSize(Number(e.target.value));
                      setStPage(1);
                    }}
                  >
                    <option value={8}>По 8 строк</option>
                    <option value={10}>По 10 строк</option>
                    <option value={20}>По 20 строк</option>
                    <option value={100}>Все ({filteredStations.length})</option>
                  </select>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      setStationId("new");
                      scrollAdminTop();
                    }}
                  >
                    + Новая АГЗС
                  </button>
                </div>
              )}

              {stationId == null ? (
                <div>
                  <p className="dash-muted" style={{ margin: "0 0 8px" }}>
                    Нажмите строку, чтобы открыть карточку настройки станции, резервуаров Shelly и владельца.
                  </p>
                  <div className="dash-table-wrap admin-table">
                    <table className="dash-table">
                      <thead>
                        <tr>
                          <th>Код / Район</th>
                          <th>Название и адрес</th>
                          <th>Остаток / Ёмкость</th>
                          <th>Свободно</th>
                          <th>Датчик и резервуары</th>
                          <th>Статус</th>
                          <th>Переход</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pagedStations.map(({ row, actual, cap, fill, free, live, region }) => (
                          <tr
                            key={row.id}
                            className={`dash-row-link${stationId === row.id ? " active" : ""}`}
                            onClick={() => {
                              setStationId(row.id);
                              scrollAdminTop();
                            }}
                          >
                            <td>
                              <strong>{row.code}</strong>
                              <div className="dash-muted">{region}</div>
                            </td>
                            <td>
                              <strong>{row.name}</strong>
                              <div className="dash-muted">{row.address || "—"}</div>
                            </td>
                            <td>
                              <strong className={isLowFill(fill) ? "text-danger" : ""}>
                                {fill == null ? "—" : `${fill}%`}
                              </strong>
                              <div className="dash-muted">
                                {actual == null
                                  ? "замера ещё нет"
                                  : `${liters(actual)} / ${liters(cap)}`}
                              </div>
                            </td>
                            <td>
                              <strong>{free == null ? "—" : liters(free)}</strong>
                            </td>
                            <td>
                              {live && live.tanks.length > 0 ? (
                                <SensorStatus level={live} />
                              ) : (
                                <span className="badge warn">не подключён</span>
                              )}
                              <div className="dash-muted">
                                емкостей: {live?.tanks.length ?? 0}
                              </div>
                            </td>
                            <td>
                              <span className={`badge ${row.is_active ? "ok" : "warn"}`}>
                                {row.is_active ? "работает" : "скрыта"}
                              </span>
                            </td>
                            <td onClick={(e) => e.stopPropagation()}>
                              <div style={{ display: "flex", gap: 4 }}>
                                {onOpenStationDashboard ? (
                                  <button
                                    type="button"
                                    className="btn secondary small"
                                    onClick={() => onOpenStationDashboard(row.id)}
                                  >
                                    Сводка
                                  </button>
                                ) : null}
                                {onOpenStationMap ? (
                                  <button
                                    type="button"
                                    className="btn secondary small"
                                    onClick={() => onOpenStationMap(row.id)}
                                  >
                                    Карта
                                  </button>
                                ) : null}
                              </div>
                            </td>
                          </tr>
                        ))}
                        {pagedStations.length === 0 && (
                          <tr>
                            <td colSpan={7} className="dash-muted">
                              По выбранному фильтру заправок не найдено.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>

                  {totalStPages > 1 && (
                    <div className="pagination-bar" style={{ marginTop: 10 }}>
                      <span className="dash-muted">
                        Стр. {safeStPage} из {totalStPages} (всего {filteredStations.length} АГЗС)
                      </span>
                      <div className="pagination-buttons">
                        <button
                          type="button"
                          className="btn secondary small"
                          disabled={safeStPage <= 1}
                          onClick={() => setStPage((p) => Math.max(1, p - 1))}
                        >
                          ← Пред.
                        </button>
                        {Array.from({ length: totalStPages }, (_, i) => i + 1).map((p) => (
                          <button
                            key={p}
                            type="button"
                            className={`btn small${p === safeStPage ? "" : " secondary"}`}
                            onClick={() => setStPage(p)}
                          >
                            {p}
                          </button>
                        ))}
                        <button
                          type="button"
                          className="btn secondary small"
                          disabled={safeStPage >= totalStPages}
                          onClick={() => setStPage((p) => Math.min(totalStPages, p + 1))}
                        >
                          След. →
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="admin-workspace">
                  <div className="admin-backbar">
                    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                      <button
                        type="button"
                        className="btn secondary small"
                        onClick={() => setStationId(null)}
                      >
                        ← К списку АГЗС ({catalog.stations.length})
                      </button>
                      {station && catalog.stations.length > 1 ? (
                        <div className="st-Detail-switcher">
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() => prevStation && setStationId(prevStation.id)}
                          >
                            ‹ Пред.
                          </button>
                          <select
                            className="st-select"
                            value={station.id}
                            aria-label="Переключить АГЗС в админке"
                            onChange={(e) => setStationId(e.target.value)}
                          >
                            {catalog.stations.map((item, idx) => (
                              <option key={item.id} value={item.id}>
                                {idx + 1}. {item.name} ({item.code})
                              </option>
                            ))}
                          </select>
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() => nextStation && setStationId(nextStation.id)}
                          >
                            След. ›
                          </button>
                        </div>
                      ) : null}
                    </div>
                    {station ? (
                      <div className="admin-editor-head-actions" style={{ marginBottom: 0 }}>
                        {onOpenStationDashboard && (
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() => onOpenStationDashboard(station.id)}
                          >
                            Детальная сводка и графики →
                          </button>
                        )}
                        {onOpenStationMap && (
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() => onOpenStationMap(station.id)}
                          >
                            Показать на карте
                          </button>
                        )}
                      </div>
                    ) : null}
                  </div>

                  {stationId === "new" ? (
                    <section className="dash-card admin-form-card">
                      <StationForm
                        key="new-station"
                        initial={null}
                        onCancel={() => setStationId(null)}
                        onSaved={(saved) => {
                          setStationId(saved.id);
                          toast.ok(`Заправка ${saved.name} создана`);
                        }}
                        onDeleted={() => setStationId(null)}
                      />
                    </section>
                  ) : station ? (
                    <>
                      {stationEnriched ? (
                        <div className="dash-kpis" style={{ marginBottom: 4 }}>
                          <div className="dash-kpi">
                            <span>Код и район</span>
                            <strong>{station.code}</strong>
                            <em>{stationEnriched.region}</em>
                          </div>
                          <div className="dash-kpi">
                            <span>Фактический остаток</span>
                            <strong
                              className={isLowFill(stationEnriched.fill) ? "text-danger" : ""}
                            >
                              {stationEnriched.actual == null
                                ? "—"
                                : liters(stationEnriched.actual)}
                            </strong>
                            <em>
                              из {liters(stationEnriched.cap)} (
                              {stationEnriched.fill == null ? "—" : `${stationEnriched.fill}%`})
                            </em>
                          </div>
                          <div className="dash-kpi">
                            <span>Свободный объём</span>
                            <strong>
                              {stationEnriched.free == null ? "—" : liters(stationEnriched.free)}
                            </strong>
                            <em>
                              до 85%:{" "}
                              {stationEnriched.safeRefill == null
                                ? "—"
                                : liters(stationEnriched.safeRefill)}
                            </em>
                          </div>
                          <div className="dash-kpi">
                            <span>Резервуары и связь</span>
                            <strong>{stationEnriched.live?.tanks.length ?? 0} шт.</strong>
                            <em>
                              {stationEnriched.live?.measuredAt
                                ? `замер ${dateTime(stationEnriched.live.measuredAt)}`
                                : "замера нет"}
                            </em>
                          </div>
                        </div>
                      ) : null}

                      <section className="dash-card admin-form-card">
                        <StationForm
                          key={station.id}
                          initial={station}
                          onCancel={() => setStationId(null)}
                          onSaved={(saved) => toast.ok(`Карточка ${saved.name} обновлена`)}
                          onDeleted={() => {
                            setStationId(null);
                            toast.ok(`Заправка ${station.name} удалена`);
                          }}
                        />
                      </section>
                      <section className="dash-card">
                        <h3>Резервуары, датчики Shelly и ручные операции</h3>
                        <p className="dash-muted">
                          Подключение локального IP датчика Shelly Plus Uni, калибровка вольтметра
                          (0%…100%), ручной ввод замера или прихода, а также X-Device-Token.
                        </p>
                        <TankDeviceRows stationId={station.id} />
                        <LevelChangesToday stationId={station.id} />
                      </section>
                      <StationOwnerCard stationId={station.id} />
                    </>
                  ) : (
                    <p className="admin-empty">Эта АГЗС больше не в списке.</p>
                  )}
                </div>
              )}
            </>
  );
}
