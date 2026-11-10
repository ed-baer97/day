import { useEffect, useMemo, useState } from "react";
import {
  api,
  type TankDevice,
  type TankIngestState,
} from "../api/client";
import { isAdmin } from "../access";
import { useAuth } from "../auth";
import { useCatalog } from "../catalog";
import { balBadge, balText, dateTime, liters, signedLiters, stationRegion } from "../format";
import {
  isLowFill,
  SensorStatus,
  tankSensorBadge,
  tankSensorLabel,
  usePublicLevels,
  useSensorDay,
  useViewPeriod,
} from "../liveLevels";
import { chartOf } from "../sensorDay";
import type { DiscrepancyEvent, StationBalance } from "../types";
import { BarChart, LineChart } from "./Charts";
import LevelChangesToday from "./LevelChangesToday";
import PeriodSwitch from "./PeriodSwitch";
import TankDeviceRows from "./TankDeviceRows";

type DetailTab = "overview" | "tanks" | "history";

export default function StationDetailPage({
  stationId,
  onBack,
  onSelectStation,
  onOpenAdmin,
  onOpenMap,
}: {
  stationId: string;
  onBack: () => void;
  onSelectStation?: (id: string) => void;
  onOpenAdmin?: (id: string) => void;
  onOpenMap?: (id: string) => void;
}) {
  const { session } = useAuth();
  const canManage = isAdmin(session);
  const catalog = useCatalog();
  const { byCode } = usePublicLevels();
  const { range, historyLoading } = useViewPeriod();
  const day = useSensorDay([stationId]);
  const [tab, setTab] = useState<DetailTab>("overview");

  const [devices, setDevices] = useState<TankDevice[]>([]);
  const [tankStates, setTankStates] = useState<Record<string, TankIngestState>>({});
  const [discrepancyEvents, setDiscrepancyEvents] = useState<DiscrepancyEvent[]>([]);

  const stations = catalog.stations.filter((row) => row.is_active);
  const index = stations.findIndex((row) => row.id === stationId);
  const station = index >= 0 ? stations[index] : catalog.stations.find((row) => row.id === stationId);

  useEffect(() => {
    let alive = true;
    async function loadExtra() {
      try {
        const list = await api.tankDevices(stationId);
        if (!alive) return;
        setDevices(list);
        const states = await Promise.all(
          list.map(async (dev) => {
            try {
              const st = await api.tankIngestState(dev.id);
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
  }, [stationId, canManage]);

  const live = station ? (byCode.get(station.code) ?? null) : null;
  const hasTanks = !!live && live.tanks.length > 0;
  const series = station ? day.get(station.id) : undefined;
  const fillPct = hasTanks && live?.fill != null ? Math.max(0, Math.min(100, live.fill)) : 0;

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
    hasTanks && live?.remainder != null && live.capacity > 0
      ? Math.max(0, live.capacity - live.remainder)
      : null;
  const safeRefill =
    hasTanks && live?.remainder != null && live.capacity > 0
      ? Math.max(0, Math.round(live.capacity * 0.85) - live.remainder)
      : null;
  const onlineTanksCount = live?.tanks.filter((t) => t.online && t.remainder_liters != null).length ?? 0;
  const totalTanksCount = live?.tanks.length ?? devices.length;

  return (
    <div className="dash">
      <div className="st-detail-nav">
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          {stations.length > 1 ? (
            <button type="button" className="btn secondary small" onClick={onBack}>
              ← Все АГЗС ({stations.length})
            </button>
          ) : null}
          {onSelectStation && stations.length > 1 ? (
            <div className="st-Detail-switcher">
              <button
                type="button"
                className="btn secondary small"
                title={`Предыдущая: ${prev.name}`}
                onClick={() => onSelectStation(prev.id)}
              >
                ‹ Пред.
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
                onClick={() => onSelectStation(next.id)}
              >
                След. ›
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
              Настроить в админке ⚙
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
            <SensorStatus level={live} />
          ) : (
            <span className="badge warn">датчик не подключён</span>
          )}
          <span className="badge">приход {liters(series?.inflow ?? 0)}</span>
          {hasDay && series ? <span className="badge">расход {liters(series.outflow)}</span> : null}
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
              ? `рекомендуемый слив до 85%: ${liters(safeRefill)}`
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
          <span>{range.expenseTitle}</span>
          <strong>{hasDay && series ? liters(series.outflow) : "—"}</strong>
          <em>
            {hasDay && series?.opening != null
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
        <div className="dash-kpi">
          <span>Книжный баланс и ТРК</span>
          <strong>
            {bookSummary?.calcSum != null ? liters(bookSummary.calcSum) : "—"}
          </strong>
          <em>
            {bookSummary?.delta != null
              ? `разница с фактом: ${signedLiters(bookSummary.delta)}`
              : bookSummary && bookSummary.dispenseSum > 0
                ? `отпуск ТРК: ${liters(bookSummary.dispenseSum)}`
                : "сверка по приходу и ТРК"}
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
                {hasDay && series ? ` Расход ${liters(series.outflow)}.` : ""}
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
            <div className="card-head-inline">
              <h3>Сводный паспорт резервуаров и сверка остатков</h3>
              <button
                type="button"
                className="btn secondary small"
                onClick={() => setTab("tanks")}
              >
                Управление резервуарами и Shelly →
              </button>
            </div>
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
                      <th>Разница (Δ)</th>
                      <th>Напряжение / Замер</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(devices.length > 0
                      ? devices
                      : (live?.tanks ?? []).map((t) => ({
                          id: t.code,
                          station_id: station.id,
                          code: t.code,
                          capacity_liters: t.capacity_liters,
                          ingest_token: "",
                          level_path: "",
                          shelly: null,
                        }))
                    ).map((dev) => {
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
                      const bStatus = (st?.balance_status || "ok") as StationBalance["status"];
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
                            {st?.delta_liters != null ? (
                              <>
                                <strong>{signedLiters(st.delta_liters)}</strong>
                                <div>
                                  <span className={`badge ${balBadge(bStatus)}`}>
                                    {balText(bStatus)}
                                  </span>
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

      {tab === "tanks" ? (
        <>
          <section className="dash-section">
            <h3>Состояние резервуаров ({live?.tanks.length ?? 0})</h3>
            {!hasTanks || !live ? (
              <p className="empty">
                {canManage
                  ? "К этой АГЗС ещё не подключён резервуар. Добавьте его ниже и привяжите датчик."
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
                              <span>Напряжение датчика</span>
                              <strong>
                                {st.last_volts == null ? "—" : `${st.last_volts.toFixed(2)} В`}
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
          <section className="dash-section">
            <h3>Настройка резервуаров, Shelly и калибровка</h3>
            <TankDeviceRows stationId={station.id} />
          </section>
        </>
      ) : null}

      {tab === "history" ? (
        <>
          <section className="dash-card" style={{ marginBottom: 16 }}>
            <LevelChangesToday stationId={station.id} />
          </section>

          <section className="dash-card">
            <h3>События сверки и инциденты ({discrepancyEvents.length})</h3>
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
                      <th>Источник / Код</th>
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
                          <div className="dash-muted">{ev.event_type}</div>
                        </td>
                        <td>
                          <span
                            className={`badge ${ev.severity === "critical" ? "danger" : "warn"}`}
                          >
                            {ev.severity}
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
    </div>
  );
}
