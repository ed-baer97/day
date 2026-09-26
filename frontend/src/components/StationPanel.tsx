import type { StationDetail } from "../types";
import Empty from "./Empty";

function liters(v?: number | null) {
  if (v == null) return "—";
  return `${v.toLocaleString("ru-RU")} л`;
}

function balanceBadge(status: string) {
  if (status === "ok") return "ok";
  if (status === "shortage" || status === "surplus") return "danger";
  return "warn";
}

export default function StationPanel({
  station,
  loading,
  onClose,
}: {
  station: StationDetail | null;
  loading?: boolean;
  onClose: () => void;
}) {
  return (
    <div className="detail-embed">
      <div className="panel-head">
        <h2>АГЗС</h2>
        <button type="button" className="btn secondary small" onClick={onClose}>
          К списку
        </button>
      </div>
      <div className="panel-body">
        {loading ? (
          <p className="empty">Загрузка…</p>
        ) : !station ? (
          <Empty title="АГЗС не выбрана" hint="Кликните станцию на карте" />
        ) : (
          <>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12, gap: 8 }}>
              <div>
                <strong style={{ fontFamily: "var(--serif)", fontSize: 18 }}>{station.name}</strong>
                <div style={{ color: "var(--muted)", fontSize: 12 }}>{station.code}</div>
              </div>
              <span className={`badge ${balanceBadge(station.balance_status)}`}>
                баланс: {station.balance_status}
              </span>
            </div>
            <dl className="kv">
              <dt>Остаток</dt>
              <dd>{liters(station.remainder_liters)}</dd>
              <dt>Ёмкость</dt>
              <dd>{liters(station.capacity_liters)}</dd>
              <dt>Δ расчёт / факт</dt>
              <dd>{station.calculated_vs_actual_delta != null ? `${station.calculated_vs_actual_delta} л` : "—"}</dd>
              <dt>Приёмки (сутки)</dt>
              <dd>{liters(station.receipts_day_liters)}</dd>
              <dt>Расход день</dt>
              <dd>{liters(station.consumption_day_liters)}</dd>
              <dt>Расход неделя</dt>
              <dd>{liters(station.consumption_week_liters)}</dd>
              <dt>Расход месяц</dt>
              <dd>{liters(station.consumption_month_liters)}</dd>
              <dt>Продажи (сутки)</dt>
              <dd>{station.sales_day_count}</dd>
            </dl>

            <h3 className="kicker" style={{ marginTop: 16 }}>
              Резервуары
            </h3>
            <ul className="trail-list">
              {station.tanks.map((t) => (
                <li key={t.id}>
                  <span className="title">
                    {t.code} · {liters(t.actual_remainder_liters)} / {liters(t.capacity_liters)}
                  </span>
                  <span className="desc">
                    источник: {t.level_source}
                    {t.has_electronic_sensor ? " · EX-датчик" : " · поплавок"}
                    {" · расчёт "}
                    {liters(t.calculated_remainder_liters)}
                  </span>
                </li>
              ))}
            </ul>

            {station.active_trucks.length > 0 && (
              <>
                <h3 className="kicker" style={{ marginTop: 16 }}>
                  Активные газовозы
                </h3>
                <ul className="trail-list">
                  {station.active_trucks.map((tr) => (
                    <li key={tr.plate}>
                      <span className="title">{tr.plate}</span>
                      <span className="desc">{tr.status}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
