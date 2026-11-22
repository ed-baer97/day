import assert from "node:assert/strict";
import type { DispenseReading, LevelReading } from "./src/api/client";
import {
  buildLiveTankSamples,
  columnDispenseReport,
  isColumnReportStation,
  stationColumnCount,
} from "./src/columnReport";
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
assert.equal(
  isColumnReportStation({ code: "AGZS-AKT-12", name: "REKON", columns_mode: "none" }),
  false,
);
assert.equal(
  isColumnReportStation({ code: "AGZS-FILE", name: "Жетыбай", columns_mode: "virtual" }),
  true,
);
assert.equal(
  isColumnReportStation({ code: "AGZS-FILE", name: "Жетыбай", columns_mode: "edge" }),
  true,
);
assert.equal(stationColumnCount({}), 2);
assert.equal(stationColumnCount({ columns_count: 4 }), 4);
assert.equal(stationColumnCount({ columns_count: 12 }), 8);

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

assert.equal(report.source, "edge");
assert.equal(report.columnCount, 2);
assert.equal(report.columns[0].total, 0);
assert.equal(report.columns[1].total, 0);
assert.equal(report.total, 0);
assert.equal(report.tankOutflowLiters, 0);
assert.equal(report.discrepancyLiters, 0);
assert.equal(report.status, "ok");
assert.equal(report.opsTotal, 0);

const fallbackSamples = buildLiveTankSamples(
  {
    tanks: [
      {
        code: "R-1",
        remainder_liters: 9800,
        measured_at: new Date(2026, 10, 18, 8, 20, 0).toISOString(),
      },
    ],
  },
  [],
  [reading(new Date(2026, 10, 18, 1, 0, 0), 10000, null, "tank-r1")],
  true,
);
assert.equal(fallbackSamples.length, 1);
assert.equal(fallbackSamples[0].tankId, "tank-r1");

const fallbackReport = columnDispenseReport(
  [reading(new Date(2026, 10, 18, 1, 0, 0), 10000, null)],
  today,
  [],
  now,
  251,
);
assert.equal(fallbackReport.columns[0].total, 0);
assert.equal(fallbackReport.columns[1].total, 0);
assert.equal(fallbackReport.total, 0);
assert.equal(fallbackReport.tankOutflowLiters, 251);
assert.equal(fallbackReport.discrepancyLiters, -251);
assert.equal(fallbackReport.status, "ok");
assert.match(fallbackReport.sensorNote, /вне полосы/);
assert.equal(fallbackReport.opsTotal, 0);

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
assert.equal(outside.source, "edge");

const realDispenses: DispenseReading[] = [
  {
    id: "d-1",
    station_id: "st-1",
    tank_id: "tank-r1",
    dispenser_id: "disp-1",
    pump_address: 1,
    mode: "dose",
    volume_liters: 20,
    price_kzt_per_liter: 72,
    started_at: new Date(2026, 10, 18, 2, 10, 0).toISOString(),
    finished_at: new Date(2026, 10, 18, 2, 11, 0).toISOString(),
    external_txn_id: "aska-1",
  },
  {
    id: "d-2",
    station_id: "st-1",
    tank_id: "tank-r1",
    dispenser_id: "disp-2",
    pump_address: 2,
    mode: "full_tank",
    volume_liters: 12.75,
    price_kzt_per_liter: 72,
    started_at: new Date(2026, 10, 18, 4, 20, 0).toISOString(),
    finished_at: new Date(2026, 10, 18, 4, 21, 0).toISOString(),
    external_txn_id: "aska-2",
  },
];
const edgeReport = columnDispenseReport([], today, [], now, 0, realDispenses);
assert.equal(edgeReport.source, "edge");
assert.equal(edgeReport.columns[0].total, 20);
assert.equal(edgeReport.columns[1].total, 12.75);
assert.equal(edgeReport.total, 32.75);
assert.equal(edgeReport.opsTotal, 2);

const strictEdgeEmpty = columnDispenseReport(
  [
    reading(new Date(2026, 10, 18, 1, 0, 0), 10000, null),
    reading(new Date(2026, 10, 18, 2, 10, 0), 9700, -300),
  ],
  today,
  [],
  now,
  300,
  [],
  { columnCount: 3, mode: "edge" },
);
assert.equal(strictEdgeEmpty.source, "edge");
assert.equal(strictEdgeEmpty.columnCount, 3);
assert.equal(strictEdgeEmpty.total, 0);
assert.equal(strictEdgeEmpty.tankOutflowLiters, 300);
assert.equal(strictEdgeEmpty.discrepancyLiters, -300);
assert.equal(strictEdgeEmpty.status, "warn");
assert.equal(strictEdgeEmpty.sensorNote, "уход без колонки");

