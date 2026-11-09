import { describe, expect, it } from "vitest";
import { bearing, parentStation, positionAt } from "./motion";
import { VehicleStore } from "./vehicles";

const coords = new Map<string, [number, number]>([
  ["101", [40.7, -74.0]],
  ["102", [40.71, -74.0]],
]);

describe("positionAt", () => {
  const v = { id: "t1", route: "A", from: "101N", to: "102N", depart: 1000, arrive: 1100 };

  it("interpolates between stations by time", () => {
    const p = positionAt(v, 1025, coords)!;
    expect(p.lat).toBeCloseTo(40.7025);
    expect(p.lon).toBeCloseTo(-74.0);
    expect(p.bearing).toBeCloseTo(0, 0);
  });

  it("waits at the first station before departure and stops at the second", () => {
    expect(positionAt(v, 900, coords)!.lat).toBeCloseTo(40.7);
    expect(positionAt(v, 5000, coords)!.lat).toBeCloseTo(40.71);
  });

  it("keeps stopped trains at their station and ignores unknown stations", () => {
    expect(positionAt({ ...v, from: "102N", to: "102N" }, 1050, coords)).toEqual({ lat: 40.71, lon: -74.0, bearing: 0 });
    expect(positionAt({ ...v, to: "999N" }, 1050, coords)).toBeNull();
  });
});

describe("helpers", () => {
  it("maps platforms to stations", () => {
    expect(parentStation("A27N")).toBe("A27");
    expect(parentStation("A27")).toBe("A27");
  });
  it("computes compass bearings", () => {
    expect(bearing([40, -74], [40, -73])).toBeCloseTo(90, 0);
  });
});

describe("VehicleStore", () => {
  it("applies a snapshot, then deltas", () => {
    const s = new VehicleStore();
    s.applySnapshot(
      1000,
      [
        ["t1", "A", "101N", "102N", 1000, 1100],
        ["t2", "A", "101N", "102N", 1000, 1100],
      ],
      990,
    );
    s.applyDelta(1015, [["t1", "A", "101N", "102N", 1030, 1130], ["t3", "B", "102N", "102N", 1015, 1015]], ["t2"], 1005);

    expect([...s.vehicles.keys()]).toEqual(["t1", "t3"]);
    expect(s.vehicles.get("t1")!.arrive).toBe(1130);
    // The user's clock is 10s behind the server's; animation uses server time.
    expect(s.serverNow(1010)).toBe(1020);
  });
});
