"use client";

import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import type { Band } from "@/lib/types";

const KEY: Record<Band, string> = { red: "dash.atRisk", yellow: "dash.watch", green: "dash.healthy" };

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
  const { t } = useT();
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1",
        band === "red" && "bg-band-red/8 text-band-red ring-band-red/25",
        band === "yellow" && "bg-band-yellow/10 text-band-yellow ring-band-yellow/25",
        band === "green" && "bg-band-green/8 text-band-green ring-band-green/25",
      )}
    >
      <BandDot band={band} />
      {t(KEY[band])}
      {typeof score === "number" && <span className="font-mono opacity-70">{score}</span>}
    </span>
  );
}

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
