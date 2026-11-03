import type { CatalogStation, CatalogTruck } from "../api/client";
import { liters, phaseLabel } from "../format";
import { SensorStatus, usePublicLevels } from "../liveLevels";

export default function MapPopup({
  truck,
  station,
  onClose,
  onOpenStation,
}: {
  truck?: CatalogTruck | null;
  station?: CatalogStation | null;
  onClose: () => void;
  onOpenStation?: (id: string) => void;
}) {
  const { byCode } = usePublicLevels();
  if (!truck && !station) return null;
  const live = station ? byCode.get(station.code) : undefined;

  return (
    <aside className="map-popup" role="dialog" aria-label="Краткая информация">
      <button type="button" className="map-popup-close" onClick={onClose} aria-label="Закрыть">
        ×
      </button>

      {truck ? (
        <>
          <p className="kicker">Газовоз</p>
          <h2>{truck.plate_number}</h2>
          <dl className="kv">
            <dt>Статус</dt>
            <dd>{phaseLabel(truck.status)}</dd>
            <dt>Вместимость</dt>
            <dd>{liters(truck.capacity_liters)}</dd>
            <dt>Перевозчик</dt>
            <dd>{truck.carrier_name || "не указан"}</dd>
            <dt>Координаты</dt>
            <dd>
              {truck.lat != null && truck.lon != null
                ? `${truck.lat.toFixed(4)}, ${truck.lon.toFixed(4)}`
                : "не передаёт"}
            </dd>
          </dl>
          <p className="dash-muted">Рейс и груз не подключены.</p>
        </>
      ) : null}

      {station ? (
        <>
          <p className="kicker">АГЗС</p>
          <h2>{station.name}</h2>
          <p className="dash-muted">{station.address || station.code}</p>
          {live && live.tanks.length > 0 ? (
            <p className="stage-vol">
              <SensorStatus level={live} />{" "}
              {live.remainder == null
                ? "замера ещё нет"
                : `${liters(live.remainder)} из ${liters(live.capacity)}`}
            </p>
          ) : (
            <p className="dash-muted">Датчик не подключён.</p>
          )}
          {onOpenStation ? (
            <button type="button" className="btn small map-popup-more" onClick={() => onOpenStation(station.id)}>
              Подробнее →
            </button>
          ) : null}
        </>
      ) : null}
    </aside>
  );
}
