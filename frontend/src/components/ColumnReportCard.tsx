import { useEffect, useMemo, useState } from "react";
import type { ColumnsMode, DispenseReading, LevelReading, TankDevice } from "../api/client";
import {
  bucketCaption,
  buildLiveTankSamples,
  columnDispenseReport,
  type ColumnOperation,
  type ColumnReport,
} from "../columnReport";
import {
  dateTimeSeconds,
  dispenseModeLabel,
  liters,
  litersPrecise,
  signedLiters,
  tenge,
  timeHMS,
} from "../format";
import type { LiveLevel } from "../liveLevels";
import type { TimeRange } from "../period";
import { BarChart } from "./Charts";
import PeriodSwitch from "./PeriodSwitch";

const OPS_PREVIEW_LIMIT = 100;
const COLUMN_COLORS = ["var(--sea)", "var(--dust)", "var(--coral)", "var(--ok)"];

function operationStartNote(op: ColumnOperation): string | null {
  if (!op.finishedAt) return null;
  const startedMs = new Date(op.startedAt).getTime();
  if (!Number.isFinite(startedMs) || op.occurredAtMs - startedMs < 1000) return null;
  if (new Date(startedMs).toDateString() === new Date(op.occurredAtMs).toDateString()) {
    return `начало ${timeHMS(op.startedAt)}`;
  }
  return `начало ${dateTimeSeconds(op.startedAt)}`;
}

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
  const [showAllOps, setShowAllOps] = useState(false);
  const rangeResetKey = `${range.preset}:${range.start.getTime()}:${range.end.getTime()}`;
  useEffect(() => {
    setShowAllOps(false);
  }, [rangeResetKey]);

  const effectiveMode = columnsMode ?? (report.source === "edge" ? "edge" : "virtual");
  const visibleOps = showAllOps
    ? report.operations
    : report.operations.slice(0, OPS_PREVIEW_LIMIT);

  return (
    <section className="dash-card" style={{ marginBottom: 18 }}>
      <div className="card-head-inline">
        <h3>Колонки · {range.title}</h3>
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
      <div className="column-report-period">
        <PeriodSwitch />
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
          <em>ориентир датчика</em>
        </div>
        <div className="fiscal-link">→</div>
        <div className="fiscal-step">
          <span>Счётчики ТРК ({report.columnCount})</span>
          <strong>
            {loading && points.length === 0 && report.opsTotal === 0
              ? "…"
              : litersPrecise(report.total)}
          </strong>
          <em>
            {report.columns
              .map((column) => `${column.name}: ${litersPrecise(column.total)}`)
              .join(" · ")}
          </em>
        </div>
        {report.source === "edge" ? (
          <>
            <div className="fiscal-link">=</div>
            <div className="fiscal-step">
              <span>Ориентир датчика</span>
              <strong className={report.status === "warn" ? "text-danger" : ""}>
                {report.discrepancyLiters != null ? signedLiters(report.discrepancyLiters) : "—"}
              </strong>
              <em>{report.sensorNote}</em>
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
              Отпуск ТРК:{" "}
              <strong>{litersPrecise(column.total)}</strong>
            </p>
            <dl className="kv">
              <dt>Операций отпуска</dt>
              <dd>{column.opsCount}</dd>
              <dt>Последний отпуск</dt>
              <dd>
                {column.lastLiters != null
                  ? `${litersPrecise(column.lastLiters)}${column.lastAt ? ` · ${dateTimeSeconds(column.lastAt)}` : ""}`
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
              <th>Счётчик ТРК</th>
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
                    ? `${litersPrecise(column.lastLiters)}${column.lastAt ? ` · ${dateTimeSeconds(column.lastAt)}` : ""}`
                    : "нет данных"}
                </td>
                <td>
                  <strong>{litersPrecise(column.total)}</strong>
                </td>
              </tr>
            ))}
            <tr className="dash-total">
              <td>Итого</td>
              <td>{report.opsTotal}</td>
              <td />
              <td>{litersPrecise(report.total)}</td>
            </tr>
            {report.source === "edge" ? (
              <tr>
                <td colSpan={3} className="dash-muted">
                  Датчик резервуара (ориентир)
                </td>
                <td>
                  {report.tankOutflowLiters != null ? (
                    <>
                      <strong>{liters(report.tankOutflowLiters)}</strong>
                      {report.discrepancyLiters != null ? (
                        <div className={report.status === "warn" ? "text-danger" : "dash-muted"}>
                          {signedLiters(report.discrepancyLiters)} · {report.sensorNote}
                        </div>
                      ) : (
                        <div className="dash-muted">{report.sensorNote}</div>
                      )}
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

      <h3 style={{ marginTop: 0 }}>Заправки за период ({report.operations.length})</h3>
      {loading && points.length === 0 && report.opsTotal === 0 ? (
        <p className="dash-muted">Загрузка данных по колонкам…</p>
      ) : report.operations.length === 0 ? (
        <p className="dash-muted">За этот срок наливов с колонок не было.</p>
      ) : (
        <>
          <div className="dash-table-wrap" style={{ maxHeight: 460 }}>
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Время заправки</th>
                  <th>Колонка</th>
                  <th>Режим</th>
                  <th>Объём</th>
                  <th>Цена / Сумма</th>
                </tr>
              </thead>
              <tbody>
                {visibleOps.map((op) => {
                  const startNote = operationStartNote(op);
                  return (
                    <tr key={op.id}>
                      <td style={{ whiteSpace: "nowrap" }}>
                        <div>{dateTimeSeconds(op.occurredAt)}</div>
                        {startNote ? <div className="dash-muted">{startNote}</div> : null}
                      </td>
                      <td>
                        <strong>
                          {op.columnName} ({op.columnCode})
                        </strong>
                      </td>
                      <td className="dash-muted">{dispenseModeLabel(op.mode)}</td>
                      <td>
                        <strong>{litersPrecise(op.volumeLiters)}</strong>
                      </td>
                      <td>
                        {op.priceKztPerLiter != null
                          ? `${op.priceKztPerLiter} ₸/л · ${op.amountKzt != null ? tenge(op.amountKzt) : ""}`
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {report.operations.length > OPS_PREVIEW_LIMIT ? (
            <div style={{ marginTop: 8 }}>
              <button
                type="button"
                className="btn secondary small"
                onClick={() => setShowAllOps((prev) => !prev)}
              >
                {showAllOps
                  ? `Свернуть до ${OPS_PREVIEW_LIMIT}`
                  : `Показать все (${report.operations.length})`}
              </button>
            </div>
          ) : null}
        </>
      )}

      {report.total > 0 ? (
        <>
          <h3 style={{ marginTop: 18 }}>
            {range.preset === "today" || range.preset === "day"
              ? "График расхода по часам"
              : "График расхода по дням"}
          </h3>
          <BarChart
            labels={report.labels.map((label) => bucketCaption(range, label))}
            series={report.columns.map((column, index) => ({
              name: column.name,
              color: COLUMN_COLORS[index % COLUMN_COLORS.length],
              values: column.liters,
            }))}
          />
        </>
      ) : null}
    </section>
  );
}
