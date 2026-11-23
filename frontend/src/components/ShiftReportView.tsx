import type { ShiftDetail, ShiftRecord, ShiftTankSnapshot } from "../api/client";
import {
  dateTime,
  dateTimeSeconds,
  dispenseModeLabel,
  liters,
  litersPrecise,
  signedLiters,
  tenge,
} from "../format";
import { sensorCue } from "../sensorBand";

function formatDuration(startIso: string, endIso?: string | null): string {
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  const diffMin = Math.max(0, Math.round((end - start) / 60000));
  const hours = Math.floor(diffMin / 60);
  const mins = diffMin % 60;
  if (hours === 0) return `${mins} мин`;
  return `${hours} ч ${mins} мин`;
}

function renderTankSnapshotLines(tanks: ShiftTankSnapshot[]) {
  if (!tanks || tanks.length === 0) return null;
  return (
    <div className="shift-tank-sublist">
      {tanks.map((tank) => (
        <span key={tank.tank_id} className="dash-muted">
          {tank.code}:{" "}
          {tank.remainder_liters == null
            ? "нет замера"
            : `${liters(tank.remainder_liters)}${tank.fill_percent != null ? ` (${Math.round(tank.fill_percent)}%)` : ""}`}
        </span>
      ))}
    </div>
  );
}

