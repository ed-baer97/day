import { useEffect, useMemo, useState } from "react";
import {
  api,
  type BatchRecord,
} from "../api/client";
import { isAdmin } from "../access";
import { useAuth } from "../auth";
import { messageOf, useCatalog } from "../catalog";
import { dateTime, liters, REGIONS, stationRegion } from "../format";
import { isLowFill, LOW_FILL_PERCENT, SensorStatus, usePublicLevels } from "../liveLevels";
import type { DiscrepancyEvent } from "../types";
import LevelChangesToday from "./LevelChangesToday";
import StationOwnerCard from "./StationOwnerCard";
import TankDeviceRows from "./TankDeviceRows";
import { useToast } from "./Toast";
import {
  ADMIN_SECTIONS,
  TRUCK_STATUS,
  statusLabel,
  type AdminTab,
} from "../pages/admin/types";
import StationForm from "../pages/admin/StationForm";
import TruckForm from "../pages/admin/TruckForm";
import AdminSecurityTab from "../pages/admin/AdminSecurityTab";

function scrollAdminTop() {
  document.querySelector(".page.dash-page")?.scrollTo({ top: 0 });
}

export default function AdminPage({
  initialStationId,
  initialTruckId,
  onOpenStationDashboard,
  onOpenStationMap,
}: {
  initialStationId?: string | null;
  initialTruckId?: string | null;
  onOpenStationDashboard?: (id: string) => void;
  onOpenStationMap?: (id: string) => void;
}) {
  const catalog = useCatalog();
  const { byCode } = usePublicLevels();
  const { session } = useAuth();
  const toast = useToast();
  const admin = isAdmin(session);

  const [tab, setTab] = useState<AdminTab>(initialTruckId ? "trucks" : "stations");
  const [stationId, setStationId] = useState<string | "new" | null>(initialStationId ?? null);
  const [truckId, setTruckId] = useState<string | "new" | null>(initialTruckId ?? null);

  // Фильтры и пагинация для большого количества АГЗС в админке
  const [stQuery, setStQuery] = useState("");
  const [stRegion, setStRegion] = useState<string>("all");
  const [stFilter, setStFilter] = useState<"all" | "active" | "inactive" | "issue" | "low">("all");
  const [stPageSize, setStPageSize] = useState<number>(10);
  const [stPage, setStPage] = useState<number>(1);

  // Фильтры для газовозов
  const [trQuery, setTrQuery] = useState("");
  const [trStatus, setTrStatus] = useState<string>("all");

  // Партии и события для вкладок Поставки и Сверка
  const [batches, setBatches] = useState<BatchRecord[]>([]);
  const [events, setEvents] = useState<DiscrepancyEvent[]>([]);
  const [batchCode, setBatchCode] = useState("");
  const [batchGrade, setBatchGrade] = useState("ПБТ (пропан-бутан технический)");
  const [batchVol, setBatchVol] = useState("18000");
  const [batchNotes, setBatchNotes] = useState("");
  const [batchSaving, setBatchSaving] = useState(false);

  useEffect(() => {
    if (initialStationId) {
      setTab("stations");
      setStationId(initialStationId);
    }
  }, [initialStationId]);

  useEffect(() => {
    if (initialTruckId) {
      setTab("trucks");
      setTruckId(initialTruckId);
    }
  }, [initialTruckId]);

  useEffect(() => {
    if (!admin) return;
    let alive = true;
    api
      .batches()
      .then((rows) => {
        if (alive) setBatches(rows);
      })
      .catch(() => undefined);
    api
      .events(undefined, false)
      .then((rows) => {
        if (alive) setEvents(rows);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [admin, tab]);

  const enrichedCatalogStations = useMemo(
    () =>
      catalog.stations.map((row) => {
        const live = byCode.get(row.code) ?? null;
        const hasLive = !!live && live.tanks.length > 0;
        const cap = hasLive && live.capacity > 0 ? live.capacity : 0;
        const actual = hasLive ? live.remainder : null;
        const fill = hasLive && live.fill != null ? Math.round(live.fill) : null;
        const free = actual != null && cap > 0 ? Math.max(0, cap - actual) : null;
        const safeRefill =
          actual != null && cap > 0 ? Math.max(0, Math.round(cap * 0.85) - actual) : null;
        const online = !!live && live.tanks.some((t) => t.online && t.remainder_liters != null);
        const region = stationRegion(row);
        return { row, cap, actual, fill, free, safeRefill, online, live, region };
      }),
    [catalog.stations, byCode]
  );

  const filteredStations = useMemo(() => {
    const q = stQuery.trim().toLowerCase();
    return enrichedCatalogStations.filter((item) => {
      if (q) {
        const hit = [item.row.name, item.row.code, item.row.address, item.region].some((p) =>
          p?.toLowerCase().includes(q)
        );
        if (!hit) return false;
      }
      if (stRegion !== "all" && item.region !== stRegion) return false;
      if (stFilter === "active" && !item.row.is_active) return false;
      if (stFilter === "inactive" && item.row.is_active) return false;
      if (
        stFilter === "issue" &&
        !(item.live && item.live.tanks.length > 0 && !item.live.tanks.some((tank) => tank.online))
      )
        return false;
      if (stFilter === "low" && !isLowFill(item.fill)) return false;
      return true;
    });
  }, [enrichedCatalogStations, stQuery, stRegion, stFilter]);

  const totalStPages = Math.max(1, Math.ceil(filteredStations.length / stPageSize));
  const safeStPage = Math.min(stPage, totalStPages);
  const pagedStations = useMemo(() => {
    const start = (safeStPage - 1) * stPageSize;
    return filteredStations.slice(start, start + stPageSize);
  }, [filteredStations, safeStPage, stPageSize]);

  const filteredTrucks = useMemo(() => {
    const q = trQuery.trim().toLowerCase();
    return catalog.trucks.filter((row) => {
      if (q) {
        const hit = [row.plate_number, row.carrier_name].some((p) => p?.toLowerCase().includes(q));
        if (!hit) return false;
      }
      if (trStatus !== "all" && row.status !== trStatus) return false;
      return true;
    });
  }, [catalog.trucks, trQuery, trStatus]);

  const stationIndex = catalog.stations.findIndex((row) => row.id === stationId);
  const station = stationIndex >= 0 ? catalog.stations[stationIndex] : null;
  const stationEnriched = enrichedCatalogStations.find((item) => item.row.id === stationId) ?? null;
  const prevStation =
    stationIndex > 0
      ? catalog.stations[stationIndex - 1]
      : catalog.stations[catalog.stations.length - 1];
  const nextStation =
    stationIndex >= 0 && stationIndex < catalog.stations.length - 1
      ? catalog.stations[stationIndex + 1]
      : catalog.stations[0];

  const truck = catalog.trucks.find((row) => row.id === truckId) ?? null;
  const heading =
    tab === "stations"
      ? stationId === "new"
        ? "Новая АГЗС"
        : (station?.name ?? "Управление сетью АГЗС")
      : tab === "trucks"
        ? truckId === "new"
          ? "Новый газовоз"
          : (truck?.plate_number ?? "Парк газовозов")
        : tab === "supplies"
          ? "Планирование подвоза и партии LPG"
          : tab === "reconcile"
            ? "Сверка баланса и аудит датчиков"
            : "Безопасность и разграничение доступа";

  async function handleCreateBatch() {
    const vol = Number(batchVol.replace(",", "."));
    if (!batchCode.trim() || !Number.isFinite(vol) || vol <= 0) {
      toast.err("Укажите код партии и объём (> 0 л)");
      return;
    }
    setBatchSaving(true);
    try {
      const created = await api.createBatch({
        trail_code: batchCode.trim(),
        product_grade: batchGrade.trim() || undefined,
        volume_liters: vol,
        notes: batchNotes.trim() || undefined,
      });
      setBatches((cur) => [created, ...cur]);
      setBatchCode("");
      setBatchNotes("");
      toast.ok(`Партия ${created.trail_code} зарегистрирована`);
    } catch (err) {
      toast.err(messageOf(err));
    } finally {
      setBatchSaving(false);
    }
  }

  async function handleResolveEvent(id: string) {
    try {
      const resolved = await api.resolveEvent(id, "Проверено администратором");
      setEvents((cur) => cur.map((item) => (item.id === id ? resolved : item)));
      toast.ok("Событие отмечено как решённое");
    } catch (err) {
      toast.err(messageOf(err));
    }
  }

  if (!admin) {
    return (
      <div className="dash">
        <p className="empty">Раздел только для администратора.</p>
      </div>
    );
  }

  const deliveryNeeds = [...enrichedCatalogStations]
    .filter((item) => item.row.is_active)
    .sort((a, b) => (a.fill ?? 101) - (b.fill ?? 101));

  return (
    <div className="dash admin">
      <div className="admin-shell">
        <nav className="admin-nav" aria-label="Разделы администратора">
          <p className="kicker">Разделы админки</p>
          {ADMIN_SECTIONS.map((item) => {
            const count =
              item.id === "stations"
                ? catalog.stations.length
                : item.id === "trucks"
                  ? catalog.trucks.length
                  : item.id === "supplies"
                    ? batches.length
                    : item.id === "reconcile"
                      ? events.filter((e) => !e.is_resolved).length
                      : null;
            return (
              <button
                key={item.id}
                type="button"
                className={tab === item.id ? "active" : ""}
                aria-current={tab === item.id ? "page" : undefined}
                onClick={() => {
                  setTab(item.id);
                  scrollAdminTop();
                }}
              >
                <span className="admin-nav-label">
                  {item.label}
                  {count != null ? <em>{count}</em> : null}
                </span>
                <small>{item.note}</small>
              </button>
            );
          })}
        </nav>

        <div className="admin-main">
          <header className="admin-toolbar">
            <div>
              <p className="kicker">
                Администратор платформы ·{" "}
                {ADMIN_SECTIONS.find((s) => s.id === tab)?.label ?? "Управление"}
              </p>
              <h2>{heading}</h2>
            </div>
          </header>
          {catalog.error ? <p className="tank-error">{catalog.error}</p> : null}

          {tab === "stations" && (
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
                            onClick={() => setStationId(prevStation.id)}
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
                            onClick={() => setStationId(nextStation.id)}
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
          )}

          {tab === "trucks" && (
            <>
              {truckId == null && (
                <div className="st-filter-bar" style={{ marginBottom: 14 }}>
                  <input
                    type="search"
                    className="st-search-input"
                    value={trQuery}
                    placeholder="Поиск газовоза по госномеру или перевозчику…"
                    onChange={(e) => setTrQuery(e.target.value)}
                  />
                  <select
                    className="st-select"
                    value={trStatus}
                    aria-label="Статус газовоза"
                    onChange={(e) => setTrStatus(e.target.value)}
                  >
                    <option value="all">Все статусы ({catalog.trucks.length})</option>
                    {TRUCK_STATUS.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      setTruckId("new");
                      scrollAdminTop();
                    }}
                  >
                    + Новый газовоз
                  </button>
                </div>
              )}

              {truckId == null ? (
                <div className="dash-table-wrap admin-table">
                  <table className="dash-table">
                    <thead>
                      <tr>
                        <th>Госномер</th>
                        <th>Объём цистерны</th>
                        <th>Перевозчик</th>
                        <th>Статус</th>
                        <th>Координаты GPS</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredTrucks.map((row) => (
                        <tr
                          key={row.id}
                          className={`dash-row-link${truckId === row.id ? " active" : ""}`}
                          onClick={() => {
                            setTruckId(row.id);
                            scrollAdminTop();
                          }}
                        >
                          <td>
                            <strong>{row.plate_number}</strong>
                          </td>
                          <td>{liters(row.capacity_liters)}</td>
                          <td>{row.carrier_name || "—"}</td>
                          <td>
                            <span className="badge ok">{statusLabel(row.status)}</span>
                          </td>
                          <td>
                            {row.lat != null && row.lon != null
                              ? `${row.lat.toFixed(4)}, ${row.lon.toFixed(4)}`
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="admin-workspace">
                  <div className="admin-backbar">
                    <button
                      type="button"
                      className="btn secondary small"
                      onClick={() => setTruckId(null)}
                    >
                      ← К списку газовозов ({catalog.trucks.length})
                    </button>
                  </div>
                  <section className="dash-card admin-form-card">
                    {truckId === "new" ? (
                      <TruckForm
                        key="new-truck"
                        initial={null}
                        onCancel={() => setTruckId(null)}
                        onSaved={(saved) => {
                          setTruckId(saved.id);
                          toast.ok(`Газовоз ${saved.plate_number} добавлен`);
                        }}
                        onDeleted={() => setTruckId(null)}
                      />
                    ) : truck ? (
                      <TruckForm
                        key={truck.id}
                        initial={truck}
                        onCancel={() => setTruckId(null)}
                        onSaved={(saved) => toast.ok(`Газовоз ${saved.plate_number} обновлён`)}
                        onDeleted={() => {
                          setTruckId(null);
                          toast.ok(`Газовоз ${truck.plate_number} удалён`);
                        }}
                      />
                    ) : (
                      <p className="admin-empty">Этот газовоз больше не в списке.</p>
                    )}
                  </section>
                </div>
              )}
            </>
          )}

          {tab === "supplies" && (
            <div className="admin-workspace">
              <section className="dash-card">
                <h3>План потребности АГЗС в подвозе газа (по приоритету заполненности)</h3>
                <p className="dash-muted">
                  Автоматический расчёт свободного объёма резервуаров для планирования рейсов
                  газовозов. Рекомендуемый объём слива рассчитан до безопасного уровня 85% ёмкости.
                </p>
                <div className="dash-table-wrap" style={{ marginTop: 10 }}>
                  <table className="dash-table">
                    <thead>
                      <tr>
                        <th>АГЗС / Район</th>
                        <th>Заполненность</th>
                        <th>Текущий остаток</th>
                        <th>Полная ёмкость</th>
                        <th>Рекомендуемый слив (до 85%)</th>
                        <th>Макс. свободно (до 100%)</th>
                        <th>Действие</th>
                      </tr>
                    </thead>
                    <tbody>
                      {deliveryNeeds.map(({ row, region, fill, actual, cap, free, safeRefill }) => (
                        <tr key={row.id}>
                          <td>
                            <strong>{row.name}</strong>
                            <div className="dash-muted">
                              {row.code} · {region}
                            </div>
                          </td>
                          <td>
                            <strong className={isLowFill(fill) ? "text-danger" : ""}>
                              {fill == null ? "—" : `${fill}%`}
                            </strong>
                          </td>
                          <td>{actual == null ? "замера нет" : liters(actual)}</td>
                          <td>{liters(cap)}</td>
                          <td>
                            <strong>{safeRefill == null ? "—" : liters(safeRefill)}</strong>
                          </td>
                          <td>{free == null ? "—" : liters(free)}</td>
                          <td>
                            <button
                              type="button"
                              className="btn secondary small"
                              onClick={() => {
                                setTab("stations");
                                setStationId(row.id);
                                scrollAdminTop();
                              }}
                            >
                              Оформить приход →
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="dash-card">
                <h3>Регистрация партии сжиженного газа (Цифровой след)</h3>
                <form
                  className="admin-form"
                  style={{ marginTop: 10 }}
                  onSubmit={(e) => {
                    e.preventDefault();
                    void handleCreateBatch();
                  }}
                >
                  <label>
                    Код партии (Trail Code)
                    <input
                      placeholder="LPG-2026-0042"
                      value={batchCode}
                      onChange={(e) => setBatchCode(e.target.value)}
                      required
                    />
                  </label>
                  <label>
                    Марка газа
                    <input
                      value={batchGrade}
                      onChange={(e) => setBatchGrade(e.target.value)}
                    />
                  </label>
                  <label>
                    Объём партии, л
                    <input
                      inputMode="decimal"
                      value={batchVol}
                      onChange={(e) => setBatchVol(e.target.value)}
                      required
                    />
                  </label>
                  <label className="span-3">
                    Примечание (завод, маршрут, газовоз)
                    <input
                      placeholder="КазГПЗ (Жанаозен) → Актау"
                      value={batchNotes}
                      onChange={(e) => setBatchNotes(e.target.value)}
                    />
                  </label>
                  <div className="admin-actions span-3">
                    <button type="submit" className="btn small" disabled={batchSaving}>
                      {batchSaving ? "Сохраняем…" : "Зарегистрировать партию"}
                    </button>
                  </div>
                </form>

                {batches.length > 0 ? (
                  <div className="dash-table-wrap" style={{ marginTop: 14 }}>
                    <table className="dash-table">
                      <thead>
                        <tr>
                          <th>Код партии</th>
                          <th>Марка</th>
                          <th>Объём</th>
                          <th>Статус</th>
                          <th>Создана</th>
                          <th>Примечание</th>
                        </tr>
                      </thead>
                      <tbody>
                        {batches.map((b) => (
                          <tr key={b.id}>
                            <td>
                              <strong>{b.trail_code}</strong>
                            </td>
                            <td>{b.product_grade || "ПБТ"}</td>
                            <td>{liters(b.volume_liters)}</td>
                            <td>
                              <span className="badge ok">{b.status}</span>
                            </td>
                            <td>{dateTime(b.created_at)}</td>
                            <td className="dash-muted">{b.notes || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="dash-muted" style={{ marginTop: 12 }}>
                    Зарегистрированных партий пока нет.
                  </p>
                )}
              </section>
            </div>
          )}

          {tab === "reconcile" && (
            <div className="admin-workspace">
              <div className="dash-kpis">
                <div className="dash-kpi">
                  <span>АГЗС на связи</span>
                  <strong>
                    {enrichedCatalogStations.filter((x) => x.online).length} /{" "}
                    {enrichedCatalogStations.length}
                  </strong>
                  <em>актуальные показания датчиков</em>
                </div>
                <div className="dash-kpi">
                  <span>АГЗС без связи</span>
                  <strong
                    className={
                      enrichedCatalogStations.some(
                        (x) => x.live && x.live.tanks.length > 0 && !x.online
                      )
                        ? "text-danger"
                        : ""
                    }
                  >
                    {
                      enrichedCatalogStations.filter(
                        (x) => x.live && x.live.tanks.length > 0 && !x.online
                      ).length
                    }
                  </strong>
                  <em>замер устарел (&gt; 30 сек)</em>
                </div>
                <div className="dash-kpi">
                  <span>Без резервуара / датчика</span>
                  <strong>
                    {
                      enrichedCatalogStations.filter(
                        (x) => !x.live || x.live.tanks.length === 0
                      ).length
                    }
                  </strong>
                  <em>требуют привязки устройства</em>
                </div>
                <div className="dash-kpi">
                  <span>Открытых расхождений</span>
                  <strong className={events.some((e) => !e.is_resolved) ? "text-danger" : ""}>
                    {events.filter((e) => !e.is_resolved).length}
                  </strong>
                  <em>всего событий в журнале: {events.length}</em>
                </div>
              </div>

              <section className="dash-card">
                <h3>Журнал событий сверки и инцидентов баланса</h3>
                {events.length === 0 ? (
                  <p className="dash-muted">
                    Расхождений между книжным остатком и показаниями датчиков не зафиксировано.
                  </p>
                ) : (
                  <div className="dash-table-wrap">
                    <table className="dash-table">
                      <thead>
                        <tr>
                          <th>Время</th>
                          <th>АГЗС</th>
                          <th>Тип / Важность</th>
                          <th>Описание</th>
                          <th>Статус</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {events.map((ev) => {
                          const evStation = catalog.stations.find((s) => s.id === ev.station_id);
                          return (
                            <tr key={ev.id}>
                              <td>{dateTime(ev.detected_at)}</td>
                              <td>
                                <strong>{evStation ? evStation.name : ev.station_id || "—"}</strong>
                              </td>
                              <td>
                                <span
                                  className={`badge ${ev.severity === "critical" ? "danger" : "warn"}`}
                                >
                                  {ev.event_type} · {ev.severity}
                                </span>
                              </td>
                              <td>
                                <strong>{ev.title}</strong>
                                {ev.description ? (
                                  <div className="dash-muted">{ev.description}</div>
                                ) : null}
                              </td>
                              <td>
                                <span className={`badge ${ev.is_resolved ? "ok" : "warn"}`}>
                                  {ev.is_resolved ? "закрыто" : "открыто"}
                                </span>
                              </td>
                              <td>
                                {!ev.is_resolved ? (
                                  <button
                                    type="button"
                                    className="btn secondary small"
                                    onClick={() => void handleResolveEvent(ev.id)}
                                  >
                                    Принять
                                  </button>
                                ) : null}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </div>
          )}

          {tab === "security" && <AdminSecurityTab username={session?.username} />}
        </div>
      </div>
    </div>
  );
}
