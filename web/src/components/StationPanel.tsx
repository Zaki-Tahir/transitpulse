import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Place } from "../lib/places";
import type { Line } from "../lib/types";
import { Bullet } from "./Bullet";

const DIRECTIONS = [
  { key: "N", label: "Uptown / northbound" },
  { key: "S", label: "Downtown / southbound" },
] as const;

interface Row {
  route: string;
  stationId: string;
  minutes: number[];
}

interface Props {
  place: Place;
  lines: Map<string, Line>;
  onClose: () => void;
  onSave: (routeId: string, stopId: string, label: string) => Promise<void>;
}

/** Next trains at a station (or station complex), by direction. */
export function StationPanel({ place, lines, onClose, onSave }: Props) {
  const [rows, setRows] = useState<Record<"N" | "S", Row[]> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const results = await Promise.all(place.stations.map((s) => api.arrivals(s.id)));
        const merged: Record<"N" | "S", Row[]> = { N: [], S: [] };
        for (const r of results) {
          for (const dir of ["N", "S"] as const) {
            for (const [route, minutes] of Object.entries(r.arrivals[dir])) merged[dir].push({ route, stationId: r.id, minutes });
          }
        }
        for (const dir of ["N", "S"] as const) merged[dir].sort((a, b) => (a.minutes[0] ?? 99) - (b.minutes[0] ?? 99));
        if (active) {
          setRows(merged);
          setError(null);
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      }
    };
    void load();
    const timer = setInterval(load, 20_000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [place]);

  return (
    <section className="rounded-xl border border-gray-200 p-4" data-testid="station-panel">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="font-semibold">{place.name}</h2>
          <div className="mt-1 flex flex-wrap gap-1">
            {/* Express variants (7X) share a bullet with the local line. */}
            {[...new Set(place.routes.map((r) => r.replace(/X$/, "")))].map((r) => (
              <Bullet key={r} route={r} line={lines.get(r)} size="sm" />
            ))}
          </div>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-900" aria-label="Close station">
          ✕
        </button>
      </div>

      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      {!rows && !error && <p className="mt-3 text-sm text-gray-400">Loading arrivals…</p>}
      {rows &&
        DIRECTIONS.map(({ key, label }) => (
          <div key={key} className="mt-4">
            <h3 className="text-xs font-medium tracking-wide text-gray-500 uppercase">{label}</h3>
            {rows[key].length === 0 ? (
              <p className="mt-1 text-sm text-gray-400">No trains in the next hour</p>
            ) : (
              <ul className="mt-1 space-y-1.5">
                {rows[key].map(({ route, stationId, minutes }) => {
                  const id = `${stationId}${key}-${route}`;
                  const label = `${place.name} (${route.replace(/X$/, "")}, ${key === "N" ? "uptown" : "downtown"})`;
                  return (
                    <li key={id} className="flex items-center gap-2 text-sm">
                      <Bullet route={route} line={lines.get(route)} size="sm" />
                      <span className="flex-1 tabular-nums">{minutes.map((m) => (m === 0 ? "now" : `${m} min`)).join(", ")}</span>
                      <button
                        onClick={() => onSave(route, stationId + key, label).then(() => setSaved(id))}
                        disabled={saved === id}
                        className="text-xs font-medium text-blue-700 hover:underline disabled:text-gray-400 disabled:no-underline"
                      >
                        {saved === id ? "Saved" : "Save commute"}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        ))}
    </section>
  );
}
