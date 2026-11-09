import type { Station } from "./types";

/**
 * What a rider thinks of as one station. The MTA data splits big complexes into separate
 * stations with the same name (Times Sq-42 St is four: 1/2/3, 7, N/Q/R/W and the shuttle),
 * so same-named stations close to each other are grouped.
 */
export interface Place {
  key: string;
  name: string;
  lat: number;
  lon: number;
  stations: Station[];
  routes: string[];
}

const COMPLEX_RADIUS_M = 400;

export function placeFor(station: Station, all: Station[]): Place {
  const stations = all.filter((s) => s.name === station.name && metersBetween(s, station) <= COMPLEX_RADIUS_M);
  const members = stations.length ? stations : [station];
  return {
    key: members.map((s) => s.id).sort().join("+"),
    name: station.name,
    lat: station.lat,
    lon: station.lon,
    stations: members,
    routes: [...new Set(members.flatMap((s) => s.routes))].sort(),
  };
}

export function metersBetween(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * 6_371_000 * Math.asin(Math.sqrt(h));
}
