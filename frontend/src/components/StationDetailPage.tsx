import { useCatalog } from "../catalog";
import { dateTime, liters, stationRegion } from "../format";
import { SensorStatus, tankSensorBadge, tankSensorLabel, usePublicLevels } from "../liveLevels";
import TankDeviceRows from "./TankDeviceRows";

export default function StationDetailPage({
  stationId,
  onBack,
  onSelectStation,
  onOpenAdmin,
  onOpenMap,
}: {
  stationId: string;
  onBack: () => void;
  onSelectStation?: (id: string) => void;
  onOpenAdmin?: (id: string) => void;
  onOpenMap?: (id: string) => void;
}) {
  const catalog = useCatalog();
  const { byCode } = usePublicLevels();
  const stations = catalog.stations.filter((row) => row.is_active);
  const index = stations.findIndex((row) => row.id === stationId);
  const station = index >= 0 ? stations[index] : catalog.stations.find((row) => row.id === stationId);

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

  const live = byCode.get(station.code) ?? null;
  const hasTanks = !!live && live.tanks.length > 0;
  const prev = index > 0 ? stations[index - 1] : stations[stations.length - 1];
  const next = index >= 0 && index < stations.length - 1 ? stations[index + 1] : stations[0];

  return (
    <div className="dash">
      <div className="st-detail-nav">
        <button type="button" className="btn secondary small" onClick={onBack}>
          ← Все АГЗС ({stations.length})
        </button>
        {onSelectStation && stations.length > 1 ? (
          <div className="st-Detail-switcher">
            <button type="button" className="btn secondary small" onClick={() => onSelectStation(prev.id)}>
              ‹ Пред.
            </button>
            <select
              className="st-select"
              value={station.id}
              aria-label="Выбрать АГЗС"
              onChange={(event) => onSelectStation(event.target.value)}
            >
              {stations.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name} ({row.code})
                </option>
              ))}
            </select>
            <button type="button" className="btn secondary small" onClick={() => onSelectStation(next.id)}>
              След. ›
            </button>
          </div>
        ) : null}
        <div className="st-detail-actions">
          {onOpenMap ? (
            <button type="button" className="btn secondary small" onClick={() => onOpenMap(station.id)}>
              Показать на карте
            </button>
          ) : null}
          {onOpenAdmin ? (
            <button type="button" className="btn small" onClick={() => onOpenAdmin(station.id)}>
              Настроить в админке
            </button>
          ) : null}
        </div>
      </div>

      <header className="st-head">
        <div>
          <p className="kicker">
            {station.code} · {stationRegion(station)} · {station.lat.toFixed(4)}, {station.lon.toFixed(4)}
          </p>
          <h2>{station.name}</h2>
          <span className="dash-muted">{station.address || "Адрес не указан"}</span>
        </div>
        <div className="st-row-badges">
          {hasTanks && live ? <SensorStatus level={live} /> : <span className="badge warn">датчик не подключён</span>}
        </div>
      </header>

      <section className="dash-section">
        <h3>Резервуары</h3>
        {!hasTanks || !live ? (
          <p className="empty">К этой АГЗС ещё не подключён резервуар. Добавьте его ниже и привяжите датчик.</p>
        ) : (
          live.tanks.map((tank) => {
            const width = tank.fill_percent == null ? 0 : Math.max(0, Math.min(100, tank.fill_percent));
            return (
              <div className={`level-tank${tank.online ? "" : " level-tank-stale"}`} key={tank.code}>
                <div className="level-tank-head">
                  <span>Резервуар {tank.code}</span>
                  <strong>{tank.fill_percent == null ? "—" : `${Math.round(tank.fill_percent)}%`}</strong>
                </div>
                <div className="public-track" aria-hidden="true">
                  <i style={{ width: `${width}%` }} />
                </div>
                <p>
                  <span className={`badge ${tankSensorBadge(tank)}`}>{tankSensorLabel(tank)}</span>
                  {" · "}
                  {tank.remainder_liters == null
                    ? "замера нет"
                    : `${liters(tank.remainder_liters)} из ${liters(tank.capacity_liters)}`}
                  {tank.measured_at ? ` · ${dateTime(tank.measured_at)}` : ""}
                </p>
              </div>
            );
          })
        )}
      </section>

      <section className="dash-section">
        <h3>Подключение датчика</h3>
        <TankDeviceRows stationId={station.id} />
      </section>

      <p className="dash-muted">Колонки, КГД и поставки не подключены — цифр по ним нет.</p>
    </div>
  );
}
