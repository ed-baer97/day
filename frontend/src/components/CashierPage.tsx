import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type DispenseReading,
  type ShiftDetail,
  type ShiftRecord,
  type TankDevice,
  type TankIngestState,
} from "../api/client";
import { useAuth } from "../auth";
import { messageOf, useCatalog } from "../catalog";
import { stationColumnCount } from "../columnReport";
import { dateTime, liters, signedLiters, stationRegion, tenge } from "../format";
import {
  isLowFill,
  SensorStatusBadge,
  tankSensorBadge,
  tankSensorLabel,
  usePublicLevels,
} from "../liveLevels";
import { freeVolumeLiters, POLL_MS } from "../policy";
import type { StationDetail } from "../types";
import ConfirmModal from "./ConfirmModal";
import ShiftReportView from "./ShiftReportView";
import { useToast } from "./Toast";

type PumpTab = "shift" | "today";

function formatDuration(startIso: string, endIso?: string | null): string {
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  const diffMin = Math.max(0, Math.round((end - start) / 60000));
  const hours = Math.floor(diffMin / 60);
  const mins = diffMin % 60;
  return hours === 0 ? `${mins} мин` : `${hours} ч ${mins} мин`;
}

function formatVol(value: number): string {
  return `${value.toLocaleString("ru-RU", { minimumFractionDigits: 0, maximumFractionDigits: 2 })} л`;
}

