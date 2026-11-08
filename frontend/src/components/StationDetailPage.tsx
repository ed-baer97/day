import { useState } from "react";
import { isAdmin } from "../access";
import { useAuth } from "../auth";
import { useCatalog } from "../catalog";
import { dateTime, liters, stationRegion } from "../format";
import { isLowFill, SensorStatus, tankSensorBadge, tankSensorLabel, usePublicLevels, useSensorDay, useViewPeriod } from "../liveLevels";
import { chartOf } from "../sensorDay";
import { BarChart, LineChart } from "./Charts";
import PeriodSwitch from "./PeriodSwitch";
import TankDeviceRows from "./TankDeviceRows";

type DetailTab = "overview" | "tanks" | "pumps" | "history";

export default function StationDetailPage({
  stationId,
  onBack,
  onSelectStation,
  onOpenAdmin,
  onOpenMap,
}: {
  stationId: string;
  onBack: () => void;
  onSelectStation?: (id: string) => void;
  onOpenAdmin?: (id: string) => void;
  onOpenMap?: (id: string) => void;
}) {
  const { session } = useAuth();
  const canManage = isAdmin(session);
  const catalog = useCatalog();
  const { byCode } = usePublicLevels();
  const { range, historyLoading } = useViewPeriod();
  const day = useSensorDay([stationId]);
  const [tab, setTab] = useState<DetailTab>("overview");
  const stations = catalog.stations.filter((row) => row.is_active);
  const index = stations.findIndex((row) => row.id === stationId);
  const station = index >= 0 ? stations[index] : catalog.stations.find((row) => row.id === stationId);

  if (!station) {
    return (
      <div className="dash">
        <button type="button" className="btn secondary small" onClick={onBack}>
          ← Все АГЗС
        </button>
        <p className="empty">АГЗС не найдена</p>
      </div>
    );
  }

  const live = byCode.get(station.code) ?? null;
  const hasTanks = !!live && live.tanks.length > 0;
  const series = day.get(station.id);
  const fillPct = hasTanks && live?.fill != null ? Math.max(0, Math.min(100, live.fill)) : 0;
  const prev = index > 0 ? stations[index - 1] : stations[stations.length - 1];
  const next = index >= 0 && index < stations.length - 1 ? stations[index + 1] : stations[0];
  const levelChart = chartOf(series?.series ?? [], series?.labels ?? range.labels);
  const hasDay = series?.opening != null;

  return (
    <div className="dash">
      <div className="st-detail-nav">
        <button type="button" className="btn secondary small" onClick={onBack}>
          ← Все АГЗС ({stations.length})
        </button>
        {onSelectStation && stations.length > 1 ? (
          <div className="st-Detail-switcher">
            <button type="button" className="btn secondary small" onClick={() => onSelectStation(prev.id)}>
              ‹ Пред.
            </button>
            <select
              className="st-select"
              value={station.id}
              aria-label="Выбрать АГЗС"
              onChange={(event) => onSelectStation(event.target.value)}
            >
              {stations.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name} ({row.code})
                </option>
              ))}
            </select>
            <button type="button" className="btn secondary small" onClick={() => onSelectStation(next.id)}>
              След. ›
            </button>
          </div>
        ) : null}
        <div className="st-detail-actions">
          <PeriodSwitch />
          {onOpenMap ? (
            <button type="button" className="btn secondary small" onClick={() => onOpenMap(station.id)}>
              Показать на карте
            </button>
          ) : null}
          {onOpenAdmin ? (
            <button type="button" className="btn small" onClick={() => onOpenAdmin(station.id)}>
              Администратор
            </button>
          ) : null}
        </div>
      </div>

      <header className="st-head">
        <div>
          <p className="kicker">
            {station.code} · {stationRegion(station)} · {station.lat.toFixed(4)}, {station.lon.toFixed(4)}
          </p>
          <h2>{station.name}</h2>
          <span className="dash-muted">{station.address || "Адрес не указан"}</span>
        </div>
        <div className="st-row-badges">
          {hasTanks && live ? <SensorStatus level={live} /> : <span className="badge warn">датчик не подключён</span>}
          <span className="badge">приход {liters(series?.inflow ?? 0)}</span>
          {hasDay && series ? <span className="badge">расход {liters(series.outflow)}</span> : null}
        </div>
      </header>

      <div className="admin-tabs" role="tablist" style={{ marginBottom: 20 }}>
        <button type="button" role="tab" aria-selected={tab === "overview"} className={tab === "overview" ? "active" : ""} onClick={() => setTab("overview")}>
          Сводка и уровень
        </button>
        <button type="button" role="tab" aria-selected={tab === "tanks"} className={tab === "tanks" ? "active" : ""} onClick={() => setTab("tanks")}>
          Резервуары и датчики ({live?.tanks.length ?? 0})
        </button>
        <button type="button" role="tab" aria-selected={tab === "pumps"} className={tab === "pumps" ? "active" : ""} onClick={() => setTab("pumps")}>
          Колонки и КГД
        </button>
        <button type="button" role="tab" aria-selected={tab === "history"} className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>
          Поставки и инциденты
        </button>
      </div>

      {tab === "overview" ? (
        <div className="st-grid">
          <section className="dash-card">
            <h3>{range.chartTitle}</h3>
            <p className="dash-muted">
              {range.countsReceipts ? (
                <>
                  Приход {liters(series?.inflow ?? 0)}
                  {(series?.inflow ?? 0) > 0 ? " — поставка." : ": поставки не было."}{" "}
                </>
              ) : (
                "Поставки в книге без даты, за этот срок не считаем. "
              )}
              На линии газ, который уже был в резервуаре.
              {hasDay && series ? ` Расход ${liters(series.outflow)}.` : ""}
            </p>
            {historyLoading && levelChart.labels.length === 0 ? (
              <p className="dash-muted">Загрузка замеров…</p>
            ) : levelChart.labels.length === 1 ? (
              <BarChart
                labels={levelChart.labels}
                series={[{ name: "Остаток", color: "var(--sea)", values: levelChart.values }]}
              />
            ) : levelChart.labels.length > 1 ? (
              <LineChart
                labels={levelChart.labels}
                series={[{ name: "Остаток", color: "var(--sea)", values: levelChart.values }]}
              />
            ) : (
              <p className="dash-muted">
                {range.includesNow && hasTanks && live?.remainder != null
                  ? `Сейчас в резервуаре ${liters(live.remainder)}. Смен уровня за этот срок не было.`
                  : "Замера датчика за этот срок ещё нет."}
              </p>
            )}
          </section>
          <section className="dash-card">
            <h3>Цифровой уровень резервуара</h3>
            <div className="gauge">
              <div className="gauge-bar">
                <i
                  style={{
                    height: `${fillPct}%`,
                    background: isLowFill(hasTanks ? live?.fill : null) ? "var(--coral)" : "linear-gradient(0deg, var(--sea-2, var(--sea)), var(--sea))",
                  }}
                />
              </div>
              <div className="gauge-meta">
                <strong>{hasTanks && live?.fill == null ? "—" : `${Math.round(fillPct)}%`}</strong>
                <span>
                  {!hasTanks || live?.remainder == null
                    ? "замера ещё нет"
                    : `${liters(live.remainder)} из ${liters(live.capacity)}`}
                </span>
                {hasTanks && live
                  ? live.tanks.map((item) => (
                      <span key={item.code}>
                        резервуар {item.code} · <span className={`badge ${tankSensorBadge(item)}`}>{tankSensorLabel(item)}</span>
                        {" · "}
                        {item.remainder_liters == null
                          ? "замера нет"
                          : `${liters(item.remainder_liters)} из ${liters(item.capacity_liters)}`}
                      </span>
                    ))
                  : null}
                <span className="dash-muted">{hasTanks && live?.measuredAt ? dateTime(live.measuredAt) : "замера нет"}</span>
              </div>
            </div>
          </section>
        </div>
      ) : null}

      {tab === "tanks" ? (
        <>
          <section className="dash-section">
            <h3>Резервуары</h3>
            {!hasTanks || !live ? (
              <p className="empty">
                {canManage
                  ? "К этой АГЗС ещё не подключён резервуар. Добавьте его ниже и привяжите датчик."
                  : "К этой АГЗС ещё не подключён резервуар."}
              </p>
            ) : (
              live.tanks.map((tank) => {
                const width = tank.fill_percent == null ? 0 : Math.max(0, Math.min(100, tank.fill_percent));
                return (
                  <div className={`level-tank${tank.online ? "" : " level-tank-stale"}`} key={tank.code}>
                    <div className="level-tank-head">
                      <span>Резервуар {tank.code}</span>
                      <strong>{tank.fill_percent == null ? "—" : `${Math.round(tank.fill_percent)}%`}</strong>
                    </div>
                    <div className="public-track" aria-hidden="true">
                      <i style={{ width: `${width}%` }} />
                    </div>
                    <p>
                      <span className={`badge ${tankSensorBadge(tank)}`}>{tankSensorLabel(tank)}</span>
                      {" · "}
                      {tank.remainder_liters == null
                        ? "замера нет"
                        : `${liters(tank.remainder_liters)} из ${liters(tank.capacity_liters)}`}
                      {tank.measured_at ? ` · ${dateTime(tank.measured_at)}` : ""}
                    </p>
                  </div>
                );
              })
            )}
          </section>
          <section className="dash-section">
            <h3>Подключение датчика</h3>
            <TankDeviceRows stationId={station.id} />
          </section>
        </>
      ) : null}

      {tab === "pumps" ? (
        <section className="dash-card">
          <h3>Колонки и КГД</h3>
          <p className="dash-muted">Колонки, кассы и сверка с КГД не подключены. Цифр по ним нет.</p>
        </section>
      ) : null}

      {tab === "history" ? (
        <section className="dash-card">
          <h3>Поставки и инциденты</h3>
          <p className="dash-muted">Поставки и журнал инцидентов не подключены. Рейсов и событий нет.</p>
        </section>
      ) : null}
    </div>
  );
}
