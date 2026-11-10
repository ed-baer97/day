import type { CatalogStation, CatalogTruck } from "../../api/client";
import { liters } from "../../format";
import TruckForm from "./TruckForm";
import { TRUCK_STATUS, statusLabel } from "./types";

export default function AdminTrucksTab({
  catalog,
  truckId,
  setTruckId,
  truck,
  query,
  setQuery,
  status,
  setStatus,
  filtered,
  toast,
  scrollTop,
}: {
  catalog: { stations: CatalogStation[]; trucks: CatalogTruck[] };
  truckId: string | "new" | null;
  setTruckId: (id: string | "new" | null) => void;
  truck: CatalogTruck | null;
  query: string;
  setQuery: (value: string) => void;
  status: string;
  setStatus: (value: string) => void;
  filtered: CatalogTruck[];
  toast: { ok: (message: string) => void };
  scrollTop: () => void;
}) {
  const trQuery = query;
  const setTrQuery = setQuery;
  const trStatus = status;
  const setTrStatus = setStatus;
  const filteredTrucks = filtered;
  const scrollAdminTop = scrollTop;
  return (
            <>
              {truckId == null && (
                <div className="st-filter-bar" style={{ marginBottom: 14 }}>
                  <input
                    type="search"
                    className="st-search-input"
                    value={trQuery}
                    placeholder="Поиск газовоза по госномеру или перевозчику…"
                    onChange={(e) => setTrQuery(e.target.value)}
                  />
                  <select
                    className="st-select"
                    value={trStatus}
                    aria-label="Статус газовоза"
                    onChange={(e) => setTrStatus(e.target.value)}
                  >
                    <option value="all">Все статусы ({catalog.trucks.length})</option>
                    {TRUCK_STATUS.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => {
                      setTruckId("new");
                      scrollAdminTop();
                    }}
                  >
                    + Новый газовоз
                  </button>
                </div>
              )}

              {truckId == null ? (
                <div className="dash-table-wrap admin-table">
                  <table className="dash-table">
                    <thead>
                      <tr>
                        <th>Госномер</th>
                        <th>Объём цистерны</th>
                        <th>Перевозчик</th>
                        <th>Статус</th>
                        <th>Координаты GPS</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredTrucks.map((row) => (
                        <tr
                          key={row.id}
                          className={`dash-row-link${truckId === row.id ? " active" : ""}`}
                          onClick={() => {
                            setTruckId(row.id);
                            scrollAdminTop();
                          }}
                        >
                          <td>
                            <strong>{row.plate_number}</strong>
                          </td>
                          <td>{liters(row.capacity_liters)}</td>
                          <td>{row.carrier_name || "—"}</td>
                          <td>
                            <span className="badge ok">{statusLabel(row.status)}</span>
                          </td>
                          <td>
                            {row.lat != null && row.lon != null
                              ? `${row.lat.toFixed(4)}, ${row.lon.toFixed(4)}`
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="admin-workspace">
                  <div className="admin-backbar">
                    <button
                      type="button"
                      className="btn secondary small"
                      onClick={() => setTruckId(null)}
                    >
                      ← К списку газовозов ({catalog.trucks.length})
                    </button>
                  </div>
                  <section className="dash-card admin-form-card">
                    {truckId === "new" ? (
                      <TruckForm
                        key="new-truck"
                        initial={null}
                        onCancel={() => setTruckId(null)}
                        onSaved={(saved) => {
                          setTruckId(saved.id);
                          toast.ok(`Газовоз ${saved.plate_number} добавлен`);
                        }}
                        onDeleted={() => setTruckId(null)}
                      />
                    ) : truck ? (
                      <TruckForm
                        key={truck.id}
                        initial={truck}
                        onCancel={() => setTruckId(null)}
                        onSaved={(saved) => toast.ok(`Газовоз ${saved.plate_number} обновлён`)}
                        onDeleted={() => {
                          setTruckId(null);
                          toast.ok(`Газовоз ${truck.plate_number} удалён`);
                        }}
                      />
                    ) : (
                      <p className="admin-empty">Этот газовоз больше не в списке.</p>
                    )}
                  </section>
                </div>
              )}
            </>
  );
}
