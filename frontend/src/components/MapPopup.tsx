import type { StationDetail, TruckDetail } from "../types";
import { fiscalCheck } from "../sim/engine";
import { useSim } from "../sim/SimContext";
import { supplyForFactory, supplyForStation, supplyForTruck } from "../sim/supply";
import { celsius, dateTime, fiscalBadge, fiscalText, liters, vsBase } from "../format";
import { SRC } from "../sources";
import StationBalanceCard from "./StationBalanceCard";

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
  onOpenSupply,
}: {
  truck?: TruckDetail | null;
  station?: StationDetail | null;
  factoryName?: string | null;
  onClose: () => void;
  onOpenStation?: (id: string) => void;
  onOpenSupply?: (id: string) => void;
}) {
  const { state } = useSim();
  const truckSupply = truck ? supplyForTruck(state, truck.id) : null;
  const stationSupply = station ? supplyForStation(state, station.id) : null;
  const factory = factoryName ? state.factories.find((f) => f.name === factoryName) : null;
  const factorySupply = factory ? supplyForFactory(state, factory.id) : null;
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
            <dd>{liters(truckSupply?.delivered_liters ?? truck.cargo_volume_liters)}</dd>
            {truckSupply?.delivered_liters != null && (
              <>
                <dt>К отгрузке</dt>
                <dd>{vsBase(truckSupply.delivered_liters, truckSupply.shipped_liters, "отгрузке")}</dd>
              </>
            )}
            <dt>Куда</dt>
            <dd>{truck.destination_name ?? "—"}</dd>
            <dt>GPS</dt>
            <dd>
              {truck.lat != null && truck.lon != null
                ? `${truck.lat.toFixed(4)}, ${truck.lon.toFixed(4)}`
                : "—"}
            </dd>
            <dt>Температура</dt>
            <dd>{celsius(truckSupply?.truck_temp_c)}</dd>
          </dl>
          <p className="src-line">
            <span>Источник</span>
            {SRC.gps} · {SRC.quantity} · {SRC.temperature}
          </p>
          {truckSupply && onOpenSupply && (
            <button type="button" className="btn small map-popup-more" onClick={() => onOpenSupply(truckSupply.supply_id)}>
              Поставка {truckSupply.supply_id} →
            </button>
          )}
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
          {stationSupply && onOpenSupply && (
            <button
              type="button"
              className="btn secondary small map-popup-more"
              onClick={() => onOpenSupply(stationSupply.supply_id)}
            >
              Поставка {stationSupply.supply_id} →
            </button>
          )}
        </>
      )}

      {factoryName && !truck && !station && (
        <>
          <p className="kicker">Завод</p>
          <h2>{factoryName}</h2>
          {factorySupply ? (
            <>
              <p className="stage-vol">
                Отгружено: <strong>{liters(factorySupply.shipped_liters)}</strong>
              </p>
              <dl className="kv">
                <dt>Дата и время</dt>
                <dd>{dateTime(factorySupply.shipped_at)}</dd>
                <dt>Накладная</dt>
                <dd>{factorySupply.waybill}</dd>
                <dt>Температура</dt>
                <dd>{celsius(factorySupply.shipped_temp_c)}</dd>
              </dl>
              <p className="src-line">
                <span>Источник</span>
                {SRC.factory}
              </p>
              {onOpenSupply && (
                <button
                  type="button"
                  className="btn small map-popup-more"
                  onClick={() => onOpenSupply(factorySupply.supply_id)}
                >
                  Поставка {factorySupply.supply_id} →
                </button>
              )}
            </>
          ) : (
            <p className="map-popup-note">Точка отгрузки LPG · Жанаозен</p>
          )}
        </>
      )}
    </aside>
  );
}
