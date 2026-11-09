import {
  type GeoJSONSource,
  type MapLayerMouseEvent,
  Map as MapLibreMap,
  NavigationControl,
  Popup,
  setWorkerUrl,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// MapLibre 6 decodes tiles in a module worker. Let Vite bundle it (with the code it shares
// with the main library) and tell MapLibre where it ended up.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";

setWorkerUrl(workerUrl);
import { useEffect, useRef } from "react";
import { type Coords, parentStation, positionAt } from "../lib/motion";
import type { Line, Station } from "../lib/types";
import type { VehicleStore } from "../lib/vehicles";

interface Props {
  store: VehicleStore;
  stations: Station[];
  lines: Map<string, Line>;
  /** Only show this line's trains, or every line when null. */
  focusLine: string | null;
  /** Where to fly the camera when a station is picked. */
  selected: { lat: number; lon: number } | null;
  onSelectStation: (station: Station) => void;
}

const STYLE = "https://tiles.openfreemap.org/styles/positron";
const FRAME_MS = 200; // ~5 updates a second is smooth at subway speeds and cheap for ~500 trains

/** Express variants ("6X") and shuttles use their base line's bullet. */
const bullet = (route: string) => route.replace(/X$/, "");

export function TrainMap({ store, stations, lines, focusLine, selected, onSelectStation }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const props = useRef({ stations, lines, focusLine, onSelectStation });
  props.current = { stations, lines, focusLine, onSelectStation };

  useEffect(() => {
    if (!container.current) return;
    const m = new MapLibreMap({
      container: container.current,
      style: STYLE,
      center: [-73.95, 40.73],
      zoom: 11,
      attributionControl: { compact: true },
    });
    map.current = m;
    m.addControl(new NavigationControl({ showCompass: false }), "bottom-right");

    m.on("load", () => {
      m.addSource("stations", { type: "geojson", data: emptyCollection() });
      m.addSource("trains", { type: "geojson", data: emptyCollection() });
      m.addLayer({
        id: "stations",
        type: "circle",
        source: "stations",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 1.5, 14, 4],
          "circle-color": "#ffffff",
          "circle-stroke-color": "#6b7280",
          "circle-stroke-width": 1,
        },
      });
      m.addLayer({
        id: "station-labels",
        type: "symbol",
        source: "stations",
        minzoom: 13.5,
        layout: { "text-field": ["get", "name"], "text-size": 11, "text-offset": [0, 1.1], "text-font": ["Noto Sans Regular"] },
        paint: { "text-color": "#374151", "text-halo-color": "#ffffff", "text-halo-width": 1.5 },
      });
      m.addLayer({
        id: "trains",
        type: "circle",
        source: "trains",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 4, 14, 9],
          "circle-color": ["get", "color"],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
        },
      });
      m.addLayer({
        id: "train-labels",
        type: "symbol",
        source: "trains",
        minzoom: 12.5,
        layout: { "text-field": ["get", "label"], "text-size": 10, "text-font": ["Noto Sans Bold"], "text-allow-overlap": true },
        paint: { "text-color": ["get", "textColor"] },
      });

      (m.getSource("stations") as GeoJSONSource).setData(stationFeatures(props.current.stations));

      m.on("click", "stations", (e: MapLayerMouseEvent) => {
        const id = e.features?.[0]?.properties?.id as string | undefined;
        const station = props.current.stations.find((s) => s.id === id);
        if (station) props.current.onSelectStation(station);
      });
      m.on("click", "trains", (e: MapLayerMouseEvent) => {
        const f = e.features?.[0];
        if (!f) return;
        const p = f.properties as { route: string; to: string; arrive: number };
        const dest = props.current.stations.find((s) => s.id === parentStation(p.to));
        const mins = Math.max(0, Math.round((p.arrive - store.serverNow()) / 60));
        new Popup({ closeButton: false })
          .setLngLat(e.lngLat)
          .setHTML(
            `<strong>${escape(bullet(p.route))} train</strong><br/>${
              dest ? `Next stop: ${escape(dest.name)}${mins > 0 ? ` in ${mins} min` : ", arriving now"}` : ""
            }`,
          )
          .addTo(m);
      });
      for (const layer of ["stations", "trains"]) {
        m.on("mouseenter", layer, () => (m.getCanvas().style.cursor = "pointer"));
        m.on("mouseleave", layer, () => (m.getCanvas().style.cursor = ""));
      }
    });

    // Animation: recompute every train's position from its motion a few times a second.
    const tick = setInterval(() => {
      const source = m.getSource("trains") as GeoJSONSource | undefined;
      if (!source) return;
      const { stations: st, lines: ln, focusLine: focus } = props.current;
      const coords: Coords = new Map(st.map((s) => [s.id, [s.lat, s.lon]]));
      const now = store.serverNow();
      const features: GeoJSON.Feature[] = [];
      for (const v of store.vehicles.values()) {
        if (focus && bullet(v.route) !== focus) continue;
        const pos = positionAt(v, now, coords);
        if (!pos) continue;
        const line = ln.get(v.route) ?? ln.get(bullet(v.route));
        features.push({
          type: "Feature",
          geometry: { type: "Point", coordinates: [pos.lon, pos.lat] },
          properties: {
            route: v.route,
            to: v.to,
            arrive: v.arrive,
            label: bullet(v.route),
            color: `#${line?.color ?? "808183"}`,
            textColor: `#${line?.text_color ?? "FFFFFF"}`,
          },
        });
      }
      void source.setData({ type: "FeatureCollection", features });
    }, FRAME_MS);

    return () => {
      clearInterval(tick);
      m.remove();
    };
  }, [store]);

  useEffect(() => {
    const source = map.current?.getSource("stations") as GeoJSONSource | undefined;
    source?.setData(stationFeatures(stations));
  }, [stations]);

  useEffect(() => {
    if (selected && map.current) {
      map.current.flyTo({ center: [selected.lon, selected.lat], zoom: Math.max(map.current.getZoom(), 14) });
    }
  }, [selected]);

  // MapLibre gives its container position: relative, so it needs a positioned wrapper to fill.
  return (
    <div className="absolute inset-0">
      <div ref={container} className="h-full w-full" data-testid="map" />
    </div>
  );
}

function emptyCollection(): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

function stationFeatures(stations: Station[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: stations.map((s) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [s.lon, s.lat] },
      properties: { id: s.id, name: s.name },
    })),
  };
}

function escape(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}
