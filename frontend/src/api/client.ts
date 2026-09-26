import type {
  BatchTrail,
  DiscrepancyEvent,
  MapOverview,
  StationDetail,
  TruckDetail,
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  mapOverview: () => getJson<MapOverview>("/map/overview"),
  truck: (id: string) => getJson<TruckDetail>(`/trucks/${id}`),
  station: (id: string) => getJson<StationDetail>(`/stations/${id}`),
  trailByCode: (code: string) =>
    getJson<BatchTrail>(`/batches/by-code/${encodeURIComponent(code)}/trail`),
  events: () => getJson<DiscrepancyEvent[]>("/events?unresolved_only=true"),
};
