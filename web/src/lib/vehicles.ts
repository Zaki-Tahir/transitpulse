import { unpack } from "./motion";
import type { PackedVehicle, Vehicle } from "./types";

/**
 * Holds every train the browser knows about. The server sends one full snapshot when the
 * socket opens, then only changes; applying them in order keeps this in sync.
 */
export class VehicleStore {
  readonly vehicles = new Map<string, Vehicle>();
  /** Server time of the last update, and how far our clock is from the server's. */
  serverTime = 0;
  clockOffset = 0;

  applySnapshot(t: number, packed: PackedVehicle[], now = Date.now() / 1000): void {
    this.vehicles.clear();
    for (const p of packed) this.vehicles.set(p[0], unpack(p));
    this.sync(t, now);
  }

  applyDelta(t: number, updated: PackedVehicle[], removed: string[], now = Date.now() / 1000): void {
    for (const p of updated) this.vehicles.set(p[0], unpack(p));
    for (const id of removed) this.vehicles.delete(id);
    this.sync(t, now);
  }

  /** Current time on the server's clock, so animation isn't off when the user's clock is wrong. */
  serverNow(now = Date.now() / 1000): number {
    return now + this.clockOffset;
  }

  private sync(t: number, now: number) {
    this.serverTime = t;
    this.clockOffset = t - now;
  }
}
