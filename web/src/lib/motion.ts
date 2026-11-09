import type { PackedVehicle, Vehicle } from "./types";

export type Coords = Map<string, [lat: number, lon: number]>;

/** "A27N" and "A27S" are platforms of station "A27". */
export function parentStation(stopId: string): string {
  const last = stopId.at(-1);
  return last === "N" || last === "S" ? stopId.slice(0, -1) : stopId;
}

export function unpack([id, route, from, to, depart, arrive]: PackedVehicle): Vehicle {
  return { id, route, from, to, depart, arrive };
}

/**
 * Where a train is at time `t` (unix seconds): linear between its two stations, based on when it
 * left one and is due at the next. Same maths as the server's position_at(). Returns null if
 * either station is unknown.
 */
export function positionAt(v: Vehicle, t: number, coords: Coords): { lat: number; lon: number; bearing: number } | null {
  const a = coords.get(parentStation(v.from));
  const b = coords.get(parentStation(v.to));
  if (!a || !b) return null;
  if (v.from === v.to || v.arrive <= v.depart) return { lat: b[0], lon: b[1], bearing: 0 };
  const p = Math.min(1, Math.max(0, (t - v.depart) / (v.arrive - v.depart)));
  return { lat: a[0] + (b[0] - a[0]) * p, lon: a[1] + (b[1] - a[1]) * p, bearing: bearing(a, b) };
}

export function bearing(a: [number, number], b: [number, number]): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const [lat1, lat2] = [toRad(a[0]), toRad(b[0])];
  const dLon = toRad(b[1] - a[1]);
  const x = Math.sin(dLon) * Math.cos(lat2);
  const y = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  return ((Math.atan2(x, y) * 180) / Math.PI + 360) % 360;
}
