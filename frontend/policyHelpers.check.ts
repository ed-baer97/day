import assert from "node:assert/strict";
import { messageOf } from "./src/errors";
import { freeVolumeLiters, SAFE_FILL_PERCENT, safeRefillLiters } from "./src/policy";

assert.equal(SAFE_FILL_PERCENT, 85);
assert.equal(freeVolumeLiters(10000, 4000), 6000);
assert.equal(freeVolumeLiters(10000, 12000), 0);
assert.equal(freeVolumeLiters(10000, null), null);
assert.equal(freeVolumeLiters(0, 100), null);

assert.equal(safeRefillLiters(10000, 5000), 3500);
assert.equal(safeRefillLiters(10000, 9000), 0);
assert.equal(safeRefillLiters(10000, null), null);
assert.equal(safeRefillLiters(10000, 5000, 90), 4000);

assert.equal(messageOf(new Error(JSON.stringify({ detail: "дубль" }))), "дубль");
assert.equal(messageOf(new Error("plain")), "plain");
assert.equal(messageOf(null), "Сервер не ответил");
assert.equal(messageOf(null, "Не удалось сохранить"), "Не удалось сохранить");

console.log("policyHelpers checks OK");
