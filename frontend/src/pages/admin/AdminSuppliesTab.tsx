import type { BatchRecord } from "../../api/client";
import { dateTime, liters } from "../../format";
import { isLowFill } from "../../liveLevels";
import type { EnrichedStation } from "./types";

export default function AdminSuppliesTab({
  batches,
  deliveryNeeds,
  batchCode,
  setBatchCode,
  batchGrade,
  setBatchGrade,
  batchVol,
  setBatchVol,
  batchNotes,
  setBatchNotes,
  batchSaving,
  onCreateBatch,
  onOpenStation,
  scrollTop,
}: {
  batches: BatchRecord[];
  deliveryNeeds: EnrichedStation[];
  batchCode: string;
  setBatchCode: (value: string) => void;
  batchGrade: string;
  setBatchGrade: (value: string) => void;
  batchVol: string;
  setBatchVol: (value: string) => void;
  batchNotes: string;
  setBatchNotes: (value: string) => void;
  batchSaving: boolean;
  onCreateBatch: () => void;
  onOpenStation: (id: string) => void;
  scrollTop: () => void;
}) {
  const handleCreateBatch = onCreateBatch;
  const scrollAdminTop = scrollTop;
  return (
            <div className="admin-workspace">
              <section className="dash-card">
                <h3>План потребности АГЗС в подвозе газа (по приоритету заполненности)</h3>
                <p className="dash-muted">
                  Автоматический расчёт свободного объёма резервуаров для планирования рейсов
                  газовозов. Рекомендуемый объём слива рассчитан до безопасного уровня 85% ёмкости.
                </p>
                <div className="dash-table-wrap" style={{ marginTop: 10 }}>
                  <table className="dash-table">
                    <thead>
                      <tr>
                        <th>АГЗС / Район</th>
                        <th>Заполненность</th>
                        <th>Текущий остаток</th>
                        <th>Полная ёмкость</th>
                        <th>Рекомендуемый слив (до 85%)</th>
                        <th>Макс. свободно (до 100%)</th>
                        <th>Действие</th>
                      </tr>
                    </thead>
                    <tbody>
                      {deliveryNeeds.map(({ row, region, fill, actual, cap, free, safeRefill }) => (
                        <tr key={row.id}>
                          <td>
                            <strong>{row.name}</strong>
                            <div className="dash-muted">
                              {row.code} · {region}
                            </div>
                          </td>
                          <td>
                            <strong className={isLowFill(fill) ? "text-danger" : ""}>
                              {fill == null ? "—" : `${fill}%`}
                            </strong>
                          </td>
                          <td>{actual == null ? "замера нет" : liters(actual)}</td>
                          <td>{liters(cap)}</td>
                          <td>
                            <strong>{safeRefill == null ? "—" : liters(safeRefill)}</strong>
                          </td>
                          <td>{free == null ? "—" : liters(free)}</td>
                          <td>
                            <button
                              type="button"
                              className="btn secondary small"
                              onClick={() => {
                                onOpenStation(row.id);
                                scrollAdminTop();
                              }}
                            >
                              Оформить приход →
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="dash-card">
                <h3>Регистрация партии сжиженного газа (Цифровой след)</h3>
                <form
                  className="admin-form"
                  style={{ marginTop: 10 }}
                  onSubmit={(e) => {
                    e.preventDefault();
                    void handleCreateBatch();
                  }}
                >
                  <label>
                    Код партии (Trail Code)
                    <input
                      placeholder="LPG-2026-0042"
                      value={batchCode}
                      onChange={(e) => setBatchCode(e.target.value)}
                      required
                    />
                  </label>
                  <label>
                    Марка газа
                    <input
                      value={batchGrade}
                      onChange={(e) => setBatchGrade(e.target.value)}
                    />
                  </label>
                  <label>
                    Объём партии, л
                    <input
                      inputMode="decimal"
                      value={batchVol}
                      onChange={(e) => setBatchVol(e.target.value)}
                      required
                    />
                  </label>
                  <label className="span-3">
                    Примечание (завод, маршрут, газовоз)
                    <input
                      placeholder="КазГПЗ (Жанаозен) → Актау"
                      value={batchNotes}
                      onChange={(e) => setBatchNotes(e.target.value)}
                    />
                  </label>
                  <div className="admin-actions span-3">
                    <button type="submit" className="btn small" disabled={batchSaving}>
                      {batchSaving ? "Сохраняем…" : "Зарегистрировать партию"}
                    </button>
                  </div>
                </form>

                {batches.length > 0 ? (
                  <div className="dash-table-wrap" style={{ marginTop: 14 }}>
                    <table className="dash-table">
                      <thead>
                        <tr>
                          <th>Код партии</th>
                          <th>Марка</th>
                          <th>Объём</th>
                          <th>Статус</th>
                          <th>Создана</th>
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
                ) : (
                  <p className="dash-muted" style={{ marginTop: 12 }}>
                    Зарегистрированных партий пока нет.
                  </p>
                )}
              </section>
            </div>
  );
}
