import { cn } from "@/lib/utils";
import type { Band } from "@/lib/types";

const BAND_LABEL: Record<Band, string> = { red: "要注意", yellow: "注視", green: "健全" };
const BAND_EN: Record<Band, string> = { red: "At risk", yellow: "Watch", green: "Healthy" };

export function BandDot({ band, className }: { band: Band; className?: string }) {
  return (
    <span
      className={cn(
        "inline-block h-2.5 w-2.5 rounded-full",
        band === "red" && "bg-band-red",
        band === "yellow" && "bg-band-yellow",
        band === "green" && "bg-band-green",
        className,
      )}
    />
  );
}

export function BandPill({ band, score }: { band: Band; score?: number }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full px-2.5 py-1 text-[11px] font-medium ring-1",
        band === "red" && "bg-band-red/8 text-band-red ring-band-red/25",
        band === "yellow" && "bg-band-yellow/10 text-band-yellow ring-band-yellow/25",
        band === "green" && "bg-band-green/8 text-band-green ring-band-green/25",
      )}
    >
      <BandDot band={band} />
      {BAND_LABEL[band]} · {BAND_EN[band]}
      {typeof score === "number" && <span className="font-mono opacity-70">{score}</span>}
    </span>
  );
}

// horizontal risk meter (0–100, higher = worse)
export function RiskMeter({ score, band }: { score: number; band: Band }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span className="eyebrow">Risk</span>
        <span className="font-mono">{score}/100</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            band === "red" && "bg-band-red",
            band === "yellow" && "bg-band-yellow",
            band === "green" && "bg-band-green",
          )}
          style={{ width: `${Math.max(4, score)}%` }}
        />
      </div>
    </div>
  );
}

export { BAND_LABEL, BAND_EN };
