/**
 * Геометрия как в LogHub / GazTrail (pitch):
 * coords = [lon, lat][], движение — along() по длине линии.
 */

export type Coord = [number, number]; // [lon, lat]

export function lerp(a: Coord, b: Coord, t: number): Coord {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

export function haversineM(a: Coord, b: Coord): number {
  const R = 6_371_000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b[1] - a[1]);
  const dLon = toRad(b[0] - a[0]);
  const lat1 = toRad(a[1]);
  const lat2 = toRad(b[1]);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function routeMeta(coords: Coord[]): { segs: number[]; total: number } {
  const segs: number[] = [];
  let total = 0;
  for (let i = 0; i < coords.length - 1; i++) {
    const d = haversineM(coords[i], coords[i + 1]);
    segs.push(d);
    total += d;
  }
  return { segs, total };
}

/** Позиция на полилинии: t ∈ [0,1] — доля длины пути (не индекс точек). */
export function along(coords: Coord[], t: number, meta?: { segs: number[]; total: number }): Coord {
  if (!coords.length) return [0, 0];
  if (coords.length < 2) return coords[0];
  const x = Math.max(0, Math.min(1, t));
  const m = meta ?? routeMeta(coords);
  if (m.total <= 0) return coords[0];
  let remain = x * m.total;
  for (let i = 0; i < m.segs.length; i++) {
    if (remain <= m.segs[i]) {
      const local = m.segs[i] === 0 ? 0 : remain / m.segs[i];
      return lerp(coords[i], coords[i + 1], local);
    }
    remain -= m.segs[i];
  }
  return coords[coords.length - 1];
}

/** Префикс линии от старта до доли t (след за машиной). */
export function alongPrefix(coords: Coord[], t: number): Coord[] {
  if (coords.length < 2) return [...coords];
  const x = Math.max(0, Math.min(1, t));
  if (x <= 0) return [coords[0]];
  if (x >= 1) return coords.slice();
  const m = routeMeta(coords);
  const target = x * m.total;
  const out: Coord[] = [coords[0]];
  let acc = 0;
  for (let i = 0; i < m.segs.length; i++) {
    if (acc + m.segs[i] < target - 1e-6) {
      out.push(coords[i + 1]);
      acc += m.segs[i];
    } else {
      out.push(along(coords, x, m));
      break;
    }
  }
  return out;
}
