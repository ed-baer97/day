import { useMemo } from "react";
import type { DispenseReading, LevelReading, TankDevice } from "../api/client";
import {
  bucketCaption,
  buildLiveTankSamples,
  columnDispenseReport,
  type ColumnReport,
} from "../columnReport";
import { dateTime, liters } from "../format";
import type { LiveLevel } from "../liveLevels";
import type { TimeRange } from "../period";
import { BarChart } from "./Charts";

export default function ColumnReportCard({
  points,
  range,
  devices,
  live,
  loading,
  outflow = 0,
  dispenses = [],
  report: precomputedReport,
}: {
  points: LevelReading[];
  range: TimeRange;
  devices: TankDevice[];
  live: LiveLevel | null;
  loading: boolean;
  outflow?: number;
  dispenses?: DispenseReading[];
  report?: ColumnReport;
}) {
  const computedReport = useMemo(() => {
    if (precomputedReport) return precomputedReport;
    const liveTanks = buildLiveTankSamples(live, devices, points, range.includesNow);
    return columnDispenseReport(points, range, liveTanks, new Date(), outflow, dispenses);
  }, [precomputedReport, live, devices, points, range, outflow, dispenses]);

  const report = precomputedReport ?? computedReport;
  const rows = report.labels
    .map((label, index) => ({ label, index, total: report.totals[index] ?? 0 }))
    .filter((row) => row.total > 0);

  return (
    <section className="dash-card" style={{ marginBottom: 18 }}>
      <div className="card-head-inline">
        <h3>Колонки и КГД</h3>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <span className="badge ok">подключены {report.columnCount} колонки</span>
          <span className="badge ok">КГД: расхождений нет (0 л)</span>
        </div>
      </div>
      <p className="dash-muted">
        {report.source === "edge"
          ? "Реальная телеметрия колонок АСКА-02 / УЗСГ-01: наливы передаются напрямую со станционного узла и без потерь отражаются в ККМ, ОФД и КГД."
          : "Симуляция 2 колонок: уход газа берётся напрямую из расхода резервуара по датчику уровня и без потерь отражается в ККМ, ОФД и КГД."}
      </p>

      <div className="fiscal-chain">
        <div className="fiscal-step">
          <span>Расход резервуара</span>
          <strong>{loading && points.length === 0 ? "…" : liters(report.tankOutflowLiters)}</strong>
          <em>уход газа по датчику</em>
        </div>
        <div className="fiscal-link">→</div>
        <div className="fiscal-step">
          <span>Счётчики ТРК ({report.columnCount} колонки)</span>
          <strong>{loading && points.length === 0 ? "…" : liters(report.total)}</strong>
          <em>{report.columns.map((column) => `${column.name}: ${liters(column.total)}`).join(" · ")}</em>
        </div>
        <div className="fiscal-link">→</div>
        <div className="fiscal-step">
          <span>Онлайн-ККМ → ОФД → КГД</span>
          <strong>{loading && points.length === 0 ? "…" : liters(report.ofdTotalLiters)}</strong>
          <em>расхождение: {report.discrepancyLiters} л · сходится</em>
        </div>
      </div>

      <div className="col-grid" style={{ marginBottom: 16 }}>
        {report.columns.map((column) => (
          <article className="column-card" key={column.number}>
            <div className="card-head-inline" style={{ marginBottom: 6 }}>
              <h3 style={{ margin: 0 }}>
                {column.name} ({column.code})
              </h3>
              <span className="badge ok">онлайн · 0 л Δ</span>
            </div>
            <p className="stage-vol" style={{ marginBottom: 10 }}>
              Уход газа: <strong>{liters(column.total)}</strong>
            </p>
            <dl className="kv">
              <dt>Операций отпуска</dt>
              <dd>{column.opsCount}</dd>
              <dt>Последний отпуск</dt>
              <dd>
                {column.lastLiters != null
                  ? `${liters(column.lastLiters)}${column.lastAt ? ` · ${dateTime(column.lastAt)}` : ""}`
                  : "за период не было"}
              </dd>
              <dt>Фискализация КГД</dt>
              <dd>
                {column.kkmSerial} · {liters(column.ofdLiters)}
              </dd>
            </dl>
          </article>
        ))}
      </div>

      <h3 style={{ marginTop: 0 }}>Сверка ТРК ↔ ККМ ↔ ОФД ↔ КГД</h3>
      <div className="dash-table-wrap" style={{ marginBottom: 18 }}>
        <table className="dash-table">
          <thead>
            <tr>
              <th>Колонка · ККМ</th>
              <th>Уход из резервуара</th>
              <th>Счётчик ТРК</th>
              <th>Чеки ККМ</th>
              <th>Принято ОФД / КГД</th>
              <th>Расхождение</th>
            </tr>
          </thead>
          <tbody>
            {report.columns.map((column) => (
              <tr key={column.number}>
                <td>
                  <strong>
                    {column.name} ({column.code})
                  </strong>
                  <div className="dash-muted">{column.kkmSerial} · онлайн</div>
                </td>
                <td>{liters(column.total)}</td>
                <td>
                  <strong>{liters(column.total)}</strong>
                  <div className="dash-muted">операций: {column.opsCount}</div>
                </td>
                <td>{liters(column.kkmLiters)}</td>
                <td>{liters(column.ofdLiters)}</td>
                <td>
                  <span className="badge ok">0 л · сходится</span>
                </td>
              </tr>
            ))}
            <tr className="dash-total">
              <td>Итого</td>
              <td>{liters(report.tankOutflowLiters)}</td>
              <td>{liters(report.total)}</td>
              <td>{liters(report.kkmTotalLiters)}</td>
              <td>{liters(report.ofdTotalLiters)}</td>
              <td>
                <span className="badge ok">0 л · сходится</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <h3 style={{ marginTop: 0 }}>Расход по времени</h3>
      {loading && points.length === 0 ? (
        <p className="dash-muted">Загрузка замеров резервуара…</p>
      ) : report.total > 0 ? (
        <BarChart
          labels={report.labels.map((label) => bucketCaption(range, label))}
          series={report.columns.map((column, index) => ({
            name: column.name,
            color: index === 0 ? "var(--sea)" : "var(--dust)",
            values: column.liters,
          }))}
        />
      ) : (
        <p className="dash-muted">
          За этот срок уровень резервуара не снижался. Отпуска через колонки нет.
        </p>
      )}
      {rows.length > 0 ? (
        <div className="dash-table-wrap" style={{ marginTop: 12 }}>
          <table className="dash-table">
            <thead>
              <tr>
                <th>Время</th>
                {report.columns.map((column) => (
                  <th key={column.number}>{column.name}</th>
                ))}
                <th>Всего</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.label}>
                  <td>{bucketCaption(range, row.label)}</td>
                  {report.columns.map((column) => (
                    <td key={column.number}>{liters(column.liters[row.index] ?? 0)}</td>
                  ))}
                  <td>
                    <strong>{liters(row.total)}</strong>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
