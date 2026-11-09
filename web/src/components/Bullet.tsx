import type { Line } from "../lib/types";

/** A subway line bullet: the coloured circle with the line's letter or number. */
export function Bullet({ line, route, size = "md" }: { line?: Line; route: string; size?: "sm" | "md" }) {
  const label = route.replace(/X$/, "");
  const dims = size === "sm" ? "h-5 w-5 text-[11px]" : "h-7 w-7 text-sm";
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-full font-bold ${dims}`}
      style={{ background: `#${line?.color ?? "808183"}`, color: `#${line?.text_color ?? "FFFFFF"}` }}
      aria-label={`${label} line`}
    >
      {label}
    </span>
  );
}
