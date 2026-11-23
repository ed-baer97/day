import { useEffect, useMemo, useState } from "react";
import {
  api,
  type ColumnsMode,
  type DispenseReading,
  type ShiftDetail,
  type ShiftRecord,
  type TankDevice,
  type TankIngestState,
} from "../api/client";
import { isAdmin, isOwner } from "../access";
import { useAuth } from "../auth";
import { messageOf, useCatalog } from "../catalog";
import {
  dateTime,
  eventTypeLabel,
  liters,
  severityLabel,
  signedLiters,
  stationRegion,
  tenge,
} from "../format";
import {
  isLowFill,
  SensorStatusBadge,
  tankSensorBadge,
  tankSensorLabel,
  usePublicLevels,
  useSensorDay,
  useViewPeriod,
} from "../liveLevels";
import { freeVolumeLiters, SAFE_FILL_PERCENT, safeRefillLiters } from "../policy";
import {
  buildLiveTankSamples,
  columnDispenseReport,
  isColumnReportStation,
  stationColumnCount,
} from "../columnReport";
import { chartOf } from "../sensorDay";
import type { DiscrepancyEvent } from "../types";
import { BarChart, LineChart } from "./Charts";
import ColumnReportCard from "./ColumnReportCard";
import LevelChangesToday from "./LevelChangesToday";
import PeriodSwitch from "./PeriodSwitch";
import ShiftReportView from "./ShiftReportView";
import StationCashiersCard from "./StationCashiersCard";
import { useToast } from "./Toast";

type DetailTab = "overview" | "pumps" | "tanks" | "history" | "staff";

