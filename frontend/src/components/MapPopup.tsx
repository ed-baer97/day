import type { CatalogStation, CatalogTruck } from "../api/client";
import { dateTime, liters, phaseLabel, stationRegion } from "../format";
import {
  isLowFill,
  SensorStatus,
  tankSensorBadge,
  tankSensorLabel,
  usePublicLevels,
} from "../liveLevels";

export default function MapPopup({
  truck,
  station,
  onClose,
  onOpenStation,
  onOpenAdminStation,
  onOpenAdminTruck,
}: {
  truck?: CatalogTruck | null;
  station?: CatalogStation | null;
  onClose: () => void;
  onOpenStation?: (id: string) => void;
  onOpenAdminStation?: (id: string) => void;
  onOpenAdminTruck?: (id: string) => void;
}) {
  const { byCode } = usePublicLevels();
  if (!truck && !station) return null;
  const live = station ? byCode.get(station.code) : undefined;
  const hasTanks = !!live && live.tanks.length > 0;
  const fill = hasTanks && live?.fill != null ? Math.round(live.fill) : null;
  const freeLiters =
    hasTanks && live?.remainder != null && live.capacity > 0
      ? Math.max(0, live.capacity - live.remainder)
      : null;
  const safeRefill =
    hasTanks && live?.remainder != null && live.capacity > 0
      ? Math.max(0, Math.round(live.capacity * 0.85) - live.remainder)
      : null;

  return (
    <aside className="map-popup" role="dialog" aria-label="Подробная карточка объекта">
      <button type="button" className="map-popup-close" onClick={onClose} aria-label="Закрыть">
        ×
      </button>

      {truck ? (
        <>
          <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 6 }}>
            <span className="kicker" style={{ margin: 0 }}>
              Газовоз
            </span>
            <span className="badge ok">{phaseLabel(truck.status)}</span>
          </div>
          <h2>{truck.plate_number}</h2>
          <dl className="kv" style={{ marginTop: 10 }}>
            <dt>Статус рейса</dt>
            <dd>{phaseLabel(truck.status)}</dd>
            <dt>Объём цистерны</dt>
            <dd>{liters(truck.capacity_liters)}</dd>
            <dt>Перевозчик</dt>
            <dd>{truck.carrier_name || "не указан"}</dd>
            <dt>Координаты GPS</dt>
            <dd>
              {truck.lat != null && truck.lon != null
                ? `${truck.lat.toFixed(4)}, ${truck.lon.toFixed(4)}`
                : "не передаёт"}
            </dd>
          </dl>
          {onOpenAdminTruck ? (
            <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
              <button
                type="button"
                className="btn secondary small"
                style={{ width: "100%" }}
                onClick={() => onOpenAdminTruck(truck.id)}
              >
                Карточка газовоза в админке →
              </button>
            </div>
          ) : null}
        </>
      ) : null}

      {station ? (
        <>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginBottom: 6 }}>
            <span className="badge">{stationRegion(station)}</span>
            <span className="badge">{station.code}</span>
            {hasTanks && live ? (
              <SensorStatus level={live} />
            ) : (
              <span className="badge warn">датчик не подключён</span>
            )}
          </div>
          <h2>{station.name}</h2>
          <p className="dash-muted" style={{ margin: "0 0 10px" }}>
            {station.address || "Адрес не указан"} · {station.lat.toFixed(4)}, {station.lon.toFixed(4)}
          </p>

          {hasTanks && live ? (
            <>
              <div className="bal-triad" style={{ marginBottom: 10 }}>
                <div className="bal-cell">
                  <span>Остаток</span>
                  <strong className={isLowFill(fill) ? "text-danger" : ""}>
                    {live.remainder == null ? "—" : liters(live.remainder)}
                  </strong>
                  <em>{fill == null ? "нет замера" : `${fill}% заполнено`}</em>
                </div>
                <div className="bal-cell">
                  <span>Ёмкость</span>
                  <strong>{liters(live.capacity)}</strong>
                  <em>резервуаров: {live.tanks.length}</em>
                </div>
                <div className="bal-cell">
                  <span>Свободно</span>
                  <strong>{freeLiters == null ? "—" : liters(freeLiters)}</strong>
                  <em>{safeRefill != null ? `до 85%: ${liters(safeRefill)}` : "под слив"}</em>
                </div>
              </div>

              <div className="fill-bar" style={{ marginBottom: 8 }}>
                <i
                  style={{
                    width: `${fill ?? 0}%`,
                    background: isLowFill(fill) ? "var(--coral)" : "var(--sea)",
                  }}
                />
              </div>

              {live.measuredAt ? (
                <p className="dash-muted" style={{ margin: "0 0 10px" }}>
                  Последний замер: <strong>{dateTime(live.measuredAt)}</strong>
                </p>
              ) : null}

              <div className="popup-tank-list">
                {live.tanks.map((tank) => (
                  <div key={tank.code} className="popup-tank-row">
                    <div>
                      <strong>Резервуар {tank.code}</strong>
                      <span className="dash-muted">
                        {" · "}
                        {tank.remainder_liters == null
                          ? "замера нет"
                          : `${liters(tank.remainder_liters)} из ${liters(tank.capacity_liters)}`}
                      </span>
                    </div>
                    <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <span className={`badge ${tankSensorBadge(tank)}`}>
                        {tankSensorLabel(tank)}
                      </span>
                      <strong className={isLowFill(tank.fill_percent) ? "text-danger" : ""}>
                        {tank.fill_percent == null ? "—" : `${Math.round(tank.fill_percent)}%`}
                      </strong>
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <p className="empty" style={{ margin: "8px 0" }}>
              К этой АГЗС ещё не подключены резервуары и датчики уровня.
            </p>
          )}

          <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            {onOpenStation ? (
              <button
                type="button"
                className="btn small"
                style={{ flex: 1 }}
                onClick={() => onOpenStation(station.id)}
              >
                Открыть сводку АГЗС →
              </button>
            ) : null}
            {onOpenAdminStation ? (
              <button
                type="button"
                className="btn secondary small"
                onClick={() => onOpenAdminStation(station.id)}
              >
                В админке ⚙
              </button>
            ) : null}
          </div>
        </>
      ) : null}
    </aside>
  );
}
