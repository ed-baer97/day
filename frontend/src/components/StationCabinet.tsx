import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, type CabinetFace } from "../api/client";
import { dateTime, tenge } from "../format";

function doseLiters(ml: number): string {
  return `${(ml / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 3 })} л`;
}

function errorText(error: unknown): string {
  if (!(error instanceof Error) || !error.message) return "Кабинет не ответил";
  try {
    const parsed = JSON.parse(error.message) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    /* текст уже готов */
  }
  return error.message;
}

export default function StationCabinet({
  stationId,
  canSetPrice = false,
}: {
  stationId: string | null;
  canSetPrice?: boolean;
}) {
  const [face, setFace] = useState<CabinetFace | null>(null);
  const [price, setPrice] = useState("");
  const [priceDirty, setPriceDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!stationId) return;
    try {
      const next = await api.cabinet(stationId);
      setFace(next);
      setPrice((current) => (priceDirty ? current : String(next.price_kzt_per_liter)));
      setError(null);
    } catch (caught) {
      setError(errorText(caught));
    }
  }, [priceDirty, stationId]);

  useEffect(() => {
    void load();
    if (!stationId) return;
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [load, stationId]);

  async function onPrice(event: FormEvent) {
    event.preventDefault();
    if (!stationId) return;
    const next = Number(price);
    if (!Number.isInteger(next) || next < 1) {
      setError("Укажите цену газа целым числом тенге за литр");
      return;
    }
    setSaving(true);
    try {
      const saved = await api.setCabinetPrice(stationId, next);
      setFace(saved);
      setPrice(String(saved.price_kzt_per_liter));
      setPriceDirty(false);
      setError(null);
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSaving(false);
    }
  }

  if (!stationId) return null;

  return (
    <section className="dash-card" style={{ margin: "0 0 16px" }}>
      <h3>Колонки</h3>
      <p className="dash-muted">
        {canSetPrice
          ? "Цену газа задаёт владелец, отдельно для этой заправки. Пульт считает по ней новые отпуски и присылает расход и стоимость."
          : "Расход и стоимость приходят с колонок. Цену газа задаёт владелец заправки."}
      </p>
      {canSetPrice ? (
      <form className="admin-form cabinet-price" onSubmit={(event) => void onPrice(event)}>
        <label>
          Стоимость газа, ₸/л
          <input
            inputMode="numeric"
            value={price}
            onChange={(event) => {
              setPriceDirty(true);
              setPrice(event.target.value.replace(/[^\d]/g, ""));
            }}
          />
        </label>
        <button className="btn small" type="submit" disabled={saving}>
          {saving ? "Сохраняю" : "Сохранить цену"}
        </button>
      </form>
      ) : face ? (
        <p className="cabinet-totals">
          <span>
            Стоимость газа <strong>{tenge(face.price_kzt_per_liter)}/л</strong>
          </span>
        </p>
      ) : null}
      {error ? <p className="tank-error">{error}</p> : null}
      {face ? (
        <>
          <p className="cabinet-totals">
            <span>Расход <strong>{doseLiters(face.delivered_ml)}</strong></span>
            <span>Стоимость <strong>{tenge(face.amount_kzt)}</strong></span>
            <span>Отпусков <strong>{face.sales}</strong></span>
          </p>
          <div className="dash-table-wrap">
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Колонка</th>
                  <th>Расход</th>
                  <th>Стоимость</th>
                  <th>Отпусков</th>
                </tr>
              </thead>
              <tbody>
                {face.pumps.map((pump) => (
                  <tr key={pump.pump_id}>
                    <td>{pump.name}</td>
                    <td>{doseLiters(pump.delivered_ml)}</td>
                    <td>{tenge(pump.amount_kzt)}</td>
                    <td>{pump.sales}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {face.recent.length === 0 ? (
            <p className="dash-muted">Колонки готовы. Расход и стоимость появятся после отпуска с пульта.</p>
          ) : (
            <div className="dash-table-wrap">
              <table className="dash-table">
                <thead>
                  <tr>
                    <th>Время</th>
                    <th>Колонка</th>
                    <th>Расход</th>
                    <th>Стоимость</th>
                    <th>Цена</th>
                  </tr>
                </thead>
                <tbody>
                  {face.recent.map((sale) => (
                    <tr key={sale.sale_id}>
                      <td>{dateTime(sale.finished_at)}</td>
                      <td>{sale.pump_name}</td>
                      <td>{doseLiters(sale.delivered_ml)}</td>
                      <td>{tenge(sale.amount_kzt)}</td>
                      <td>{tenge(sale.price_kzt_per_liter)}/л</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
