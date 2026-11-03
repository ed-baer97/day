import { useEffect, useMemo, useState } from "react";
import { type CatalogStation, type CatalogTruck, type StationDraft, type TruckDraft } from "../api/client";
import { useAuth } from "../auth";
import { messageOf, useCatalog } from "../catalog";
import { liters, REGIONS, stationRegion } from "../format";
import { SensorStatus, usePublicLevels } from "../liveLevels";
import LevelChangesToday from "./LevelChangesToday";
import TankDeviceRows from "./TankDeviceRows";
import { useToast } from "./Toast";

const TRUCK_STATUS = [
  { value: "idle", label: "ожидание" },
  { value: "loading", label: "погрузка" },
  { value: "in_transit", label: "в пути" },
  { value: "arrived", label: "прибыл" },
  { value: "unloading", label: "слив" },
] as const;

function statusLabel(value: string) {
  return TRUCK_STATUS.find((row) => row.value === value)?.label ?? value;
}

type AdminTab = "stations" | "trucks" | "security";

export default function AdminPage({
  initialStationId,
  onOpenStationDashboard,
  onOpenStationMap,
}: {
  initialStationId?: string | null;
  onOpenStationDashboard?: (id: string) => void;
  onOpenStationMap?: (id: string) => void;
}) {
  const catalog = useCatalog();
  const { byCode } = usePublicLevels();
  const { session } = useAuth();
  const toast = useToast();

  const [tab, setTab] = useState<AdminTab>("stations");
  const [stationId, setStationId] = useState<string | "new" | null>(
    initialStationId ?? catalog.stations[0]?.id ?? null
  );
  const [truckId, setTruckId] = useState<string | "new" | null>(catalog.trucks[0]?.id ?? null);

  // Фильтры и пагинация для большого количества АГЗС в админке
  const [stQuery, setStQuery] = useState("");
  const [stRegion, setStRegion] = useState<string>("all");
  const [stFilter, setStFilter] = useState<"all" | "active" | "inactive" | "issue" | "low">("all");
  const [stPageSize, setStPageSize] = useState<number>(10);
  const [stPage, setStPage] = useState<number>(1);

  // Фильтры для газовозов
  const [trQuery, setTrQuery] = useState("");
  const [trStatus, setTrStatus] = useState<string>("all");

  useEffect(() => {
    if (initialStationId) {
      setTab("stations");
      setStationId(initialStationId);
    }
  }, [initialStationId]);

  const enrichedCatalogStations = useMemo(
    () =>
      catalog.stations.map((row) => {
        const live = byCode.get(row.code) ?? null;
        const hasLive = !!live && live.tanks.length > 0;
        const cap = hasLive && live.capacity > 0 ? live.capacity : 0;
        const actual = hasLive ? live.remainder : null;
        const fill = hasLive && live.fill != null ? Math.round(live.fill) : null;
        const region = stationRegion(row);
        return { row, cap, actual, fill, live, region };
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
      if (stFilter === "issue" && !(item.live && item.live.tanks.length > 0 && !item.live.tanks.some((tank) => tank.online))) return false;
      if (stFilter === "low" && (item.fill == null || item.fill >= 25)) return false;
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
        const hit = [row.plate_number, row.carrier_name].some((p) =>
          p?.toLowerCase().includes(q)
        );
        if (!hit) return false;
      }
      if (trStatus !== "all" && row.status !== trStatus) return false;
      return true;
    });
  }, [catalog.trucks, trQuery, trStatus]);

  const station = catalog.stations.find((row) => row.id === stationId) ?? null;
  const truck = catalog.trucks.find((row) => row.id === truckId) ?? null;

  return (
    <div className="dash admin">
      <header className="admin-toolbar">
        <div>
          <p className="kicker">Защищённый административный контур</p>
          <h2>Панель управления сетью АГЗС Мангыстау</h2>
        </div>
        <div className="admin-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "stations"}
            className={tab === "stations" ? "active" : ""}
            onClick={() => setTab("stations")}
          >
            АГЗС и резервуары ({catalog.stations.length})
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "trucks"}
            className={tab === "trucks" ? "active" : ""}
            onClick={() => setTab("trucks")}
          >
            Газовозы ({catalog.trucks.length})
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "security"}
            className={tab === "security" ? "active" : ""}
            onClick={() => setTab("security")}
          >
            Безопасность и доступ
          </button>
        </div>
      </header>
      {catalog.error ? <p className="tank-error">{catalog.error}</p> : null}

      {tab === "stations" && (
        <>
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
              <option value="inactive">Выключены</option>
              <option value="issue">Нет связи с датчиком</option>
              <option value="low">Мало газа (&lt; 25%)</option>
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
            <button type="button" className="btn" onClick={() => setStationId("new")}>
              + Новая АГЗС
            </button>
          </div>

          <div className="admin-split">
            <div>
              <div className="dash-table-wrap admin-table">
                <table className="dash-table">
                  <thead>
                    <tr>
                      <th>Код / Район</th>
                      <th>Название и адрес</th>
                      <th>Остаток датчика</th>
                      <th>Датчик</th>
                      <th>Статус</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagedStations.map(({ row, actual, cap, fill, live, region }) => (
                      <tr
                        key={row.id}
                        className={`dash-row-link${stationId === row.id ? " active" : ""}`}
                        onClick={() => setStationId(row.id)}
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
                          <strong className={fill != null && fill < 25 ? "text-danger" : ""}>
                            {fill == null ? "—" : `${fill}%`}
                          </strong>
                          <div className="dash-muted">
                            {actual == null ? "замера ещё нет" : `${liters(actual)} / ${liters(cap)}`}
                          </div>
                        </td>
                        <td>
                          {live && live.tanks.length > 0 ? <SensorStatus level={live} /> : <span className="badge warn">не подключён</span>}
                        </td>
                        <td>
                          <span className={`badge ${row.is_active ? "ok" : "warn"}`}>
                            {row.is_active ? "работает" : "скрыта"}
                          </span>
                        </td>
                      </tr>
                    ))}
                    {pagedStations.length === 0 && (
                      <tr>
                        <td colSpan={5} className="dash-muted">
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

            <aside className="admin-editor dash-card">
              {stationId === "new" ? (
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
              ) : station ? (
                <>
                  <div className="admin-editor-head-actions">
                    {onOpenStationDashboard && (
                      <button
                        type="button"
                        className="btn secondary small"
                        onClick={() => onOpenStationDashboard(station.id)}
                      >
                        Открыть детальную сводку
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
                  <h3 className="admin-sub">Резервуары, датчики Shelly и публикация остатка</h3>
                  <TankDeviceRows stationId={station.id} />
                  <LevelChangesToday stationId={station.id} />
                </>
              ) : (
                <p className="admin-empty">
                  Выберите заправку в таблице слева или нажмите «+ Новая АГЗС».
                </p>
              )}
            </aside>
          </div>
        </>
      )}

      {tab === "trucks" && (
        <>
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
            <button type="button" className="btn" onClick={() => setTruckId("new")}>
              + Новый газовоз
            </button>
          </div>

          <div className="admin-split">
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
                      onClick={() => setTruckId(row.id)}
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
            <aside className="admin-editor dash-card">
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
                <p className="admin-empty">Выберите газовоз в таблице или создайте новый.</p>
              )}
            </aside>
          </div>
        </>
      )}

      {tab === "security" && (
        <div className="security-grid">
          <section className="dash-card">
            <h3>Разграничение публичных и конфиденциальных данных</h3>
            <p className="dash-muted">
              Соблюдение политики конфиденциальности: на публичном лэндинге (
              <code>GET /api/v1/public/levels</code>) публикуется только наличие газа на АГЗС.
            </p>
            <table className="dash-table" style={{ marginTop: 10 }}>
              <thead>
                <tr>
                  <th>Категория данных</th>
                  <th>Публичный лэндинг</th>
                  <th>Админ-панель</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Название, код, адрес АГЗС и % / литры в резервуаре</td>
                  <td>
                    <span className="badge ok">Открыто (публично)</span>
                  </td>
                  <td>
                    <span className="badge ok">Доступно</span>
                  </td>
                </tr>
                <tr>
                  <td>Книжный остаток, расхождения (недостача / излишек)</td>
                  <td>
                    <span className="badge danger">Скрыто (конфиденциально)</span>
                  </td>
                  <td>
                    <span className="badge ok">Только с токеном админа</span>
                  </td>
                </tr>
                <tr>
                  <td>Сверка ТРК ↔ ККМ ↔ ОФД ↔ КГД (продажи без чека)</td>
                  <td>
                    <span className="badge danger">Скрыто (конфиденциально)</span>
                  </td>
                  <td>
                    <span className="badge ok">Только с токеном админа</span>
                  </td>
                </tr>
                <tr>
                  <td>Госномера газовозов, GPS-трекинг, маршруты и партии</td>
                  <td>
                    <span className="badge danger">Скрыто (конфиденциально)</span>
                  </td>
                  <td>
                    <span className="badge ok">Только с токеном админа</span>
                  </td>
                </tr>
                <tr>
                  <td>IP-адреса контроллеров Shelly и X-Device-Token резервуаров</td>
                  <td>
                    <span className="badge danger">Скрыто (конфиденциально)</span>
                  </td>
                  <td>
                    <span className="badge ok">Только с токеном админа</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </section>

          <section className="dash-card">
            <h3>Активная защита и устранённые уязвимости</h3>
            <ul className="trail-list" style={{ marginTop: 10 }}>
              <li>
                <span className="title">Защита от утечки телеметрии на лэндинге</span>
                <span className="desc">
                  Из фоновой карты лэндинга исключены газовозы, заводы, маршруты поставок и статусы
                  расхождений; удалён глобальный объект <code>window.__lpgDebug</code>.
                </span>
              </li>
              <li>
                <span className="title">Защита API приёма телеметрии и IDOR-контроль</span>
                <span className="desc">
                  Эндпоинты <code>/api/v1/ingest/*</code> требуют валидный <code>X-Device-Token</code>{" "}
                  или <code>Bearer</code>-токен администратора; токен резервуара привязан строго к
                  своему <code>tank_id</code> и <code>station_id</code>.
                </span>
              </li>
              <li>
                <span className="title">Защита от SSRF при опросе датчиков Shelly</span>
                <span className="desc">
                  Валидатор хостов блокирует обращение к <code>localhost</code>,{" "}
                  <code>127.0.0.0/8</code>, <code>169.254.0.0/16</code> (cloud metadata),{" "}
                  <code>0.0.0.0</code> и внутренним контейнерам инфраструктуры.
                </span>
              </li>
              <li>
                <span className="title">Rate-Limiting входа и отзыв токенов при выходе</span>
                <span className="desc">
                  Защита от брутфорса (не более 5 неудачных попыток за 60 секунд → HTTP 429) и
                  серверный отзыв токена (<code>POST /api/v1/auth/logout</code> с проверкой{" "}
                  <code>jti</code>).
                </span>
              </li>
              <li>
                <span className="title">Текущая сессия администратора</span>
                <span className="desc">
                  Пользователь: <strong>{session?.username}</strong> · Хранение:{" "}
                  <code>sessionStorage</code> (автоматическая очистка при закрытии вкладки + отзыв{" "}
                  <code>jti</code> при выходе)
                </span>
              </li>
            </ul>
          </section>
        </div>
      )}
    </div>
  );
}

function StationForm({
  initial,
  onCancel,
  onSaved,
  onDeleted,
}: {
  initial: CatalogStation | null;
  onCancel: () => void;
  onSaved: (saved: CatalogStation) => void;
  onDeleted: () => void;
}) {
  const { saveStation, deleteStation } = useCatalog();
  const [code, setCode] = useState(initial?.code ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [address, setAddress] = useState(initial?.address ?? "");
  const [lat, setLat] = useState(initial ? String(initial.lat) : "43.65");
  const [lon, setLon] = useState(initial ? String(initial.lon) : "51.20");
  const [active, setActive] = useState(initial?.is_active ?? true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit() {
    const latitude = Number(lat.replace(",", "."));
    const longitude = Number(lon.replace(",", "."));
    if (!code.trim() || !name.trim() || !Number.isFinite(latitude) || !Number.isFinite(longitude)) {
      setError("Укажите код, название и координаты");
      return;
    }
    const body: StationDraft = {
      code: code.trim(),
      name: name.trim(),
      address: address.trim() || null,
      lat: latitude,
      lon: longitude,
      is_active: active,
    };
    setSaving(true);
    setError(null);
    try {
      onSaved(await saveStation(initial?.id ?? null, body));
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!initial) return;
    setSaving(true);
    setError(null);
    try {
      await deleteStation(initial.id);
      onDeleted();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      className="admin-form"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <h3 className="span-3">{initial ? initial.name : "Новая заправка"}</h3>
      <label>
        Код
        <input value={code} onChange={(event) => setCode(event.target.value)} />
      </label>
      <label className="span-2">
        Название
        <input value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <label className="span-3">
        Адрес (с указанием города/района для авто-группировки)
        <input value={address} onChange={(event) => setAddress(event.target.value)} />
      </label>
      <label>
        Широта
        <input inputMode="decimal" value={lat} onChange={(event) => setLat(event.target.value)} />
      </label>
      <label>
        Долгота
        <input inputMode="decimal" value={lon} onChange={(event) => setLon(event.target.value)} />
      </label>
      <label className="admin-check">
        <input
          type="checkbox"
          checked={active}
          onChange={(event) => setActive(event.target.checked)}
        />
        Работает (публиковать на лэндинге)
      </label>
      {error ? <p className="tank-error span-3">{error}</p> : null}
      <div className="admin-actions span-3">
        <button type="submit" className="btn small" disabled={saving}>
          Сохранить
        </button>
        {initial && (
          <button
            type="button"
            className="btn secondary small text-danger"
            disabled={saving}
            onClick={() => void handleDelete()}
          >
            Удалить АГЗС
          </button>
        )}
        <button type="button" className="btn secondary small" onClick={onCancel}>
          Закрыть
        </button>
      </div>
    </form>
  );
}

function TruckForm({
  initial,
  onCancel,
  onSaved,
  onDeleted,
}: {
  initial: CatalogTruck | null;
  onCancel: () => void;
  onSaved: (saved: CatalogTruck) => void;
  onDeleted: () => void;
}) {
  const { saveTruck, deleteTruck } = useCatalog();
  const [plate, setPlate] = useState(initial?.plate_number ?? "");
  const [capacity, setCapacity] = useState(initial ? String(initial.capacity_liters) : "");
  const [carrier, setCarrier] = useState(initial?.carrier_name ?? "");
  const [status, setStatus] = useState(initial?.status ?? "idle");
  const [lat, setLat] = useState(initial?.lat != null ? String(initial.lat) : "");
  const [lon, setLon] = useState(initial?.lon != null ? String(initial.lon) : "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit() {
    const volume = Number(capacity.replace(",", "."));
    const latitude = lat.trim() ? Number(lat.replace(",", ".")) : null;
    const longitude = lon.trim() ? Number(lon.replace(",", ".")) : null;
    if (!plate.trim() || !Number.isFinite(volume) || volume <= 0) {
      setError("Укажите номер и объём цистерны");
      return;
    }
    const coordsMissing = (latitude == null) !== (longitude == null);
    const coordsBad =
      (latitude != null && !Number.isFinite(latitude)) ||
      (longitude != null && !Number.isFinite(longitude));
    if (coordsMissing || coordsBad) {
      setError("Широту и долготу укажите вместе");
      return;
    }
    const body: TruckDraft = {
      plate_number: plate.trim(),
      capacity_liters: volume,
      carrier_name: carrier.trim() || null,
      status,
      lat: latitude,
      lon: longitude,
    };
    setSaving(true);
    setError(null);
    try {
      onSaved(await saveTruck(initial?.id ?? null, body));
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!initial) return;
    setSaving(true);
    setError(null);
    try {
      await deleteTruck(initial.id);
      onDeleted();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      className="admin-form"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <h3 className="span-3">{initial ? initial.plate_number : "Новый газовоз"}</h3>
      <label>
        Номер
        <input value={plate} onChange={(event) => setPlate(event.target.value)} />
      </label>
      <label>
        Объём цистерны, л
        <input
          inputMode="decimal"
          value={capacity}
          onChange={(event) => setCapacity(event.target.value)}
        />
      </label>
      <label>
        Статус
        <select value={status} onChange={(event) => setStatus(event.target.value)}>
          {TRUCK_STATUS.map((row) => (
            <option key={row.value} value={row.value}>
              {row.label}
            </option>
          ))}
        </select>
      </label>
      <label className="span-3">
        Перевозчик
        <input value={carrier} onChange={(event) => setCarrier(event.target.value)} />
      </label>
      <label>
        Широта
        <input inputMode="decimal" value={lat} onChange={(event) => setLat(event.target.value)} />
      </label>
      <label>
        Долгота
        <input inputMode="decimal" value={lon} onChange={(event) => setLon(event.target.value)} />
      </label>
      <p className="dash-muted span-3">
        Для нового газовоза координаты ставят его на карту. Уже едущий рейс координаты не сдвигает.
      </p>
      {error ? <p className="tank-error span-3">{error}</p> : null}
      <div className="admin-actions span-3">
        <button type="submit" className="btn small" disabled={saving}>
          Сохранить
        </button>
        {initial && (
          <button
            type="button"
            className="btn secondary small text-danger"
            disabled={saving}
            onClick={() => void handleDelete()}
          >
            Удалить газовоз
          </button>
        )}
        <button type="button" className="btn secondary small" onClick={onCancel}>
          Закрыть
        </button>
      </div>
    </form>
  );
}
