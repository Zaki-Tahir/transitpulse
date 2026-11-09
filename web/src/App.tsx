import { useCallback, useEffect, useMemo, useState } from "react";
import { CommutePanel } from "./components/CommutePanel";
import { LinesPanel } from "./components/LinesPanel";
import { StationPanel } from "./components/StationPanel";
import { TrainMap } from "./components/TrainMap";
import { api } from "./lib/api";
import { type Place, placeFor } from "./lib/places";
import type { Commute, Line, ServerMessage, Station } from "./lib/types";
import { useLive } from "./lib/useLive";

type Toast = { id: number; title: string; body: string };

export function App() {
  const [lines, setLines] = useState<Line[]>([]);
  const [stations, setStations] = useState<Station[]>([]);
  const [commutes, setCommutes] = useState<Commute[]>([]);
  const [focus, setFocus] = useState<string | null>(null);
  const [selected, setSelected] = useState<Place | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [query, setQuery] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);

  const refreshCommutes = useCallback(() => api.commutes().then(setCommutes).catch(() => {}), []);

  useEffect(() => {
    Promise.all([api.lines(), api.stations()])
      .then(([l, s]) => {
        setLines(l);
        setStations(s);
      })
      .catch((e: Error) => setLoadError(e.message));
    void refreshCommutes();
    const timer = setInterval(refreshCommutes, 30_000);
    return () => clearInterval(timer);
  }, [refreshCommutes]);

  const notify = useCallback((title: string, body: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, title, body }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 10_000);
    if ("Notification" in window && Notification.permission === "granted") new Notification(title, { body });
  }, []);

  const { store, connection, count } = useLive({
    onStatus: (update: Extract<ServerMessage, { type: "status" }>["lines"]) =>
      setLines((current) => current.map((l) => (update[l.route_id] ? { ...l, ...update[l.route_id] } : l))),
    onCommute: (alert) => {
      notify(`${alert.label}`, alert.reason);
      void refreshCommutes();
    },
  });

  const lineMap = useMemo(() => new Map(lines.map((l) => [l.route_id, l])), [lines]);

  const saveCommute = async (routeId: string, stopId: string, label: string) => {
    await api.addCommute({ route_id: routeId, stop_id: stopId, label, threshold_minutes: 12 });
    await refreshCommutes();
    if ("Notification" in window && Notification.permission === "default") void Notification.requestPermission();
  };

  const search = (name: string) => {
    setQuery(name);
    const match = stations.find((s) => s.name.toLowerCase() === name.toLowerCase());
    if (match) {
      setSelected(placeFor(match, stations));
      setQuery("");
    }
  };

  return (
    <div className="relative h-screen w-screen overflow-hidden">
      <TrainMap
        store={store}
        stations={stations}
        lines={lineMap}
        focusLine={focus}
        selected={selected}
        onSelectStation={(s: Station) => setSelected(placeFor(s, stations))}
      />

      <aside className="absolute top-3 left-3 flex max-h-[calc(100vh-1.5rem)] w-[min(24rem,calc(100vw-1.5rem))] flex-col gap-5 overflow-y-auto rounded-2xl bg-white/95 p-5 shadow-lg ring-1 ring-black/5 backdrop-blur">
        <header>
          <h1 className="text-lg font-bold tracking-tight">TransitPulse</h1>
          <p className="mt-0.5 flex items-center gap-2 text-sm text-gray-600" data-testid="live-count">
            <span
              className={`h-2 w-2 rounded-full ${connection === "live" ? "animate-pulse bg-emerald-500" : "bg-amber-400"}`}
            />
            {connection === "live" ? `${count} trains live` : connection === "connecting" ? "Connecting…" : "Reconnecting…"}
          </p>
        </header>

        {loadError && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">Couldn't load the map data: {loadError}</p>}

        <label className="block">
          <span className="sr-only">Find a station</span>
          <input
            list="station-names"
            value={query}
            onChange={(e) => search(e.target.value)}
            placeholder="Find a station"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gray-900 focus:outline-none"
          />
          <datalist id="station-names">
            {stations.map((s) => (
              <option key={s.id} value={s.name} />
            ))}
          </datalist>
        </label>

        <LinesPanel lines={lines} focus={focus} onFocus={setFocus} />

        {selected && (
          <StationPanel key={selected.key} place={selected} lines={lineMap} onClose={() => setSelected(null)} onSave={saveCommute} />
        )}

        <CommutePanel
          commutes={commutes}
          lines={lineMap}
          onRemove={(id) => api.removeCommute(id).then(refreshCommutes)}
        />

        <footer className="text-xs text-gray-400">
          Live data from MTA GTFS-realtime, updated every 15 seconds. Positions between stations are estimated.
        </footer>
      </aside>

      <div className="pointer-events-none absolute top-3 right-3 flex w-80 flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} role="alert" className="pointer-events-auto rounded-xl bg-gray-900 p-4 text-sm text-white shadow-lg">
            <p className="font-semibold">{t.title}</p>
            <p className="mt-0.5 text-gray-300">{t.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
