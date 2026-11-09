import type { Arrivals, Commute, Line, Station } from "./types";

const CLIENT_KEY = "transitpulse.clientId";

/** Riders are anonymous: the browser makes up an id once and uses it for saved commutes. */
export function clientId(): string {
  try {
    let id = localStorage.getItem(CLIENT_KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(CLIENT_KEY, id);
    }
    return id;
  } catch {
    return (window as unknown as { __tpClient?: string }).__tpClient ??= crypto.randomUUID();
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", "x-client-id": clientId(), ...init?.headers },
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

export const api = {
  lines: () => request<Line[]>("/api/lines"),
  stations: () => request<Station[]>("/api/stations"),
  arrivals: (stationId: string) => request<Arrivals>(`/api/stations/${stationId}/arrivals`),
  commutes: () => request<Commute[]>("/api/commutes"),
  addCommute: (body: { route_id: string; stop_id: string; label: string; threshold_minutes: number }) =>
    request<Commute>("/api/commutes", { method: "POST", body: JSON.stringify(body) }),
  removeCommute: (id: string) => request<void>(`/api/commutes/${id}`, { method: "DELETE" }),
};
