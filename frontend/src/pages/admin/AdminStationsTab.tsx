import type { Dispatch, SetStateAction } from "react";
import type {
  CatalogStation,
  CatalogTruck,
  EdgeFleetSummary,
  OwnerAccount,
} from "../../api/client";
import LevelChangesToday from "../../components/LevelChangesToday";
import StationOwnerCard from "../../components/StationOwnerCard";
import TankDeviceRows from "../../components/TankDeviceRows";
import { columnsModeLabel, dateTime, liters, REGIONS } from "../../format";
import { isLowFill, LOW_FILL_PERCENT, SensorStatusBadge } from "../../liveLevels";
import { SAFE_FILL_PERCENT } from "../../policy";
import StationColumnsCard from "./StationColumnsCard";
import StationForm from "./StationForm";
import type { EnrichedStation } from "./types";

type CatalogSlice = {
  stations: CatalogStation[];
  trucks: CatalogTruck[];
  error: string | null;
};

export type StationAdminFilter = "all" | "active" | "inactive" | "issue" | "low" | "no_sensor";

export default function AdminStationsTab({
  catalog,
  enriched,
  owners,
  edgeFleet,
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
  onOpenAccessTab,
  onRefreshOverview,
  onRefreshOwners,
  toast,
  scrollTop,
}: {
  catalog: CatalogSlice;
  enriched: EnrichedStation[];
  owners: OwnerAccount[];
  edgeFleet: EdgeFleetSummary | null;
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
  filter: StationAdminFilter;
  setFilter: (value: StationAdminFilter) => void;
  pageSize: number;
  setPageSize: (value: number) => void;
  setPage: Dispatch<SetStateAction<number>>;
  filtered: EnrichedStation[];
  paged: EnrichedStation[];
  totalPages: number;
  safePage: number;
  onOpenStationDashboard?: (id: string) => void;
  onOpenStationMap?: (id: string) => void;
  onOpenAccessTab?: () => void;
  onRefreshOverview: () => void;
  onRefreshOwners: () => void;
  toast: { ok: (message: string) => void };
  scrollTop: () => void;
}) {
  const edgeNode = station
    ? edgeFleet?.nodes.find((n) => n.station_code === station.code) ?? null
    : null;

  return (
    <>
      {stationId == null && (
        <div className="st-filter-bar" style={{ marginBottom: 14 }}>
          <input
            type="search"
            className="st-search-input"
            value={query}
            placeholder="Быстрый фильтр АГЗС по названию, коду, адресу или району…"
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
          />
          <select
            className="st-select"
            value={region}
            aria-label="Фильтр по району"
            onChange={(e) => {
              setRegion(e.target.value);
              setPage(1);
            }}
          >
            <option value="all">Все районы ({catalog.stations.length})</option>
            {REGIONS.map((reg) => {
              const cnt = enriched.filter((x) => x.region === reg).length;
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
            value={filter}
            aria-label="Статус станции"
            onChange={(e) => {
              setFilter(e.target.value as StationAdminFilter);
              setPage(1);
            }}
          >
            <option value="all">Все статусы ({catalog.stations.length})</option>
            <option value="active">Работают</option>
            <option value="inactive">Скрыты</option>
            <option value="issue">Нет связи с датчиком</option>
            <option value="no_sensor">Без резервуара / датчика</option>
            <option value="low">Мало газа (&lt; {LOW_FILL_PERCENT}%)</option>
          </select>
          <select
            className="st-select"
            value={pageSize}
            aria-label="На странице"
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setPage(1);
            }}
          >
            <option value={8}>По 8 строк</option>
            <option value={10}>По 10 строк</option>
            <option value={20}>По 20 строк</option>
            <option value={100}>Все ({filtered.length})</option>
          </select>
          <button
            type="button"
            className="btn"
            onClick={() => {
              setStationId("new");
              scrollTop();
            }}
          >
            + Новая АГЗС
          </button>
        </div>
      )}

      {stationId == null ? (
        <div>
          <p className="dash-muted" style={{ margin: "0 0 8px" }}>
            Нажмите строку, чтобы открыть паспорт АГЗС, режим колонок (виртуальные / edge),
            резервуары Shelly и привязку владельца.
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
                  <th>Колонки (ТРК)</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {paged.map((item) => {
                  const { row, actual, cap, fill, free, live, region: reg, tanksCount, calibratedCount, online } = item;
                  const mode = row.columns_mode ?? "none";
                  const count = row.columns_count ?? 2;
                  return (
                    <tr
                      key={row.id}
                      className={`dash-row-link${stationId === row.id ? " active" : ""}`}
                      onClick={() => {
                        setStationId(row.id);
                        scrollTop();
                      }}
                    >
                      <td>
                        <strong>{row.code}</strong>
                        <div className="dash-muted">{reg}</div>
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
                          <SensorStatusBadge level={live} />
                        ) : tanksCount > 0 ? (
                          <span
                            className={`badge ${
                              actual == null ? "warn" : online ? "ok" : "danger"
                            }`}
                          >
                            {actual == null
                              ? "замера нет"
                              : online
                                ? "датчик работает"
                                : "нет связи"}
                          </span>
                        ) : (
                          <span className="badge warn">не подключён</span>
                        )}
                        <div className="dash-muted">
                          емкостей: {tanksCount}
                          {tanksCount > 0 ? ` (калибр. ${calibratedCount}/${tanksCount})` : ""}
                        </div>
                      </td>
                      <td>
                        <span
                          className={`badge ${
                            mode === "edge" ? "ok" : mode === "virtual" ? "warn" : ""
                          }`}
                        >
                          {mode === "none" ? "—" : `${columnsModeLabel(mode)} · ${count}`}
                        </span>
                      </td>
                      <td>
                        <span className={`badge ${row.is_active ? "ok" : "warn"}`}>
                          {row.is_active ? "работает" : "скрыта"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
                {paged.length === 0 && (
                  <tr>
                    <td colSpan={7} className="dash-muted">
                      По выбранному фильтру заправок не найдено.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="pagination-bar" style={{ marginTop: 10 }}>
              <span className="dash-muted">
                Стр. {safePage} из {totalPages} (всего {filtered.length} АГЗС)
              </span>
              <div className="pagination-buttons">
                <button
                  type="button"
                  className="btn secondary small"
                  disabled={safePage <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  ← Пред.
                </button>
                {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                  <button
                    key={p}
                    type="button"
                    className={`btn small${p === safePage ? "" : " secondary"}`}
                    onClick={() => setPage(p)}
                  >
                    {p}
                  </button>
                ))}
                <button
                  type="button"
                  className="btn secondary small"
                  disabled={safePage >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
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
                    {(filtered.length > 0 ? filtered.map((f) => f.row) : catalog.stations).map(
                      (item, idx) => (
                        <option key={item.id} value={item.id}>
                          {idx + 1}. {item.name} ({item.code})
                        </option>
                      )
                    )}
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
                {onOpenStationDashboard && station.is_active && (
                  <button
                    type="button"
                    className="btn secondary small"
                    onClick={() => onOpenStationDashboard(station.id)}
                  >
                    Детальная сводка и графики →
                  </button>
                )}
                {onOpenStationMap && station.is_active && (
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
                onSaved={(saved) => {
                  onRefreshOverview();
                  setStationId(saved.id);
                  toast.ok(`Заправка ${saved.name} создана`);
                }}
                onDeleted={() => {
                  onRefreshOverview();
                  setStationId(null);
                }}
              />
            </section>
          ) : station ? (
            <>
              {stationEnriched ? (
                <div className="dash-kpis" style={{ marginBottom: 4 }}>
                  <div className="dash-kpi">
                    <span>Код и район</span>
                    <strong>{station.code}</strong>
                    <em>
                      {stationEnriched.region}
                      {!station.is_active ? " · скрыта с витрины" : ""}
                    </em>
                  </div>
                  <div className="dash-kpi">
                    <span>Фактический остаток</span>
                    <strong className={isLowFill(stationEnriched.fill) ? "text-danger" : ""}>
                      {stationEnriched.actual == null ? "—" : liters(stationEnriched.actual)}
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
                      до {SAFE_FILL_PERCENT}%:{" "}
                      {stationEnriched.safeRefill == null
                        ? "—"
                        : liters(stationEnriched.safeRefill)}
                    </em>
                  </div>
                  <div className="dash-kpi">
                    <span>Резервуары и связь</span>
                    <strong>{stationEnriched.tanksCount} шт.</strong>
                    <em>
                      {stationEnriched.live?.measuredAt
                        ? `замер ${dateTime(stationEnriched.live.measuredAt)}`
                        : stationEnriched.online
                          ? "датчик на связи"
                          : "замера нет"}
                    </em>
                  </div>
                </div>
              ) : null}

              <section className="dash-card admin-form-card">
                <StationForm
                  key={station.id}
                  initial={station}
                  onSaved={(saved) => {
                    onRefreshOverview();
                    toast.ok(`Карточка ${saved.name} обновлена`);
                  }}
                  onDeleted={() => {
                    onRefreshOverview();
                    setStationId(null);
                    toast.ok(`Заправка ${station.name} удалена`);
                  }}
                />
              </section>

              <StationColumnsCard
                station={station}
                edgeNode={edgeNode}
                onSaved={onRefreshOverview}
                toast={toast}
              />

              <section className="dash-card">
                <h3>Резервуары, датчики Shelly и ручные операции</h3>
                <p className="dash-muted">
                  Подключение локального IP датчика Shelly Plus Uni, калибровка вольтметра
                  (0%…100%), ручной ввод замера или прихода, а также управление X-Device-Token.
                </p>
                <TankDeviceRows
                  stationId={station.id}
                  initialStates={stationEnriched?.overview?.tanks}
                  onChanged={onRefreshOverview}
                />
                <LevelChangesToday stationId={station.id} />
              </section>

              <StationOwnerCard
                stationId={station.id}
                allOwners={owners}
                onChanged={onRefreshOwners}
                onOpenAccessTab={onOpenAccessTab}
              />
            </>
          ) : (
            <p className="admin-empty">Эта АГЗС больше не в списке.</p>
          )}
        </div>
      )}
    </>
  );
}
