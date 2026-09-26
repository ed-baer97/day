import type { TruckDetail } from "../types";
import Empty from "./Empty";

function fmt(dt?: string | null) {
  if (!dt) return "—";
  try {
    return new Date(dt).toLocaleString("ru-RU");
  } catch {
    return dt;
  }
}

function liters(v?: number | null) {
  if (v == null) return "—";
  return `${v.toLocaleString("ru-RU")} л`;
}

export default function TruckPanel({
  truck,
  loading,
  onClose,
}: {
  truck: TruckDetail | null;
  loading?: boolean;
  onClose: () => void;
}) {
  return (
    <div className="detail-embed">
      <div className="panel-head">
        <h2>Газовоз</h2>
        <button type="button" className="btn secondary small" onClick={onClose}>
          К списку
        </button>
      </div>
      <div className="panel-body">
        {loading ? (
          <p className="empty">Загрузка…</p>
        ) : !truck ? (
          <Empty title="Газовоз не выбран" hint="Кликните маркер на карте" />
        ) : (
          <>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
              <strong style={{ fontFamily: "var(--serif)", fontSize: 18 }}>{truck.plate_number}</strong>
              <span className="badge ok">{truck.trip_status ?? truck.status}</span>
            </div>
            <dl className="kv">
              <dt>Координаты</dt>
              <dd>
                {truck.lat != null && truck.lon != null
                  ? `${truck.lat.toFixed(4)}, ${truck.lon.toFixed(4)}`
                  : "—"}
              </dd>
              <dt>Поставщик</dt>
              <dd>{truck.supplier_name ?? "—"}</dd>
              <dt>Откуда</dt>
              <dd>{truck.origin_name ?? "—"}</dd>
              <dt>Куда</dt>
              <dd>{truck.destination_name ?? "—"}</dd>
              <dt>Объём груза</dt>
              <dd>{liters(truck.cargo_volume_liters)}</dd>
              <dt>Ёмкость</dt>
              <dd>{liters(truck.capacity_liters)}</dd>
              <dt>Выезд</dt>
              <dd>{fmt(truck.departed_at)}</dd>
              <dt>Прибытие</dt>
              <dd>{fmt(truck.arrived_at)}</dd>
              <dt>Перевозчик</dt>
              <dd>{truck.carrier_name ?? "—"}</dd>
            </dl>
          </>
        )}
      </div>
    </div>
  );
}
