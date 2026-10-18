import { stationBalance } from "../sim/engine";
import { useSim } from "../sim/SimContext";
import { balBadge, balText, celsius, columnLabel, dateTime, linkText, liters, signedLiters, timeHM } from "../format";
import { SRC } from "../sources";
import ColumnCard, { type ColumnOperation } from "./ColumnCard";
import FiscalCheckTable from "./FiscalCheckTable";
import StationBalanceCard from "./StationBalanceCard";
import TankDeviceRows from "./TankDeviceRows";

export default function StationDetailPage({
  stationId,
  onBack,
}: {
  stationId: string;
  onBack: () => void;
}) {
  const { state } = useSim();
  const station = state.stations.find((s) => s.detail.id === stationId)?.detail;

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
        <h3>Резервуары</h3>
        <TankDeviceRows stationId={station.id} />
      </section>

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
      </div>
    </div>
  );
}
