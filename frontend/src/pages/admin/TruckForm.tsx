import { useState } from "react";
import type { CatalogTruck, TruckDraft } from "../../api/client";
import { messageOf, useCatalog } from "../../catalog";
import { TRUCK_STATUS } from "./types";

export default function TruckForm({
  initial,
  onCancel,
  onSaved,
  onDeleted,
}: {
  initial: CatalogTruck | null;
  onCancel: () => void;
  onSaved: (saved: CatalogTruck) => void;
  onDeleted: () => void;
}) {
  const { saveTruck, deleteTruck } = useCatalog();
  const [plate, setPlate] = useState(initial?.plate_number ?? "");
  const [capacity, setCapacity] = useState(initial ? String(initial.capacity_liters) : "");
  const [carrier, setCarrier] = useState(initial?.carrier_name ?? "");
  const [status, setStatus] = useState(initial?.status ?? "idle");
  const [lat, setLat] = useState(initial?.lat != null ? String(initial.lat) : "");
  const [lon, setLon] = useState(initial?.lon != null ? String(initial.lon) : "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit() {
    const volume = Number(capacity.replace(",", "."));
    const latitude = lat.trim() ? Number(lat.replace(",", ".")) : null;
    const longitude = lon.trim() ? Number(lon.replace(",", ".")) : null;
    if (!plate.trim() || !Number.isFinite(volume) || volume <= 0) {
      setError("Укажите номер и объём цистерны");
      return;
    }
    const coordsMissing = (latitude == null) !== (longitude == null);
    const coordsBad =
      (latitude != null && !Number.isFinite(latitude)) ||
      (longitude != null && !Number.isFinite(longitude));
    if (coordsMissing || coordsBad) {
      setError("Широту и долготу укажите вместе");
      return;
    }
    const body: TruckDraft = {
      plate_number: plate.trim(),
      capacity_liters: volume,
      carrier_name: carrier.trim() || null,
      status,
      lat: latitude,
      lon: longitude,
    };
    setSaving(true);
    setError(null);
    try {
      onSaved(await saveTruck(initial?.id ?? null, body));
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!initial) return;
    setSaving(true);
    setError(null);
    try {
      await deleteTruck(initial.id);
      onDeleted();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      className="admin-form"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <h3 className="span-3">Карточка газовоза</h3>
      <label>
        Номер
        <input value={plate} onChange={(event) => setPlate(event.target.value)} />
      </label>
      <label>
        Объём цистерны, л
        <input
          inputMode="decimal"
          value={capacity}
          onChange={(event) => setCapacity(event.target.value)}
        />
      </label>
      <label>
        Статус
        <select value={status} onChange={(event) => setStatus(event.target.value)}>
          {TRUCK_STATUS.map((row) => (
            <option key={row.value} value={row.value}>
              {row.label}
            </option>
          ))}
        </select>
      </label>
      <label className="span-3">
        Перевозчик
        <input value={carrier} onChange={(event) => setCarrier(event.target.value)} />
      </label>
      <label>
        Широта
        <input inputMode="decimal" value={lat} onChange={(event) => setLat(event.target.value)} />
      </label>
      <label>
        Долгота
        <input inputMode="decimal" value={lon} onChange={(event) => setLon(event.target.value)} />
      </label>
      <p className="dash-muted span-3">
        Для нового газовоза координаты ставят его на карту. Уже едущий рейс координаты не сдвигает.
      </p>
      {error ? <p className="tank-error span-3">{error}</p> : null}
      <div className="admin-actions span-3">
        <button type="submit" className="btn small" disabled={saving}>
          Сохранить
        </button>
        {initial && (
          <button
            type="button"
            className="btn secondary small text-danger"
            disabled={saving}
            onClick={() => void handleDelete()}
          >
            Удалить газовоз
          </button>
        )}
        <button type="button" className="btn secondary small" onClick={onCancel}>
          К списку
        </button>
      </div>
    </form>
  );
}
