"use client";

import { CalendarClock, Package, Receipt, ZapOff, type LucideIcon } from "lucide-react";
import type { TimelineEvent } from "@/lib/types";
import { useT } from "@/lib/i18n";
import { cn, formatYen } from "@/lib/utils";
import { TranslatedText } from "@/components/site/translated-text";

// Visual chronological log of a deal — Pillar 2: Experience. Folds activities,
// quotes, and orders into one sequence and surfaces stretches of silence, so a
// junior or manager can *see* how the deal actually moved. Pure presentation
// over the timeline the API builds; type labels are localized here.
const ICONS: Record<TimelineEvent["kind"], LucideIcon> = {
  activity: CalendarClock,
  quote: Receipt,
  order: Package,
  gap: ZapOff,
};

function eventLabel(
  t: (k: string, v?: Record<string, string>) => string,
  ev: TimelineEvent,
): string {
  if (ev.kind === "quote") return t("timeline.quote");
  if (ev.kind === "order") return t("timeline.order");
  if (ev.kind === "gap") return t("timeline.gap", { days: String(ev.days ?? 0) });
  const code = (ev.type || "").split("_")[0];
  return t(`timeline.type.${code}`);
}

export function DealTimeline({ events }: { events: TimelineEvent[] }) {
  const { t } = useT();
  if (!events.length) {
    return <p className="text-[13px] text-muted-foreground">{t("timeline.empty")}</p>;
  }
  return (
    <ol className="relative space-y-4 border-l border-border pl-6">
      {events.map((ev, i) => {
        const Icon = ICONS[ev.kind];
        const gap = ev.kind === "gap";
        const tone =
          gap ? "bg-band-yellow/15 text-band-yellow"
            : ev.kind === "order" ? "bg-conf-high/15 text-conf-high"
            : ev.kind === "quote" ? "bg-navy/10 text-navy"
            : "bg-primary/10 text-primary";
        return (
          <li key={i} className="relative">
            <span className={cn(
              "absolute -left-[31px] flex h-5 w-5 items-center justify-center rounded-full border-2 border-background",
              tone,
            )}>
              <Icon className="h-3 w-3" />
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[11px] text-muted-foreground">{ev.date}</span>
              <span className={cn("text-[12px] font-semibold", gap ? "text-band-yellow" : "text-foreground/90")}>
                {eventLabel(t, ev)}
              </span>
              {ev.amount != null && (
                <span className="text-[11px] text-muted-foreground">{formatYen(ev.amount)}</span>
              )}
            </div>
            {!gap && ev.title && (
              <div className="mt-0.5 font-jp text-[11.5px] text-muted-foreground">
                <TranslatedText text={ev.title} />
              </div>
            )}
            {!gap && ev.detail && (
              <p className="mt-0.5 font-jp text-[12.5px] leading-snug text-foreground/80">
                <TranslatedText text={ev.detail} />
              </p>
            )}
          </li>
        );
      })}
    </ol>
  );
}
