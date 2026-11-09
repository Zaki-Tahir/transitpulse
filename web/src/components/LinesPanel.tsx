import type { Line } from "../lib/types";
import { Bullet } from "./Bullet";

const DOT: Record<Line["status"], string> = {
  good: "",
  planned_work: "bg-amber-400",
  service_change: "bg-orange-500",
  delays: "bg-red-600",
};

interface Props {
  lines: Line[];
  focus: string | null;
  onFocus: (route: string | null) => void;
}

export function LinesPanel({ lines, focus, onFocus }: Props) {
  // Express variants (6X) and shuttles share a bullet with their main line; show each bullet once.
  const shown = lines.filter((l) => !l.route_id.endsWith("X") && l.route_id !== "SI");
  const focused = lines.find((l) => l.route_id === focus);
  const delayed = shown.filter((l) => l.status === "delays").length;

  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold">Lines</h2>
        <span className="text-xs text-gray-500">
          {delayed === 0 ? "No delays reported" : `${delayed} line${delayed === 1 ? "" : "s"} delayed`}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {shown.map((line) => (
          <button
            key={line.route_id}
            onClick={() => onFocus(focus === line.route_id ? null : line.route_id)}
            title={`${line.short_name}: ${line.label}`}
            aria-pressed={focus === line.route_id}
            className={`relative rounded-full p-0.5 transition ${
              focus === line.route_id ? "ring-2 ring-gray-900" : focus ? "opacity-40 hover:opacity-100" : ""
            }`}
          >
            <Bullet line={line} route={line.route_id} />
            {line.status !== "good" && (
              <span
                className={`absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full ring-2 ring-white ${DOT[line.status]}`}
                aria-label={line.label}
              />
            )}
          </button>
        ))}
      </div>
      {focused && (
        <div className="mt-3 rounded-lg bg-gray-50 p-3 text-sm" data-testid="line-detail">
          <p className="font-medium">
            {focused.short_name} · {focused.long_name}
          </p>
          <p className={focused.status === "good" ? "text-emerald-700" : "text-red-700"}>{focused.label}</p>
          {focused.summary && <p className="mt-1 text-gray-600">{focused.summary}</p>}
        </div>
      )}
    </section>
  );
}
