import type { StationDetail } from "../types";
import { stationBalance } from "../sim/engine";
import { balBadge, balText, liters, signedLiters } from "../format";

/** Три потока: доставлено · хранилище · колонки */
export default function StationBalanceCard({
  station,
  compact = false,
}: {
  station: StationDetail;
  compact?: boolean;
}) {
  const bal = stationBalance(station);

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
          {!compact && <em>факт · датчик / замер</em>}
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
        <span className={`badge ${balBadge(bal.status)}`}>
          Δ {Math.abs(bal.delta) < 0.5 ? "0 л" : signedLiters(bal.delta)} · {balText(bal.status)}
        </span>
      </div>
    </div>
  );
}