export default function StationDetailPage({
  stationId,
  onBack,
  onSelectStation,
  onOpenAdmin,
  onOpenMap,
  onOpenAdminReconcile,
}: {
  stationId: string;
  onBack: () => void;
  onSelectStation?: (id: string) => void;
  onOpenAdmin?: (id: string) => void;
  onOpenMap?: (id: string) => void;
  onOpenAdminReconcile?: () => void;
}) {
  const { session } = useAuth();
  const toast = useToast();
  const canManage = isAdmin(session);
  const owner = isOwner(session);
  const canSeeStaffAndShifts = canManage || owner;
  const catalog = useCatalog();
  const { byCode } = usePublicLevels();
  const { range, historyLoading } = useViewPeriod();
  const day = useSensorDay([stationId]);
  const [tab, setTab] = useState<DetailTab>("overview");

  const [devices, setDevices] = useState<TankDevice[]>([]);
  const [tankStates, setTankStates] = useState<Record<string, TankIngestState>>({});
  const [dispenses, setDispenses] = useState<DispenseReading[]>([]);
  const [discrepancyEvents, setDiscrepancyEvents] = useState<DiscrepancyEvent[]>([]);
  const [shifts, setShifts] = useState<ShiftRecord[]>([]);
  const [selectedShiftReport, setSelectedShiftReport] = useState<ShiftDetail | null>(null);
  const [shiftReportBusyId, setShiftReportBusyId] = useState<string | null>(null);

  const stations = owner ? catalog.stations : catalog.stations.filter((row) => row.is_active);
  const index = stations.findIndex((row) => row.id === stationId);
  const station = index >= 0 ? stations[index] : catalog.stations.find((row) => row.id === stationId);

  const sinceIso = range.start.toISOString();
  const untilIso = range.end.toISOString();

  useEffect(() => {
    setSelectedShiftReport(null);
  }, [stationId]);

  useEffect(() => {
    let alive = true;
    async function loadExtra() {
      const dispPromise = api.stationDispenses(stationId, sinceIso, 5000, untilIso).catch(() => []);
      try {
        const list = await api.tankDevices(stationId);
        if (!alive) return;
        setDevices(list);
        const states = await Promise.all(
          list.map(async (dev) => {
            try {
              const st = await api.stationTankState(stationId, dev.id);
              return [dev.id, st] as const;
            } catch {
              return null;
            }
          })
        );
        if (!alive) return;
        const map: Record<string, TankIngestState> = {};
        for (const item of states) {
          if (item) map[item[0]] = item[1];
        }
        setTankStates(map);
      } catch {
        if (!alive) return;
        setDevices([]);
        setTankStates({});
      }

      const dispRows = await dispPromise;
      if (alive) setDispenses(dispRows);

      if (canSeeStaffAndShifts) {
        api
          .stationShifts(stationId, 30)
          .then((rows) => {
            if (alive) setShifts(rows);
          })
          .catch(() => {
            if (alive) setShifts([]);
          });
      }

      if (canManage) {
        try {
          const evs = await api.events(stationId, false);
          if (alive) setDiscrepancyEvents(evs);
        } catch {
          if (alive) setDiscrepancyEvents([]);
        }
      }
    }
    void loadExtra();
    const timer = window.setInterval(() => void loadExtra(), 8000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [stationId, canManage, canSeeStaffAndShifts, sinceIso, untilIso]);

  const live = station ? (byCode.get(station.code) ?? null) : null;
  const hasTanks = !!live && live.tanks.length > 0;
  const series = station ? day.get(station.id) : undefined;
  const fillPct = hasTanks && live?.fill != null ? Math.max(0, Math.min(100, live.fill)) : 0;
  const showColumns = station ? isColumnReportStation(station) : false;
  const colCount = station ? stationColumnCount(station) : 2;
  const colMode = station?.columns_mode;

  const columnReport = useMemo(() => {
    if (!showColumns) return null;
    const points = series?.points ?? [];
    const liveTanks = buildLiveTankSamples(live, devices, points, range.includesNow);
    const fallbackOutflow = series?.opening != null ? series.outflow : 0;
    const sensorOutflowLiters = series?.opening != null ? series.outflow : null;
    const tankCapacity = devices.reduce((sum, device) => sum + (device.capacity_liters || 0), 0);
    return columnDispenseReport(points, range, liveTanks, new Date(), fallbackOutflow, dispenses, {
      columnCount: colCount,
      mode: colMode,
      sensorOutflowLiters,
      capacityLiters: tankCapacity > 0 ? tankCapacity : null,
    });
  }, [showColumns, series, live, devices, range, dispenses, colCount, colMode]);

  const bookSummary = useMemo(() => {
    const stateList = Object.values(tankStates);
    if (stateList.length === 0) return null;
    let calcSum = 0;
    let calcKnown = false;
    let actualSum = 0;
    let actualKnown = false;
    let receiptsSum = 0;
    let dispenseSum = 0;
    for (const st of stateList) {
      receiptsSum += st.receipts_liters || 0;
      dispenseSum += st.dispense_liters || 0;
      if (st.calculated_remainder_liters != null) {
        calcSum += st.calculated_remainder_liters;
        calcKnown = true;
      }
      if (st.actual_remainder_liters != null) {
        actualSum += st.actual_remainder_liters;
        actualKnown = true;
      }
    }
    const delta = calcKnown && actualKnown ? actualSum - calcSum : null;
    return {
      calcSum: calcKnown ? calcSum : null,
      actualSum: actualKnown ? actualSum : null,
      delta,
      receiptsSum,
      dispenseSum,
    };
  }, [tankStates]);

  if (!station) {
    return (
      <div className="dash">
        <button type="button" className="btn secondary small" onClick={onBack}>
          ← Все АГЗС
        </button>
        <p className="empty">АГЗС не найдена</p>
      </div>
    );
  }

  const prev = index > 0 ? stations[index - 1] : stations[stations.length - 1];
  const next = index >= 0 && index < stations.length - 1 ? stations[index + 1] : stations[0];
  const levelChart = chartOf(series?.series ?? [], series?.labels ?? range.labels);
  const hasDay = series?.opening != null;
  const freeLiters =
    hasTanks && live ? freeVolumeLiters(live.capacity, live.remainder) : null;
  const safeRefill =
    hasTanks && live ? safeRefillLiters(live.capacity, live.remainder) : null;
  const onlineTanksCount = live?.tanks.filter((t) => t.online && t.remainder_liters != null).length ?? 0;
  const totalTanksCount = live?.tanks.length ?? devices.length;
  const savedColumnsMode: ColumnsMode =
    station.columns_mode === "none" ||
    station.columns_mode === "virtual" ||
    station.columns_mode === "edge"
      ? station.columns_mode
      : showColumns
        ? "virtual"
        : "none";
  const isEdgeMode = savedColumnsMode === "edge";
  const dispensedLiters = showColumns && columnReport ? columnReport.total : null;
  const sensorSpent = hasDay && series ? series.outflow : null;
  const expenseLiters = dispensedLiters != null ? dispensedLiters : sensorSpent;
  const tankRows =
    devices.length > 0
      ? devices
      : (live?.tanks ?? []).map((t) => ({
          id: t.code,
          station_id: station.id,
          code: t.code,
          capacity_liters: t.capacity_liters,
          ingest_token: null,
          level_path: "",
          shelly: null,
        }));

  return (
    <div className="dash">
      <div className="st-detail-nav">
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <button type="button" className="btn secondary small" onClick={onBack}>
            {owner ? "← Мои АГЗС" : "← Все АГЗС"}
          </button>
          {onSelectStation && stations.length > 1 ? (
            <div className="st-Detail-switcher">
              <button
                type="button"
                className="btn secondary small"
                title={`Предыдущая: ${prev.name}`}
                aria-label="Предыдущая АГЗС"
                onClick={() => onSelectStation(prev.id)}
              >
                ‹
              </button>
              <select
                className="st-select"
                value={station.id}
                aria-label="Выбрать АГЗС"
                onChange={(event) => onSelectStation(event.target.value)}
              >
                {stations.map((row, idx) => {
                  const rowLive = byCode.get(row.code);
                  const rowFill =
                    rowLive && rowLive.tanks.length > 0 && rowLive.fill != null
                      ? `${Math.round(rowLive.fill)}%`
                      : "нет замера";
                  return (
                    <option key={row.id} value={row.id}>
                      {idx + 1}. {row.name} ({row.code} · {rowFill})
                    </option>
                  );
                })}
              </select>
              <button
                type="button"
                className="btn secondary small"
                title={`Следующая: ${next.name}`}
                aria-label="Следующая АГЗС"
                onClick={() => onSelectStation(next.id)}
              >
                ›
              </button>
            </div>
          ) : null}
        </div>
        <div className="st-detail-actions">
          <PeriodSwitch />
          {onOpenMap ? (
            <button type="button" className="btn secondary small" onClick={() => onOpenMap(station.id)}>
              На карте
            </button>
          ) : null}
          {onOpenAdmin ? (
            <button type="button" className="btn small" onClick={() => onOpenAdmin(station.id)}>
              Администратор
            </button>
          ) : null}
        </div>
      </div>

      <header className="st-head">
        <div>
          <p className="kicker">
            {station.code} · {stationRegion(station)} · GPS {station.lat.toFixed(4)}, {station.lon.toFixed(4)}
            {stations.length > 1 && index >= 0 ? ` · станция ${index + 1} из ${stations.length}` : ""}
          </p>
          <h2>{station.name}</h2>
          <span className="dash-muted">{station.address || "Адрес не указан"}</span>
        </div>
        <div className="st-row-badges">
          {hasTanks && live ? (
            <SensorStatusBadge level={live} />
          ) : (
            <span className="badge warn">датчик не подключён</span>
          )}
          <span className="badge">приход {liters(series?.inflow ?? 0)}</span>
          {dispensedLiters != null ? (
            <span className="badge">отпуск {liters(dispensedLiters)}</span>
          ) : sensorSpent != null ? (
            <span className="badge">расход {liters(sensorSpent)}</span>
          ) : null}
          {showColumns ? (
            <span className={`badge ${isEdgeMode ? "ok" : "warn"}`}>
              {isEdgeMode
                ? `ТРК edge (${colCount})`
                : columnReport?.source === "edge"
                  ? `вирт. колонки · есть наливы edge (${colCount})`
                  : `вирт. колонки (${colCount})`}
            </span>
          ) : null}
        </div>
      </header>

      <div className="dash-kpis" style={{ marginBottom: 22 }}>
        <div className="dash-kpi">
          <span>Фактический остаток</span>
          <strong className={isLowFill(hasTanks ? live?.fill : null) ? "text-danger" : ""}>
            {!hasTanks || live?.remainder == null ? "—" : liters(live.remainder)}
          </strong>
          <em>
            {!hasTanks
              ? "резервуар не добавлен"
              : `из ${liters(live?.capacity ?? 0)} (${live?.fill == null ? "—" : `${Math.round(live.fill)}%`})`}
          </em>
        </div>
        <div className="dash-kpi">
          <span>Свободная ёмкость</span>
          <strong>{freeLiters == null ? "—" : liters(freeLiters)}</strong>
          <em>
            {safeRefill != null
              ? `рекомендуемый слив до ${SAFE_FILL_PERCENT}%: ${liters(safeRefill)}`
              : "доступный объём под слив"}
          </em>
        </div>
        <div className="dash-kpi">
          <span>{range.inflowTitle}</span>
          <strong>{range.countsReceipts ? liters(series?.inflow ?? 0) : "—"}</strong>
          <em>
            {bookSummary && bookSummary.receiptsSum > 0
              ? `всего по книге: ${liters(bookSummary.receiptsSum)}`
              : "принятые поставки"}
          </em>
        </div>
        <div className="dash-kpi">
          <span>{dispensedLiters != null ? range.expenseTitle.replace("Расход", "Отпуск") : range.expenseTitle}</span>
          <strong>{expenseLiters != null ? liters(expenseLiters) : "—"}</strong>
          <em>
            {dispensedLiters != null
              ? "по наливам колонок"
              : hasDay && series?.opening != null
                ? `старт периода: ${liters(series.opening)}`
                : "по замерам датчика"}
          </em>
        </div>
        <div className="dash-kpi">
          <span>Резервуары и связь</span>
          <strong>
            {onlineTanksCount} / {totalTanksCount}
          </strong>
          <em>
            {hasTanks && live?.measuredAt
              ? `замер ${dateTime(live.measuredAt)}`
              : "ожидание телеметрии"}
          </em>
        </div>
      </div>

      <div className="admin-tabs" role="tablist" style={{ marginBottom: 20, flexWrap: "wrap" }}>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "overview"}
          className={tab === "overview" ? "active" : ""}
          onClick={() => setTab("overview")}
        >
          Сводка и аналитика
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "pumps"}
          className={tab === "pumps" ? "active" : ""}
          onClick={() => setTab("pumps")}
        >
          {showColumns ? `Колонки (${columnReport?.columnCount ?? colCount})` : "Колонки"}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "tanks"}
          className={tab === "tanks" ? "active" : ""}
          onClick={() => setTab("tanks")}
        >
          Резервуары и датчики ({totalTanksCount})
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "history"}
          className={tab === "history" ? "active" : ""}
          onClick={() => setTab("history")}
        >
          Журнал замеров и сверка
          {discrepancyEvents.length > 0 ? ` (${discrepancyEvents.length})` : ""}
        </button>
        {canSeeStaffAndShifts ? (
          <button
            type="button"
            role="tab"
            aria-selected={tab === "staff"}
            className={tab === "staff" ? "active" : ""}
            onClick={() => setTab("staff")}
          >
            Кассиры и смены
            {shifts.length > 0 ? ` (${shifts.length})` : ""}
          </button>
        ) : null}
      </div>

      {tab === "overview" ? (
        <>
          <div className="st-grid" style={{ marginBottom: 18 }}>
            <section className="dash-card">
              <h3>{range.chartTitle}</h3>
              <p className="dash-muted">
                {range.countsReceipts ? (
                  <>
                    Приход {liters(series?.inflow ?? 0)}
                    {(series?.inflow ?? 0) > 0 ? " — поставка." : ": поставки не было."}{" "}
                  </>
                ) : (
                  "Поставки в книге без даты, за этот срок не считаем. "
                )}
                На линии газ, который уже был в резервуаре.
                {sensorSpent != null ? ` Уход по датчику ${liters(sensorSpent)}.` : ""}
                {dispensedLiters != null ? ` Отпуск колонками ${liters(dispensedLiters)}.` : ""}
              </p>
              {historyLoading && levelChart.labels.length === 0 ? (
                <p className="dash-muted">Загрузка замеров…</p>
              ) : levelChart.labels.length === 1 ? (
                <BarChart
                  labels={levelChart.labels}
                  series={[{ name: "Остаток", color: "var(--sea)", values: levelChart.values }]}
                />
              ) : levelChart.labels.length > 1 ? (
                <LineChart
                  labels={levelChart.labels}
                  series={[{ name: "Остаток", color: "var(--sea)", values: levelChart.values }]}
                />
              ) : (
                <p className="dash-muted">
                  {range.includesNow && hasTanks && live?.remainder != null
                    ? `Сейчас в резервуаре ${liters(live.remainder)}. Смен уровня за этот срок не было.`
                    : "Замера датчика за этот срок ещё нет."}
                </p>
              )}
            </section>

            <section className="dash-card">
              <h3>Цифровой уровень резервуара</h3>
              <div className="gauge">
                <div className="gauge-bar">
                  <i
                    style={{
                      height: `${fillPct}%`,
                      background: isLowFill(hasTanks ? live?.fill : null)
                        ? "var(--coral)"
                        : "linear-gradient(0deg, var(--sea-2, var(--sea)), var(--sea))",
                    }}
                  />
                </div>
                <div className="gauge-meta">
                  <strong>{hasTanks && live?.fill == null ? "—" : `${Math.round(fillPct)}%`}</strong>
                  <span>
                    {!hasTanks || live?.remainder == null
                      ? "замера ещё нет"
                      : `${liters(live.remainder)} из ${liters(live.capacity)}`}
                  </span>
                  {freeLiters != null ? (
                    <span className="dash-muted">Свободно под слив: {liters(freeLiters)}</span>
                  ) : null}
                  {hasTanks && live
                    ? live.tanks.map((item) => (
                        <span key={item.code}>
                          резервуар {item.code} ·{" "}
                          <span className={`badge ${tankSensorBadge(item)}`}>
                            {tankSensorLabel(item)}
                          </span>
                          {" · "}
                          {item.remainder_liters == null
                            ? "замера нет"
                            : `${liters(item.remainder_liters)} из ${liters(item.capacity_liters)}`}
                        </span>
                      ))
                    : null}
                  <span className="dash-muted">
                    {hasTanks && live?.measuredAt ? `Замер: ${dateTime(live.measuredAt)}` : "замера нет"}
                  </span>
                </div>
              </div>
            </section>
          </div>

          <section className="dash-card" style={{ marginBottom: 18 }}>
            <h3>Сводный паспорт резервуаров и сверка остатков</h3>
            {devices.length === 0 && (!live || live.tanks.length === 0) ? (
              <p className="empty">К этой АГЗС ещё не подключены резервуары.</p>
            ) : (
              <div className="dash-table-wrap">
                <table className="dash-table">
                  <thead>
                    <tr>
                      <th>Код</th>
                      <th>Связь / Shelly</th>
                      <th>Уровень %</th>
                      <th>Факт (датчик)</th>
                      <th>Ёмкость / Свободно</th>
                      <th>Книжный остаток</th>
                      <th>Напряжение / Замер</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tankRows.map((dev) => {
                      const pubTank = live?.tanks.find((t) => t.code === dev.code);
                      const st = tankStates[dev.id];
                      const rem = pubTank?.remainder_liters ?? st?.actual_remainder_liters ?? null;
                      const pct =
                        pubTank?.fill_percent ??
                        (rem != null && dev.capacity_liters > 0
                          ? Math.round((rem / dev.capacity_liters) * 100)
                          : null);
                      const free =
                        rem != null ? Math.max(0, dev.capacity_liters - rem) : null;
                      return (
                        <tr key={dev.id}>
                          <td>
                            <strong>{dev.code}</strong>
                          </td>
                          <td>
                            {pubTank ? (
                              <span className={`badge ${tankSensorBadge(pubTank)}`}>
                                {tankSensorLabel(pubTank)}
                              </span>
                            ) : (
                              <span className="badge warn">ожидание</span>
                            )}
                            {dev.shelly ? (
                              <div className="dash-muted">Shelly {dev.shelly.host}</div>
                            ) : null}
                          </td>
                          <td>
                            <strong className={isLowFill(pct) ? "text-danger" : ""}>
                              {pct == null ? "—" : `${Math.round(pct)}%`}
                            </strong>
                          </td>
                          <td>
                            <strong>{rem == null ? "замера нет" : liters(rem)}</strong>
                          </td>
                          <td>
                            <div>{liters(dev.capacity_liters)}</div>
                            <div className="dash-muted">
                              своб. {free == null ? "—" : liters(free)}
                            </div>
                          </td>
                          <td>
                            {st?.calculated_remainder_liters != null ? (
                              <>
                                <strong>{liters(st.calculated_remainder_liters)}</strong>
                                <div className="dash-muted">
                                  приход {liters(st.receipts_liters)} · ТРК{" "}
                                  {liters(st.dispense_liters)}
                                </div>
                              </>
                            ) : (
                              <span className="dash-muted">—</span>
                            )}
                          </td>
                          <td>
                            <div>
                              {st?.last_volts != null
                                ? `${st.last_volts.toFixed(2)} В`
                                : dev.shelly?.volts != null
                                  ? `${dev.shelly.volts.toFixed(2)} В`
                                  : "—"}
                              {st?.calibrated ? " (калибр.)" : ""}
                            </div>
                            <div className="dash-muted">
                              {pubTank?.measured_at
                                ? dateTime(pubTank.measured_at)
                                : st?.last_measured_at
                                  ? dateTime(st.last_measured_at)
                                  : "нет замера"}
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
        </>
      ) : null}

      {tab === "pumps" ? (
        showColumns && columnReport ? (
          <ColumnReportCard
            points={series?.points ?? []}
            range={range}
            devices={devices}
            live={live}
            loading={historyLoading}
            outflow={hasDay && series ? series.outflow : 0}
            dispenses={dispenses}
            report={columnReport}
            columnsMode={savedColumnsMode}
            onConfigureColumns={onOpenAdmin ? () => onOpenAdmin(station.id) : undefined}
          />
        ) : (
          <section className="dash-card">
            <div className="card-head-inline">
              <h3>Колонки</h3>
              {onOpenAdmin ? (
                <button
                  type="button"
                  className="btn secondary small"
                  onClick={() => onOpenAdmin(station.id)}
                >
                  Настроить колонки в админке →
                </button>
              ) : null}
            </div>
            <p className="dash-muted">
              Колонки для этой АГЗС не подключены. Можно включить виртуальные колонки или приём
              реальных наливов station-edge в карточке станции.
            </p>
          </section>
        )
      ) : null}

      {tab === "tanks" ? (
        <>
          <section className="dash-section">
            <h3>Состояние резервуаров ({live?.tanks.length ?? 0})</h3>
            {!hasTanks || !live ? (
              <p className="empty">
                {canManage
                  ? "К этой АГЗС ещё не подключён резервуар. Настройте его в кабинете администратора."
                  : "К этой АГЗС ещё не подключён резервуар."}
              </p>
            ) : (
              <div className="st-card-grid">
                {live.tanks.map((tank) => {
                  const width =
                    tank.fill_percent == null ? 0 : Math.max(0, Math.min(100, tank.fill_percent));
                  const free =
                    tank.remainder_liters != null
                      ? Math.max(0, tank.capacity_liters - tank.remainder_liters)
                      : null;
                  const dev = devices.find((d) => d.code === tank.code);
                  const st = dev ? tankStates[dev.id] : undefined;
                  return (
                    <article
                      className={`dash-card${tank.online ? "" : " level-tank-stale"}`}
                      key={tank.code}
                    >
                      <div className="st-grid-card-head">
                        <div>
                          <span className={`badge ${tankSensorBadge(tank)}`}>
                            {tankSensorLabel(tank)}
                          </span>
                          <h4>Резервуар {tank.code}</h4>
                        </div>
                        <strong
                          className={`st-grid-pct${isLowFill(tank.fill_percent) ? " text-danger" : ""}`}
                        >
                          {tank.fill_percent == null ? "—" : `${Math.round(tank.fill_percent)}%`}
                        </strong>
                      </div>
                      <div className="public-track" aria-hidden="true">
                        <i style={{ width: `${width}%` }} />
                      </div>
                      <div className="st-grid-metrics">
                        <div>
                          <span>Фактический остаток</span>
                          <strong>
                            {tank.remainder_liters == null
                              ? "замера нет"
                              : liters(tank.remainder_liters)}
                          </strong>
                        </div>
                        <div>
                          <span>Полная ёмкость</span>
                          <strong>{liters(tank.capacity_liters)}</strong>
                        </div>
                        <div>
                          <span>Свободный объём</span>
                          <strong>{free == null ? "—" : liters(free)}</strong>
                        </div>
                        <div>
                          <span>Время замера</span>
                          <strong>
                            {tank.measured_at ? dateTime(tank.measured_at) : "ожидание"}
                          </strong>
                        </div>
                        {st ? (
                          <>
                            <div>
                              <span>Книжный остаток</span>
                              <strong>
                                {st.calculated_remainder_liters == null
                                  ? "—"
                                  : liters(st.calculated_remainder_liters)}
                              </strong>
                            </div>
                            <div>
                              <span>Напряжение / Калибровка</span>
                              <strong>
                                {st?.last_volts == null ? "—" : `${st.last_volts.toFixed(2)} В`}
                                {st?.calibrated && st.cal_low_volts != null && st.cal_high_volts != null
                                  ? ` (${st.cal_low_volts} В${
                                      st.cal_low_percent != null ? ` = ${st.cal_low_percent}%` : ""
                                    } … ${st.cal_high_volts} В${
                                      st.cal_high_percent != null ? ` = ${st.cal_high_percent}%` : ""
                                    })`
                                  : ""}
                              </strong>
                            </div>
                          </>
                        ) : null}
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>
          {canManage ? (
            <section className="dash-card">
              <div className="card-head-inline">
                <div>
                  <h3 style={{ margin: 0 }}>Настройка оборудования и токены датчиков</h3>
                  <p className="dash-muted" style={{ margin: "6px 0 0" }}>
                    Добавление и удаление резервуаров, подключение Shelly, калибровка вольтметра,
                    ручной ввод остатка и перевыпуск X-Device-Token выполняются в кабинете
                    администратора.
                  </p>
                </div>
                {onOpenAdmin ? (
                  <button
                    type="button"
                    className="btn small"
                    onClick={() => onOpenAdmin(station.id)}
                  >
                    Настроить АГЗС и датчики →
                  </button>
                ) : null}
              </div>
            </section>
          ) : (
            <section className="dash-card">
              <h3 style={{ marginTop: 0 }}>Обслуживание датчиков и телеметрии</h3>
              <p className="dash-muted" style={{ marginBottom: 0 }}>
                Карточки резервуаров работают в режиме только для чтения. Добавление резервуаров,
                настройку Shelly, калибровку и токены доступа выполняет администратор платформы.
              </p>
            </section>
          )}
        </>
      ) : null}

      {tab === "history" ? (
        <>
          <section className="dash-card" style={{ marginBottom: 16 }}>
            <LevelChangesToday stationId={station.id} />
          </section>

          <section className="dash-card">
            <div className="card-head-inline">
              <h3>События сверки и инциденты ({discrepancyEvents.length})</h3>
              {onOpenAdminReconcile ? (
                <button
                  type="button"
                  className="btn secondary small"
                  onClick={onOpenAdminReconcile}
                >
                  Сверка и закрытие в админке →
                </button>
              ) : null}
            </div>
            {discrepancyEvents.length === 0 ? (
              <p className="dash-muted">
                Расхождений книжного баланса по данной АГЗС не зафиксировано.
              </p>
            ) : (
              <div className="dash-table-wrap">
                <table className="dash-table">
                  <thead>
                    <tr>
                      <th>Время</th>
                      <th>Источник / Тип</th>
                      <th>Уровень важности</th>
                      <th>Описание события</th>
                      <th>Статус</th>
                    </tr>
                  </thead>
                  <tbody>
                    {discrepancyEvents.map((ev) => (
                      <tr key={ev.id}>
                        <td>{dateTime(ev.detected_at)}</td>
                        <td>
                          <strong>Сверка резервуара</strong>
                          <div className="dash-muted">{eventTypeLabel(ev.event_type)}</div>
                        </td>
                        <td>
                          <span
                            className={`badge ${ev.severity === "critical" ? "danger" : "warn"}`}
                          >
                            {severityLabel(ev.severity)}
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
                            {ev.is_resolved ? "решено" : "открыто"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      ) : null}

      {tab === "staff" && canSeeStaffAndShifts ? (
        <div className="admin-workspace">
          <StationCashiersCard stationId={station.id} canManage={owner} />

          {selectedShiftReport ? (
            <ShiftReportView
              report={selectedShiftReport}
              stationName={station.name}
              stationCode={station.code}
              onClose={() => setSelectedShiftReport(null)}
            />
          ) : null}

          <section className="dash-card">
            <div className="card-head-inline" style={{ marginBottom: 10 }}>
              <div>
                <h3 style={{ margin: 0 }}>Кассовые смены АГЗС ({shifts.length})</h3>
                <p className="dash-muted" style={{ margin: "4px 0 0" }}>
                  Смены открывает и закрывает кассир станции. Нажмите на любую смену для просмотра
                  отчёта.
                </p>
              </div>
            </div>
            {shifts.length === 0 ? (
              <p className="dash-muted" style={{ marginBottom: 0 }}>
                По этой АГЗС ещё не открывали смен.
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
                          <strong>
                            {sh.dispensed_liters.toLocaleString("ru-RU", {
                              minimumFractionDigits: 0,
                              maximumFractionDigits: 2,
                            })}{" "}
                            л
                          </strong>
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
                            disabled={shiftReportBusyId === sh.id}
                            onClick={async () => {
                              setShiftReportBusyId(sh.id);
                              try {
                                const detail = await api.shiftReport(station.id, sh.id);
                                setSelectedShiftReport(detail);
                              } catch (err) {
                                toast.err(messageOf(err));
                              } finally {
                                setShiftReportBusyId(null);
                              }
                            }}
                          >
                            {shiftReportBusyId === sh.id ? "Загрузка…" : "Открыть отчёт"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      ) : null}
    </div>
  );
}
