"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowUpRight, Building2, CalendarClock, Landmark, Sparkles, TrendingUp, User } from "lucide-react";
import { api } from "@/lib/api";
import type { AccountHealth, DealDetail } from "@/lib/types";
import { formatYen } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { customerText, repText, flagMessageText, signalReasonText } from "@/lib/content-i18n";
import { JpOriginalBadge } from "@/components/jp-original-badge";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { BandDot, BandPill, RiskMeter } from "@/components/band";
import { DealTimeline } from "@/components/dashboard/deal-timeline";

const SEV: Record<string, string> = {
  high: "border-band-red/30 bg-band-red/5 text-band-red",
  medium: "border-band-yellow/30 bg-band-yellow/5 text-band-yellow",
  low: "border-border bg-muted text-muted-foreground",
};

export function DealDrawer({
  dealId, open, onOpenChange, onAskCopilot,
}: {
  dealId: string | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  /** When set, show a CTA that grounds the Copilot on this deal and closes the drawer. */
  onAskCopilot?: (g: { dealId: string; customerId: string; customerName: string }) => void;
}) {
  const { t, lang } = useT();
  const pathname = usePathname();
  const role = pathname?.startsWith("/manager") ? "manager" : "junior";
  const [detail, setDetail] = useState<DealDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [acctHealth, setAcctHealth] = useState<AccountHealth | null>(null);

  useEffect(() => {
    if (!open || !dealId) return;
    setLoading(true);
    setDetail(null);
    setAcctHealth(null);
    api.deal(dealId).then(({ data }) => {
      setDetail(data);
      setLoading(false);
      // Fetch the account roll-up so the deal can be weighed against the whole
      // relationship — the deal↔account cross-link.
      if (data?.deal.customer_id) {
        api.account(data.deal.customer_id).then(({ data: a }) => setAcctHealth(a?.health ?? null));
      }
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
              <DialogTitle className="font-jp">
                {(() => { const ct = customerText(lang, detail.deal.customer); return <>{ct.text}{ct.fallback && <JpOriginalBadge />}</>; })()}
              </DialogTitle>
              <DialogDescription className="flex flex-wrap items-center gap-3 font-jp">
                <span className="inline-flex items-center gap-1">
                  <User className="h-3.5 w-3.5" />
                  {(() => { const rt = repText(lang, detail.deal.rep); return <>{rt.text}{rt.fallback && <JpOriginalBadge />}</>; })()}
                </span>
                <span className="inline-flex items-center gap-1"><TrendingUp className="h-3.5 w-3.5" /> {formatYen(detail.deal.amount)}</span>
                <span className="inline-flex items-center gap-1"><CalendarClock className="h-3.5 w-3.5" /> {detail.deal.expected_close_date ?? "—"}</span>
              </DialogDescription>
            </div>

            <div className="flex items-center justify-between gap-4 rounded-xl border border-border bg-card p-4">
              <BandPill band={detail.band} score={detail.score} />
              <div className="w-40"><RiskMeter score={detail.score} band={detail.band} /></div>
            </div>

            {/* Ground the Copilot on this deal, then close the drawer so the rail is in view */}
            {onAskCopilot && (
              <button
                onClick={() => {
                  onAskCopilot({
                    dealId: detail.deal.deal_id,
                    customerId: detail.deal.customer_id,
                    customerName: customerText(lang, detail.deal.customer).text,
                  });
                  onOpenChange(false);
                }}
                className="flex w-full items-center justify-center gap-1.5 rounded-xl bg-navy px-4 py-2.5 text-[13px] font-semibold text-white transition-colors hover:bg-navy/90"
              >
                <Sparkles className="h-4 w-4" /> {t("mcc.askThisDeal")}
              </button>
            )}

            {/* Junior-only: rehearse how this deal will fare in the customer's
                closed-door consensus (稟議) review — a lens on the same engine. */}
            {role === "junior" && (
              <Link
                href={`/junior/training/ringi?deal=${detail.deal.deal_id}`}
                onClick={() => onOpenChange(false)}
                className="flex items-center justify-between gap-3 rounded-xl border border-primary/25 bg-primary/[0.03] px-4 py-3 transition-colors hover:border-primary/50"
              >
                <span className="flex items-center gap-2 text-[13px]">
                  <Landmark className="h-4 w-4 text-primary" />
                  <span className="font-medium text-foreground">
                    {lang === "ja" ? "この案件で稟議を予行する" : "Rehearse the consensus review"}
                  </span>
                </span>
                <span className="inline-flex items-center gap-1 text-[12.5px] font-medium text-primary">
                  {lang === "ja" ? "シミュレーション" : "Simulate"}
                  <ArrowUpRight className="h-3.5 w-3.5" />
                </span>
              </Link>
            )}

            {/* Account cross-link: weigh this deal against the whole relationship */}
            {acctHealth && (
              <Link
                href={`/${role}/accounts/${detail.deal.customer_id}`}
                onClick={() => onOpenChange(false)}
                className="flex items-center justify-between gap-3 rounded-xl border border-primary/25 bg-primary/[0.03] px-4 py-3 transition-colors hover:border-primary/50"
              >
                <span className="flex items-center gap-2 text-[13px]">
                  <Building2 className="h-4 w-4 text-primary" />
                  <span className="text-muted-foreground">
                    {lang === "ja" ? "このアカウントの健全度" : "This account has Health"}
                  </span>
                  <span className="inline-flex items-center gap-1 font-semibold text-foreground">
                    <BandDot band={acctHealth.band} /> {acctHealth.score}/100
                  </span>
                </span>
                <span className="inline-flex items-center gap-1 text-[12.5px] font-medium text-primary">
                  {lang === "ja" ? "アカウント分析を見る" : "View Account Intelligence"}
                  <ArrowUpRight className="h-3.5 w-3.5" />
                </span>
              </Link>
            )}

            <section>
              <div className="eyebrow mb-3">{t("dash.signalBreakdown")} · {t("dash.whyScore")}</div>
              <ul className="space-y-2">
                {detail.signals.length === 0 && <li className="text-[13px] text-muted-foreground">{t("dash.noSignals")}</li>}
                {detail.signals.map((s) => {
                  const sr = signalReasonText(lang, s.reason);
                  return (
                    <li key={s.name} className="flex items-start gap-3 rounded-lg border border-border bg-card px-3 py-2">
                      <span className="mt-0.5 inline-flex h-6 min-w-9 items-center justify-center rounded bg-band-red/10 px-1.5 font-mono text-[11px] font-semibold text-band-red">
                        +{s.points}
                      </span>
                      <span className="font-jp text-[13px] leading-snug text-foreground/90">
                        {sr.text}
                        {sr.fallback && <JpOriginalBadge />}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </section>

            {detail.flags.length > 0 && (
              <section>
                <div className="eyebrow mb-3">{t("dash.relFlags")}</div>
                <ul className="space-y-2">
                  {detail.flags.map((f) => {
                    const fm = flagMessageText(lang, f.message);
                    return (
                      <li key={f.name} className={`rounded-lg border px-3 py-2 ${SEV[f.severity] ?? SEV.low}`}>
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="border-current/30 text-current">{f.severity}</Badge>
                          <span className="font-mono text-[10px] opacity-70">{f.name}</span>
                        </div>
                        <p className="mt-1 font-jp text-[13px] leading-snug">
                          {fm.text}
                          {fm.fallback && <JpOriginalBadge />}
                        </p>
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}

            <section>
              <div className="eyebrow mb-1 flex items-center gap-1.5"><CalendarClock className="h-3.5 w-3.5" /> {t("timeline.title")}</div>
              <p className="mb-3 text-[11.5px] text-muted-foreground">{t("timeline.sub")}</p>
              <DealTimeline events={detail.timeline} />
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
