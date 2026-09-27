import { useMemo } from "react";
import { stationBalance, stationHourly } from "../sim/engine";
import { useSim } from "../sim/SimContext";
import { balBadge, balText, liters, signedLiters, timeHM } from "../format";
import { BarChart, LineChart } from "./Charts";
import FiscalCheckTable from "./FiscalCheckTable";
import StationBalanceCard from "./StationBalanceCard";

export default function StationDetailPage({
  stationId,
  onBack,
}: {
  stationId: string;
  onBack: () => void;
}) {
  const { state } = useSim();
  const station = state.stations.find((s) => s.detail.id === stationId)?.detail;

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
  const fillPct = station.capacity_liters
    ? Math.min(100, Math.round((bal.storage_actual / station.capacity_liters) * 100))
    : 0;
  const labels = hourly.map((h) => `${String(h.hour).padStart(2, "0")}:00`);

  return (
    <div className="dash">
      <button type="button" className="btn secondary small dash-back" onClick={onBack}>
        ← Все АГЗС
      </button>

      <header className="st-head">
        <div>
          <p className="kicker">{station.code}</p>
          <h2>{station.name}</h2>
          <span className="dash-muted">{station.address}</span>
        </div>
        <span className={`badge ${balBadge(bal.status)}`}>
          Δ {signedLiters(bal.delta)} · {balText(bal.status)}
        </span>
      </header>

      <section className="dash-section">
        <StationBalanceCard station={station} />
      </section>

      <section className="dash-section">
        <h3>Сверка колонок с КГД</h3>
        <FiscalCheckTable station={station} />
      </section>

      <div className="st-grid">
        <section className="dash-card st-wide">
          <h3>Остаток в хранилище за сутки</h3>
          <LineChart
            labels={labels}
            series={[
              { name: "Факт (датчик)", color: "var(--sea)", values: hourly.map((h) => h.actual) },
              {
                name: "Книга (доставки − колонки)",
                color: "var(--dust)",
                values: hourly.map((h) => h.book),
                dashed: true,
              },
            ]}
          />
        </section>

        <section className="dash-card">
          <h3>Заполнение ёмкости</h3>
          <div className="gauge">
            <div className="gauge-bar">
              <i style={{ height: `${fillPct}%` }} />
            </div>
            <div className="gauge-meta">
              <strong>{fillPct}%</strong>
              <span>
                {liters(bal.storage_actual)} из {liters(station.capacity_liters)}
              </span>
              <span className="dash-muted">
                {station.tanks[0]?.has_electronic_sensor ? "электронный датчик" : "ручной замер"}
              </span>
            </div>
          </div>
        </section>

        <section className="dash-card st-wide">
          <h3>Через колонки по часам</h3>
          <BarChart
            labels={labels}
            series={[{ name: "Колонки", color: "var(--sea)", values: hourly.map((h) => h.pumps) }]}
          />
        </section>

        <section className="dash-card">
          <h3>Расход</h3>
          <dl className="kv">
            <dt>Сегодня</dt>
            <dd>{liters(station.consumption_day_liters)}</dd>
            <dt>Неделя</dt>
            <dd>{liters(station.consumption_week_liters)}</dd>
            <dt>Месяц</dt>
            <dd>{liters(station.consumption_month_liters)}</dd>
            <dt>Заправок сегодня</dt>
            <dd>{station.sales_day_count}</dd>
            <dt>Средняя заправка</dt>
            <dd>{station.avg_fill_liters} л</dd>
          </dl>
        </section>

        <section className="dash-card">
          <h3>Доставки газовозами</h3>
          {station.recent_deliveries.length === 0 ? (
            <p className="dash-muted">Сегодня доставок не было</p>
          ) : (
            <ul className="st-events">
              {station.recent_deliveries.map((d, i) => (
                <li key={`${d.occurred_at}-${i}`}>
                  <strong>{liters(d.liters)}</strong>
                  <span>{d.plate}</span>
                  <em>{timeHM(d.occurred_at)}</em>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="dash-card">
          <h3>Последние заправки</h3>
          <ul className="st-events">
            {station.recent_fills.map((f, i) => (
              <li key={`${f.occurred_at}-${i}`}>
                <strong>{f.liters} л</strong>
                <span>колонка</span>
                <em>{timeHM(f.occurred_at)}</em>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
