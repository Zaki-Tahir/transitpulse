import type { Commute, Line } from "../lib/types";
import { Bullet } from "./Bullet";

const STATE: Record<Commute["state"], { label: string; className: string }> = {
  on_time: { label: "On time", className: "bg-emerald-50 text-emerald-700" },
  late: { label: "Running late", className: "bg-red-50 text-red-700" },
  no_trains: { label: "No trains", className: "bg-gray-100 text-gray-600" },
};

interface Props {
  commutes: Commute[];
  lines: Map<string, Line>;
  onRemove: (id: string) => void;
}

export function CommutePanel({ commutes, lines, onRemove }: Props) {
  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold">My commutes</h2>
      {commutes.length === 0 ? (
        <p className="text-sm text-gray-500">
          Pick a station on the map and choose <span className="font-medium">Save commute</span>. You'll get an alert here
          when it's running late.
        </p>
      ) : (
        <ul className="space-y-2" data-testid="commutes">
          {commutes.map((c) => (
            <li key={c.id} className="flex items-start gap-3 rounded-lg border border-gray-200 p-3">
              <Bullet route={c.route_id} line={lines.get(c.route_id)} size="sm" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{c.label}</p>
                <p className="text-xs text-gray-500">{c.reason}</p>
              </div>
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATE[c.state].className}`}>
                {STATE[c.state].label}
              </span>
              <button onClick={() => onRemove(c.id)} className="text-gray-300 hover:text-gray-700" aria-label={`Remove ${c.label}`}>
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
