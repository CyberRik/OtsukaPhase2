import { cn } from "@/lib/utils";

// Honest status: green when the FastAPI engine answered, amber when we're showing
// the committed fixture snapshot. Never silently fakes liveness.
export function LiveBadge({ live }: { live: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium",
        live ? "border-band-green/30 bg-band-green/5 text-band-green" : "border-band-yellow/30 bg-band-yellow/5 text-band-yellow",
      )}
      title={live ? "Live from the deterministic engine" : "API offline — showing the committed seed snapshot"}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", live ? "bg-band-green" : "bg-band-yellow")} />
      {live ? "Live engine" : "Seed snapshot"}
    </span>
  );
}
