import { useMemo } from "react";
import type { LevelReading, TankDevice } from "../api/client";
import {
  bucketCaption,
  columnDispenseReport,
  type LiveTankSample,
} from "../columnReport";
import { liters } from "../format";
import type { LiveLevel } from "../liveLevels";
import type { TimeRange } from "../period";
import { BarChart } from "./Charts";

export default function ColumnReportCard({
  points,
  range,
  devices,
  live,
  loading,
}: {
  points: LevelReading[];
  range: TimeRange;
  devices: TankDevice[];
  live: LiveLevel | null;
  loading: boolean;
}) {
  const liveTanks = useMemo(() => {
    if (!range.includesNow || !live) return [] as LiveTankSample[];
    const samples: LiveTankSample[] = [];
    for (const tank of live.tanks) {
      const device = devices.find((item) => item.code === tank.code);
      if (!device || tank.remainder_liters == null) continue;
      samples.push({
        tankId: device.id,
        remainder: tank.remainder_liters,
        measuredAt: tank.measured_at,
      });
    }
    return samples;
  }, [devices, live, range.includesNow]);

  const report = useMemo(
    () => columnDispenseReport(points, range, liveTanks),
    [points, range, liveTanks],
  );
  const rows = report.labels
    .map((label, index) => ({ label, index, total: report.totals[index] ?? 0 }))
    .filter((row) => row.total > 0);

  return (
    <section className="dash-card" style={{ marginBottom: 18 }}>
      <div className="card-head-inline">
        <h3>Колонки</h3>
        <span className="badge ok">подключены {report.columnCount} колонки</span>
      </div>
      <p className="dash-muted">
        Отпуск для отчёта берётся из снижения газа в резервуаре и раскладывается по колонкам.
        Колонка только отпускает газ: в расход попадает уменьшение уровня.
      </p>
      <div className="dash-kpis" style={{ marginBottom: 16 }}>
        {report.columns.map((column) => (
          <div className="dash-kpi" key={column.number}>
            <span>{column.name}</span>
            <strong>{liters(column.total)}</strong>
            <em>подключена · только отпуск</em>
          </div>
        ))}
        <div className="dash-kpi">
          <span>Отпуск за срок</span>
          <strong>{loading && points.length === 0 ? "…" : liters(report.total)}</strong>
          <em>сумма двух колонок, литры</em>
        </div>
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
