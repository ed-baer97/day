import { useMemo } from "react";
import { stationBalance, stationHourly } from "../sim/engine";
import { useSim } from "../sim/SimContext";
import { balBadge, balText, celsius, columnLabel, dateTime, linkText, liters, signedLiters, timeHM } from "../format";
import { SRC } from "../sources";
import { BarChart, LineChart } from "./Charts";
import ColumnCard, { type ColumnOperation } from "./ColumnCard";
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
  const tank = station.tanks[0];
  const cap = tank?.capacity_liters ?? station.capacity_liters ?? 0;
  const stored = tank?.actual_remainder_liters ?? bal.storage_actual;
  const fillPct = cap ? Math.min(100, Math.round((stored / cap) * 100)) : 0;
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
        <h3>Колонки</h3>
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
          <h3>Цифровой уровень резервуара</h3>
          <div className="gauge">
            <div className="gauge-bar">
              <i style={{ height: `${fillPct}%` }} />
            </div>
            <div className="gauge-meta">
              <strong>{fillPct}%</strong>
              <span>
                {liters(stored)} из {liters(cap)}
              </span>
              <span>{tank ? `резервуар ${tank.code}` : "резервуар"}</span>
              <span>{celsius(tank?.temperature_c)}</span>
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
                <span>{f.pump_code}</span>
                <em>{timeHM(f.occurred_at)}</em>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
