import assert from "node:assert/strict";
import {
  entryLabelFor,
  ROLE_ADMIN,
  ROLE_CASHIER,
  ROLE_OWNER,
  ROLE_STATION,
  screenFor,
  sessionCapabilities,
} from "./src/access";
import { parseRoute } from "./src/route";
import { normalizeSession, normalizeStationIds } from "./src/session";

// --- normalizeStationIds & normalizeSession ---
assert.deepEqual(normalizeStationIds(["s1", "", "s1", "s2"], null), ["s1", "s2"]);
assert.deepEqual(normalizeStationIds([], "s1"), ["s1"]);
assert.deepEqual(normalizeStationIds(undefined, "s1"), ["s1"]);
assert.deepEqual(normalizeStationIds([], null), []);

const unknownRoleSession = normalizeSession({
  token: "tok",
  username: "old-user",
  role: "legacy_unknown",
  station_ids: ["s1"],
});
assert.ok(unknownRoleSession);
assert.equal(unknownRoleSession.role, undefined);
assert.equal(unknownRoleSession.station_id, "s1");
assert.deepEqual(unknownRoleSession.station_ids, ["s1"]);

const missingRoleSession = normalizeSession({
  token: "tok",
  username: "no-role",
});
assert.ok(missingRoleSession);
assert.equal(missingRoleSession.role, undefined);
assert.equal(missingRoleSession.station_id, null);
assert.deepEqual(missingRoleSession.station_ids, []);

const multiStationOwner = normalizeSession({
  token: "tok",
  username: "owner1",
  role: ROLE_OWNER,
  station_id: "s1",
  station_ids: ["s1", "s2"],
});
assert.ok(multiStationOwner);
assert.equal(multiStationOwner.role, ROLE_OWNER);
assert.equal(multiStationOwner.station_id, null);
assert.deepEqual(multiStationOwner.station_ids, ["s1", "s2"]);

const legacyStationSession = normalizeSession({
  token: "tok",
  username: "st1",
  role: ROLE_STATION,
  station_ids: [],
  station_id: "s1",
});
assert.ok(legacyStationSession);
assert.equal(legacyStationSession.role, ROLE_STATION);
assert.equal(legacyStationSession.station_id, "s1");
assert.deepEqual(legacyStationSession.station_ids, ["s1"]);

const cashierSession = normalizeSession({
  token: "tok",
  username: "kassir1",
  role: ROLE_CASHIER,
  station_id: "s1",
});
assert.ok(cashierSession);
assert.equal(cashierSession.role, ROLE_CASHIER);
assert.equal(cashierSession.station_id, "s1");
assert.deepEqual(cashierSession.station_ids, ["s1"]);

const adminSession = normalizeSession({
  token: "tok",
  username: "admin",
  role: ROLE_ADMIN,
});
assert.ok(adminSession);
assert.equal(adminSession.role, ROLE_ADMIN);
assert.equal(adminSession.station_id, null);
assert.deepEqual(adminSession.station_ids, []);

// --- sessionCapabilities ---
assert.deepEqual(sessionCapabilities(null), {
  admin: false,
  owner: false,
  cashier: false,
  stationSide: false,
  knownRole: false,
  homeScreen: "landing",
});

assert.deepEqual(sessionCapabilities(unknownRoleSession), {
  admin: false,
  owner: false,
  cashier: false,
  stationSide: false,
  knownRole: false,
  homeScreen: "landing",
});

assert.deepEqual(sessionCapabilities(adminSession), {
  admin: true,
  owner: false,
  cashier: false,
  stationSide: false,
  knownRole: true,
  homeScreen: "dashboard",
});

for (const owner of [multiStationOwner, legacyStationSession]) {
  assert.deepEqual(sessionCapabilities(owner), {
    admin: false,
    owner: true,
    cashier: false,
    stationSide: true,
    knownRole: true,
    homeScreen: "dashboard",
  });
}

assert.deepEqual(sessionCapabilities(cashierSession), {
  admin: false,
  owner: false,
  cashier: true,
  stationSide: true,
  knownRole: true,
  homeScreen: "cashier",
});

// --- screenFor ---
// Кассир: с /dashboard, /dashboard/123, /map, /admin остаётся на смене; с / — на лендинге
assert.equal(screenFor(cashierSession, parseRoute("/dashboard")), "cashier");
assert.equal(screenFor(cashierSession, parseRoute("/dashboard/123")), "cashier");
assert.equal(screenFor(cashierSession, parseRoute("/map")), "cashier");
assert.equal(screenFor(cashierSession, parseRoute("/admin/stations")), "cashier");
assert.equal(screenFor(cashierSession, parseRoute("/cashier")), "cashier");
assert.equal(screenFor(cashierSession, parseRoute("/")), "landing");

// Владелец (и legacy station): /map, /admin, /supply, /cashier -> /dashboard; /dashboard/123 сохраняется
for (const owner of [multiStationOwner, legacyStationSession]) {
  assert.equal(screenFor(owner, parseRoute("/map")), "dashboard");
  assert.equal(screenFor(owner, parseRoute("/map/station/1")), "dashboard");
  assert.equal(screenFor(owner, parseRoute("/admin/stations")), "dashboard");
  assert.equal(screenFor(owner, parseRoute("/supply")), "dashboard");
  assert.equal(screenFor(owner, parseRoute("/cashier")), "dashboard");
  assert.equal(screenFor(owner, parseRoute("/dashboard")), "dashboard");
  assert.equal(screenFor(owner, parseRoute("/dashboard/123")), "dashboard");
  assert.equal(screenFor(owner, parseRoute("/")), "landing");
}

// Администратор: map, supply, admin, dashboard, landing доступны; /cashier -> dashboard
assert.equal(screenFor(adminSession, parseRoute("/map")), "map");
assert.equal(screenFor(adminSession, parseRoute("/supply")), "supply");
assert.equal(screenFor(adminSession, parseRoute("/admin/access")), "admin");
assert.equal(screenFor(adminSession, parseRoute("/dashboard")), "dashboard");
assert.equal(screenFor(adminSession, parseRoute("/dashboard/123")), "dashboard");
assert.equal(screenFor(adminSession, parseRoute("/")), "landing");
assert.equal(screenFor(adminSession, parseRoute("/cashier")), "dashboard");

// Неизвестная роль и null: только landing
assert.equal(screenFor(unknownRoleSession, parseRoute("/admin/stations")), "landing");
assert.equal(screenFor(unknownRoleSession, parseRoute("/map")), "landing");
assert.equal(screenFor(unknownRoleSession, parseRoute("/dashboard")), "landing");
assert.equal(screenFor(null, parseRoute("/admin")), "landing");
assert.equal(screenFor(null, parseRoute("/dashboard")), "landing");

// Подписи лендинга
assert.equal(entryLabelFor(adminSession), "Диспетчерская");
assert.equal(entryLabelFor(cashierSession), "Рабочее место кассира");
assert.equal(entryLabelFor(multiStationOwner), "Кабинет");
assert.equal(entryLabelFor(legacyStationSession), "Кабинет");
assert.equal(entryLabelFor(unknownRoleSession), "Проверка…");

console.log("access checks OK");
