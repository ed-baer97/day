import type { CatalogStation } from "../../api/client";
import { dateTime } from "../../format";
import type { DiscrepancyEvent } from "../../types";
import type { EnrichedStation } from "./types";

export default function AdminReconcileTab({
  enriched,
  events,
  stations,
  onResolve,
}: {
  enriched: EnrichedStation[];
  events: DiscrepancyEvent[];
  stations: CatalogStation[];
  onResolve: (id: string) => void;
}) {
  const enrichedCatalogStations = enriched;
  const catalog = { stations };
  const handleResolveEvent = onResolve;
  return (
            <div className="admin-workspace">
              <div className="dash-kpis">
                <div className="dash-kpi">
                  <span>АГЗС на связи</span>
                  <strong>
                    {enrichedCatalogStations.filter((x) => x.online).length} /{" "}
                    {enrichedCatalogStations.length}
                  </strong>
                  <em>актуальные показания датчиков</em>
                </div>
                <div className="dash-kpi">
                  <span>АГЗС без связи</span>
                  <strong
                    className={
                      enrichedCatalogStations.some(
                        (x) => x.live && x.live.tanks.length > 0 && !x.online
                      )
                        ? "text-danger"
                        : ""
                    }
                  >
                    {
                      enrichedCatalogStations.filter(
                        (x) => x.live && x.live.tanks.length > 0 && !x.online
                      ).length
                    }
                  </strong>
                  <em>замер устарел (&gt; 30 сек)</em>
                </div>
                <div className="dash-kpi">
                  <span>Без резервуара / датчика</span>
                  <strong>
                    {
                      enrichedCatalogStations.filter(
                        (x) => !x.live || x.live.tanks.length === 0
                      ).length
                    }
                  </strong>
                  <em>требуют привязки устройства</em>
                </div>
                <div className="dash-kpi">
                  <span>Открытых расхождений</span>
                  <strong className={events.some((e) => !e.is_resolved) ? "text-danger" : ""}>
                    {events.filter((e) => !e.is_resolved).length}
                  </strong>
                  <em>всего событий в журнале: {events.length}</em>
                </div>
              </div>

              <section className="dash-card">
                <h3>Журнал событий сверки и инцидентов баланса</h3>
                {events.length === 0 ? (
                  <p className="dash-muted">
                    Расхождений между книжным остатком и показаниями датчиков не зафиксировано.
                  </p>
                ) : (
                  <div className="dash-table-wrap">
                    <table className="dash-table">
                      <thead>
                        <tr>
                          <th>Время</th>
                          <th>АГЗС</th>
                          <th>Тип / Важность</th>
                          <th>Описание</th>
                          <th>Статус</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {events.map((ev) => {
                          const evStation = catalog.stations.find((s) => s.id === ev.station_id);
                          return (
                            <tr key={ev.id}>
                              <td>{dateTime(ev.detected_at)}</td>
                              <td>
                                <strong>{evStation ? evStation.name : ev.station_id || "—"}</strong>
                              </td>
                              <td>
                                <span
                                  className={`badge ${ev.severity === "critical" ? "danger" : "warn"}`}
                                >
                                  {ev.event_type} · {ev.severity}
                                </span>
                              </td>
                              <td>
                                <strong>{ev.title}</strong>
                                {ev.description ? (
                                  <div className="dash-muted">{ev.description}</div>
                                ) : null}
                              </td>
                              <td>
                                <span className={`badge ${ev.is_resolved ? "ok" : "warn"}`}>
                                  {ev.is_resolved ? "закрыто" : "открыто"}
                                </span>
                              </td>
                              <td>
                                {!ev.is_resolved ? (
                                  <button
                                    type="button"
                                    className="btn secondary small"
                                    onClick={() => void handleResolveEvent(ev.id)}
                                  >
                                    Принять
                                  </button>
                                ) : null}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </div>
  );
}
