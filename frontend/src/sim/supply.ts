import type { LpgSupply } from "../types";
import type { SimState } from "./seed";

export function supplyForTruck(state: SimState, truckId: string): LpgSupply | null {
  const list = state.supplies.filter((s) => s.truck_id === truckId);
  return list.find((s) => s.live) ?? list[0] ?? null;
}

export function supplyForStation(state: SimState, stationId: string): LpgSupply | null {
  const list = state.supplies.filter((s) => s.station_id === stationId);
  return (
    list.find((s) => s.status === "selling" || s.status === "accepted") ??
    list.find((s) => s.live) ??
    list[0] ??
    null
  );
}

export function supplyForFactory(state: SimState, factoryId: string): LpgSupply | null {
  const list = state.supplies.filter((s) => s.factory_id === factoryId);
  return list.find((s) => s.live) ?? list.find((s) => s.status === "selling") ?? list[0] ?? null;
}

export function supplyTank(state: SimState, supply: LpgSupply) {
  const station = state.stations.find((s) => s.detail.id === supply.station_id)?.detail ?? null;
  const tank =
    station?.tanks.find((t) => t.id === supply.tank_id) ?? station?.tanks[0] ?? null;
  return { station, tank };
}
