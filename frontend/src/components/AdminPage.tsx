import { useState } from "react";
import type { CatalogStation, CatalogTruck, StationDraft, TruckDraft } from "../api/client";
import { messageOf, useCatalog } from "../catalog";
import { liters } from "../format";
import TankDeviceRows from "./TankDeviceRows";

const TRUCK_STATUS = [
  { value: "idle", label: "ожидание" },
  { value: "loading", label: "погрузка" },
  { value: "in_transit", label: "в пути" },
  { value: "arrived", label: "прибыл" },
  { value: "unloading", label: "слив" },
] as const;

function statusLabel(value: string) {
  return TRUCK_STATUS.find((row) => row.value === value)?.label ?? value;
}

export default function AdminPage() {
  const catalog = useCatalog();
  const [tab, setTab] = useState<"stations" | "trucks">("stations");
  const [stationId, setStationId] = useState<string | "new" | null>(null);
  const [truckId, setTruckId] = useState<string | "new" | null>(null);

  const station = catalog.stations.find((row) => row.id === stationId) ?? null;
  const truck = catalog.trucks.find((row) => row.id === truckId) ?? null;

  return (
    <div className="dash admin">
      <header className="admin-toolbar">
        <div>
          <p className="kicker">Справочник</p>
          <h2>Заправки и газовозы</h2>
        </div>
        <div className="admin-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "stations"}
            className={tab === "stations" ? "active" : ""}
            onClick={() => setTab("stations")}
          >
            Заправки
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "trucks"}
            className={tab === "trucks" ? "active" : ""}
            onClick={() => setTab("trucks")}
          >
            Газовозы
          </button>
        </div>
        {tab === "stations" ? (
          <button type="button" className="btn" onClick={() => setStationId("new")}>
            Новая заправка
          </button>
        ) : (
          <button type="button" className="btn" onClick={() => setTruckId("new")}>
            Новый газовоз
          </button>
        )}
      </header>
      {catalog.error ? <p className="tank-error">{catalog.error}</p> : null}

      {tab === "stations" ? (
        <div className="admin-split">
          <div className="dash-table-wrap admin-table">
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Код</th>
                  <th>Название</th>
                  <th>Адрес</th>
                  <th>Координаты</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {catalog.stations.map((row) => (
                  <tr
                    key={row.id}
                    className={`dash-row-link${stationId === row.id ? " active" : ""}`}
                    onClick={() => setStationId(row.id)}
                  >
                    <td>{row.code}</td>
                    <td>{row.name}</td>
                    <td>{row.address || "—"}</td>
                    <td>
                      {row.lat.toFixed(4)}, {row.lon.toFixed(4)}
                    </td>
                    <td>{row.is_active ? "работает" : "выключена"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <aside className="admin-editor dash-card">
            {stationId === "new" ? (
              <StationForm
                key="new-station"
                initial={null}
                onCancel={() => setStationId(null)}
                onSaved={(saved) => setStationId(saved.id)}
              />
            ) : station ? (
              <>
                <StationForm
                  key={station.id}
                  initial={station}
                  onCancel={() => setStationId(null)}
                  onSaved={() => undefined}
                />
                <h3 className="admin-sub">Резервуары</h3>
                <TankDeviceRows stationId={station.id} />
              </>
            ) : (
              <p className="admin-empty">Выберите заправку в таблице или создайте новую.</p>
            )}
          </aside>
        </div>
      ) : (
        <div className="admin-split">
          <div className="dash-table-wrap admin-table">
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Номер</th>
                  <th>Объём</th>
                  <th>Перевозчик</th>
                  <th>Статус</th>
                  <th>Координаты</th>
                </tr>
              </thead>
              <tbody>
                {catalog.trucks.map((row) => (
                  <tr
                    key={row.id}
                    className={`dash-row-link${truckId === row.id ? " active" : ""}`}
                    onClick={() => setTruckId(row.id)}
                  >
                    <td>{row.plate_number}</td>
                    <td>{liters(row.capacity_liters)}</td>
                    <td>{row.carrier_name || "—"}</td>
                    <td>{statusLabel(row.status)}</td>
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
          <aside className="admin-editor dash-card">
            {truckId === "new" ? (
              <TruckForm
                key="new-truck"
                initial={null}
                onCancel={() => setTruckId(null)}
                onSaved={(saved) => setTruckId(saved.id)}
              />
            ) : truck ? (
              <TruckForm
                key={truck.id}
                initial={truck}
                onCancel={() => setTruckId(null)}
                onSaved={() => undefined}
              />
            ) : (
              <p className="admin-empty">Выберите газовоз в таблице или создайте новый.</p>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

function StationForm({
  initial,
  onCancel,
  onSaved,
}: {
  initial: CatalogStation | null;
  onCancel: () => void;
  onSaved: (saved: CatalogStation) => void;
}) {
  const { saveStation } = useCatalog();
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

  return (
    <form
      className="admin-form"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <h3 className="span-3">{initial ? initial.name : "Новая заправка"}</h3>
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
        <input value={address} onChange={(event) => setAddress(event.target.value)} />
      </label>
      <label>
        Широта
        <input inputMode="decimal" value={lat} onChange={(event) => setLat(event.target.value)} />
      </label>
      <label>
        Долгота
        <input inputMode="decimal" value={lon} onChange={(event) => setLon(event.target.value)} />
      </label>
      <label className="admin-check">
        <input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />
        Работает
      </label>
      {error ? <p className="tank-error span-3">{error}</p> : null}
      <div className="admin-actions span-3">
        <button type="submit" className="btn small" disabled={saving}>
          Сохранить
        </button>
        <button type="button" className="btn secondary small" onClick={onCancel}>
          Закрыть
        </button>
      </div>
    </form>
  );
}

function TruckForm({
  initial,
  onCancel,
  onSaved,
}: {
  initial: CatalogTruck | null;
  onCancel: () => void;
  onSaved: (saved: CatalogTruck) => void;
}) {
  const { saveTruck } = useCatalog();
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
      (latitude != null && !Number.isFinite(latitude)) || (longitude != null && !Number.isFinite(longitude));
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

  return (
    <form
      className="admin-form"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <h3 className="span-3">{initial ? initial.plate_number : "Новый газовоз"}</h3>
      <label>
        Номер
        <input value={plate} onChange={(event) => setPlate(event.target.value)} />
      </label>
      <label>
        Объём цистерны, л
        <input inputMode="decimal" value={capacity} onChange={(event) => setCapacity(event.target.value)} />
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
        <button type="button" className="btn secondary small" onClick={onCancel}>
          Закрыть
        </button>
      </div>
    </form>
  );
}
