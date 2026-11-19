import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { api, type BatchRecord, type CatalogStation, type CatalogTruck, type TankDevice } from "../api/client";
import { messageOf } from "../catalog";
import { useToast } from "../components/Toast";
import {
  batchStatusLabel,
  dateTime,
  liters,
  phaseLabel,
  stationRegion,
  trailNodeLabel,
} from "../format";
import type { NetworkStats } from "../layout/Topbar";
import { isLowFill, type LiveLevel, LOW_FILL_PERCENT, SensorStatusBadge } from "../liveLevels";
import { freeVolumeLiters, SAFE_FILL_PERCENT, safeRefillLiters } from "../policy";
import type { BatchTrail } from "../types";
import { truckStatusBadge } from "./admin/types";

const BATCH_STATUS_OPTIONS = ["formed", "in_transit", "delivered", "closed"] as const;

export default function SupplyPage({
  stations,
  trucks,
  batches,
  byCode,
  networkStats,
  onBatchesChange,
  onReloadBatches,
  onOpenTrucksOnMap,
  onCreateNewTruck,
  onOpenStationPage,
  onOpenAdminStation,
  onOpenTruckOnMap,
  onOpenAdminTruck,
}: {
  stations: CatalogStation[];
  trucks: CatalogTruck[];
  batches: BatchRecord[];
  byCode: Map<string, LiveLevel>;
  networkStats: NetworkStats;
  onBatchesChange?: Dispatch<SetStateAction<BatchRecord[]>>;
  onReloadBatches?: () => Promise<void>;
  onOpenTrucksOnMap: () => void;
  onCreateNewTruck: () => void;
  onOpenStationPage: (id: string) => void;
  onOpenAdminStation: (id: string) => void;
  onOpenTruckOnMap: (id: string) => void;
  onOpenAdminTruck: (id: string) => void;
}) {
  const toast = useToast();

  // Форма регистрации партии
  const [batchCode, setBatchCode] = useState("");
  const [batchGrade, setBatchGrade] = useState("ПБТ (пропан-бутан технический)");
  const [batchVol, setBatchVol] = useState("18000");
  const [batchStationId, setBatchStationId] = useState("");
  const [batchTruckId, setBatchTruckId] = useState("");
  const [batchNotes, setBatchNotes] = useState("");
  const [batchSaving, setBatchSaving] = useState(false);

  // Просмотр цифрового следа партии
  const [trailQuery, setTrailQuery] = useState("");
  const [activeTrail, setActiveTrail] = useState<BatchTrail | null>(null);
  const [trailLoading, setTrailLoading] = useState(false);
  const [trailError, setTrailError] = useState<string | null>(null);
  const [updatingBatchId, setUpdatingBatchId] = useState<string | null>(null);

  // Модалка быстрой приёмки слива на АГЗС
  const [receiptStation, setReceiptStation] = useState<CatalogStation | null>(null);
  const [receiptDevices, setReceiptDevices] = useState<TankDevice[]>([]);
  const [receiptTankId, setReceiptTankId] = useState("");
  const [receiptLiters, setReceiptLiters] = useState("");
  const [receiptBatchId, setReceiptBatchId] = useState("");
  const [receiptLoadingDevices, setReceiptLoadingDevices] = useState(false);
  const [receiptSaving, setReceiptSaving] = useState(false);
  const [receiptError, setReceiptError] = useState<string | null>(null);

  useEffect(() => {
    if (!receiptStation) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !receiptSaving) {
        setReceiptStation(null);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [receiptStation, receiptSaving]);

  async function openReceiptModal(station: CatalogStation, suggestedLiters: number | null) {
    setReceiptStation(station);
    setReceiptDevices([]);
    setReceiptTankId("");
    setReceiptLiters(suggestedLiters != null && suggestedLiters > 0 ? String(Math.round(suggestedLiters)) : "");
    setReceiptBatchId("");
    setReceiptError(null);
    setReceiptLoadingDevices(true);
    try {
      const devs = await api.tankDevices(station.id);
      setReceiptDevices(devs);
      setReceiptTankId(devs[0]?.id ?? "");
    } catch (err) {
      setReceiptError(messageOf(err));
    } finally {
      setReceiptLoadingDevices(false);
    }
  }

  async function handleAcceptReceipt() {
    if (!receiptStation) return;
    const vol = Number(receiptLiters.replace(",", "."));
    if (!receiptTankId) {
      setReceiptError("Выберите резервуар АГЗС");
      return;
    }
    if (!Number.isFinite(vol) || vol <= 0) {
      setReceiptError("Укажите принятый объём слива (> 0 л)");
      return;
    }
    setReceiptSaving(true);
    setReceiptError(null);
    try {
      await api.ingestReceipt({
        station_id: receiptStation.id,
        tank_id: receiptTankId,
        volume_liters: vol,
        recorded_at: new Date().toISOString(),
      });
      if (receiptBatchId) {
        const tank = receiptDevices.find((d) => d.id === receiptTankId);
        const updatedTrail = await api.addBatchEvent(receiptBatchId, {
          node_type: "tank",
          title: `Слив на ${receiptStation.name}${tank ? ` (${tank.code})` : ""}`,
          description: `Принято в резервуар ${Math.round(vol)} л`,
          ref_entity_type: "station",
          ref_entity_id: receiptStation.id,
          volume_liters: vol,
          status: "delivered",
        });
        onBatchesChange?.((prev) =>
          prev.map((row) => (row.id === receiptBatchId ? { ...row, status: "delivered" } : row))
        );
        setActiveTrail(updatedTrail);
      }
      toast.ok(`Приход ${Math.round(vol)} л принят на ${receiptStation.name}`);
      setReceiptStation(null);
    } catch (err) {
      setReceiptError(messageOf(err));
    } finally {
      setReceiptSaving(false);
    }
  }

  async function handleCreateBatch() {
    const vol = Number(batchVol.replace(",", "."));
    if (!batchCode.trim() || !Number.isFinite(vol) || vol <= 0) {
      toast.err("Укажите код партии и объём (> 0 л)");
      return;
    }
    const targetStation = stations.find((s) => s.id === batchStationId);
    const targetTruck = trucks.find((t) => t.id === batchTruckId);
    const autoParts = [
      targetTruck ? `Газовоз ${targetTruck.plate_number}` : "",
      targetStation ? `→ ${targetStation.name} (${targetStation.code})` : "",
      batchNotes.trim(),
    ].filter(Boolean);

    setBatchSaving(true);
    try {
      const created = await api.createBatch({
        trail_code: batchCode.trim(),
        product_grade: batchGrade.trim() || undefined,
        volume_liters: vol,
        notes: autoParts.join(" · ") || undefined,
      });
      if (targetTruck) {
        await api.addBatchEvent(created.id, {
          node_type: "truck",
          title: `Назначен газовоз ${targetTruck.plate_number}`,
          description: targetTruck.carrier_name || undefined,
          ref_entity_type: "truck",
          ref_entity_id: targetTruck.id,
          volume_liters: vol,
        });
      }
      if (targetStation) {
        await api.addBatchEvent(created.id, {
          node_type: "station",
          title: `Пункт назначения: ${targetStation.name}`,
          description: targetStation.address || targetStation.code,
          ref_entity_type: "station",
          ref_entity_id: targetStation.id,
        });
      }
      onBatchesChange?.((cur) => [created, ...cur]);
      setBatchCode("");
      setBatchNotes("");
      setBatchStationId("");
      setBatchTruckId("");
      toast.ok(`Партия ${created.trail_code} зарегистрирована`);
      void openTrail(created.trail_code);
    } catch (err) {
      toast.err(messageOf(err));
    } finally {
      setBatchSaving(false);
    }
  }

  async function handleStatusChange(batchId: string, status: string) {
    setUpdatingBatchId(batchId);
    try {
      const updated = await api.updateBatchStatus(batchId, { status });
      onBatchesChange?.((cur) => cur.map((b) => (b.id === batchId ? updated : b)));
      if (activeTrail?.batch.id === batchId) {
        await openTrail(updated.trail_code);
      }
      toast.ok(`Статус партии ${updated.trail_code}: ${batchStatusLabel(status)}`);
    } catch (err) {
      toast.err(messageOf(err));
    } finally {
      setUpdatingBatchId(null);
    }
  }

  async function openTrail(code: string) {
    const cleaned = code.trim();
    if (!cleaned) return;
    setTrailQuery(cleaned);
    setTrailLoading(true);
    setTrailError(null);
    try {
      const trail = await api.trailByCode(cleaned);
      setActiveTrail(trail);
    } catch (err) {
      setActiveTrail(null);
      setTrailError(messageOf(err, "Партия не найдена"));
    } finally {
      setTrailLoading(false);
    }
  }

  const completedNodes = new Set(activeTrail?.events.map((ev) => ev.node_type) ?? []);

  return (
    <div className="dash">
      <header className="dash-hero">
        <div>
          <p className="kicker">Единый логистический контур · Мангистауская область</p>
          <h2>Поставки, подвоз, газовозы и партии LPG</h2>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button type="button" className="btn secondary small" onClick={onOpenTrucksOnMap}>
            Газовозы на карте ({trucks.length})
          </button>
          <button type="button" className="btn small" onClick={onCreateNewTruck}>
            + Добавить газовоз
          </button>
        </div>
      </header>

      <div className="dash-kpis">
        <div className="dash-kpi">
          <span>Парк газовозов</span>
          <strong>{trucks.length}</strong>
          <em>
            общая вместимость: {liters(trucks.reduce((s, t) => s + (t.capacity_liters || 0), 0))}
          </em>
        </div>
        <div className="dash-kpi">
          <span>АГЗС требуют подвоза (&lt; {LOW_FILL_PERCENT}%)</span>
          <strong className={networkStats.low > 0 ? "text-danger" : ""}>{networkStats.low}</strong>
          <em>приоритетные станции</em>
        </div>
        <div className="dash-kpi">
          <span>Свободная ёмкость сети</span>
          <strong>{liters(networkStats.freeSum)}</strong>
          <em>доступно под слив по всем АГЗС</em>
        </div>
        <div className="dash-kpi">
          <span>Партий в реестре</span>
          <strong>{batches.length}</strong>
          <em>цифровой след партий LPG</em>
        </div>
      </div>

      <section className="dash-section">
        <div className="card-head-inline">
          <h3>Приоритет подвоза газа по АГЗС (по остатку в резервуарах)</h3>
        </div>
        <div className="dash-table-wrap">
          <table className="dash-table">
            <thead>
              <tr>
                <th>АГЗС и район</th>
                <th>Уровень %</th>
                <th>Фактический остаток</th>
                <th>Полная ёмкость</th>
                <th>Рекомендуемый слив (до {SAFE_FILL_PERCENT}%)</th>
                <th>Макс. свободно (до 100%)</th>
                <th>Датчик</th>
                <th>Приёмка слива</th>
              </tr>
            </thead>
            <tbody>
              {[...stations]
                .map((st) => {
                  const live = byCode.get(st.code) ?? null;
                  const hasLive = !!live && live.tanks.length > 0;
                  const fill = hasLive && live?.fill != null ? Math.round(live.fill) : null;
                  const rem = hasLive ? (live?.remainder ?? null) : null;
                  const cap = hasLive ? (live?.capacity ?? 0) : 0;
                  const free = freeVolumeLiters(cap, rem);
                  const safe = safeRefillLiters(cap, rem);
                  return { st, live, hasLive, fill, rem, cap, free, safe };
                })
                .sort((a, b) => (a.fill ?? 101) - (b.fill ?? 101))
                .map(({ st, live, hasLive, fill, rem, cap, free, safe }) => (
                  <tr key={st.id} className="dash-row-link" onClick={() => onOpenStationPage(st.id)}>
                    <td>
                      <strong>{st.name}</strong>
                      <div className="dash-muted">
                        {st.code} · {stationRegion(st)}
                      </div>
                    </td>
                    <td>
                      <strong className={isLowFill(fill) ? "text-danger" : ""}>
                        {fill == null ? "—" : `${fill}%`}
                      </strong>
                    </td>
                    <td>{rem == null ? "замера нет" : liters(rem)}</td>
                    <td>{liters(cap)}</td>
                    <td>
                      <strong>{safe == null ? "—" : liters(safe)}</strong>
                    </td>
                    <td>{free == null ? "—" : liters(free)}</td>
                    <td>
                      {hasLive && live ? (
                        <SensorStatusBadge level={live} />
                      ) : (
                        <span className="badge warn">не подключён</span>
                      )}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <div style={{ display: "flex", gap: 6 }}>
                        <button
                          type="button"
                          className="btn small"
                          onClick={() => void openReceiptModal(st, safe)}
                        >
                          Принять слив
                        </button>
                        <button
                          type="button"
                          className="btn secondary small"
                          title="Настройки АГЗС в админке"
                          onClick={() => onOpenAdminStation(st.id)}
                        >
                          ⚙
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="dash-section">
        <h3>Автопарк газовозов ({trucks.length})</h3>
        {trucks.length === 0 ? (
          <p className="empty">Газовозы ещё не добавлены в каталог.</p>
        ) : (
          <div className="dash-table-wrap">
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Госномер</th>
                  <th>Перевозчик</th>
                  <th>Объём цистерны</th>
                  <th>Статус рейса</th>
                  <th>Координаты GPS</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>
                {trucks.map((tr) => {
                  const tone = truckStatusBadge(tr.status);
                  return (
                    <tr key={tr.id}>
                      <td>
                        <strong>{tr.plate_number}</strong>
                      </td>
                      <td>{tr.carrier_name || "—"}</td>
                      <td>{liters(tr.capacity_liters)}</td>
                      <td>
                        <span className={`badge${tone ? ` ${tone}` : ""}`}>
                          {phaseLabel(tr.status)}
                        </span>
                      </td>
                      <td>
                        {tr.lat != null && tr.lon != null
                          ? `${tr.lat.toFixed(4)}, ${tr.lon.toFixed(4)}`
                          : "нет координат"}
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }}>
                          {tr.lat != null && tr.lon != null ? (
                            <button
                              type="button"
                              className="btn secondary small"
                              onClick={() => onOpenTruckOnMap(tr.id)}
                            >
                              На карте
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() => onOpenAdminTruck(tr.id)}
                          >
                            Редактировать
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="dash-section">
        <div className="card-head-inline">
          <h3>Регистрация партии и цифровой след LPG</h3>
          {onReloadBatches ? (
            <button
              type="button"
              className="btn secondary small"
              onClick={() => void onReloadBatches()}
            >
              Обновить реестр
            </button>
          ) : null}
        </div>

        <div className="dash-card" style={{ marginBottom: 16 }}>
          <form
            className="admin-form"
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
              <input value={batchGrade} onChange={(e) => setBatchGrade(e.target.value)} />
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
            <label>
              Газовоз (необязательно)
              <select value={batchTruckId} onChange={(e) => setBatchTruckId(e.target.value)}>
                <option value="">— не выбран —</option>
                {trucks.map((tr) => (
                  <option key={tr.id} value={tr.id}>
                    {tr.plate_number} ({liters(tr.capacity_liters)})
                  </option>
                ))}
              </select>
            </label>
            <label>
              АГЗС назначения (необязательно)
              <select value={batchStationId} onChange={(e) => setBatchStationId(e.target.value)}>
                <option value="">— не выбрана —</option>
                {stations.map((st) => (
                  <option key={st.id} value={st.id}>
                    {st.name} ({st.code})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Примечание (завод, маршрут)
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
        </div>

        <div className="dash-card" style={{ marginBottom: 16 }}>
          <div className="card-head-inline">
            <h4>Реестр партий ({batches.length})</h4>
            <form
              style={{ display: "flex", gap: 6, flexWrap: "wrap" }}
              onSubmit={(e) => {
                e.preventDefault();
                void openTrail(trailQuery);
              }}
            >
              <input
                type="search"
                className="st-select"
                placeholder="Найти след по коду партии…"
                value={trailQuery}
                onChange={(e) => setTrailQuery(e.target.value)}
              />
              <button type="submit" className="btn secondary small" disabled={trailLoading}>
                {trailLoading ? "Поиск…" : "Показать след"}
              </button>
            </form>
          </div>

          {batches.length === 0 ? (
            <p className="dash-muted" style={{ margin: "6px 0 0" }}>
              Зарегистрированных партий пока нет.
            </p>
          ) : (
            <div className="dash-table-wrap">
              <table className="dash-table">
                <thead>
                  <tr>
                    <th>Код партии</th>
                    <th>Марка</th>
                    <th>Объём</th>
                    <th>Статус</th>
                    <th>Создана</th>
                    <th>Примечание</th>
                    <th>Действия</th>
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
                        <select
                          className="st-select"
                          aria-label={`Статус партии ${b.trail_code}`}
                          value={b.status}
                          disabled={updatingBatchId === b.id}
                          onChange={(e) => void handleStatusChange(b.id, e.target.value)}
                        >
                          {BATCH_STATUS_OPTIONS.map((st) => (
                            <option key={st} value={st}>
                              {batchStatusLabel(st)}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>{dateTime(b.created_at)}</td>
                      <td className="dash-muted">{b.notes || "—"}</td>
                      <td>
                        <button
                          type="button"
                          className="btn secondary small"
                          onClick={() => void openTrail(b.trail_code)}
                        >
                          Цифровой след
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {trailError ? <p className="tank-error">{trailError}</p> : null}

        {activeTrail ? (
          <div className="dash-card">
            <div className="card-head-inline">
              <div>
                <p className="kicker">Цифровой след партии</p>
                <h4 style={{ margin: 0 }}>
                  {activeTrail.batch.trail_code} · {liters(activeTrail.batch.volume_liters)}
                </h4>
              </div>
              <button
                type="button"
                className="btn secondary small"
                onClick={() => setActiveTrail(null)}
              >
                Закрыть след
              </button>
            </div>

            <div className="trail-chain" style={{ marginTop: 12 }}>
              {activeTrail.chain.map((node) => (
                <span
                  key={node}
                  className={`badge ${completedNodes.has(node) ? "ok" : ""}`}
                >
                  {trailNodeLabel(node)}
                </span>
              ))}
            </div>

            {activeTrail.events.length === 0 ? (
              <p className="dash-muted" style={{ marginTop: 10 }}>
                Событий по цепочке пока не зафиксировано.
              </p>
            ) : (
              <ul className="trail-list" style={{ marginTop: 12 }}>
                {activeTrail.events.map((ev) => (
                  <li key={ev.id}>
                    <span className="title">
                      {trailNodeLabel(ev.node_type)}: {ev.title}
                      {ev.volume_liters != null ? ` (${liters(ev.volume_liters)})` : ""}
                    </span>
                    <span className="desc">
                      {dateTime(ev.occurred_at)}
                      {ev.description ? ` · ${ev.description}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </section>

      {receiptStation ? (
        <div
          className="login-layer"
          role="dialog"
          aria-modal="true"
          onClick={() => {
            if (!receiptSaving) setReceiptStation(null);
          }}
        >
          <form
            className="login-card"
            onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => {
              e.preventDefault();
              void handleAcceptReceipt();
            }}
          >
            <h2>Принять слив на АГЗС</h2>
            <p>
              <strong>{receiptStation.name}</strong> ({receiptStation.code})
            </p>
            {receiptLoadingDevices ? (
              <p className="dash-muted">Загрузка резервуаров…</p>
            ) : receiptDevices.length === 0 ? (
              <p className="tank-error">
                У этой АГЗС нет резервуаров. Добавьте резервуар в карточке станции в админке.
              </p>
            ) : (
              <>
                <label>
                  Резервуар
                  <select
                    value={receiptTankId}
                    onChange={(e) => setReceiptTankId(e.target.value)}
                    required
                  >
                    {receiptDevices.map((dev) => (
                      <option key={dev.id} value={dev.id}>
                        {dev.code} ({liters(dev.capacity_liters)})
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Принятый объём, л
                  <input
                    inputMode="decimal"
                    placeholder="4500"
                    value={receiptLiters}
                    onChange={(e) => setReceiptLiters(e.target.value)}
                    required
                  />
                </label>
                {batches.length > 0 ? (
                  <label>
                    Привязать к партии LPG (необязательно)
                    <select
                      value={receiptBatchId}
                      onChange={(e) => setReceiptBatchId(e.target.value)}
                    >
                      <option value="">— без привязки к партии —</option>
                      {batches.map((b) => (
                        <option key={b.id} value={b.id}>
                          {b.trail_code} ({liters(b.volume_liters)})
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
              </>
            )}
            {receiptError ? <p className="tank-error">{receiptError}</p> : null}
            <div className="login-actions">
              <button
                type="button"
                className="btn secondary small"
                onClick={() => {
                  const id = receiptStation.id;
                  setReceiptStation(null);
                  onOpenAdminStation(id);
                }}
              >
                В админку ⚙
              </button>
              <button
                type="button"
                className="btn secondary"
                disabled={receiptSaving}
                onClick={() => setReceiptStation(null)}
              >
                Отмена
              </button>
              <button
                type="submit"
                className="btn"
                disabled={receiptSaving || receiptDevices.length === 0}
              >
                {receiptSaving ? "Проводим…" : "Записать приход"}
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}