function csvCell(value: string | number | null | undefined): string {
  const text = value == null ? "" : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

export default function ShiftReportView({
  report,
  stationName,
  stationCode,
  onClose,
}: {
  report: ShiftDetail | ShiftRecord;
  stationName?: string;
  stationCode?: string;
  onClose?: () => void;
}) {
  const isOpen = report.status === "open";
  const dispenses = "dispenses" in report && Array.isArray(report.dispenses) ? report.dispenses : [];
  const labelName = stationName ?? report.station_name ?? "АГЗС";
  const labelCode = stationCode ?? report.station_code ?? "";
  const shiftTanks = report.closing_tanks?.length ? report.closing_tanks : report.opening_tanks;
  const shiftCapacity = (shiftTanks ?? []).reduce((sum, tank) => sum + (tank.capacity_liters || 0), 0);
  const sensor = sensorCue({
    discrepancyLiters: report.discrepancy_liters ?? null,
    outflowLiters: report.tank_delta_liters ?? null,
    dispensedLiters: report.dispensed_liters,
    capacityLiters: shiftCapacity > 0 ? shiftCapacity : null,
  });

  function downloadCsv() {
    const lines: string[] = [];
    lines.push(
      [
        "Отчёт по смене",
        labelName,
        labelCode,
        isOpen ? "Открыта" : "Закрыта",
      ]
        .map(csvCell)
        .join(";")
    );
    lines.push(["Открыл", report.opened_by, "Открыта", report.opened_at].map(csvCell).join(";"));
    lines.push(
      [
        "Закрыл",
        report.closed_by ?? "",
        "Закрыта",
        report.closed_at ?? "",
      ]
        .map(csvCell)
        .join(";")
    );
    lines.push(
      [
        "Цистерна начало (л)",
        report.opening_tank_liters ?? "",
        "Приход (л)",
        report.receipts_liters,
        isOpen ? "Цистерна сейчас (л)" : "Цистерна конец (л)",
        report.closing_tank_liters ?? "",
        "Уход по цистерне (л)",
        report.tank_delta_liters ?? "",
        "Разница ТРК - цистерна (л)",
        report.discrepancy_liters ?? "",
      ]
        .map(csvCell)
        .join(";")
    );
    lines.push("");
    lines.push(["Колонка", "Код", "Операций", "Объём (л)", "Сумма (KZT)"].map(csvCell).join(";"));
    for (const col of report.columns) {
      lines.push(
        [col.name, col.code, col.ops_count, col.volume_liters, col.amount_kzt ?? ""]
          .map(csvCell)
          .join(";")
      );
    }
    lines.push(
      [
        "ИТОГО",
        "",
        report.dispense_count,
        report.dispensed_liters,
        report.total_amount_kzt ?? "",
      ]
        .map(csvCell)
        .join(";")
    );
    if (dispenses.length > 0) {
      lines.push("");
      lines.push(
        ["Время", "Колонка", "Режим", "Объём (л)", "Цена (KZT/л)", "Сумма (KZT)"]
          .map(csvCell)
          .join(";")
      );
      for (const item of dispenses) {
        const amount =
          item.price_kzt_per_liter != null
            ? Math.round(item.volume_liters * item.price_kzt_per_liter * 100) / 100
            : "";
        lines.push(
          [
            item.finished_at ?? item.started_at,
            item.pump_address ? `ТРК-${item.pump_address}` : item.dispenser_id,
            item.mode ?? "",
            item.volume_liters,
            item.price_kzt_per_liter ?? "",
            amount,
          ]
            .map(csvCell)
            .join(";")
        );
      }
    }

    const blob = new Blob(["\uFEFF" + lines.join("\r\n")], {
      type: "text/csv;charset=utf-8;",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const dayTag = report.opened_at.slice(0, 10);
    link.href = url;
    link.download = `shift-report-${labelCode || report.station_id}-${dayTag}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  return (
    <section className="dash-card shift-report-sheet" aria-label="Отчёт о смене">
      <div className="card-head-inline" style={{ marginBottom: 12 }}>
        <div>
          <span className={`badge ${isOpen ? "warn" : "ok"}`}>
            {isOpen ? "Смена открыта — предварительный отчёт" : "Смена закрыта — итоговый отчёт"}
          </span>
          <h3 style={{ margin: "6px 0 2px" }}>
            Отчёт о смене · {labelName}
            {labelCode ? ` (${labelCode})` : ""}
          </h3>
          <p className="dash-muted" style={{ margin: 0 }}>
            Открыл: <strong>{report.opened_by}</strong> ({dateTime(report.opened_at)})
            {report.closed_at ? (
              <>
                {" · "}Закрыл: <strong>{report.closed_by ?? "—"}</strong> ({dateTime(report.closed_at)})
              </>
            ) : null}
            {" · "}Длительность: <strong>{formatDuration(report.opened_at, report.closed_at)}</strong>
          </p>
        </div>
        <div className="no-print" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          <button type="button" className="btn secondary small" onClick={() => window.print()}>
            Печать / PDF
          </button>
          <button type="button" className="btn secondary small" onClick={downloadCsv}>
            Скачать CSV
          </button>
          {onClose ? (
            <button type="button" className="btn secondary small" onClick={onClose}>
              Скрыть отчёт
            </button>
          ) : null}
        </div>
      </div>

      <div className="dash-kpis" style={{ marginBottom: 16 }}>
        <div className="dash-kpi">
          <span>Цистерна на начало смены</span>
          <strong>{liters(report.opening_tank_liters)}</strong>
          {renderTankSnapshotLines(report.opening_tanks)}
        </div>
        <div className="dash-kpi">
          <span>Приход за смену</span>
          <strong>{liters(report.receipts_liters)}</strong>
          <em>сливы газовозов за период смены</em>
        </div>
        <div className="dash-kpi">
          <span>{isOpen ? "Цистерна сейчас" : "Цистерна на конец смены"}</span>
          <strong>{liters(report.closing_tank_liters)}</strong>
          {renderTankSnapshotLines(report.closing_tanks)}
        </div>
        <div className="dash-kpi">
          <span>Уход по цистерне</span>
          <strong>{report.tank_delta_liters == null ? "—" : liters(report.tank_delta_liters)}</strong>
          <em>начало + приход − {isOpen ? "текущий" : "конец"}</em>
        </div>
      </div>

      <div className="fiscal-chain" style={{ marginBottom: 16 }}>
        <div className="fiscal-step">
          <span>Отпуск по колонкам (ТРК)</span>
          <strong>{litersPrecise(report.dispensed_liters)}</strong>
          <em>
            операций: {report.dispense_count}
            {report.total_amount_kzt != null ? ` · ${tenge(report.total_amount_kzt)}` : ""}
          </em>
        </div>
        <div className="fiscal-link">↔</div>
        <div className="fiscal-step">
          <span>Уход по датчику цистерны</span>
          <strong>
            {report.tank_delta_liters == null ? "нет данных" : litersPrecise(report.tank_delta_liters)}
          </strong>
          <em>ориентир, не учёт продажи</em>
        </div>
        <div className="fiscal-link">=</div>
        <div className="fiscal-step">
          <span>Ориентир датчика</span>
          <strong className={sensor.status === "warn" ? "text-danger" : ""}>
            {report.discrepancy_liters == null ? "—" : signedLiters(report.discrepancy_liters)}
          </strong>
          <em>{sensor.note}</em>
        </div>
      </div>

      <h4 style={{ margin: "0 0 8px" }}>Расход по колонкам за смену</h4>
      {report.columns.length === 0 ? (
        <p className="dash-muted">Для АГЗС колонки не настроены и наливы не поступали.</p>
      ) : (
        <div className="dash-table-wrap" style={{ marginBottom: 16 }}>
          <table className="dash-table">
            <thead>
              <tr>
                <th>Колонка</th>
                <th>Операций</th>
                <th>Фактический расход</th>
                <th>Сумма</th>
                <th>Последний отпуск</th>
              </tr>
            </thead>
            <tbody>
              {report.columns.map((col) => (
                <tr key={col.pump_address}>
                  <td>
                    <strong>
                      {col.name} ({col.code})
                    </strong>
                  </td>
                  <td>{col.ops_count}</td>
                  <td>
                    <strong>{litersPrecise(col.volume_liters)}</strong>
                  </td>
                  <td>{col.amount_kzt != null ? tenge(col.amount_kzt) : "—"}</td>
                  <td className="dash-muted">
                    {col.last_liters != null
                      ? `${litersPrecise(col.last_liters)}${col.last_at ? ` · ${dateTimeSeconds(col.last_at)}` : ""}`
                      : "наливов не было"}
                  </td>
                </tr>
              ))}
              <tr className="dash-total">
                <td>Итого за смену</td>
                <td>{report.dispense_count}</td>
                <td>{litersPrecise(report.dispensed_liters)}</td>
                <td>{report.total_amount_kzt != null ? tenge(report.total_amount_kzt) : "—"}</td>
                <td />
              </tr>
            </tbody>
          </table>
        </div>
      )}

      {report.note ? (
        <p className="dash-muted" style={{ marginBottom: 14 }}>
          Примечание кассира: <strong>{report.note}</strong>
        </p>
      ) : null}

      {dispenses.length > 0 ? (
        <>
          <h4 style={{ margin: "0 0 8px" }}>Операции отпуска за смену ({dispenses.length})</h4>
          <div className="dash-table-wrap">
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Время</th>
                  <th>Колонка</th>
                  <th>Режим</th>
                  <th>Объём</th>
                  <th>Цена / Сумма</th>
                </tr>
              </thead>
              <tbody>
                {dispenses.map((item) => {
                  const amount =
                    item.price_kzt_per_liter != null
                      ? item.volume_liters * item.price_kzt_per_liter
                      : null;
                  return (
                    <tr key={item.id}>
                      <td>{dateTimeSeconds(item.finished_at ?? item.started_at)}</td>
                      <td>
                        <strong>
                          {item.pump_address ? `ТРК-${item.pump_address}` : "ТРК"}
                        </strong>
                      </td>
                      <td className="dash-muted">{dispenseModeLabel(item.mode)}</td>
                      <td>
                        <strong>{litersPrecise(item.volume_liters)}</strong>
                      </td>
                      <td>
                        {item.price_kzt_per_liter != null
                          ? `${item.price_kzt_per_liter} ₸/л · ${amount != null ? tenge(amount) : ""}`
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </section>
  );
}