const virtualFourCols = columnDispenseReport(
  [reading(new Date(2026, 10, 18, 1, 0, 0), 10000, null)],
  today,
  [],
  now,
  400,
  [],
  { columnCount: 4, mode: "virtual" },
);
assert.equal(virtualFourCols.source, "edge");
assert.equal(virtualFourCols.columnCount, 4);
assert.equal(virtualFourCols.total, 0);
assert.equal(virtualFourCols.tankOutflowLiters, 400);
assert.equal(virtualFourCols.columns[3].total, 0);

const zeroSensorEdge = columnDispenseReport(
  [],
  today,
  [],
  now,
  0,
  [
    {
      ...realDispenses[0],
      id: "d-zero-1",
      volume_liters: 80,
      external_txn_id: "aska-zero-1",
    },
  ],
  { columnCount: 2, mode: "edge", sensorOutflowLiters: 0 },
);
assert.equal(zeroSensorEdge.source, "edge");
assert.equal(zeroSensorEdge.total, 80);
assert.equal(zeroSensorEdge.tankOutflowLiters, 0);
assert.equal(zeroSensorEdge.discrepancyLiters, 80);
assert.equal(zeroSensorEdge.status, "ok");
assert.match(zeroSensorEdge.sensorNote, /ориентир/);

const silentSensorEdge = columnDispenseReport([], today, [], now, 0, realDispenses, {
  columnCount: 2,
  mode: "edge",
  sensorOutflowLiters: null,
});
assert.equal(silentSensorEdge.source, "edge");
assert.equal(silentSensorEdge.total, 32.75);
assert.equal(silentSensorEdge.tankOutflowLiters, null);
assert.equal(silentSensorEdge.discrepancyLiters, null);
assert.equal(silentSensorEdge.status, "ok");
assert.equal(silentSensorEdge.sensorNote, "датчик недоступен");

const silentSensorIdle = columnDispenseReport([], today, [], now, 0, [], {
  columnCount: 2,
  mode: "edge",
  sensorOutflowLiters: null,
});
assert.equal(silentSensorIdle.tankOutflowLiters, null);
assert.equal(silentSensorIdle.discrepancyLiters, null);
assert.equal(silentSensorIdle.status, "ok");

const zeroSensorUnder50 = columnDispenseReport(
  [],
  today,
  [],
  now,
  0,
  [
    {
      ...realDispenses[0],
      id: "d-zero-40",
      volume_liters: 40,
      external_txn_id: "aska-zero-40",
    },
  ],
  { columnCount: 2, mode: "edge", sensorOutflowLiters: 0 },
);
assert.equal(zeroSensorUnder50.total, 40);
assert.equal(zeroSensorUnder50.tankOutflowLiters, 0);
assert.equal(zeroSensorUnder50.discrepancyLiters, 40);
assert.equal(zeroSensorUnder50.status, "ok");

const zeroSensorIdle = columnDispenseReport([], today, [], now, 0, [], {
  columnCount: 2,
  mode: "edge",
  sensorOutflowLiters: 0,
});
assert.equal(zeroSensorIdle.tankOutflowLiters, 0);
assert.equal(zeroSensorIdle.discrepancyLiters, 0);
assert.equal(zeroSensorIdle.status, "ok");

const activeSensorWithinTolerance = columnDispenseReport(
  [],
  today,
  [],
  now,
  0,
  [
    {
      ...realDispenses[0],
      id: "d-act-140",
      volume_liters: 140,
      external_txn_id: "aska-act-140",
    },
  ],
  { columnCount: 2, mode: "edge", sensorOutflowLiters: 100 },
);
assert.equal(activeSensorWithinTolerance.total, 140);
assert.equal(activeSensorWithinTolerance.tankOutflowLiters, 100);
assert.equal(activeSensorWithinTolerance.discrepancyLiters, 40);
assert.equal(activeSensorWithinTolerance.status, "ok");

const activeSensorOverTolerance = columnDispenseReport(
  [],
  today,
  [],
  now,
  0,
  [
    {
      ...realDispenses[0],
      id: "d-act-160",
      volume_liters: 160,
      external_txn_id: "aska-act-160",
    },
  ],
  { columnCount: 2, mode: "edge", sensorOutflowLiters: 100 },
);
assert.equal(activeSensorOverTolerance.total, 160);
assert.equal(activeSensorOverTolerance.tankOutflowLiters, 100);
assert.equal(activeSensorOverTolerance.discrepancyLiters, 60);
assert.equal(activeSensorOverTolerance.status, "ok");

console.log("columnReport.check ok");
