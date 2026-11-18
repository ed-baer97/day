import type { BatchRecord } from "../../api/client";
import { dateTime, liters } from "../../format";

export default function AdminSuppliesTab({
  batches,
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
}: {
  batches: BatchRecord[];
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
}) {
  const handleCreateBatch = onCreateBatch;
  return (
            <div className="admin-workspace">
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
