"use client";

import { useEffect, useState } from "react";
import { CalendarClock, TrendingUp, User } from "lucide-react";
import { api } from "@/lib/api";
import type { DealDetail } from "@/lib/types";
import { formatYen } from "@/lib/utils";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { BandPill, RiskMeter } from "@/components/band";

const SEV: Record<string, string> = {
  high: "border-band-red/30 bg-band-red/5 text-band-red",
  medium: "border-band-yellow/30 bg-band-yellow/5 text-band-yellow",
  low: "border-border bg-muted text-muted-foreground",
};

export function DealDrawer({
  dealId,
  open,
  onOpenChange,
}: {
  dealId: string | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const [detail, setDetail] = useState<DealDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !dealId) return;
    setLoading(true);
    setDetail(null);
    api.deal(dealId).then(({ data }) => {
      setDetail(data);
      setLoading(false);
    });
  }, [open, dealId]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        {loading || !detail ? (
          <div className="space-y-4 p-7">
            <Skeleton className="h-8 w-40" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-40 w-full" />
          </div>
        ) : (
          <div className="space-y-6 p-7">
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                <span className="font-mono">{detail.deal.deal_id}</span>
                <span>·</span>
                <span className="capitalize">{detail.deal.stage}</span>
              </div>
              <DialogTitle>{detail.deal.customer}</DialogTitle>
              <DialogDescription className="flex flex-wrap items-center gap-3">
                <span className="inline-flex items-center gap-1"><User className="h-3.5 w-3.5" /> {detail.deal.rep}</span>
                <span className="inline-flex items-center gap-1"><TrendingUp className="h-3.5 w-3.5" /> {formatYen(detail.deal.amount)}</span>
                <span className="inline-flex items-center gap-1"><CalendarClock className="h-3.5 w-3.5" /> {detail.deal.expected_close_date ?? "—"}</span>
              </DialogDescription>
            </div>

            <div className="flex items-center justify-between gap-4 rounded-lg border border-border bg-card p-4">
              <BandPill band={detail.band} score={detail.score} />
              <div className="w-40"><RiskMeter score={detail.score} band={detail.band} /></div>
            </div>

            {/* Signal breakdown — the explainability core */}
            <section>
              <div className="eyebrow mb-3">Signal breakdown · なぜこのスコアか</div>
              <ul className="space-y-2">
                {detail.signals.length === 0 && (
                  <li className="text-[13px] text-muted-foreground">リスク信号なし。</li>
                )}
                {detail.signals.map((s) => (
                  <li key={s.name} className="flex items-start gap-3 rounded-md border border-border bg-card px-3 py-2">
                    <span className="mt-0.5 inline-flex h-6 min-w-9 items-center justify-center rounded bg-band-red/10 px-1.5 font-mono text-[11px] font-semibold text-band-red">
                      +{s.points}
                    </span>
                    <span className="font-jp text-[13px] leading-snug text-foreground/90">{s.reason}</span>
                  </li>
                ))}
              </ul>
            </section>

            {/* Reliability flags */}
            {detail.flags.length > 0 && (
              <section>
                <div className="eyebrow mb-3">Reliability flags · 信頼性フラグ</div>
                <ul className="space-y-2">
                  {detail.flags.map((f) => (
                    <li key={f.name} className={`rounded-md border px-3 py-2 ${SEV[f.severity] ?? SEV.low}`}>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className="border-current/30 text-current">{f.severity}</Badge>
                        <span className="font-mono text-[10px] opacity-70">{f.name}</span>
                      </div>
                      <p className="mt-1 font-jp text-[13px] leading-snug">{f.message}</p>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Recent notes */}
            <section>
              <div className="eyebrow mb-3">Recent notes · 直近メモ</div>
              <ul className="space-y-2">
                {detail.notes.slice(0, 4).map((n) => (
                  <li key={n.note_id} className="rounded-md border border-border bg-paper px-3 py-2">
                    <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                      <span className="font-mono">{n.date}</span>
                      <Badge variant="default">{n.channel}</Badge>
                    </div>
                    <p className="mt-1 font-jp text-[13px] leading-snug text-foreground/90">{n.text}</p>
                  </li>
                ))}
                {detail.notes.length === 0 && (
                  <li className="text-[13px] text-muted-foreground">メモなし。</li>
                )}
              </ul>
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
