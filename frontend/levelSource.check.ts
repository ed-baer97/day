import assert from "node:assert/strict";
import type { LevelReading } from "./src/api/client";
import { isLowFill, LOW_FILL_PERCENT, summarizeLevel } from "./src/liveLevels";
import { sensorDayFromReadings, withLiveRemainder } from "./src/sensorDay";

function reading(hour: number, liters: number): LevelReading {
  return {
    id: String(hour),
    tank_id: "t",
    volts: null,
    remainder_liters: liters,
    fill_percent: null,
    recorded_at: new Date(2026, 10, 4, hour, 0, 0).toISOString(),
    delta_liters: null,
  };
}

const now = new Date(2026, 10, 4, 8, 30, 0);
const day = sensorDayFromReadings(
  [reading(1, 6700), reading(2, 6400), reading(3, 6700), reading(4, 6500)],
  now
);

assert.equal(day.opening, 6700);
assert.equal(day.closing, 6500);
assert.equal(day.outflow, 200);

const live = withLiveRemainder(day, 6400, 8);
assert.equal(live.hourlyLevel[8], 6400);
assert.equal(live.closing, 6400);
assert.equal(live.outflow, 300);
assert.equal(live.hourlyLevel[4], 6500);
assert.equal(day.hourlyLevel[8], 6500);
assert.equal(withLiveRemainder(day, null, 8), day);

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
assert.equal(withLiveRemainder(day, summary.remainder, 8).hourlyLevel[8], summary.remainder);
assert.equal(isLowFill(summary.fill), false);
assert.equal(isLowFill(LOW_FILL_PERCENT - 1), true);
assert.equal(isLowFill(LOW_FILL_PERCENT), false);
assert.equal(isLowFill(null), false);

console.log("level source ok");
