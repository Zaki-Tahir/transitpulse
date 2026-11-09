export type LineStatusCode = "good" | "planned_work" | "service_change" | "delays";

export interface Line {
  route_id: string;
  short_name: string;
  long_name: string;
  color: string;
  text_color: string;
  status: LineStatusCode;
  label: string;
  summary: string | null;
}

export interface Station {
  id: string;
  name: string;
  lat: number;
  lon: number;
  routes: string[];
}

/** Wire format from the server: [id, route, fromStop, toStop, depart, arrive]. */
export type PackedVehicle = [string, string, string, string, number, number];

export interface Vehicle {
  id: string;
  route: string;
  from: string;
  to: string;
  depart: number;
  arrive: number;
}

export type CommuteState = "on_time" | "late" | "no_trains";

export interface Commute {
  id: string;
  route_id: string;
  stop_id: string;
  label: string;
  threshold_minutes: number;
  state: CommuteState;
  next_minutes: number[];
  reason: string;
}

export interface Arrivals {
  id: string;
  name: string;
  routes: string[];
  updated: number;
  arrivals: { N: Record<string, number[]>; S: Record<string, number[]> };
}

export type ServerMessage =
  | { type: "snapshot"; t: number; v: PackedVehicle[] }
  | { type: "delta"; t: number; u: PackedVehicle[]; r: string[] }
  | { type: "status"; lines: Record<string, { status: LineStatusCode; label: string; summary: string | null }> }
  | { type: "commute"; id: string; label: string; route: string; state: CommuteState; reason: string; next: number[] };
