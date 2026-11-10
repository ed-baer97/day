import type { PublicStation } from "../../api/client";
import { dateTime, liters } from "../../format";
import {
  isLowFill,
  type LiveLevel,
  SensorStatus,
  tankSensorBadge,
  tankSensorLabel,
} from "../../liveLevels";

function percentLabel(v: number | null | undefined): string {
  return v == null ? "—" : String(Math.round(v));
}

export default function PublicStationModal({
  station,
  live,
  region,
  freeLiters,
  onClose,
  onPrev,
  onNext,
}: {
  station: PublicStation;
  live: LiveLevel;
  region: string;
  freeLiters: number | null;
  onClose: () => void;
  onPrev?: () => void;
  onNext?: () => void;
}) {
  return (
    <div className="login-layer" onClick={onClose}>
      <div
        className="login-card public-detail-modal"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-label={`Паспорт ${station.name}`}
      >
        <div className="st-detail-nav" style={{ marginBottom: 4 }}>
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <span className="badge">{region}</span>
            <span className="badge">{station.code}</span>
            {station.tanks.length > 0 ? <SensorStatus level={live} /> : null}
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            {onPrev ? (
              <button type="button" className="btn secondary small" onClick={onPrev}>
                ← Пред.
              </button>
            ) : null}
            {onNext ? (
              <button type="button" className="btn secondary small" onClick={onNext}>
                След. →
              </button>
            ) : null}
            <button type="button" className="btn secondary small" onClick={onClose}>
              Закрыть ✕
            </button>
          </div>
        </div>

        <div>
          <h2>{station.name}</h2>
          <p className="dash-muted" style={{ marginTop: 4 }}>
            Адрес: <strong>{station.address || "не указан"}</strong>
            {station.lat != null && station.lon != null
              ? ` · Координаты: ${station.lat.toFixed(4)}, ${station.lon.toFixed(4)}`
              : ""}
          </p>
        </div>

        <div className="dash-kpis" style={{ marginBottom: 8 }}>
          <div className="dash-kpi">
            <span>Фактический остаток</span>
            <strong>{live.remainder == null ? "—" : liters(live.remainder)}</strong>
            <em>суммарно по резервуарам</em>
          </div>
          <div className="dash-kpi">
            <span>Общая ёмкость</span>
            <strong>{liters(live.capacity)}</strong>
            <em>свободно: {freeLiters == null ? "—" : liters(freeLiters)}</em>
          </div>
          <div className="dash-kpi">
            <span>Заполненность</span>
            <strong className={isLowFill(live.fill) ? "text-danger" : ""}>
              {live.fill == null ? "—" : `${live.fill}%`}
            </strong>
            <em>{live.measuredAt ? `замер ${dateTime(live.measuredAt)}` : "ожидание замера"}</em>
          </div>
        </div>

        <div>
          <h3 style={{ margin: "4px 0 8px", fontSize: 15 }}>
            Резервуарный парк станции ({station.tanks.length})
          </h3>
          {station.tanks.length === 0 ? (
            <p className="empty">К этой заправке ещё не привязаны резервуары.</p>
          ) : (
            <div className="dash-table-wrap">
              <table className="dash-table">
                <thead>
                  <tr>
                    <th>Резервуар</th>
                    <th>Статус датчика</th>
                    <th>Уровень %</th>
                    <th>Остаток газа</th>
                    <th>Полная ёмкость</th>
                    <th>Свободно</th>
                    <th>Время замера</th>
                  </tr>
                </thead>
                <tbody>
                  {station.tanks.map((tank) => {
                    const free =
                      tank.remainder_liters != null
                        ? Math.max(0, tank.capacity_liters - tank.remainder_liters)
                        : null;
                    return (
                      <tr key={tank.code}>
                        <td>
                          <strong>{tank.code}</strong>
                        </td>
                        <td>
                          <span className={`badge ${tankSensorBadge(tank)}`}>
                            {tankSensorLabel(tank)}
                          </span>
                        </td>
                        <td>
                          <strong className={isLowFill(tank.fill_percent) ? "text-danger" : ""}>
                            {tank.fill_percent == null
                              ? "—"
                              : `${percentLabel(tank.fill_percent)}%`}
                          </strong>
                        </td>
                        <td>{liters(tank.remainder_liters)}</td>
                        <td>{liters(tank.capacity_liters)}</td>
                        <td>{free == null ? "—" : liters(free)}</td>
                        <td>{tank.measured_at ? dateTime(tank.measured_at) : "замера нет"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="login-actions" style={{ justifyContent: "space-between", marginTop: 6 }}>
          {station.lat != null && station.lon != null ? (
            <a
              className="btn secondary small"
              href={`https://www.google.com/maps?q=${station.lat},${station.lon}`}
              target="_blank"
              rel="noreferrer"
            >
              Открыть координаты в Google Картах ↗
            </a>
          ) : (
            <span />
          )}
          <button type="button" className="btn small" onClick={onClose}>
            Готово
          </button>
        </div>
      </div>
    </div>
  );
}
