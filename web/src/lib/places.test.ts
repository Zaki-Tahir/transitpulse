import { describe, expect, it } from "vitest";
import { metersBetween, placeFor } from "./places";
import type { Station } from "./types";

const st = (id: string, name: string, lat: number, lon: number, routes: string[]): Station => ({ id, name, lat, lon, routes });

const stations = [
  st("127", "Times Sq-42 St", 40.75529, -73.987495, ["1", "2", "3"]),
  st("725", "Times Sq-42 St", 40.755477, -73.987691, ["7"]),
  st("R16", "Times Sq-42 St", 40.754672, -73.986754, ["N", "Q", "R", "W"]),
  // Same name, other side of the city: a different station.
  st("X99", "Times Sq-42 St", 40.6, -73.9, ["Z"]),
  st("A27", "42 St-Port Authority Bus Terminal", 40.757308, -73.989735, ["A", "C", "E"]),
];

describe("placeFor", () => {
  it("groups a station complex that MTA splits into several stations", () => {
    const place = placeFor(stations[1]!, stations);
    expect(place.stations.map((s) => s.id).sort()).toEqual(["127", "725", "R16"]);
    expect(place.routes).toEqual(["1", "2", "3", "7", "N", "Q", "R", "W"]);
  });

  it("leaves standalone stations alone", () => {
    expect(placeFor(stations[4]!, stations).stations.map((s) => s.id)).toEqual(["A27"]);
  });
});

describe("metersBetween", () => {
  it("is roughly right at NYC latitudes", () => {
    // 0.001 degrees of latitude is about 111 m.
    expect(metersBetween({ lat: 40.75, lon: -73.98 }, { lat: 40.751, lon: -73.98 })).toBeCloseTo(111, -1);
  });
});
