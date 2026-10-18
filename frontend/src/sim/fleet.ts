import type { StationDetail } from "../types";
import { PRICE_KZT, type SimState, type SimStation } from "./seed";

export type FleetStation = {
  id: string;
  code: string;
  name: string;
  address?: string | null;
  lat: number;
  lon: number;
  is_active: boolean;
};

export type FleetTruck = {
  id: string;
  plate_number: string;
  capacity_liters: number;
  carrier_name?: string | null;
  status: string;
  lat?: number | null;
  lon?: number | null;
};

function blankStation(row: FleetStation): SimStation {
  const detail: StationDetail = {
    id: row.id,
    code: row.code,
    name: row.name,
    address: row.address,
    lat: row.lat,
    lon: row.lon,
    is_active: row.is_active,
    tanks: [],
    opening_remainder_liters: 0,
    remainder_liters: 0,
    capacity_liters: 0,
    receipts_day_liters: 0,
    consumption_day_liters: 0,
    consumption_week_liters: 0,
    consumption_month_liters: 0,
    sales_day_count: 0,
    delivery_count_day: 0,
    avg_fill_liters: 0,
    recent_fills: [],
    recent_deliveries: [],
    active_trucks: [],
    balance_status: "unknown",
    price_kzt_per_liter: PRICE_KZT,
    pumps: [],
  };
  return { detail, saleAcc: 0 };
}

/** Подписывает имена и координаты справочника на живую карту, не трогая рейсы. */
export function applyFleet(state: SimState, stations: FleetStation[], trucks: FleetTruck[]): SimState {
  const byStation = new Map(stations.map((row) => [row.id, row]));
  const byTruck = new Map(trucks.map((row) => [row.id, row]));
  const nextStations = state.stations.map((station) => {
    const row = byStation.get(station.detail.id);
    if (!row) return station;
    return {
      ...station,
      detail: {
        ...station.detail,
        code: row.code,
        name: row.name,
        address: row.address,
        lat: row.lat,
        lon: row.lon,
        is_active: row.is_active,
      },
    };
  });
  for (const row of stations) {
    if (!nextStations.some((station) => station.detail.id === row.id)) {
      nextStations.push(blankStation(row));
    }
  }
  const nextTrucks = state.trucks.map((truck) => {
    const row = byTruck.get(truck.detail.id);
    if (!row) return truck;
    return {
      ...truck,
      detail: {
        ...truck.detail,
        plate_number: row.plate_number,
        capacity_liters: row.capacity_liters,
        carrier_name: row.carrier_name,
      },
    };
  });
  return { ...state, stations: nextStations, trucks: nextTrucks };
}
