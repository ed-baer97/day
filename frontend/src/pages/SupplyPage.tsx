import type { BatchRecord, CatalogStation, CatalogTruck } from "../api/client";
import { dateTime, liters, phaseLabel, stationRegion } from "../format";
import type { NetworkStats } from "../layout/Topbar";
import { isLowFill, type LiveLevel, LOW_FILL_PERCENT, SensorStatus } from "../liveLevels";

export default function SupplyPage({
  stations,
  trucks,
  batches,
  byCode,
  networkStats,
  onOpenTrucksOnMap,
  onCreateNewTruck,
  onOpenStationPage,
  onOpenStationOnMap,
  onOpenAdminStation,
  onOpenTruckOnMap,
  onOpenAdminTruck,
}: {
  stations: CatalogStation[];
  trucks: CatalogTruck[];
  batches: BatchRecord[];
  byCode: Map<string, LiveLevel>;
  networkStats: NetworkStats;
  onOpenTrucksOnMap: () => void;
  onCreateNewTruck: () => void;
  onOpenStationPage: (id: string) => void;
  onOpenStationOnMap: (id: string) => void;
  onOpenAdminStation: (id: string) => void;
  onOpenTruckOnMap: (id: string) => void;
  onOpenAdminTruck: (id: string) => void;
}) {
  return (
    <div className="dash">
      <header className="dash-hero">
        <div>
          <p className="kicker">Логистический контур · Мангистауская область</p>
          <h2>Планирование поставок, газовозы и партии LPG</h2>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" className="btn secondary small" onClick={onOpenTrucksOnMap}>
            Газовозы на карте ({trucks.length})
          </button>
          <button type="button" className="btn small" onClick={onCreateNewTruck}>
            + Добавить газовоз
          </button>
        </div>
      </header>

      <div className="dash-kpis">
        <div className="dash-kpi">
          <span>Парк газовозов</span>
          <strong>{trucks.length}</strong>
          <em>
            общая вместимость: {liters(trucks.reduce((s, t) => s + (t.capacity_liters || 0), 0))}
          </em>
        </div>
        <div className="dash-kpi">
          <span>АГЗС требуют подвоза (&lt; {LOW_FILL_PERCENT}%)</span>
          <strong className={networkStats.low > 0 ? "text-danger" : ""}>{networkStats.low}</strong>
          <em>приоритетные станции</em>
        </div>
        <div className="dash-kpi">
          <span>Свободная ёмкость сети</span>
          <strong>{liters(networkStats.freeSum)}</strong>
          <em>доступно под слив по всем АГЗС</em>
        </div>
        <div className="dash-kpi">
          <span>Партий в реестре</span>
          <strong>{batches.length}</strong>
          <em>цифровой след партий LPG</em>
        </div>
      </div>

      <section className="dash-section">
        <div className="card-head-inline">
          <h3>Приоритет подвоза газа по АГЗС (по остатку в резервуарах)</h3>
        </div>
        <div className="dash-table-wrap">
          <table className="dash-table">
            <thead>
              <tr>
                <th>АГЗС и район</th>
                <th>Уровень %</th>
                <th>Фактический остаток</th>
                <th>Полная ёмкость</th>
                <th>Рекомендуемый слив (до 85%)</th>
                <th>Макс. свободно (до 100%)</th>
                <th>Датчик</th>
                <th>Переход</th>
              </tr>
            </thead>
            <tbody>
              {[...stations]
                .map((st) => {
                  const live = byCode.get(st.code) ?? null;
                  const hasLive = !!live && live.tanks.length > 0;
                  const fill = hasLive && live?.fill != null ? Math.round(live.fill) : null;
                  const rem = hasLive ? (live?.remainder ?? null) : null;
                  const cap = hasLive ? (live?.capacity ?? 0) : 0;
                  const free = rem != null && cap > 0 ? Math.max(0, cap - rem) : null;
                  const safe =
                    rem != null && cap > 0
                      ? Math.max(0, Math.round(cap * 0.85) - rem)
                      : null;
                  return { st, live, hasLive, fill, rem, cap, free, safe };
                })
                .sort((a, b) => (a.fill ?? 101) - (b.fill ?? 101))
                .map(({ st, live, hasLive, fill, rem, cap, free, safe }) => (
                  <tr key={st.id} className="dash-row-link" onClick={() => onOpenStationPage(st.id)}>
                    <td>
                      <strong>{st.name}</strong>
                      <div className="dash-muted">
                        {st.code} · {stationRegion(st)}
                      </div>
                    </td>
                    <td>
                      <strong className={isLowFill(fill) ? "text-danger" : ""}>
                        {fill == null ? "—" : `${fill}%`}
                      </strong>
                    </td>
                    <td>{rem == null ? "замера нет" : liters(rem)}</td>
                    <td>{liters(cap)}</td>
                    <td>
                      <strong>{safe == null ? "—" : liters(safe)}</strong>
                    </td>
                    <td>{free == null ? "—" : liters(free)}</td>
                    <td>
                      {hasLive && live ? (
                        <SensorStatus level={live} />
                      ) : (
                        <span className="badge warn">не подключён</span>
                      )}
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <div style={{ display: "flex", gap: 4 }}>
                        <button
                          type="button"
                          className="btn secondary small"
                          onClick={() => onOpenStationPage(st.id)}
                        >
                          Сводка
                        </button>
                        <button
                          type="button"
                          className="btn secondary small"
                          onClick={() => onOpenStationOnMap(st.id)}
                        >
                          Карта
                        </button>
                        <button
                          type="button"
                          className="btn secondary small"
                          onClick={() => onOpenAdminStation(st.id)}
                        >
                          Принять слив
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="dash-section">
        <h3>Автопарк газовозов ({trucks.length})</h3>
        {trucks.length === 0 ? (
          <p className="empty">Газовозы ещё не добавлены в каталог.</p>
        ) : (
          <div className="dash-table-wrap">
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Госномер</th>
                  <th>Перевозчик</th>
                  <th>Объём цистерны</th>
                  <th>Статус рейса</th>
                  <th>Координаты GPS</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>
                {trucks.map((tr) => (
                  <tr key={tr.id}>
                    <td>
                      <strong>{tr.plate_number}</strong>
                    </td>
                    <td>{tr.carrier_name || "—"}</td>
                    <td>{liters(tr.capacity_liters)}</td>
                    <td>
                      <span className="badge ok">{phaseLabel(tr.status)}</span>
                    </td>
                    <td>
                      {tr.lat != null && tr.lon != null
                        ? `${tr.lat.toFixed(4)}, ${tr.lon.toFixed(4)}`
                        : "нет координат"}
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }}>
                        {tr.lat != null && tr.lon != null ? (
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() => onOpenTruckOnMap(tr.id)}
                          >
                            На карте
                          </button>
                        ) : null}
                        <button
                          type="button"
                          className="btn secondary small"
                          onClick={() => onOpenAdminTruck(tr.id)}
                        >
                          Редактировать
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {batches.length > 0 ? (
        <section className="dash-section">
          <h3>Зарегистрированные партии газа ({batches.length})</h3>
          <div className="dash-table-wrap">
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Код партии</th>
                  <th>Марка</th>
                  <th>Объём</th>
                  <th>Статус</th>
                  <th>Дата регистрации</th>
                  <th>Примечание</th>
                </tr>
              </thead>
              <tbody>
                {batches.map((b) => (
                  <tr key={b.id}>
                    <td>
                      <strong>{b.trail_code}</strong>
                    </td>
                    <td>{b.product_grade || "ПБТ"}</td>
                    <td>{liters(b.volume_liters)}</td>
                    <td>
                      <span className="badge ok">{b.status}</span>
                    </td>
                    <td>{dateTime(b.created_at)}</td>
                    <td className="dash-muted">{b.notes || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
