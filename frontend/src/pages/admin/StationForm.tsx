import { useState } from "react";
import type { CatalogStation, StationDraft } from "../../api/client";
import { messageOf, useCatalog } from "../../catalog";

export default function StationForm({
  initial,
  onCancel,
  onSaved,
  onDeleted,
}: {
  initial: CatalogStation | null;
  onCancel: () => void;
  onSaved: (saved: CatalogStation) => void;
  onDeleted: () => void;
}) {
  const { saveStation, deleteStation } = useCatalog();
  const [code, setCode] = useState(initial?.code ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [address, setAddress] = useState(initial?.address ?? "");
  const [lat, setLat] = useState(initial ? String(initial.lat) : "43.65");
  const [lon, setLon] = useState(initial ? String(initial.lon) : "51.20");
  const [active, setActive] = useState(initial?.is_active ?? true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit() {
    const latitude = Number(lat.replace(",", "."));
    const longitude = Number(lon.replace(",", "."));
    if (!code.trim() || !name.trim() || !Number.isFinite(latitude) || !Number.isFinite(longitude)) {
      setError("Укажите код, название и координаты");
      return;
    }
    const body: StationDraft = {
      code: code.trim(),
      name: name.trim(),
      address: address.trim() || null,
      lat: latitude,
      lon: longitude,
      is_active: active,
    };
    setSaving(true);
    setError(null);
    try {
      onSaved(await saveStation(initial?.id ?? null, body));
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
      await deleteStation(initial.id);
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
      <h3 className="span-3">{initial ? "Паспортные данные станции" : "Новая заправка"}</h3>
      <label>
        Код
        <input value={code} onChange={(event) => setCode(event.target.value)} />
      </label>
      <label className="span-2">
        Название
        <input value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <label className="span-3">
        Адрес
        <input
          value={address}
          placeholder="Город, район, улица — район нужен для группировки"
          onChange={(event) => setAddress(event.target.value)}
        />
      </label>
      <label>
        Широта
        <input inputMode="decimal" value={lat} onChange={(event) => setLat(event.target.value)} />
      </label>
      <label>
        Долгота
        <input inputMode="decimal" value={lon} onChange={(event) => setLon(event.target.value)} />
      </label>
      <label className="admin-check span-3">
        <input
          type="checkbox"
          checked={active}
          onChange={(event) => setActive(event.target.checked)}
        />
        Работает (публиковать на лэндинге)
      </label>
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
            Удалить АГЗС
          </button>
        )}
        <button type="button" className="btn secondary small" onClick={onCancel}>
          К списку
        </button>
      </div>
    </form>
  );
}
