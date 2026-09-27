import type { StationDetail, TruckDetail } from "../types";
import { fiscalCheck } from "../sim/engine";
import { fiscalBadge, fiscalText } from "../format";
import StationBalanceCard from "./StationBalanceCard";

function liters(v?: number | null) {
  if (v == null || Number.isNaN(v)) return "—";
  return `${Math.round(v).toLocaleString("ru-RU")} л`;
}

function phaseLabel(status?: string | null) {
  const map: Record<string, string> = {
    loading: "погрузка",
    routing: "маршрут",
    in_transit: "в пути",
    arrived: "прибыл",
    unloading: "слив",
    idle: "ожидание",
  };
  return status ? map[status] ?? status : "—";
}

export default function MapPopup({
  truck,
  station,
  factoryName,
  onClose,
  onOpenStation,
}: {
  truck?: TruckDetail | null;
  station?: StationDetail | null;
  factoryName?: string | null;
  onClose: () => void;
  onOpenStation?: (id: string) => void;
}) {
  if (!truck && !station && !factoryName) return null;

  return (
    <aside className="map-popup" role="dialog" aria-label="Краткая информация">
      <button type="button" className="map-popup-close" onClick={onClose} aria-label="Закрыть">
        ×
      </button>

      {truck && (
        <>
          <p className="kicker">Газовоз</p>
          <h2>{truck.plate_number}</h2>
          <dl className="kv">
            <dt>Статус</dt>
            <dd>
              <span className="badge ok">{phaseLabel(truck.status)}</span>
            </dd>
            <dt>Груз</dt>
            <dd>{liters(truck.cargo_volume_liters)}</dd>
            <dt>Куда</dt>
            <dd>{truck.destination_name ?? "—"}</dd>
            <dt>Перевозчик</dt>
            <dd>{truck.carrier_name ?? "—"}</dd>
          </dl>
        </>
      )}

      {station && (
        <>
          <p className="kicker">АГЗС</p>
          <h2>{station.name}</h2>
          <StationBalanceCard station={station} compact />
          {(() => {
            const fc = fiscalCheck(station);
            return (
              <div className="map-popup-fiscal">
                <span>ТРК → ККМ → ОФД → КГД</span>
                <span className={`badge ${fiscalBadge(fc.status)}`}>
                  {fc.status === "ok"
                    ? fiscalText(fc.status)
                    : `${fiscalText(fc.status)} · ${liters(fc.gap_liters)}`}
                </span>
              </div>
            );
          })()}
          {onOpenStation && (
            <button
              type="button"
              className="btn small map-popup-more"
              onClick={() => onOpenStation(station.id)}
            >
              Подробнее →
            </button>
          )}
        </>
      )}

      {factoryName && !truck && !station && (
        <>
          <p className="kicker">Завод</p>
          <h2>{factoryName}</h2>
          <p className="map-popup-note">Точка отгрузки LPG · Жанаозен</p>
        </>
      )}
    </aside>
  );
}
