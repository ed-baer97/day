import assert from "node:assert/strict";
import type { LevelReading } from "./src/api/client";
import { isLowFill, LOW_FILL_PERCENT, summarizeLevel } from "./src/liveLevels";
import { resolveRange, shiftPeriod, todayPeriod } from "./src/period";
import { chartOf, spanFromReadings, withLiveRemainder } from "./src/sensorDay";

function reading(stamp: Date, liters: number): LevelReading {
  return {
    id: String(stamp.getTime()),
    tank_id: "t",
    volts: null,
    remainder_liters: liters,
    fill_percent: null,
    recorded_at: stamp.toISOString(),
    delta_liters: null,
  };
}

const now = new Date(2026, 10, 4, 8, 30, 0);
const today = resolveRange(todayPeriod(now), now);
const day = spanFromReadings(
  [
    reading(new Date(2026, 10, 4, 1, 0, 0), 6700),
    reading(new Date(2026, 10, 4, 2, 0, 0), 6400),
    reading(new Date(2026, 10, 4, 3, 0, 0), 6700),
    reading(new Date(2026, 10, 4, 4, 0, 0), 6500),
  ],
  today,
  now
);

assert.equal(day.opening, 6700);
assert.equal(day.closing, 6500);
assert.equal(day.outflow, 200);
assert.equal(day.series[4], 6500);
assert.equal(day.series[8], 6500);
assert.equal(day.series[9], null);

const live = withLiveRemainder(day, 6400, now);
assert.equal(live.series[8], 6400);
assert.equal(live.closing, 6400);
assert.equal(live.outflow, 300);
assert.equal(live.series[4], 6500);
assert.equal(day.series[8], 6500);
assert.equal(withLiveRemainder(day, null, now), day);

const past = resolveRange({ preset: "day", day: "2026-11-03" }, now);
const pastSpan = spanFromReadings([reading(new Date(2026, 10, 3, 12, 0, 0), 7000)], past, now);
assert.equal(past.includesNow, false);
assert.equal(past.countsReceipts, false);
assert.equal(withLiveRemainder(pastSpan, 1000, now).closing, 7000);
assert.equal(pastSpan.series[12], 7000);
assert.equal(pastSpan.series[23], 7000);

const week = resolveRange({ preset: "week", day: "2026-11-04" }, now);
assert.equal(week.labels.length, 7);
assert.equal(week.labels[0], "пн 2");
assert.equal(week.labels[2], "ср 4");
assert.equal(week.includesNow, true);
const weekSpan = spanFromReadings(
  [reading(new Date(2026, 10, 2, 10, 0, 0), 1000), reading(new Date(2026, 10, 4, 8, 0, 0), 800)],
  week,
  now
);
assert.equal(weekSpan.opening, 1000);
assert.equal(weekSpan.closing, 800);
assert.equal(weekSpan.outflow, 200);
assert.equal(weekSpan.series[0], 1000);
assert.equal(weekSpan.series[1], 1000);
assert.equal(weekSpan.series[2], 800);
assert.equal(weekSpan.series[3], null);
assert.deepEqual(chartOf(weekSpan.series, weekSpan.labels).labels, ["пн 2", "вт 3", "ср 4"]);

const month = resolveRange({ preset: "month", day: "2026-10-15" }, now);
assert.equal(month.includesNow, false);
assert.equal(month.labels.length, 31);
assert.equal(shiftPeriod({ preset: "month", day: "2026-10-15" }, 1, now).day, "2026-11-01");
assert.equal(shiftPeriod({ preset: "day", day: "2026-11-06" }, 1, now).day, "2026-11-04");

const summary = summarizeLevel({
  code: "A",
  name: "АГЗС",
  address: null,
  lat: 0,
  lon: 0,
  tanks: [
    {
      code: "1",
      capacity_liters: 10000,
      remainder_liters: 6400,
      fill_percent: 64,
      measured_at: null,
      online: true,
    },
  ],
});
assert.equal(summary.remainder, 6400);
assert.equal(withLiveRemainder(day, summary.remainder, now).series[8], summary.remainder);
assert.equal(isLowFill(summary.fill), false);
assert.equal(isLowFill(LOW_FILL_PERCENT - 1), true);
assert.equal(isLowFill(LOW_FILL_PERCENT), false);
assert.equal(isLowFill(null), false);

console.log("level source ok");
