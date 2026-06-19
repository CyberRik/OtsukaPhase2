"use client";

import {
  ArrowDownRight,
  ArrowUpRight,
  Check,
  Flag,
  Minus,
  ShieldAlert,
  ShieldCheck,
  TrendingUp,
  Users,
  X,
} from "lucide-react";
import type {
  CoachingCardItem,
  CoachingTrend,
  CoachingWorkspace,
  ConfVRItem,
} from "@/lib/types";
import { useT } from "@/lib/i18n";
import { repText, customerText } from "@/lib/content-i18n";
import { cn } from "@/lib/utils";

const PRIORITY_TONE: Record<string, string> = {
  high: "bg-band-red/10 text-band-red border-band-red/30",
  medium: "bg-band-yellow/10 text-band-yellow border-band-yellow/30",
  low: "bg-muted text-muted-foreground border-border",
};
const BAND_DOT: Record<string, string> = {
  red: "bg-band-red", yellow: "bg-band-yellow", green: "bg-conf-high",
};

// --- Section 4 (top digest): Coaching Summary ------------------------------
function SummaryDigest({ s }: { s: CoachingWorkspace["summary"] }) {
  const { t } = useT();
  const stats = [
    { n: s.reps_need_coaching, label: t("coaching.sum.reps") },
    { n: s.opportunities_flagged, label: t("coaching.sum.flagged") },
    { n: s.improving, label: t("coaching.sum.improving") },
  ];
  return (
    <div className="rounded-2xl border border-navy/20 bg-gradient-to-br from-navy/[0.05] to-transparent p-5">
      <div className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-navy">
        <TrendingUp className="h-3.5 w-3.5" /> {t("coaching.summaryTitle")}
      </div>
      <div className="mt-4 flex flex-wrap items-start gap-x-8 gap-y-4">
        {stats.map((st) => (
          <div key={st.label} className="flex items-baseline gap-1.5">
            <span className="text-[28px] font-semibold leading-none tracking-tight text-foreground">{st.n}</span>
            <span className="max-w-[10rem] text-[12.5px] leading-snug text-foreground/70">{st.label}</span>
          </div>
        ))}
        {s.top_issue && (
          <div className="flex flex-col gap-0.5">
            <span className="text-[11px] text-muted-foreground">{t("coaching.sum.topIssue")}</span>
            <span className="rounded-full bg-band-red/10 px-2.5 py-1 text-[12.5px] font-medium text-band-red">
              {t(`coaching.issue.${s.top_issue}`)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// --- Section 1: Needs Coaching ---------------------------------------------
function NeedsCard({ c }: { c: CoachingCardItem }) {
  const { t, lang } = useT();
  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2">
          <span className={cn("h-2 w-2 rounded-full", BAND_DOT[c.band] ?? "bg-muted")} />
          <span className="font-jp text-[14px] font-semibold text-foreground">
            {repText(lang, c.rep).text}
          </span>
        </span>
        <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide", PRIORITY_TONE[c.priority])}>
          {t(`coaching.priority.${c.priority}`)}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1 text-[13px] font-medium text-foreground">
          <Flag className="h-3.5 w-3.5 text-band-red" /> {t(`coaching.issue.${c.issue}`)}
        </span>
        <span className="font-mono text-[10px] text-muted-foreground">{c.deal_id}</span>
        <span className="font-jp text-[11px] text-muted-foreground">
          · {customerText(lang, c.customer).text}
        </span>
      </div>
      <p className="mt-2 text-[12.5px] leading-relaxed text-foreground/75">
        {t(`coaching.reason.${c.issue}`, c.params)}
      </p>
    </div>
  );
}

// --- Section 2: Team Coaching Trends ---------------------------------------
const TREND_ICON = { up: ArrowUpRight, down: ArrowDownRight, flat: Minus };
const TREND_TONE: Record<string, string> = {
  up: "text-band-red", down: "text-conf-high", flat: "text-muted-foreground",
};

function TrendRow({ tr, max }: { tr: CoachingTrend; max: number }) {
  const { t } = useT();
  const Icon = TREND_ICON[tr.trend];
  return (
    <div className="rounded-xl border border-border bg-card px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[13px] font-medium text-foreground">{t(`coaching.issue.${tr.issue}`)}</span>
        <span className="flex items-center gap-2">
          <span className={cn("inline-flex items-center gap-0.5 text-[11px] font-medium", TREND_TONE[tr.trend])}>
            <Icon className="h-3.5 w-3.5" /> {t(`coaching.trend.${tr.trend}`)}
          </span>
          <span className="font-mono text-[13px] font-semibold text-foreground">{tr.count}</span>
        </span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-navy/60" style={{ width: `${(tr.count / max) * 100}%` }} />
      </div>
      <div className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-muted-foreground">
        <Users className="h-3 w-3" /> {t("coaching.affectedReps", { n: String(tr.reps.length) })}
      </div>
    </div>
  );
}

// --- Section 3: Confidence vs Reality (signature) --------------------------
function ConfCard({ c }: { c: ConfVRItem }) {
  const { t, lang } = useT();
  const mismatch = c.status === "mismatch";
  return (
    <div className={cn(
      "overflow-hidden rounded-xl border bg-card shadow-[0_1px_2px_rgba(16,24,40,0.04)]",
      mismatch ? "border-band-red/30" : "border-conf-high/30",
    )}>
      <div className={cn("flex items-center justify-between gap-2 px-4 py-2.5",
        mismatch ? "bg-band-red/[0.05]" : "bg-conf-high/[0.06]")}>
        <span className="flex items-center gap-2">
          <span className="font-jp text-[13px] font-semibold text-foreground">
            {repText(lang, c.rep).text}
          </span>
          <span className="font-jp text-[11px] text-muted-foreground">
            · {customerText(lang, c.customer).text}
          </span>
        </span>
        <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
          mismatch ? "bg-band-red/15 text-band-red" : "bg-conf-high/15 text-conf-high")}>
          {mismatch ? <ShieldAlert className="h-3 w-3" /> : <ShieldCheck className="h-3 w-3" />}
          {t(`coaching.confStatus.${c.status}`)}
        </span>
      </div>
      <div className="px-4 py-3">
        <div className="text-[12px] font-medium text-foreground/80">{t(`coaching.confLevel.${c.confidence}`)}</div>
        <div className="mt-2 text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">{t("coaching.observed")}</div>
        <ul className="mt-1.5 space-y-1">
          {c.signals.map((s) => (
            <li key={s.key} className="flex items-center gap-2 text-[12.5px]">
              {s.positive
                ? <Check className="h-3.5 w-3.5 shrink-0 text-conf-high" />
                : <X className="h-3.5 w-3.5 shrink-0 text-band-red" />}
              <span className={cn(s.positive ? "text-foreground/85" : "text-foreground/70")}>{t(`coaching.dim.${s.key}`)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export function ManagerCoaching({ data }: { data: CoachingWorkspace }) {
  const { t } = useT();
  const maxTrend = Math.max(1, ...data.trends.map((tr) => tr.count));

  return (
    <div className="space-y-8">
      <SummaryDigest s={data.summary} />

      {/* Section 1 — Needs Coaching */}
      <section>
        <div className="eyebrow mb-1 flex items-center gap-1.5"><Flag className="h-3.5 w-3.5" /> {t("coaching.needsTitle")}</div>
        <p className="mb-3 text-[12px] text-muted-foreground">{t("coaching.needsSub")}</p>
        {data.needs_coaching.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border bg-muted/30 p-8 text-center text-[13px] text-muted-foreground">
            {t("coaching.workspaceEmpty")}
          </div>
        ) : (
          <div className="grid gap-2.5 md:grid-cols-2">
            {data.needs_coaching.map((c) => <NeedsCard key={c.deal_id} c={c} />)}
          </div>
        )}
      </section>

      {/* Section 2 — Team Coaching Trends */}
      <section>
        <div className="eyebrow mb-1 flex items-center gap-1.5"><TrendingUp className="h-3.5 w-3.5" /> {t("coaching.trendsTitle")}</div>
        <p className="mb-3 text-[12px] text-muted-foreground">{t("coaching.trendsSub")}</p>
        <div className="grid gap-2.5 md:grid-cols-2">
          {data.trends.map((tr) => <TrendRow key={tr.issue} tr={tr} max={maxTrend} />)}
        </div>
      </section>

      {/* Section 3 — Confidence vs Reality */}
      <section>
        <div className="eyebrow mb-1 flex items-center gap-1.5"><ShieldAlert className="h-3.5 w-3.5" /> {t("coaching.confTitle")}</div>
        <p className="mb-3 text-[12px] text-muted-foreground">{t("coaching.confSub")}</p>
        <div className="grid gap-2.5 md:grid-cols-2">
          {data.confidence.map((c) => <ConfCard key={c.deal_id} c={c} />)}
        </div>
      </section>
    </div>
  );
}
