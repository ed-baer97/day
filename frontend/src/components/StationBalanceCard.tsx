import type { StationBalance, StationDetail } from "../types";
import { stationBalance, withMeasured } from "../sim/engine";

function liters(v: number) {
  return `${Math.round(v).toLocaleString("ru-RU")} л`;
}

function deltaLabel(d: number) {
  if (Math.abs(d) < 0.5) return "0 л";
  const sign = d > 0 ? "+" : "";
  return `${sign}${Math.round(d).toLocaleString("ru-RU")} л`;
}

function statusBadge(status: StationBalance["status"]) {
  if (status === "ok") return "ok";
  if (status === "warn") return "warn";
  return "danger";
}

function statusText(status: StationBalance["status"]) {
  if (status === "ok") return "сходится";
  if (status === "warn") return "погрешность";
  if (status === "shortage") return "недостача";
  return "излишек";
}

/** Три потока: доставлено · хранилище · колонки */
export default function StationBalanceCard({
  station,
  compact = false,
  measuredLiters = null,
}: {
  station: StationDetail;
  compact?: boolean;
  measuredLiters?: number | null;
}) {
  const bal = withMeasured(stationBalance(station), measuredLiters);

  return (
    <div className={`bal-card${compact ? " compact" : ""}`}>
      <div className="bal-triad">
        <div className="bal-cell">
          <span>Доставлено</span>
          <strong>{liters(bal.delivered)}</strong>
          {!compact && <em>газовозы · {station.delivery_count_day} рейс.</em>}
        </div>
        <div className="bal-cell">
          <span>В хранилище</span>
          <strong>{liters(bal.storage_actual)}</strong>
          {!compact && <em>{measuredLiters != null ? "факт · датчик" : "факт · датчик / замер"}</em>}
        </div>
        <div className="bal-cell">
          <span>Через колонки</span>
          <strong>{liters(bal.through_pumps)}</strong>
          {!compact && (
            <em>
              {station.sales_day_count} запр. · ~{station.avg_fill_liters} л
            </em>
          )}
        </div>
      </div>

      <div className="bal-eq">
        <span className="bal-eq-formula">
          {liters(bal.opening)} + {liters(bal.delivered)} − {liters(bal.through_pumps)} ={" "}
          <strong>{liters(bal.book_remainder)}</strong>
          <em> книга</em>
        </span>
        <span className={`badge ${statusBadge(bal.status)}`}>
          Δ {deltaLabel(bal.delta)} · {statusText(bal.status)}
        </span>
      </div>
    </div>
  );
}
