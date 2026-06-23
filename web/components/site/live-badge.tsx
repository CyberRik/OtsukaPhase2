"use client";

import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";

// Honest status: green when the FastAPI engine answered, neutral when showing the
// committed seed snapshot. Never silently fakes liveness.
export function LiveBadge({ live }: { live: boolean }) {
  const { t } = useT();
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        live ? "border-band-green/30 bg-band-green/5 text-band-green" : "border-border bg-muted text-muted-foreground",
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", live ? "bg-band-green" : "bg-muted-foreground")} />
      {live ? t("common.live") : t("common.snapshot")}
    </span>
  );
}
