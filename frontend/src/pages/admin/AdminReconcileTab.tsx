import { useMemo, useState } from "react";
import { api, type BalanceSnapshot, type CatalogStation } from "../../api/client";
import { messageOf } from "../../catalog";
import {
  balBadge,
  balText,
  dateTime,
  eventTypeLabel,
  liters,
  severityLabel,
  signedLiters,
} from "../../format";
import { SENSOR_STALE_SECONDS } from "../../policy";
import type { DiscrepancyEvent } from "../../types";
import type { EnrichedStation } from "./types";

type KpiFilter = "all" | "online" | "offline" | "no_tank" | "open_events";
type EventStatusFilter = "all" | "open" | "resolved";

type ReconcileTarget = {
  stationId: string;
  stationName: string;
  tankId: string;
  tankCode: string;
  opening: string;
  receipts: string;
  dispense: string;
  actual: string;
  periodStart: string;
  periodEnd: string;
};

function toLocalDatetimeInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export default function AdminReconcileTab({
  enriched,
  events,
  stations,
  onResolve,
  onRefresh,
  onOpenStation,
  toast,
}: {
  enriched: EnrichedStation[];
  events: DiscrepancyEvent[];
  stations: CatalogStation[];
  onResolve: (id: string, note: string) => Promise<void>;
  onRefresh: () => Promise<void>;
  onOpenStation: (id: string) => void;
  toast: { ok: (msg: string) => void; err: (msg: string) => void };
}) {
  const [scope, setScope] = useState<"active" | "all">("active");
  const [kpiFilter, setKpiFilter] = useState<KpiFilter>("all");
  const [evFilter, setEvFilter] = useState<EventStatusFilter>("all");
  const [evStationFilter, setEvStationFilter] = useState<string>("all");

  // Inline закрытие события с комментарием
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [resolveNote, setResolveNote] = useState("Проверено администратором");
  const [resolveBusy, setResolveBusy] = useState(false);

  // Модалка ручной сверки POST /balance/reconcile
  const [reconcileTarget, setReconcileTarget] = useState<ReconcileTarget | null>(null);
  const [reconcileBusy, setReconcileBusy] = useState(false);
  const [reconcileError, setReconcileError] = useState<string | null>(null);

  // Просмотр истории снимков сверки GET /balance/stations/{id}/snapshots
  const [snapshotsStation, setSnapshotsStation] = useState<{ id: string; name: string } | null>(null);
  const [snapshots, setSnapshots] = useState<BalanceSnapshot[]>([]);
  const [snapshotsLoading, setSnapshotsLoading] = useState(false);

  const scopedStations = useMemo(
    () => (scope === "active" ? enriched.filter((x) => x.row.is_active) : enriched),
    [enriched, scope]
  );

  const openEventsByStation = useMemo(() => {
    const set = new Set<string>();
    for (const ev of events) {
      if (!ev.is_resolved) set.add(ev.station_id);
    }
    return set;
  }, [events]);

  const onlineCount = scopedStations.filter((x) => x.online).length;
  const offlineCount = scopedStations.filter((x) => x.tanksCount > 0 && !x.online).length;
  const noTankCount = scopedStations.filter((x) => x.tanksCount === 0).length;
  const openEventsCount = events.filter((e) => !e.is_resolved).length;

  const filteredBalanceStations = useMemo(() => {
    return scopedStations.filter((x) => {
      if (kpiFilter === "online") return x.online;
      if (kpiFilter === "offline") return x.tanksCount > 0 && !x.online;
      if (kpiFilter === "no_tank") return x.tanksCount === 0;
      if (kpiFilter === "open_events") return openEventsByStation.has(x.row.id);
      return true;
    });
  }, [scopedStations, kpiFilter, openEventsByStation]);

  const filteredEvents = useMemo(() => {
    return events.filter((ev) => {
      if (evFilter === "open" && ev.is_resolved) return false;
      if (evFilter === "resolved" && !ev.is_resolved) return false;
      if (evStationFilter !== "all" && ev.station_id !== evStationFilter) return false;
      return true;
    });
  }, [events, evFilter, evStationFilter]);

  function toggleKpi(next: KpiFilter) {
    setKpiFilter((cur) => (cur === next ? "all" : next));
  }

  function openReconcileModal(
    st: EnrichedStation,
    tankId: string,
    tankCode: string,
    opening: number | null,
    receipts: number,
    dispense: number,
    actual: number | null
  ) {
    const now = new Date();
    const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
    setReconcileError(null);
    setReconcileTarget({
      stationId: st.row.id,
      stationName: st.row.name,
      tankId,
      tankCode,
      opening: opening != null ? String(Math.round(opening)) : "0",
      receipts: String(Math.round(receipts)),
      dispense: String(Math.round(dispense)),
      actual: actual != null ? String(Math.round(actual)) : "",
      periodStart: toLocalDatetimeInput(startOfDay),
      periodEnd: toLocalDatetimeInput(now),
    });
  }

  async function submitReconcile() {
    if (!reconcileTarget) return;
    const prevRem = Number(reconcileTarget.opening.replace(",", "."));
    const receipts = Number(reconcileTarget.receipts.replace(",", "."));
    const dispense = Number(reconcileTarget.dispense.replace(",", "."));
    const actualRaw = reconcileTarget.actual.trim();
    const actual = actualRaw ? Number(actualRaw.replace(",", ".")) : null;
    if (
      !Number.isFinite(prevRem) ||
      !Number.isFinite(receipts) ||
      !Number.isFinite(dispense) ||
      (actual != null && !Number.isFinite(actual))
    ) {
      setReconcileError("Проверьте числовые значения объёмов");
      return;
    }
    const startDate = new Date(reconcileTarget.periodStart);
    const endDate = new Date(reconcileTarget.periodEnd);
    if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) {
      setReconcileError("Укажите корректный период сверки");
      return;
    }

    setReconcileBusy(true);
    setReconcileError(null);
    try {
      const snap = await api.reconcileBalance({
        station_id: reconcileTarget.stationId,
        tank_id: reconcileTarget.tankId,
        period_start: startDate.toISOString(),
        period_end: endDate.toISOString(),
        previous_remainder_liters: prevRem,
        receipts_liters: receipts,
        dispense_liters: dispense,
        actual_remainder_liters: actual,
      });
      toast.ok(
        `Сверка ${reconcileTarget.stationName} (${reconcileTarget.tankCode}): ${balText(
          snap.status as "ok" | "warn" | "shortage" | "surplus"
        )}`
      );
      const stId = reconcileTarget.stationId;
      const stName = reconcileTarget.stationName;
      setReconcileTarget(null);
      await onRefresh();
      void loadSnapshots(stId, stName);
    } catch (err) {
      setReconcileError(messageOf(err));
    } finally {
      setReconcileBusy(false);
    }
  }

  async function loadSnapshots(stationId: string, stationName: string) {
    setSnapshotsStation({ id: stationId, name: stationName });
    setSnapshotsLoading(true);
    try {
      const list = await api.stationSnapshots(stationId);
      setSnapshots(list);
    } catch (err) {
      setSnapshots([]);
      toast.err(messageOf(err));
    } finally {
      setSnapshotsLoading(false);
    }
  }

  async function confirmResolve(eventId: string) {
    setResolveBusy(true);
    try {
      await onResolve(eventId, resolveNote.trim() || "Проверено администратором");
      setResolvingId(null);
    } finally {
      setResolveBusy(false);
    }
  }

  return (
    <div className="admin-workspace">
      <div className="card-head-inline">
        <span className="dash-muted">
          Порог актуальности телеметрии: {SENSOR_STALE_SECONDS} сек · Нажмите на карточку KPI для фильтрации
        </span>
        <div className="mini-tabs">
          <button
            type="button"
            className={scope === "active" ? "active" : ""}
            onClick={() => setScope("active")}
          >
            Активные АГЗС ({enriched.filter((x) => x.row.is_active).length})
          </button>
          <button
            type="button"
            className={scope === "all" ? "active" : ""}
            onClick={() => setScope("all")}
          >
            Все, вкл. скрытые ({enriched.length})
          </button>
        </div>
      </div>

      <div className="dash-kpis">
        <div
          className={`dash-kpi${kpiFilter === "online" ? " active-kpi" : ""}`}
          style={{ cursor: "pointer" }}
          onClick={() => toggleKpi("online")}
        >
          <span>АГЗС на связи</span>
          <strong>
            {onlineCount} / {scopedStations.length}
          </strong>
          <em>актуальные показания датчиков</em>
        </div>
        <div
          className={`dash-kpi${kpiFilter === "offline" ? " active-kpi" : ""}`}
          style={{ cursor: "pointer" }}
          onClick={() => toggleKpi("offline")}
        >
          <span>АГЗС без связи</span>
          <strong className={offlineCount > 0 ? "text-danger" : ""}>{offlineCount}</strong>
          <em>замер устарел (&gt; {SENSOR_STALE_SECONDS} сек)</em>
        </div>
        <div
          className={`dash-kpi${kpiFilter === "no_tank" ? " active-kpi" : ""}`}
          style={{ cursor: "pointer" }}
          onClick={() => toggleKpi("no_tank")}
        >
          <span>Без резервуара / датчика</span>
          <strong>{noTankCount}</strong>
          <em>требуют привязки устройства</em>
        </div>
        <div
          className={`dash-kpi${kpiFilter === "open_events" ? " active-kpi" : ""}`}
          style={{ cursor: "pointer" }}
          onClick={() => toggleKpi("open_events")}
        >
          <span>Открытых расхождений</span>
          <strong className={openEventsCount > 0 ? "text-danger" : ""}>{openEventsCount}</strong>
          <em>всего событий в журнале: {events.length}</em>
        </div>
      </div>

      <section className="dash-card">
        <div className="card-head-inline">
          <h3 style={{ margin: 0 }}>Сводный баланс книги и датчиков по АГЗС</h3>
          {kpiFilter !== "all" ? (
            <button
              type="button"
              className="btn secondary small"
              onClick={() => setKpiFilter("all")}
            >
              Сбросить фильтр KPI
            </button>
          ) : null}
        </div>
        <div className="dash-table-wrap" style={{ marginTop: 10 }}>
          <table className="dash-table">
            <thead>
              <tr>
                <th>АГЗС</th>
                <th>Резервуар</th>
                <th>Старт</th>
                <th>Приход</th>
                <th>ТРК</th>
                <th>Книга</th>
                <th>Факт (датчик)</th>
                <th>Δ / Статус</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {filteredBalanceStations.length === 0 ? (
                <tr>
                  <td colSpan={9} className="dash-muted">
                    По выбранному фильтру АГЗС нет.
                  </td>
                </tr>
              ) : (
                filteredBalanceStations.flatMap((st) => {
                  const tanks = st.overview?.tanks ?? [];
                  if (tanks.length === 0) {
                    return [
                      <tr key={st.row.id}>
                        <td>
                          <button
                            type="button"
                            className="link-inline"
                            onClick={() => onOpenStation(st.row.id)}
                          >
                            <strong>{st.row.name}</strong>
                          </button>
                          <div className="dash-muted">{st.row.code}</div>
                        </td>
                        <td colSpan={7} className="dash-muted">
                          Резервуар ещё не привязан
                        </td>
                        <td>
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() => onOpenStation(st.row.id)}
                          >
                            Настроить
                          </button>
                        </td>
                      </tr>,
                    ];
                  }
                  return tanks.map((tank) => {
                    const bStatus = (tank.balance_status || "unknown") as
                      | "ok"
                      | "warn"
                      | "shortage"
                      | "surplus"
                      | "unknown";
                    return (
                      <tr key={tank.id}>
                        <td>
                          <button
                            type="button"
                            className="link-inline"
                            onClick={() => onOpenStation(st.row.id)}
                          >
                            <strong>{st.row.name}</strong>
                          </button>
                          <div className="dash-muted">
                            {st.row.code}
                            {!st.row.is_active ? " · скрыта" : ""}
                          </div>
                        </td>
                        <td>
                          <strong>{tank.code}</strong>
                          <div className="dash-muted">{liters(tank.capacity_liters)}</div>
                        </td>
                        <td>
                          {tank.opening_liters == null ? "—" : liters(tank.opening_liters)}
                        </td>
                        <td>{liters(tank.receipts_liters)}</td>
                        <td>{liters(tank.dispense_liters)}</td>
                        <td>
                          {tank.calculated_remainder_liters == null
                            ? "—"
                            : liters(tank.calculated_remainder_liters)}
                        </td>
                        <td>
                          {tank.actual_remainder_liters == null
                            ? "—"
                            : liters(tank.actual_remainder_liters)}
                        </td>
                        <td>
                          {tank.delta_liters != null ? (
                            <div>
                              <strong>{signedLiters(tank.delta_liters)}</strong>
                            </div>
                          ) : null}
                          {bStatus !== "unknown" ? (
                            <span className={`badge ${balBadge(bStatus)}`}>{balText(bStatus)}</span>
                          ) : (
                            <span className="badge">нет данных</span>
                          )}
                        </td>
                        <td>
                          <div style={{ display: "flex", gap: 6 }}>
                            <button
                              type="button"
                              className="btn secondary small"
                              onClick={() =>
                                openReconcileModal(
                                  st,
                                  tank.id,
                                  tank.code,
                                  tank.opening_liters,
                                  tank.receipts_liters,
                                  tank.dispense_liters,
                                  tank.actual_remainder_liters
                                )
                              }
                            >
                              Сверить
                            </button>
                            <button
                              type="button"
                              className="btn secondary small"
                              onClick={() => void loadSnapshots(st.row.id, st.row.name)}
                            >
                              Снимки
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  });
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      {snapshotsStation ? (
        <section className="dash-card">
          <div className="card-head-inline">
            <h3 style={{ margin: 0 }}>История снимков сверки: {snapshotsStation.name}</h3>
            <button
              type="button"
              className="btn secondary small"
              onClick={() => setSnapshotsStation(null)}
            >
              Закрыть
            </button>
          </div>
          {snapshotsLoading ? (
            <p className="dash-muted">Загрузка снимков…</p>
          ) : snapshots.length === 0 ? (
            <p className="dash-muted">Снимков сверки по этой АГЗС пока нет.</p>
          ) : (
            <div className="dash-table-wrap" style={{ marginTop: 10 }}>
              <table className="dash-table">
                <thead>
                  <tr>
                    <th>Создан</th>
                    <th>Период</th>
                    <th>Старт</th>
                    <th>Приход</th>
                    <th>ТРК</th>
                    <th>Расчёт</th>
                    <th>Факт</th>
                    <th>Δ / Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshots.map((snap) => {
                    const st = snap.status as "ok" | "warn" | "shortage" | "surplus";
                    return (
                      <tr key={snap.id}>
                        <td>{dateTime(snap.created_at)}</td>
                        <td className="dash-muted">
                          {dateTime(snap.period_start)} — {dateTime(snap.period_end)}
                        </td>
                        <td>{liters(snap.previous_remainder_liters)}</td>
                        <td>{liters(snap.receipts_liters)}</td>
                        <td>{liters(snap.dispense_liters)}</td>
                        <td>{liters(snap.calculated_remainder_liters)}</td>
                        <td>
                          {snap.actual_remainder_liters == null
                            ? "—"
                            : liters(snap.actual_remainder_liters)}
                        </td>
                        <td>
                          {snap.delta_liters != null ? (
                            <div>
                              <strong>{signedLiters(snap.delta_liters)}</strong>
                            </div>
                          ) : null}
                          <span className={`badge ${balBadge(st)}`}>{balText(st)}</span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      <section className="dash-card">
        <div className="card-head-inline">
          <h3 style={{ margin: 0 }}>Журнал событий сверки и инцидентов ({filteredEvents.length})</h3>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <select
              className="st-select"
              value={evStationFilter}
              aria-label="Фильтр событий по АГЗС"
              onChange={(e) => setEvStationFilter(e.target.value)}
            >
              <option value="all">Все АГЗС</option>
              {stations.map((st) => (
                <option key={st.id} value={st.id}>
                  {st.name}
                </option>
              ))}
            </select>
            <div className="mini-tabs">
              <button
                type="button"
                className={evFilter === "all" ? "active" : ""}
                onClick={() => setEvFilter("all")}
              >
                Все
              </button>
              <button
                type="button"
                className={evFilter === "open" ? "active" : ""}
                onClick={() => setEvFilter("open")}
              >
                Открытые ({openEventsCount})
              </button>
              <button
                type="button"
                className={evFilter === "resolved" ? "active" : ""}
                onClick={() => setEvFilter("resolved")}
              >
                Закрытые
              </button>
            </div>
          </div>
        </div>

        {filteredEvents.length === 0 ? (
          <p className="dash-muted" style={{ marginTop: 10 }}>
            Событий сверки по выбранным условиям нет.
          </p>
        ) : (
          <div className="dash-table-wrap" style={{ marginTop: 10 }}>
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
                {filteredEvents.map((ev) => {
                  const evStation = stations.find((s) => s.id === ev.station_id);
                  const isResolving = resolvingId === ev.id;
                  return (
                    <tr key={ev.id}>
                      <td>{dateTime(ev.detected_at)}</td>
                      <td>
                        {evStation ? (
                          <button
                            type="button"
                            className="link-inline"
                            onClick={() => onOpenStation(evStation.id)}
                          >
                            <strong>{evStation.name}</strong>
                          </button>
                        ) : (
                          <strong>{ev.station_id || "—"}</strong>
                        )}
                      </td>
                      <td>
                        <span
                          className={`badge ${ev.severity === "critical" ? "danger" : "warn"}`}
                        >
                          {eventTypeLabel(ev.event_type)} · {severityLabel(ev.severity)}
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
                          isResolving ? (
                            <form
                              className="inline-resolve-form"
                              onSubmit={(e) => {
                                e.preventDefault();
                                void confirmResolve(ev.id);
                              }}
                            >
                              <input
                                value={resolveNote}
                                onChange={(e) => setResolveNote(e.target.value)}
                                placeholder="Комментарий к закрытию…"
                                required
                              />
                              <button
                                type="submit"
                                className="btn small"
                                disabled={resolveBusy}
                              >
                                Подтвердить
                              </button>
                              <button
                                type="button"
                                className="btn secondary small"
                                disabled={resolveBusy}
                                onClick={() => setResolvingId(null)}
                              >
                                Отмена
                              </button>
                            </form>
                          ) : (
                            <button
                              type="button"
                              className="btn secondary small"
                              onClick={() => {
                                setResolvingId(ev.id);
                                setResolveNote("Проверено администратором");
                              }}
                            >
                              Закрыть
                            </button>
                          )
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

      {reconcileTarget ? (
        <div
          className="login-layer"
          role="dialog"
          aria-modal="true"
          onClick={() => {
            if (!reconcileBusy) setReconcileTarget(null);
          }}
        >
          <form
            className="login-card"
            onClick={(e) => e.stopPropagation()}
            onSubmit={(e) => {
              e.preventDefault();
              void submitReconcile();
            }}
          >
            <h2>Сверка баланса резервуара</h2>
            <p>
              <strong>{reconcileTarget.stationName}</strong> · резервуар{" "}
              <strong>{reconcileTarget.tankCode}</strong>
            </p>
            <label>
              Начальный остаток (старт), л
              <input
                inputMode="decimal"
                value={reconcileTarget.opening}
                onChange={(e) =>
                  setReconcileTarget({ ...reconcileTarget, opening: e.target.value })
                }
                required
              />
            </label>
            <label>
              Приход за период, л
              <input
                inputMode="decimal"
                value={reconcileTarget.receipts}
                onChange={(e) =>
                  setReconcileTarget({ ...reconcileTarget, receipts: e.target.value })
                }
                required
              />
            </label>
            <label>
              Отпуск через ТРК, л
              <input
                inputMode="decimal"
                value={reconcileTarget.dispense}
                onChange={(e) =>
                  setReconcileTarget({ ...reconcileTarget, dispense: e.target.value })
                }
                required
              />
            </label>
            <label>
              Фактический остаток по датчику, л
              <input
                inputMode="decimal"
                value={reconcileTarget.actual}
                onChange={(e) =>
                  setReconcileTarget({ ...reconcileTarget, actual: e.target.value })
                }
              />
            </label>
            <label>
              Начало периода
              <input
                type="datetime-local"
                value={reconcileTarget.periodStart}
                onChange={(e) =>
                  setReconcileTarget({ ...reconcileTarget, periodStart: e.target.value })
                }
                required
              />
            </label>
            <label>
              Конец периода
              <input
                type="datetime-local"
                value={reconcileTarget.periodEnd}
                onChange={(e) =>
                  setReconcileTarget({ ...reconcileTarget, periodEnd: e.target.value })
                }
                required
              />
            </label>
            {reconcileError ? <p className="tank-error">{reconcileError}</p> : null}
            <div className="login-actions">
              <button
                type="button"
                className="btn secondary"
                disabled={reconcileBusy}
                onClick={() => setReconcileTarget(null)}
              >
                Отмена
              </button>
              <button type="submit" className="btn" disabled={reconcileBusy}>
                {reconcileBusy ? "Сверяем…" : "Выполнить сверку"}
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}
