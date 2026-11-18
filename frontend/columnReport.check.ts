import assert from "node:assert/strict";
import type { LevelReading } from "./src/api/client";
import { columnDispenseReport, isColumnReportStation } from "./src/columnReport";
import { resolveRange, todayPeriod } from "./src/period";

function reading(stamp: Date, liters: number, delta: number | null, tank = "tank-r1"): LevelReading {
  return {
    id: String(stamp.getTime()),
    tank_id: tank,
    volts: null,
    remainder_liters: liters,
    fill_percent: null,
    recorded_at: stamp.toISOString(),
    delta_liters: delta,
  };
}

const now = new Date(2026, 10, 18, 8, 30, 0);
const today = resolveRange(todayPeriod(now), now);

assert.equal(isColumnReportStation({ code: "AGZS-AKT-12", name: "REKON" }), true);
assert.equal(isColumnReportStation({ code: "AKT-12MKR", name: "Актау" }), true);
assert.equal(isColumnReportStation({ code: "AGZS-FILE", name: "Жетыбай" }), false);

const report = columnDispenseReport(
  [
    reading(new Date(2026, 10, 18, 1, 0, 0), 10000, null),
    reading(new Date(2026, 10, 18, 2, 10, 0), 9700, -300),
    reading(new Date(2026, 10, 18, 3, 0, 0), 10200, 500),
    reading(new Date(2026, 10, 18, 4, 20, 0), 10000, -200),
    reading(new Date(2026, 10, 18, 5, 0, 0), 9999.4, -0.6),
  ],
  today,
  [{ tankId: "tank-r1", remainder: 9800, measuredAt: new Date(2026, 10, 18, 8, 20, 0).toISOString() }],
  now,
);

assert.equal(report.columnCount, 2);
assert.equal(report.columns[0].total, 499);
assert.equal(report.columns[1].total, 200);
assert.equal(report.total, 699);
assert.equal(report.columns[0].liters[2], 300);
assert.equal(report.columns[1].liters[4], 200);
assert.equal(report.columns[0].liters[8], 199);
assert.equal(report.totals[3], 0);
assert.equal(
  report.columns.reduce((sum, column) => sum + column.total, 0),
  report.total,
);

const riseOnly = columnDispenseReport(
  [
    reading(new Date(2026, 10, 18, 6, 0, 0), 8000, null),
    reading(new Date(2026, 10, 18, 7, 0, 0), 9000, 1000),
  ],
  today,
  [{ tankId: "tank-r1", remainder: 9500, measuredAt: new Date(2026, 10, 18, 8, 0, 0).toISOString() }],
  now,
);
assert.equal(riseOnly.total, 0);

const outside = columnDispenseReport(
  [reading(new Date(2026, 10, 17, 12, 0, 0), 5000, -400)],
  today,
);
assert.equal(outside.total, 0);

console.log("columnReport.check ok");
