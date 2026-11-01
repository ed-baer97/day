import { useMemo, useState } from "react";
import { fiscalCheck, stationBalance, stationHourly } from "../sim/engine";
import { useSim } from "../sim/SimContext";
import {
  balBadge,
  balText,
  celsius,
  columnLabel,
  dateTime,
  fiscalBadge,
  linkText,
  liters,
  signedLiters,
  stationRegion,
  tenge,
  timeHM,
} from "../format";
import { SRC } from "../sources";
import { BarChart } from "./Charts";
import ColumnCard, { type ColumnOperation } from "./ColumnCard";
import FiscalCheckTable from "./FiscalCheckTable";
import StationBalanceCard from "./StationBalanceCard";
import TankDeviceRows from "./TankDeviceRows";

type DetailTab = "overview" | "pumps" | "tanks" | "history";

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
  const { state, resolveSimEvent } = useSim();
  const [tab, setTab] = useState<DetailTab>("overview");

  const stationIndex = state.stations.findIndex((s) => s.detail.id === stationId);
  const station = stationIndex >= 0 ? state.stations[stationIndex].detail : undefined;

  const prevStation =
    stationIndex > 0
      ? state.stations[stationIndex - 1].detail
      : state.stations[state.stations.length - 1]?.detail;
  const nextStation =
    stationIndex >= 0 && stationIndex < state.stations.length - 1
      ? state.stations[stationIndex + 1].detail
      : state.stations[0]?.detail;

  const hourly = useMemo(
    () => (station ? stationHourly(station, state.simTimeMs) : []),
    [station, state.simTimeMs]
  );

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

  const bal = stationBalance(station);
  const fc = fiscalCheck(station);
  const tank = station.tanks[0];
  const cap = tank?.capacity_liters ?? station.capacity_liters ?? 0;
  const stored = tank?.actual_remainder_liters ?? bal.storage_actual;
  const fillPct = cap ? Math.min(100, Math.round((stored / cap) * 100)) : 0;
  const region = stationRegion(station);

  const stationSupplies = state.supplies.filter((s) => s.station_id === station.id);
  const stationEvents = state.events.filter((e) => e.station_id === station.id);

  return (
    <div className="dash">
      <div className="st-detail-nav">
        <button type="button" className="btn secondary small" onClick={onBack}>
          ← Все АГЗС ({state.stations.length})
        </button>

        <div className="st-Detail-switcher">
          {onSelectStation && prevStation && (
            <button
              type="button"
              className="btn secondary small"
              onClick={() => onSelectStation(prevStation.id)}
              title={`Предыдущая: ${prevStation.name}`}
            >
              ‹ Пред.
            </button>
          )}
          {onSelectStation && (
            <select
              className="st-select"
              value={station.id}
              aria-label="Выбрать другую АГЗС"
              onChange={(e) => onSelectStation(e.target.value)}
            >
              {state.stations.map((s) => (
                <option key={s.detail.id} value={s.detail.id}>
                  {s.detail.name} ({s.detail.code} · {stationRegion(s.detail)})
                </option>
              ))}
            </select>
          )}
          {onSelectStation && nextStation && (
            <button
              type="button"
              className="btn secondary small"
              onClick={() => onSelectStation(nextStation.id)}
              title={`Следующая: ${nextStation.name}`}
            >
              След. ›
            </button>
          )}
        </div>

        <div className="st-detail-actions">
          {onOpenMap && (
            <button
              type="button"
              className="btn secondary small"
              onClick={() => onOpenMap(station.id)}
            >
              Показать на карте
            </button>
          )}
          {onOpenAdmin && (
            <button
              type="button"
              className="btn small"
              onClick={() => onOpenAdmin(station.id)}
            >
              Настроить в админке
            </button>
          )}
        </div>
      </div>

      <header className="st-head">
        <div>
          <p className="kicker">
            {station.code} · {region} · {station.lat.toFixed(4)}, {station.lon.toFixed(4)}
          </p>
          <h2>{station.name}</h2>
          <span className="dash-muted">
            {station.address} · Розничная цена: <strong>{tenge(station.price_kzt_per_liter)}/л</strong>
          </span>
        </div>
        <div className="st-row-badges">
          <span className={`badge ${balBadge(bal.status)}`}>
            Баланс ёмкости: Δ {signedLiters(bal.delta)} · {balText(bal.status)}
          </span>
          <span className={`badge ${fiscalBadge(fc.status)}`}>
            Сверка КГД: {fc.status === "ok" ? "сходится" : `расхождение ${liters(fc.gap_liters)}`}
          </span>
        </div>
      </header>

      <div className="admin-tabs" role="tablist" style={{ marginBottom: 20 }}>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "overview"}
          className={tab === "overview" ? "active" : ""}
          onClick={() => setTab("overview")}
        >
          Сводка и баланс
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "pumps"}
          className={tab === "pumps" ? "active" : ""}
          onClick={() => setTab("pumps")}
        >
          Колонки и КГД ({station.pumps.length})
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "tanks"}
          className={tab === "tanks" ? "active" : ""}
          onClick={() => setTab("tanks")}
        >
          Резервуары и датчики ({station.tanks.length})
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "history"}
          className={tab === "history" ? "active" : ""}
          onClick={() => setTab("history")}
        >
          Поставки и инциденты ({stationSupplies.length + stationEvents.length})
        </button>
      </div>

      {tab === "overview" && (
        <>
          <section className="dash-section">
            <StationBalanceCard station={station} />
          </section>

          <div className="st-grid">
            <section className="dash-card">
              <h3>Почасовой отпуск газа через колонки (сегодня)</h3>
              <BarChart
                labels={hourly.map((r) => `${String(r.hour).padStart(2, "0")}`)}
                series={[
                  { name: "Через колонки", color: "var(--sea)", values: hourly.map((r) => r.pumps) },
                  { name: "Слив поставок", color: "var(--dust)", values: hourly.map((r) => r.delivered) },
                ]}
              />
            </section>

            <section className="dash-card">
              <h3>Цифровой уровень резервуара</h3>
              <div className="gauge">
                <div className="gauge-bar">
                  <i
                    style={{
                      height: `${fillPct}%`,
                      background:
                        fillPct < 25
                          ? "var(--coral)"
                          : "linear-gradient(0deg, var(--sea-2, var(--sea)), var(--sea))",
                    }}
                  />
                </div>
                <div className="gauge-meta">
                  <strong>{fillPct}%</strong>
                  <span>
                    {liters(stored)} из {liters(cap)}
                  </span>
                  <span>{tank ? `резервуар ${tank.code}` : "резервуар"}</span>
                  <span>Температура: {celsius(tank?.temperature_c)}</span>
                  <span className="dash-muted">{tank ? dateTime(tank.last_measured_at) : "—"}</span>
                  <span className="dash-muted">
                    {tank?.phone_label ?? SRC.phone}
                    {tank ? ` · связь ${linkText(tank.link_quality)}` : ""}
                  </span>
                  <span className="src-line">
                    <span>Источник</span>
                    {SRC.srg} · {SRC.rochester} · {SRC.bluetooth}
                  </span>
                </div>
              </div>
            </section>
          </div>
        </>
      )}

      {tab === "pumps" && (
        <>
          <section className="dash-section">
            <h3>Сверка колонок с ОФД и КГД</h3>
            <FiscalCheckTable station={station} />
          </section>

          <section className="dash-section">
            <h3>Топливораздаточные колонки (ТРК)</h3>
            <div className="col-grid">
              {station.pumps.map((p) => {
                const title = columnLabel(p.code);
                const pouring = p.pouring_liters > 0.5;
                const own = station.recent_fills.filter((f) => f.pump_code === title);
                const last = own[0];
                const operations: ColumnOperation[] = [
                  ...(pouring
                    ? [
                        {
                          id: `${p.id}-pour`,
                          pump: title,
                          liters: p.pouring_liters,
                          price: station.price_kzt_per_liter,
                          amount: Math.round(p.pouring_liters * station.price_kzt_per_liter),
                          time: "сейчас",
                          state: "pouring" as const,
                          link: p.link_status,
                        },
                      ]
                    : []),
                  ...own.map((f, i) => ({
                    id: `${p.id}-f${i}`,
                    pump: f.pump_code,
                    liters: f.liters,
                    price: f.price_kzt_per_liter,
                    amount: Math.round(f.liters * f.price_kzt_per_liter),
                    time: timeHM(f.occurred_at),
                    state: "done" as const,
                    link: p.link_status,
                  })),
                ];
                return (
                  <ColumnCard
                    key={p.id}
                    title={title}
                    dispensedLabel="Отпущено сегодня"
                    dispensed={p.counter_liters}
                    operation={pouring ? "налив" : "нет"}
                    volume={pouring ? p.pouring_liters : last?.liters ?? null}
                    pricePerLiter={station.price_kzt_per_liter}
                    time={pouring ? "сейчас" : last ? timeHM(last.occurred_at) : "—"}
                    link={p.link_status === "ok" ? "есть" : "нет связи"}
                    operations={operations}
                  />
                );
              })}
            </div>
          </section>
        </>
      )}

      {tab === "tanks" && (
        <section className="dash-section">
          <h3>Резервуары, контроллеры Shelly, калибровка и ручной ввод</h3>
          <TankDeviceRows stationId={station.id} />
        </section>
      )}

      {tab === "history" && (
        <>
          <section className="dash-section">
            <h3>Инциденты и уведомления по станции</h3>
            {stationEvents.length === 0 ? (
              <p className="empty">По данной АГЗС активных или архивных инцидентов нет.</p>
            ) : (
              <div className="dash-table-wrap">
                <table className="dash-table">
                  <thead>
                    <tr>
                      <th>Время</th>
                      <th>Событие</th>
                      <th>Описание</th>
                      <th>Отклонение</th>
                      <th>Статус</th>
                      <th>Действие</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stationEvents.map((ev) => (
                      <tr key={ev.id}>
                        <td className="dash-muted">{dateTime(ev.detected_at)}</td>
                        <td>
                          <strong>{ev.title}</strong>
                        </td>
                        <td>{ev.description}</td>
                        <td>
                          {ev.delta_liters != null ? signedLiters(ev.delta_liters) : "—"}
                        </td>
                        <td>
                          <span className={`badge ${!ev.is_resolved ? "danger" : "ok"}`}>
                            {!ev.is_resolved ? "Открыт" : "Закрыт"}
                          </span>
                        </td>
                        <td>
                          {!ev.is_resolved ? (
                            <button
                              type="button"
                              className="btn secondary small"
                              onClick={() => resolveSimEvent(ev.id)}
                            >
                              Закрыть инцидент
                            </button>
                          ) : (
                            <span className="dash-muted">Проверено</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="dash-section">
            <h3>Поставки на АГЗС</h3>
            {stationSupplies.length === 0 ? (
              <p className="empty">Записей о поставках по этой станции пока нет.</p>
            ) : (
              <div className="dash-table-wrap">
                <table className="dash-table">
                  <thead>
                    <tr>
                      <th>Партия / ТТН</th>
                      <th>Завод</th>
                      <th>Газовоз</th>
                      <th>Отгружено</th>
                      <th>Принято в резервуар</th>
                      <th>Статус</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stationSupplies.map((sp) => (
                      <tr key={sp.supply_id}>
                        <td>
                          <strong>{sp.waybill || sp.supply_id}</strong>
                        </td>
                        <td>{sp.factory_name}</td>
                        <td>{sp.plate}</td>
                        <td>{liters(sp.shipped_liters)}</td>
                        <td>
                          {sp.accepted_liters != null
                            ? liters(sp.accepted_liters)
                            : "В пути"}
                        </td>
                        <td>
                          <span className="badge ok">{sp.status}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