export default function CashierPage() {
  const { session } = useAuth();
  const catalog = useCatalog();
  const { byCode } = usePublicLevels();
  const toast = useToast();

  const stationId =
    session?.station_id ?? session?.station_ids?.[0] ?? catalog.stations[0]?.id ?? null;
  const catalogStation = catalog.stations.find((s) => s.id === stationId) ?? null;

  const [stationDetail, setStationDetail] = useState<StationDetail | null>(null);
  const [devices, setDevices] = useState<TankDevice[]>([]);
  const [tankStates, setTankStates] = useState<Record<string, TankIngestState>>({});
  const [todayDispenses, setTodayDispenses] = useState<DispenseReading[]>([]);
  const [currentShift, setCurrentShift] = useState<ShiftDetail | null>(null);
  const [shifts, setShifts] = useState<ShiftRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [pumpTab, setPumpTab] = useState<PumpTab>("shift");
  const [shiftNote, setShiftNote] = useState("");
  const [busyShift, setBusyShift] = useState(false);
  const [closeModalOpen, setCloseModalOpen] = useState(false);

  const [selectedReport, setSelectedReport] = useState<ShiftDetail | null>(null);
  const [reportLoadingId, setReportLoadingId] = useState<string | null>(null);
  const reportSectionRef = useRef<HTMLDivElement>(null);

  const loadWorkspace = useCallback(async () => {
    if (!stationId) return;
    const todayStart = new Date();
    todayStart.setHours(0, 0, 0, 0);
    try {
      const [detail, devs, curShift, shiftHistory, dispRows] = await Promise.all([
        api.station(stationId),
        api.tankDevices(stationId).catch(() => [] as TankDevice[]),
        api.currentShift(stationId),
        api.stationShifts(stationId, 30),
        api.stationDispenses(stationId, todayStart.toISOString(), 500).catch(() => [] as DispenseReading[]),
      ]);
      setStationDetail(detail);
      setDevices(devs);
      setCurrentShift(curShift);
      setShifts(shiftHistory);
      setTodayDispenses(dispRows);

      const states = await Promise.all(
        devs.map(async (dev) => {
          try {
            return [dev.id, await api.stationTankState(stationId, dev.id)] as const;
          } catch {
            return null;
          }
        })
      );
      const stateMap: Record<string, TankIngestState> = {};
      for (const item of states) {
        if (item) stateMap[item[0]] = item[1];
      }
      setTankStates(stateMap);
      setError(null);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setLoading(false);
    }
  }, [stationId]);

  useEffect(() => {
    if (!stationId) return;
    void loadWorkspace();
    const timer = window.setInterval(() => void loadWorkspace(), Math.min(POLL_MS, 8000));
    return () => window.clearInterval(timer);
  }, [stationId, loadWorkspace]);

  const station = catalogStation ?? stationDetail;
  const live = station ? (byCode.get(station.code) ?? null) : null;

  const tankCards = useMemo(() => {
    const baseTanks =
      stationDetail?.tanks && stationDetail.tanks.length > 0
        ? stationDetail.tanks
        : devices.map((dev) => ({
            id: dev.id,
            code: dev.code,
            capacity_liters: dev.capacity_liters,
            actual_remainder_liters: tankStates[dev.id]?.actual_remainder_liters ?? null,
            last_measured_at: tankStates[dev.id]?.last_measured_at ?? null,
          }));
    return baseTanks.map((tank) => {
      const pubTank = live?.tanks.find((t) => t.code === tank.code);
      const st = tankStates[tank.id];
      const remainder =
        pubTank?.remainder_liters ??
        st?.actual_remainder_liters ??
        tank.actual_remainder_liters ??
        null;
      const capacity = tank.capacity_liters || pubTank?.capacity_liters || 0;
      const fill =
        pubTank?.fill_percent ??
        (remainder != null && capacity > 0 ? Math.round((remainder / capacity) * 100) : null);
      const free = freeVolumeLiters(capacity, remainder);
      const openingSnap = currentShift?.opening_tanks.find(
        (item) => item.tank_id === tank.id || item.code === tank.code
      );
      const shiftDelta =
        openingSnap?.remainder_liters != null && remainder != null
          ? remainder - openingSnap.remainder_liters
          : null;
      return {
        id: tank.id,
        code: tank.code,
        capacity,
        remainder,
        fill,
        free,
        measuredAt: pubTank?.measured_at ?? st?.last_measured_at ?? tank.last_measured_at ?? null,
        pubTank,
        shiftDelta,
      };
    });
  }, [stationDetail, devices, tankStates, live, currentShift]);

  const tankTotals = useMemo(() => {
    const capacity = tankCards.reduce((sum, item) => sum + item.capacity, 0);
    const known = tankCards.filter((item) => item.remainder != null);
    const remainder = known.length
      ? known.reduce((sum, item) => sum + (item.remainder ?? 0), 0)
      : null;
    const fill = remainder != null && capacity > 0 ? Math.round((remainder / capacity) * 100) : null;
    const free = freeVolumeLiters(capacity, remainder);
    const shiftDelta =
      currentShift?.opening_tank_liters != null && remainder != null
        ? remainder - currentShift.opening_tank_liters
        : null;
    return { capacity, remainder, fill, free, shiftDelta };
  }, [tankCards, currentShift]);

  const activeMode: PumpTab = currentShift ? pumpTab : "today";
  const activeDispenses = useMemo(() => {
    if (activeMode === "shift" && currentShift) return currentShift.dispenses;
    return todayDispenses;
  }, [activeMode, currentShift, todayDispenses]);

  const columnCount = useMemo(() => {
    const configured = stationColumnCount({
      columns_count: catalogStation?.columns_count,
    });
    const maxDispenseAddr = activeDispenses.reduce(
      (max, row) => Math.max(max, row.pump_address ?? 1),
      0
    );
    return Math.max(configured, maxDispenseAddr);
  }, [catalogStation?.columns_count, activeDispenses]);

  const columnRows = useMemo(() => {
    const buckets = Array.from({ length: columnCount }, (_, index) => ({
      pumpAddress: index + 1,
      code: `ТРК-${index + 1}`,
      name: `Колонка ${index + 1}`,
      volume: 0,
      ops: 0,
      amount: 0,
      hasPrice: false,
      lastLiters: null as number | null,
      lastAt: null as string | null,
    }));
    const ordered = [...activeDispenses].sort(
      (a, b) =>
        new Date(a.finished_at ?? a.started_at).getTime() -
        new Date(b.finished_at ?? b.started_at).getTime()
    );
    for (const item of ordered) {
      if (item.volume_liters <= 0) continue;
      const idx =
        item.pump_address != null && item.pump_address >= 1 && item.pump_address <= columnCount
          ? item.pump_address - 1
          : 0;
      const col = buckets[idx];
      col.volume = Math.round((col.volume + item.volume_liters) * 1000) / 1000;
      col.ops += 1;
      col.lastLiters = item.volume_liters;
      col.lastAt = item.finished_at ?? item.started_at;
      if (item.price_kzt_per_liter != null && item.price_kzt_per_liter > 0) {
        col.amount += item.volume_liters * item.price_kzt_per_liter;
        col.hasPrice = true;
      }
    }
    const totalVolume = Math.round(buckets.reduce((s, c) => s + c.volume, 0) * 1000) / 1000;
    const totalOps = buckets.reduce((s, c) => s + c.ops, 0);
    const anyPrice = buckets.some((c) => c.hasPrice);
    const totalAmount = anyPrice
      ? Math.round(buckets.reduce((s, c) => s + (c.hasPrice ? c.amount : 0), 0) * 100) / 100
      : null;
    return { buckets, totalVolume, totalOps, totalAmount };
  }, [columnCount, activeDispenses]);

  async function handleOpenShift() {
    if (!stationId) return;
    setBusyShift(true);
    try {
      const opened = await api.openShift(stationId, shiftNote.trim() || null);
      setCurrentShift(opened);
      setSelectedReport(null);
      setShiftNote("");
      setPumpTab("shift");
      await loadWorkspace();
      toast.ok("Смена открыта");
    } catch (err) {
      toast.err(messageOf(err));
    } finally {
      setBusyShift(false);
    }
  }

  async function handleCloseShift() {
    if (!stationId || !currentShift) return;
    setBusyShift(true);
    try {
      const closed = await api.closeShift(stationId, currentShift.id, shiftNote.trim() || null);
      setCurrentShift(null);
      setCloseModalOpen(false);
      setShiftNote("");
      setSelectedReport(closed);
      await loadWorkspace();
      toast.ok("Смена закрыта · сформирован итоговый отчёт");
      window.setTimeout(() => {
        reportSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 80);
    } catch (err) {
      toast.err(messageOf(err));
    } finally {
      setBusyShift(false);
    }
  }

  async function handleOpenShiftReport(shiftId: string) {
    if (!stationId) return;
    setReportLoadingId(shiftId);
    try {
      const detail = await api.shiftReport(stationId, shiftId);
      setSelectedReport(detail);
      window.setTimeout(() => {
        reportSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 80);
    } catch (err) {
      toast.err(messageOf(err));
    } finally {
      setReportLoadingId(null);
    }
  }

  if (!stationId) {
    return (
      <main className="page dash-page">
        <div className="dash">
          <p className="empty">К вашей учётной записи не привязана заправка.</p>
        </div>
      </main>
    );
  }

  return (
    <main className="page dash-page">
      <div className="dash cashier-workspace">
        <header className="st-head no-print">
          <div>
            <p className="kicker">
              Рабочее место кассира · {station?.code ?? ""}
              {station ? ` · ${stationRegion(station)}` : ""}
            </p>
            <h2>{station?.name ?? "Заправка"}</h2>
            <span className="dash-muted">
              {station?.address || "Контроль цистерны, фактического расхода по колонкам и смены"}
            </span>
          </div>
          <div className="st-row-badges">
            {live && live.tanks.length > 0 ? (
              <SensorStatusBadge level={live} />
            ) : (
              <span className="badge warn">ожидание датчика</span>
            )}
            <span className={`badge ${currentShift ? "ok" : "warn"}`}>
              {currentShift ? "Смена открыта" : "Смена закрыта"}
            </span>
          </div>
        </header>

        {error ? <p className="tank-error">{error}</p> : null}

        <section className="dash-card shift-banner no-print">
          <div className="shift-banner-main">
            <div>
              <span className={`badge ${currentShift ? "ok" : "warn"}`}>
                {currentShift ? "Активная смена" : "Смена не открыта"}
              </span>
              <h3 style={{ margin: "6px 0 4px" }}>
                {currentShift
                  ? `Смена открыта с ${dateTime(currentShift.opened_at)}`
                  : "Откройте смену для фиксации отчёта"}
              </h3>
              <p className="dash-muted" style={{ margin: 0 }}>
                {currentShift ? (
                  <>
                    Кассир: <strong>{currentShift.opened_by}</strong> · длительность{" "}
                    <strong>{formatDuration(currentShift.opened_at)}</strong> · на старте в
                    цистерне:{" "}
                    <strong>{liters(currentShift.opening_tank_liters)}</strong>
                  </>
                ) : (
                  "При открытии смены система фиксирует начальный объём газа в цистерне и начинает учёт отпусков по колонкам."
                )}
              </p>
            </div>
            <div className="shift-banner-controls">
              <input
                type="text"
                className="shift-note-input"
                value={shiftNote}
                onChange={(e) => setShiftNote(e.target.value)}
                placeholder={
                  currentShift ? "Комментарий к закрытию (необязательно)…" : "Комментарий к открытию (необязательно)…"
                }
                maxLength={500}
              />
              {currentShift ? (
                <>
                  <button
                    type="button"
                    className="btn secondary"
                    onClick={() => void handleOpenShiftReport(currentShift.id)}
                  >
                    Предварительный отчёт
                  </button>
                  <button
                    type="button"
                    className="btn danger"
                    disabled={busyShift}
                    onClick={() => setCloseModalOpen(true)}
                  >
                    Закрыть смену
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className="btn"
                  disabled={busyShift || loading}
                  onClick={() => void handleOpenShift()}
                >
                  {busyShift ? "Открываем…" : "Открыть смену"}
                </button>
              )}
            </div>
          </div>

          {currentShift ? (
            <div className="dash-kpis" style={{ marginTop: 14 }}>
              <div className="dash-kpi">
                <span>В цистерне на начало</span>
                <strong>{liters(currentShift.opening_tank_liters)}</strong>
                <em>зафиксировано при открытии</em>
              </div>
              <div className="dash-kpi">
                <span>В цистерне сейчас</span>
                <strong className={isLowFill(tankTotals.fill) ? "text-danger" : ""}>
                  {liters(tankTotals.remainder)}
                </strong>
                <em>
                  {tankTotals.shiftDelta != null
                    ? `изменение за смену: ${signedLiters(tankTotals.shiftDelta)}`
                    : "по датчику уровня"}
                </em>
              </div>
              <div className="dash-kpi">
                <span>Отпуск по колонкам (ТРК)</span>
                <strong>{formatVol(currentShift.dispensed_liters)}</strong>
                <em>операций за смену: {currentShift.dispense_count}</em>
              </div>
              <div className="dash-kpi">
                <span>Приход / Выручка</span>
                <strong>
                  {currentShift.total_amount_kzt != null
                    ? tenge(currentShift.total_amount_kzt)
                    : liters(currentShift.receipts_liters)}
                </strong>
                <em>
                  {currentShift.total_amount_kzt != null
                    ? `приход газа: ${liters(currentShift.receipts_liters)}`
                    : "принято в цистерну за смену"}
                </em>
              </div>
            </div>
          ) : null}
        </section>

        <section className="dash-card no-print">
          <div className="card-head-inline" style={{ marginBottom: 12 }}>
            <div>
              <h3 style={{ margin: 0 }}>Объём в цистерне</h3>
              <p className="dash-muted" style={{ margin: "4px 0 0" }}>
                Текущие показания датчиков резервуаров АГЗС.
              </p>
            </div>
            <strong className={`st-grid-pct${isLowFill(tankTotals.fill) ? " text-danger" : ""}`}>
              {tankTotals.fill == null ? "—" : `${tankTotals.fill}%`}
            </strong>
          </div>

          {tankCards.length === 0 ? (
            <p className="dash-muted">К этой заправке ещё не подключены резервуары.</p>
          ) : (
            <div className="st-grid">
              <div className="gauge">
                <div className="gauge-bar">
                  <i
                    style={{
                      height: `${Math.max(0, Math.min(100, tankTotals.fill ?? 0))}%`,
                      background: isLowFill(tankTotals.fill)
                        ? "var(--coral)"
                        : "linear-gradient(0deg, var(--sea-2, var(--sea)), var(--sea))",
                    }}
                  />
                </div>
                <div className="gauge-meta">
                  <strong>{tankTotals.fill == null ? "—" : `${tankTotals.fill}%`}</strong>
                  <span>
                    {tankTotals.remainder == null
                      ? "замера ещё нет"
                      : `${liters(tankTotals.remainder)} из ${liters(tankTotals.capacity)}`}
                  </span>
                  {tankTotals.free != null ? (
                    <span className="dash-muted">Свободно под слив: {liters(tankTotals.free)}</span>
                  ) : null}
                  {tankTotals.shiftDelta != null ? (
                    <span className="dash-muted">
                      С начала смены: <strong>{signedLiters(tankTotals.shiftDelta)}</strong>
                    </span>
                  ) : null}
                </div>
              </div>

              <div className="st-card-grid">
                {tankCards.map((tank) => (
                  <article className="column-card" key={tank.id}>
                    <div className="card-head-inline" style={{ marginBottom: 6 }}>
                      <strong>Резервуар {tank.code}</strong>
                      {tank.pubTank ? (
                        <span className={`badge ${tankSensorBadge(tank.pubTank)}`}>
                          {tankSensorLabel(tank.pubTank)}
                        </span>
                      ) : (
                        <span className="badge warn">
                          {tank.remainder == null ? "замера нет" : "датчик"}
                        </span>
                      )}
                    </div>
                    <p className="stage-vol" style={{ marginBottom: 8 }}>
                      Остаток:{" "}
                      <strong className={isLowFill(tank.fill) ? "text-danger" : ""}>
                        {tank.remainder == null ? "—" : liters(tank.remainder)}
                      </strong>{" "}
                      ({tank.fill == null ? "—" : `${Math.round(tank.fill)}%`})
                    </p>
                    <dl className="kv">
                      <dt>Ёмкость</dt>
                      <dd>{liters(tank.capacity)}</dd>
                      <dt>Свободно</dt>
                      <dd>{tank.free == null ? "—" : liters(tank.free)}</dd>
                      <dt>Замер</dt>
                      <dd>{tank.measuredAt ? dateTime(tank.measuredAt) : "ожидание"}</dd>
                      {tank.shiftDelta != null ? (
                        <>
                          <dt>С начала смены</dt>
                          <dd>{signedLiters(tank.shiftDelta)}</dd>
                        </>
                      ) : null}
                    </dl>
                  </article>
                ))}
              </div>
            </div>
          )}
        </section>

        <section className="dash-card no-print">
          <div className="card-head-inline" style={{ marginBottom: 12 }}>
            <div>
              <h3 style={{ margin: 0 }}>Фактический расход по колонкам</h3>
              <p className="dash-muted" style={{ margin: "4px 0 0" }}>
                Реальный отпуск газа через ТРК за выбранный период.
              </p>
            </div>
            {currentShift ? (
              <div className="mini-tabs">
                <button
                  type="button"
                  className={activeMode === "shift" ? "active" : ""}
                  onClick={() => setPumpTab("shift")}
                >
                  За текущую смену
                </button>
                <button
                  type="button"
                  className={activeMode === "today" ? "active" : ""}
                  onClick={() => setPumpTab("today")}
                >
                  За сегодня
                </button>
              </div>
            ) : (
              <span className="badge">За сегодня</span>
            )}
          </div>

          {columnRows.buckets.length === 0 ? (
            <p className="dash-muted">Колонки не настроены и наливов ещё не поступало.</p>
          ) : (
            <>
              <div className="col-grid" style={{ marginBottom: 16 }}>
                {columnRows.buckets.map((col) => (
                  <article className="column-card" key={col.pumpAddress}>
                    <div className="card-head-inline" style={{ marginBottom: 6 }}>
                      <h4 style={{ margin: 0 }}>
                        {col.name} ({col.code})
                      </h4>
                    </div>
                    <p className="stage-vol" style={{ marginBottom: 8 }}>
                      Фактический расход: <strong>{formatVol(col.volume)}</strong>
                    </p>
                    <dl className="kv">
                      <dt>Операций</dt>
                      <dd>{col.ops}</dd>
                      {col.hasPrice ? (
                        <>
                          <dt>Сумма</dt>
                          <dd>{tenge(col.amount)}</dd>
                        </>
                      ) : null}
                      <dt>Последний налив</dt>
                      <dd>
                        {col.lastLiters != null
                          ? `${formatVol(col.lastLiters)}${col.lastAt ? ` · ${dateTime(col.lastAt)}` : ""}`
                          : "не было"}
                      </dd>
                    </dl>
                  </article>
                ))}
              </div>

              <div className="dash-table-wrap" style={{ marginBottom: 14 }}>
                <table className="dash-table">
                  <thead>
                    <tr>
                      <th>Колонка</th>
                      <th>Операций</th>
                      <th>Расход (л)</th>
                      <th>Сумма</th>
                      <th>Последний налив</th>
                    </tr>
                  </thead>
                  <tbody>
                    {columnRows.buckets.map((col) => (
                      <tr key={col.pumpAddress}>
                        <td>
                          <strong>
                            {col.name} ({col.code})
                          </strong>
                        </td>
                        <td>{col.ops}</td>
                        <td>
                          <strong>{formatVol(col.volume)}</strong>
                        </td>
                        <td>{col.hasPrice ? tenge(col.amount) : "—"}</td>
                        <td className="dash-muted">
                          {col.lastLiters != null
                            ? `${formatVol(col.lastLiters)}${col.lastAt ? ` · ${dateTime(col.lastAt)}` : ""}`
                            : "нет данных"}
                        </td>
                      </tr>
                    ))}
                    <tr className="dash-total">
                      <td>Итого</td>
                      <td>{columnRows.totalOps}</td>
                      <td>{formatVol(columnRows.totalVolume)}</td>
                      <td>{columnRows.totalAmount != null ? tenge(columnRows.totalAmount) : "—"}</td>
                      <td />
                    </tr>
                  </tbody>
                </table>
              </div>

              {activeDispenses.length > 0 ? (
                <details>
                  <summary style={{ cursor: "pointer", fontWeight: 600 }}>
                    Последние операции налива ({activeDispenses.length})
                  </summary>
                  <div className="dash-table-wrap" style={{ marginTop: 10 }}>
                    <table className="dash-table">
                      <thead>
                        <tr>
                          <th>Время</th>
                          <th>Колонка</th>
                          <th>Режим</th>
                          <th>Объём</th>
                          <th>Цена / Сумма</th>
                        </tr>
                      </thead>
                      <tbody>
                        {activeDispenses.slice(0, 50).map((item) => {
                          const amount =
                            item.price_kzt_per_liter != null
                              ? item.volume_liters * item.price_kzt_per_liter
                              : null;
                          return (
                            <tr key={item.id}>
                              <td>{dateTime(item.finished_at ?? item.started_at)}</td>
                              <td>
                                <strong>
                                  {item.pump_address ? `ТРК-${item.pump_address}` : "ТРК"}
                                </strong>
                              </td>
                              <td className="dash-muted">
                                {item.mode === "full_tank"
                                  ? "До полного"
                                  : item.mode === "dose"
                                    ? "Доза"
                                    : item.mode || "—"}
                              </td>
                              <td>
                                <strong>{formatVol(item.volume_liters)}</strong>
                              </td>
                              <td>
                                {item.price_kzt_per_liter != null
                                  ? `${item.price_kzt_per_liter} ₸/л · ${amount != null ? tenge(amount) : ""}`
                                  : "—"}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </details>
              ) : null}
            </>
          )}
        </section>

        <div ref={reportSectionRef}>
          {selectedReport ? (
            <ShiftReportView
              report={selectedReport}
              stationName={station?.name}
              stationCode={station?.code}
              onClose={() => setSelectedReport(null)}
            />
          ) : null}
        </div>

        <section className="dash-card no-print">
          <div className="card-head-inline" style={{ marginBottom: 10 }}>
            <div>
              <h3 style={{ margin: 0 }}>История смен и отчёты ({shifts.length})</h3>
              <p className="dash-muted" style={{ margin: "4px 0 0" }}>
                После закрытия смены формируется итоговый отчёт, доступный для просмотра, печати и
                выгрузки в CSV.
              </p>
            </div>
          </div>

          {shifts.length === 0 ? (
            <p className="dash-muted" style={{ marginBottom: 0 }}>
              Смен по этой заправке ещё не было. Нажмите «Открыть смену», чтобы начать.
            </p>
          ) : (
            <div className="dash-table-wrap">
              <table className="dash-table">
                <thead>
                  <tr>
                    <th>Статус</th>
                    <th>Открыта / Закрыта</th>
                    <th>Кассир</th>
                    <th>Цистерна (нач. → кон.)</th>
                    <th>Отпуск ТРК</th>
                    <th>Разница</th>
                    <th>Отчёт</th>
                  </tr>
                </thead>
                <tbody>
                  {shifts.map((sh) => (
                    <tr key={sh.id}>
                      <td>
                        <span className={`badge ${sh.status === "open" ? "warn" : "ok"}`}>
                          {sh.status === "open" ? "открыта" : "закрыта"}
                        </span>
                      </td>
                      <td>
                        <div>{dateTime(sh.opened_at)}</div>
                        <div className="dash-muted">
                          {sh.closed_at ? dateTime(sh.closed_at) : "в работе"}
                        </div>
                      </td>
                      <td>
                        <strong>{sh.opened_by}</strong>
                        {sh.closed_by && sh.closed_by !== sh.opened_by ? (
                          <div className="dash-muted">закр.: {sh.closed_by}</div>
                        ) : null}
                      </td>
                      <td>
                        {liters(sh.opening_tank_liters)} → {liters(sh.closing_tank_liters)}
                      </td>
                      <td>
                        <strong>{formatVol(sh.dispensed_liters)}</strong>
                        <div className="dash-muted">
                          оп.: {sh.dispense_count}
                          {sh.total_amount_kzt != null ? ` · ${tenge(sh.total_amount_kzt)}` : ""}
                        </div>
                      </td>
                      <td>
                        {sh.discrepancy_liters != null ? (
                          <strong>{signedLiters(sh.discrepancy_liters)}</strong>
                        ) : (
                          <span className="dash-muted">—</span>
                        )}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn secondary small"
                          disabled={reportLoadingId === sh.id}
                          onClick={() => void handleOpenShiftReport(sh.id)}
                        >
                          {reportLoadingId === sh.id ? "Загрузка…" : "Открыть отчёт"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <ConfirmModal
          open={closeModalOpen}
          title="Закрыть кассовую смену?"
          message={`Смена от ${currentShift ? dateTime(currentShift.opened_at) : ""} будет закрыта.`}
          details="Система зафиксирует остаток в цистерне, фактический расход по каждой колонке и сформирует итоговый отчёт о смене."
          confirmLabel="Закрыть смену"
          danger
          busy={busyShift}
          onConfirm={() => void handleCloseShift()}
          onCancel={() => setCloseModalOpen(false)}
        />
      </div>
    </main>
  );
}
