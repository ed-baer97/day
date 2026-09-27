import { useMemo } from "react";
import { fiscalCheck, fleetStats, stationBalance, stationHourly } from "../sim/engine";
import { useSim } from "../sim/SimContext";
import {
  balBadge,
  balText,
  fiscalBadge,
  fiscalText,
  liters,
  phaseLabel,
  shortStationName,
  signedLiters,
  tenge,
} from "../format";
import { BarChart } from "./Charts";
import StationDetailPage from "./StationDetailPage";

export default function Dashboard({
  stationId,
  onOpenStation,
}: {
  stationId: string | null;
  onOpenStation: (id: string | null) => void;
}) {
  if (stationId) {
    return <StationDetailPage stationId={stationId} onBack={() => onOpenStation(null)} />;
  }
  return <Overview onOpenStation={onOpenStation} />;
}

function Overview({ onOpenStation }: { onOpenStation: (id: string) => void }) {
  const { state } = useSim();
  const stats = useMemo(() => fleetStats(state), [state]);

  const stations = useMemo(
    () =>
      state.stations
        .map((s) => ({ d: s.detail, bal: stationBalance(s.detail), fc: fiscalCheck(s.detail) }))
        .sort(
          (a, b) =>
            Math.abs(b.bal.delta) + b.fc.gap_liters - (Math.abs(a.bal.delta) + a.fc.gap_liters)
        ),
    [state.stations]
  );

  const hourlyTotal = useMemo(() => {
    const perStation = state.stations.map((s) => stationHourly(s.detail, state.simTimeMs));
    const hours = perStation[0]?.length ?? 0;
    return Array.from({ length: hours }, (_, h) =>
      perStation.reduce((sum, rows) => sum + (rows[h]?.pumps ?? 0), 0)
    );
  }, [state.stations, state.simTimeMs]);

  const mismatch = stations.filter((s) => s.bal.status !== "ok").length;

  return (
    <div className="dash">
      <header className="dash-hero">
        <p className="kicker">Сводка за сутки</p>
        <h2>Доставки и сверка АГЗС</h2>
      </header>

      <div className="dash-kpis">
        <div className="dash-kpi">
          <span>Доставлено</span>
          <strong>{liters(stats.delivered_liters_day)}</strong>
          <em>{stats.delivery_trips_day} рейсов</em>
        </div>
        <div className="dash-kpi">
          <span>Через колонки</span>
          <strong>{liters(stats.sold_liters_day)}</strong>
          <em>{stats.fills_day} заправок</em>
        </div>
        <div className="dash-kpi">
          <span>В работе</span>
          <strong>{stats.trucks_in_transit}</strong>
          <em>из {state.trucks.length} газовозов</em>
        </div>
        <div className="dash-kpi">
          <span>Расхождения в хранилище</span>
          <strong className={mismatch ? "text-danger" : ""}>{mismatch}</strong>
          <em>из {stats.stations_active} АГЗС</em>
        </div>
        <div className="dash-kpi">
          <span>КГД не видит</span>
          <strong className={stats.gap_liters ? "text-danger" : ""}>{liters(stats.gap_liters)}</strong>
          <em>
            {tenge(stats.gap_kzt)} · без чека {liters(stats.unreceipted_liters)} · ККМ офлайн{" "}
            {stats.kkm_offline}
          </em>
        </div>
      </div>

      <div className="dash-charts">
        <section className="dash-card">
          <h3>Доставлено и продано по АГЗС</h3>
          <BarChart
            labels={stations.map((s) => shortStationName(s.d.name))}
            series={[
              { name: "Доставлено", color: "var(--dust)", values: stations.map((s) => s.bal.delivered) },
              { name: "Через колонки", color: "var(--sea)", values: stations.map((s) => s.bal.through_pumps) },
            ]}
          />
        </section>
        <section className="dash-card">
          <h3>Через колонки по часам · все АГЗС</h3>
          <BarChart
            labels={hourlyTotal.map((_, h) => `${String(h).padStart(2, "0")}`)}
            series={[{ name: "Колонки", color: "var(--sea)", values: hourlyTotal }]}
          />
        </section>
      </div>

      <section className="dash-section">
        <h3>АГЗС</h3>
        <ul className="st-list">
          {stations.map(({ d, bal, fc }) => {
            const fill = d.capacity_liters
              ? Math.min(100, Math.round((bal.storage_actual / d.capacity_liters) * 100))
              : 0;
            return (
              <li key={d.id}>
                <button type="button" className="st-row" onClick={() => onOpenStation(d.id)}>
                  <div className="st-row-main">
                    <strong>{d.name}</strong>
                    <span>{d.code}</span>
                  </div>
                  <div className="st-row-fill">
                    <div className="fill-bar">
                      <i style={{ width: `${fill}%` }} />
                    </div>
                    <span>
                      {liters(bal.storage_actual)} · {fill}%
                    </span>
                  </div>
                  <div className="st-row-num">
                    <strong>{liters(bal.delivered)}</strong>
                    <span>доставлено · {d.delivery_count_day}</span>
                  </div>
                  <div className="st-row-num">
                    <strong>{liters(bal.through_pumps)}</strong>
                    <span>колонки · {d.sales_day_count} запр.</span>
                  </div>
                  <div className="st-row-badges">
                    <span className={`badge ${balBadge(bal.status)}`}>
                      ёмкость {bal.status === "ok" ? balText(bal.status) : signedLiters(bal.delta)}
                    </span>
                    <span className={`badge ${fiscalBadge(fc.status)}`}>
                      КГД {fc.status === "ok" ? "сходится" : `−${liters(fc.gap_liters)}`}
                    </span>
                  </div>
                  <span className="st-row-chevron" aria-hidden>
                    ›
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="dash-section">
        <h3>Сверка колонок с КГД</h3>
        <div className="dash-table-wrap">
          <table className="dash-table">
            <thead>
              <tr>
                <th>АГЗС</th>
                <th>Счётчики ТРК</th>
                <th>Чеки ККМ</th>
                <th>ОФД → КГД</th>
                <th>Расхождение</th>
              </tr>
            </thead>
            <tbody>
              {stations.map(({ d, fc }) => (
                <tr key={d.id} className="dash-row-link" onClick={() => onOpenStation(d.id)}>
                  <td>
                    <strong>{d.name}</strong>
                    <div className="dash-muted">{d.pumps.length} ТРК</div>
                  </td>
                  <td>
                    {liters(fc.counter_liters)}
                    <div className="dash-muted">{fc.fills} заправок</div>
                  </td>
                  <td>
                    {liters(fc.kkm_liters)}
                    <div className="dash-muted">{fc.kkm_receipts} чеков</div>
                  </td>
                  <td>
                    {liters(fc.ofd_liters)}
                    <div className="dash-muted">{tenge(fc.ofd_amount_kzt)}</div>
                  </td>
                  <td>
                    <span className={`badge ${fiscalBadge(fc.status)}`}>
                      {fc.status === "ok"
                        ? fiscalText(fc.status)
                        : `${fiscalText(fc.status)} · ${liters(fc.gap_liters)}`}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="dash-section">
        <h3>Газовозы</h3>
        <div className="dash-table-wrap">
          <table className="dash-table">
            <thead>
              <tr>
                <th>Номер</th>
                <th>Статус</th>
                <th>Груз</th>
                <th>Маршрут</th>
                <th>Перевозчик</th>
              </tr>
            </thead>
            <tbody>
              {state.trucks.map((t) => (
                <tr key={t.detail.id}>
                  <td>
                    <strong>{t.detail.plate_number}</strong>
                  </td>
                  <td>
                    <span className="badge ok">{phaseLabel(t.phase)}</span>
                  </td>
                  <td>{liters(t.cargo)}</td>
                  <td className="dash-muted">
                    {t.detail.origin_name} → {t.detail.destination_name}
                  </td>
                  <td className="dash-muted">{t.detail.carrier_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
