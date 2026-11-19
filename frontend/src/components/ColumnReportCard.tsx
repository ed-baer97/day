import { useMemo } from "react";
import type { ColumnsMode, DispenseReading, LevelReading, TankDevice } from "../api/client";
import {
  bucketCaption,
  buildLiveTankSamples,
  columnDispenseReport,
  type ColumnReport,
} from "../columnReport";
import { dateTime, liters, signedLiters } from "../format";
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
  columnsMode,
  onConfigureColumns,
}: {
  points: LevelReading[];
  range: TimeRange;
  devices: TankDevice[];
  live: LiveLevel | null;
  loading: boolean;
  outflow?: number;
  dispenses?: DispenseReading[];
  report?: ColumnReport;
  columnsMode?: ColumnsMode;
  onConfigureColumns?: () => void;
}) {
  const computedReport = useMemo(() => {
    if (precomputedReport) return precomputedReport;
    const liveTanks = buildLiveTankSamples(live, devices, points, range.includesNow);
    return columnDispenseReport(points, range, liveTanks, new Date(), outflow, dispenses, {
      mode: columnsMode,
    });
  }, [precomputedReport, live, devices, points, range, outflow, dispenses, columnsMode]);

  const report = precomputedReport ?? computedReport;
  const rows = report.labels
    .map((label, index) => ({ label, index, total: report.totals[index] ?? 0 }))
    .filter((row) => row.total > 0);
  const effectiveMode = columnsMode ?? (report.source === "edge" ? "edge" : "virtual");

  return (
    <section className="dash-card" style={{ marginBottom: 18 }}>
      <div className="card-head-inline">
        <h3>Колонки</h3>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          {report.source === "edge" ? (
            <span className="badge ok">Реальные ТРК · station-edge ({report.columnCount})</span>
          ) : null}
          {onConfigureColumns ? (
            <button
              type="button"
              className="btn secondary small"
              onClick={onConfigureColumns}
            >
              Настроить колонки ⚙
            </button>
          ) : null}
        </div>
      </div>
      {report.source === "edge" ? (
        <p className="dash-muted">
          Наливы поступают со станционного узла АСКА-02 / УЗСГ-01 (station-edge).
        </p>
      ) : null}
      {effectiveMode === "virtual" && report.source === "edge" && onConfigureColumns ? (
        <p className="dash-muted" style={{ marginTop: -4 }}>
          Обнаружены реальные наливы station-edge — можно закрепить режим «Реальные ТРК» в админке.
        </p>
      ) : null}

      <div className="fiscal-chain">
        <div className="fiscal-step">
          <span>Расход резервуара</span>
          <strong>
            {loading && points.length === 0
              ? "…"
              : report.tankOutflowLiters != null
                ? liters(report.tankOutflowLiters)
                : "нет данных"}
          </strong>
          <em>уход газа по датчику</em>
        </div>
        <div className="fiscal-link">→</div>
        <div className="fiscal-step">
          <span>Счётчики ТРК ({report.columnCount})</span>
          <strong>{loading && points.length === 0 ? "…" : liters(report.total)}</strong>
          <em>{report.columns.map((column) => `${column.name}: ${liters(column.total)}`).join(" · ")}</em>
        </div>
        {report.source === "edge" ? (
          <>
            <div className="fiscal-link">=</div>
            <div className="fiscal-step">
              <span>Разница (ТРК − уровень)</span>
              <strong className={report.status === "warn" ? "text-danger" : ""}>
                {report.discrepancyLiters != null ? signedLiters(report.discrepancyLiters) : "—"}
              </strong>
              <em>
                {report.discrepancyLiters == null
                  ? "нет данных датчика для сверки"
                  : report.tankOutflowLiters === 0 && report.total > 0
                    ? "датчик не зафиксировал расход"
                    : report.status === "warn"
                      ? "есть расхождение"
                      : report.discrepancyLiters === 0
                        ? "совпадает с датчиком"
                        : "в пределах допуска"}
              </em>
            </div>
          </>
        ) : null}
      </div>

      <div className="col-grid" style={{ marginBottom: 16 }}>
        {report.columns.map((column) => (
          <article className="column-card" key={column.number}>
            <div className="card-head-inline" style={{ marginBottom: 6 }}>
              <h3 style={{ margin: 0 }}>
                {column.name} ({column.code})
              </h3>
            </div>
            <p className="stage-vol" style={{ marginBottom: 10 }}>
              {report.source === "edge" ? "Отпуск ТРК:" : "Уход газа:"}{" "}
              <strong>{liters(column.total)}</strong>
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
            </dl>
          </article>
        ))}
      </div>

      <h3 style={{ marginTop: 0 }}>Отпуск по колонкам</h3>
      <div className="dash-table-wrap" style={{ marginBottom: 18 }}>
        <table className="dash-table">
          <thead>
            <tr>
              <th>Колонка</th>
              <th>Операций</th>
              <th>Последний отпуск</th>
              <th>{report.source === "edge" ? "Счётчик ТРК" : "Расчётный отпуск (по уровню)"}</th>
            </tr>
          </thead>
          <tbody>
            {report.columns.map((column) => (
              <tr key={column.number}>
                <td>
                  <strong>
                    {column.name} ({column.code})
                  </strong>
                </td>
                <td>{column.opsCount}</td>
                <td className="dash-muted">
                  {column.lastLiters != null
                    ? `${liters(column.lastLiters)}${column.lastAt ? ` · ${dateTime(column.lastAt)}` : ""}`
                    : "нет данных"}
                </td>
                <td>
                  <strong>{liters(column.total)}</strong>
                </td>
              </tr>
            ))}
            <tr className="dash-total">
              <td>Итого</td>
              <td>{report.opsTotal}</td>
              <td />
              <td>{liters(report.total)}</td>
            </tr>
            {report.source === "edge" ? (
              <tr>
                <td colSpan={3} className="dash-muted">
                  Уход газа из резервуара (по датчику уровня)
                </td>
                <td>
                  {report.tankOutflowLiters != null ? (
                    <>
                      <strong>{liters(report.tankOutflowLiters)}</strong>
                      {report.discrepancyLiters != null ? (
                        <div className={report.status === "warn" ? "text-danger" : "dash-muted"}>
                          разница: {signedLiters(report.discrepancyLiters)}
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <span className="dash-muted">нет данных</span>
                  )}
                </td>
              </tr>
            ) : null}
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
          {effectiveMode === "edge"
            ? "Режим реальных ТРК (station-edge): наливов за выбранный период не поступало."
            : "За этот срок уровень резервуара не снижался. Отпуска через колонки нет."}
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
