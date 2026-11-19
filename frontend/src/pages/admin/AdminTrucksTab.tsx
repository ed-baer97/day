import { useMemo, useState } from "react";
import type { CatalogStation, CatalogTruck } from "../../api/client";
import { liters } from "../../format";
import TruckForm from "./TruckForm";
import { statusLabel, TRUCK_STATUS, truckStatusBadge } from "./types";

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
  onOpenTruckMap,
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
  onOpenTruckMap?: (id: string) => void;
  toast: { ok: (message: string) => void };
  scrollTop: () => void;
}) {
  const [pageSize, setPageSize] = useState(10);
  const [page, setPage] = useState(1);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const paged = useMemo(() => {
    const start = (safePage - 1) * pageSize;
    return filtered.slice(start, start + pageSize);
  }, [filtered, safePage, pageSize]);

  const truckIdx = catalog.trucks.findIndex((row) => row.id === truckId);
  const prevTruck =
    truckIdx > 0 ? catalog.trucks[truckIdx - 1] : catalog.trucks[catalog.trucks.length - 1];
  const nextTruck =
    truckIdx >= 0 && truckIdx < catalog.trucks.length - 1
      ? catalog.trucks[truckIdx + 1]
      : catalog.trucks[0];

  return (
    <>
      {truckId == null && (
        <div className="st-filter-bar" style={{ marginBottom: 14 }}>
          <input
            type="search"
            className="st-search-input"
            value={query}
            placeholder="Поиск газовоза по госномеру или перевозчику…"
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(1);
            }}
          />
          <select
            className="st-select"
            value={status}
            aria-label="Статус газовоза"
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
          >
            <option value="all">Все статусы ({catalog.trucks.length})</option>
            {TRUCK_STATUS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          <select
            className="st-select"
            value={pageSize}
            aria-label="На странице"
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setPage(1);
            }}
          >
            <option value={10}>По 10 строк</option>
            <option value={20}>По 20 строк</option>
            <option value={100}>Все ({filtered.length})</option>
          </select>
          <button
            type="button"
            className="btn"
            onClick={() => {
              setTruckId("new");
              scrollTop();
            }}
          >
            + Новый газовоз
          </button>
        </div>
      )}

      {truckId == null ? (
        <div>
          <div className="dash-table-wrap admin-table">
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Госномер</th>
                  <th>Объём цистерны</th>
                  <th>Перевозчик</th>
                  <th>Статус</th>
                  <th>Координаты GPS</th>
                  <th>Карта</th>
                </tr>
              </thead>
              <tbody>
                {paged.map((row) => {
                  const tone = truckStatusBadge(row.status);
                  return (
                    <tr
                      key={row.id}
                      className={`dash-row-link${truckId === row.id ? " active" : ""}`}
                      onClick={() => {
                        setTruckId(row.id);
                        scrollTop();
                      }}
                    >
                      <td>
                        <strong>{row.plate_number}</strong>
                      </td>
                      <td>{liters(row.capacity_liters)}</td>
                      <td>{row.carrier_name || "—"}</td>
                      <td>
                        <span className={`badge${tone ? ` ${tone}` : ""}`}>
                          {statusLabel(row.status)}
                        </span>
                      </td>
                      <td>
                        {row.lat != null && row.lon != null
                          ? `${row.lat.toFixed(4)}, ${row.lon.toFixed(4)}`
                          : "—"}
                      </td>
                      <td onClick={(e) => e.stopPropagation()}>
                        {onOpenTruckMap && row.lat != null && row.lon != null ? (
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() => onOpenTruckMap(row.id)}
                          >
                            На карте
                          </button>
                        ) : (
                          <span className="dash-muted">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {paged.length === 0 && (
                  <tr>
                    <td colSpan={6} className="dash-muted">
                      {catalog.trucks.length === 0
                        ? "Газовозы ещё не добавлены в автопарк."
                        : "По выбранному фильтру газовозов не найдено."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="pagination-bar" style={{ marginTop: 10 }}>
              <span className="dash-muted">
                Стр. {safePage} из {totalPages} (всего {filtered.length} газовозов)
              </span>
              <div className="pagination-buttons">
                <button
                  type="button"
                  className="btn secondary small"
                  disabled={safePage <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  ← Пред.
                </button>
                {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                  <button
                    key={p}
                    type="button"
                    className={`btn small${p === safePage ? "" : " secondary"}`}
                    onClick={() => setPage(p)}
                  >
                    {p}
                  </button>
                ))}
                <button
                  type="button"
                  className="btn secondary small"
                  disabled={safePage >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                >
                  След. →
                </button>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="admin-workspace">
          <div className="admin-backbar">
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <button
                type="button"
                className="btn secondary small"
                onClick={() => setTruckId(null)}
              >
                ← К списку газовозов ({catalog.trucks.length})
              </button>
              {truck && catalog.trucks.length > 1 ? (
                <div className="st-Detail-switcher">
                  <button
                    type="button"
                    className="btn secondary small"
                    onClick={() => prevTruck && setTruckId(prevTruck.id)}
                  >
                    ‹ Пред.
                  </button>
                  <select
                    className="st-select"
                    value={truck.id}
                    aria-label="Переключить газовоз в админке"
                    onChange={(e) => setTruckId(e.target.value)}
                  >
                    {catalog.trucks.map((item, idx) => (
                      <option key={item.id} value={item.id}>
                        {idx + 1}. {item.plate_number}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn secondary small"
                    onClick={() => nextTruck && setTruckId(nextTruck.id)}
                  >
                    След. ›
                  </button>
                </div>
              ) : null}
            </div>
            {truck && onOpenTruckMap && truck.lat != null && truck.lon != null ? (
              <button
                type="button"
                className="btn secondary small"
                onClick={() => onOpenTruckMap(truck.id)}
              >
                Показать на карте
              </button>
            ) : null}
          </div>
          <section className="dash-card admin-form-card">
            {truckId === "new" ? (
              <TruckForm
                key="new-truck"
                initial={null}
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
