"use client";

import { useMemo } from "react";
import { AlertTriangle, Flag, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { useWorkspaceFocus } from "@/lib/chat-store";
import { customerText, repText } from "@/lib/content-i18n";
import { Card, CardContent } from "@/components/ui/card";
import { BandPill } from "@/components/band";
import type { Band, CoachingCardItem, DealRow } from "@/lib/types";

// Most urgent first: at-risk deals before watch before healthy.
const BAND_ORDER: Record<Band, number> = { red: 0, yellow: 1, green: 2 };
const PRIORITY_TONE: Record<string, string> = {
  high: "bg-band-red/10 text-band-red border-band-red/30",
  medium: "bg-band-yellow/10 text-band-yellow border-band-yellow/30",
  low: "bg-muted text-muted-foreground border-border",
};

/**
 * The left pane of the Manager Command Center: team triage. Two stacked groups —
 * at-risk deals across the team, and the reps who need coaching — each grounding
 * the Copilot (right pane) on click via the shared workspace focus. The manager
 * picks a deal or a rep, then just asks ("what's the risk?" / "how do I coach
 * them?") with no slash command or retyping.
 */
export function ManagerContextPane({
  deals,
  needsCoaching,
}: {
  deals: DealRow[];
  needsCoaching: CoachingCardItem[];
}) {
  const { t, lang } = useT();
  const { focus, setFocus } = useWorkspaceFocus("manager");

  // At-risk only (red/yellow), most severe first, then largest amount.
  const atRisk = useMemo(
    () =>
      deals
        .filter((d) => d.band !== "green")
        .slice()
        .sort((a, b) => BAND_ORDER[a.band] - BAND_ORDER[b.band] || b.amount - a.amount),
    [deals],
  );

  return (
    <div className="space-y-5">
      {/* --- At-risk deals --------------------------------------------------- */}
      <div>
        <div className="eyebrow flex items-center gap-1.5">
          <AlertTriangle className="h-3.5 w-3.5" /> {t("mcc.atRisk")}
          <span className="ml-auto font-mono text-[11px] text-muted-foreground">{atRisk.length}</span>
        </div>
        <div className="mt-2 space-y-2">
          {atRisk.length === 0 && (
            <p className="px-1 py-4 text-center text-[12.5px] text-muted-foreground">{t("mcc.noAtRisk")}</p>
          )}
          {atRisk.map((d) => {
            const name = customerText(lang, d.customer).text;
            const active = focus.dealId === d.deal_id;
            return (
              <Card
                key={d.deal_id}
                role="button"
                tabIndex={0}
                onClick={() => setFocus({ dealId: d.deal_id, customerId: d.customer_id, customerName: name })}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setFocus({ dealId: d.deal_id, customerId: d.customer_id, customerName: name });
                  }
                }}
                className={cn(
                  "cursor-pointer transition-colors",
                  active ? "ring-2 ring-primary/40" : "hover:border-primary/40",
                )}
              >
                <CardContent className="flex items-center justify-between gap-3 p-3">
                  <div className="min-w-0">
                    <div className="truncate text-[13.5px] font-medium">{name}</div>
                    <div className="truncate text-[11.5px] text-muted-foreground">
                      {repText(lang, d.rep).text} · {d.stage}
                    </div>
                  </div>
                  <BandPill band={d.band} score={d.score} />
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {/* --- Reps to coach -------------------------------------------------- */}
      <div>
        <div className="eyebrow flex items-center gap-1.5">
          <Users className="h-3.5 w-3.5" /> {t("mcc.toCoach")}
          <span className="ml-auto font-mono text-[11px] text-muted-foreground">{needsCoaching.length}</span>
        </div>
        <div className="mt-2 space-y-2">
          {needsCoaching.length === 0 && (
            <p className="px-1 py-4 text-center text-[12.5px] text-muted-foreground">{t("mcc.noCoaching")}</p>
          )}
          {needsCoaching.map((c) => {
            const name = customerText(lang, c.customer).text;
            const active = focus.dealId === c.deal_id;
            return (
              <Card
                key={c.deal_id}
                role="button"
                tabIndex={0}
                onClick={() => setFocus({ dealId: c.deal_id, customerName: name })}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setFocus({ dealId: c.deal_id, customerName: name });
                  }
                }}
                className={cn(
                  "cursor-pointer transition-colors",
                  active ? "ring-2 ring-primary/40" : "hover:border-primary/40",
                )}
              >
                <CardContent className="space-y-1.5 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-jp text-[13.5px] font-medium">{repText(lang, c.rep).text}</span>
                    <span className={cn("shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide", PRIORITY_TONE[c.priority])}>
                      {t(`coaching.priority.${c.priority}`)}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 text-[12px] text-foreground/80">
                    <Flag className="h-3 w-3 shrink-0 text-band-red" />
                    <span className="truncate">{t(`coaching.issue.${c.issue}`)}</span>
                  </div>
                  <div className="truncate text-[11px] text-muted-foreground">{name}</div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}
