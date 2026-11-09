import { useMemo, useState } from "react";
import { isAdmin } from "../access";
import type { CabinetFace, CabinetSale } from "../api/client";
import { useAuth } from "../auth";
import { useCatalog } from "../catalog";
import { dateTime, liters, stationRegion, tenge } from "../format";
import { isLowFill, SensorStatus, tankSensorBadge, tankSensorLabel, usePublicLevels, useSensorDay, useViewPeriod } from "../liveLevels";
import type { TimeRange } from "../period";
import { chartOf } from "../sensorDay";
import { BarChart, LineChart } from "./Charts";
import ConsoleAdminsCard from "./ConsoleAdminsCard";
import PeriodSwitch from "./PeriodSwitch";
import StationCabinet from "./StationCabinet";
import TankDeviceRows from "./TankDeviceRows";

type DetailTab = "tanks" | "pumps" | "history";

function doseLiters(ml: number): string {
  return `${(ml / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 3 })} л`;
}

function salesInRange(sales: CabinetSale[], range: TimeRange): CabinetSale[] {
  const start = range.start.getTime();
  const end = range.end.getTime();
  return sales.filter((sale) => {
    const time = new Date(sale.finished_at).getTime();
    return time >= start && time < end;
  });
}

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
  const canSetPrice = session?.role === "owner" || session?.role === "station";
  const { byCode } = usePublicLevels();
  const { range, historyLoading } = useViewPeriod();
  const day = useSensorDay([stationId]);
  const [tab, setTab] = useState<DetailTab>("tanks");
  const [face, setFace] = useState<CabinetFace | null>(null);
  const stations = catalog.stations.filter((row) => row.is_active);
  const index = stations.findIndex((row) => row.id === stationId);
  const station = index >= 0 ? stations[index] : catalog.stations.find((row) => row.id === stationId);

  const ledger = useMemo(() => {
    if (!face) return [];
    return face.history && face.history.length > 0 ? face.history : face.recent;
  }, [face]);
  const periodSales = useMemo(() => salesInRange(ledger, range), [ledger, range]);
  const consoleMl = periodSales.reduce((sum, sale) => sum + sale.delivered_ml, 0);
  const consoleKzt = periodSales.reduce((sum, sale) => sum + sale.amount_kzt, 0);
  const pumpChart = useMemo(() => {
    const pumps = face?.pumps ?? [];
    return {
      labels: pumps.map((pump) => pump.name),
      values: pumps.map(
        (pump) =>
          periodSales.filter((sale) => sale.pump_name === pump.name).reduce((sum, sale) => sum + sale.delivered_ml, 0) /
          1000
      ),
    };
  }, [face, periodSales]);
  const saleChart = useMemo(() => {
    const values = range.labels.map(() => 0);
    for (const sale of periodSales) {
      const index = range.indexAt(new Date(sale.finished_at).getTime());
      if (index >= 0) values[index] += sale.delivered_ml / 1000;
    }
    return values;
  }, [periodSales, range]);

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
  const online = !!live && live.tanks.some((tank) => tank.online === true && tank.remainder_liters != null);
  const pumpHasVolume = pumpChart.values.some((value) => value > 0);
  const saleHasVolume = saleChart.some((value) => value > 0);
  const periodNote = face?.history_capped ? " В расчёт вошли последние 500 отпусков." : "";

  return (
    <div className="dash">
      <div className="st-detail-nav">
        {stations.length > 1 ? (
          <button type="button" className="btn secondary small" onClick={onBack}>
            ← Все АГЗС ({stations.length})
          </button>
        ) : null}
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
        </div>
      </header>

      <div className="dash-kpis">
        <div className="dash-kpi">
          <span>Газ в резервуаре</span>
          <strong>{hasTanks && live?.remainder != null ? liters(live.remainder) : "—"}</strong>
          <em>{hasTanks ? `из ${liters(live?.capacity ?? 0)}` : "резервуара в кабинете нет"}</em>
        </div>
        <div className="dash-kpi">
          <span>Заполнение</span>
          <strong>{!hasTanks || live?.fill == null ? "—" : `${Math.round(fillPct)}%`}</strong>
          <em>
            {!hasTanks || live?.fill == null ? "замера нет" : isLowFill(live.fill) ? "мало газа" : "доля ёмкости"}
          </em>
        </div>
        <div className="dash-kpi">
          <span>{range.inflowTitle}</span>
          <strong>{range.countsReceipts ? liters(series?.inflow ?? 0) : "—"}</strong>
          <em>
            {range.countsReceipts
              ? (series?.inflow ?? 0) > 0
                ? "принятые поставки"
                : "поставок не было"
              : "поставки в книге без даты, за этот срок не считаем"}
          </em>
        </div>
        <div className="dash-kpi">
          <span>{range.expenseTitle}</span>
          <strong>{hasDay && series ? liters(series.outflow) : "—"}</strong>
          <em>на сколько уровень ниже первого замера за срок</em>
        </div>
        <div className="dash-kpi">
          <span>Отпуск колонок</span>
          <strong>{face ? doseLiters(consoleMl) : "—"}</strong>
          <em>за выбранный срок</em>
        </div>
        <div className="dash-kpi">
          <span>Выручка колонок</span>
          <strong>{face ? tenge(consoleKzt) : "—"}</strong>
          <em>за выбранный срок</em>
        </div>
        <div className="dash-kpi">
          <span>Отпусков</span>
          <strong>{face ? periodSales.length : "—"}</strong>
          <em>законченные дозы пульта</em>
        </div>
        <div className="dash-kpi">
          <span>Датчик</span>
          <strong>{!hasTanks ? "нет" : online ? "на связи" : live?.remainder == null ? "нет замера" : "нет связи"}</strong>
          <em>
            {!hasTanks
              ? "резервуар не подключён"
              : online
                ? "замер свежий"
                : live?.remainder == null
                  ? "количество газа ещё не пришло"
                  : "замер устарел"}
          </em>
        </div>
      </div>

      <div className="dash-charts">
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
                  background: isLowFill(hasTanks ? live?.fill : null)
                    ? "var(--coral)"
                    : "linear-gradient(0deg, var(--sea-2, var(--sea)), var(--sea))",
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
        <section className="dash-card">
          <h3>Колонки за срок</h3>
          <p className="dash-muted">
            Литры, которые пульт отпустил за выбранный срок.{periodNote}
          </p>
          {!face ? (
            <p className="dash-muted">Жду ответ пульта…</p>
          ) : pumpChart.labels.length === 0 ? (
            <p className="dash-muted">Колонок на этой АГЗС нет.</p>
          ) : pumpHasVolume ? (
            <BarChart
              labels={pumpChart.labels}
              series={[{ name: "Отпуск", color: "var(--dust)", values: pumpChart.values }]}
            />
          ) : (
            <p className="dash-muted">За этот срок колонки ничего не отпустили.</p>
          )}
        </section>
        <section className="dash-card">
          <h3>Отпуски по времени</h3>
          <p className="dash-muted">
            Те же литры, разложенные по {range.preset === "week" || range.preset === "month" ? "дням" : "часам"} срока.
            {periodNote}
          </p>
          {!face ? (
            <p className="dash-muted">Жду ответ пульта…</p>
          ) : saleHasVolume ? (
            <BarChart
              labels={range.labels}
              series={[{ name: "Отпуск", color: "var(--coral)", values: saleChart }]}
            />
          ) : (
            <p className="dash-muted">За этот срок отпусков нет.</p>
          )}
        </section>
      </div>

      <StationCabinet stationId={station.id} canSetPrice={canSetPrice} onFace={setFace} />
      {session?.role === "console" ? null : (
        <ConsoleAdminsCard stationId={station.id} canCreate={canSetPrice} />
      )}

      <div className="admin-tabs" role="tablist" style={{ marginBottom: 20 }}>
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
          <p className="dash-muted">Сверка с КГД не подключена. Отпуски колонок уже в сводке и в таблице выше.</p>
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
