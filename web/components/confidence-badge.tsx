"use client";

import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import type { Confidence } from "@/lib/types";

const STYLE: Record<Confidence, { dot: string; text: string; ring: string }> = {
  high: { dot: "bg-conf-high", text: "text-conf-high", ring: "ring-conf-high/25 bg-conf-high/5" },
  medium: { dot: "bg-conf-medium", text: "text-conf-medium", ring: "ring-conf-medium/25 bg-conf-medium/5" },
  low: { dot: "bg-conf-low", text: "text-conf-low", ring: "ring-conf-low/25 bg-conf-low/5" },
  unverified: { dot: "bg-conf-unverified", text: "text-conf-unverified", ring: "ring-conf-unverified/30 bg-conf-unverified/5" },
};

export function ConfidenceBadge({
  level,
  showWhy = false,
  className,
}: {
  level: Confidence;
  showWhy?: boolean;
  className?: string;
}) {
  const { t } = useT();
  const s = STYLE[level] ?? STYLE.unverified;
  const why = t(`conf.${level}.why`);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1",
        s.ring,
        s.text,
        className,
      )}
      title={why}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", s.dot)} />
      {t(`conf.${level}`)}
      {showWhy && <span className="font-normal text-muted-foreground">— {why}</span>}
    </span>
  );
}
