"use client";

import { useState } from "react";
import {
  BookOpen,
  ChevronDown,
  Flag,
  Minus,
  MessagesSquare,
  Sparkles,
  Target,
  TrendingDown,
  TrendingUp,
  Users,
} from "lucide-react";
import type {
  CoachingThread,
  RepProfile,
  RepProfileRow,
  RepProgress,
} from "@/lib/types";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { repText } from "@/lib/content-i18n";
import { cn } from "@/lib/utils";

const BAND_DOT: Record<string, string> = {
  red: "bg-band-red",
  yellow: "bg-band-yellow",
  green: "bg-conf-high",
};
const TREND_ICON = { improving: TrendingDown, worsening: TrendingUp, flat: Minus };
const TREND_TONE: Record<string, string> = {
  improving: "text-conf-high",
  worsening: "text-band-red",
  flat: "text-muted-foreground",
};
const STATUS_TONE: Record<string, string> = {
  open: "bg-band-red/10 text-band-red border-band-red/30",
  acknowledged: "bg-band-yellow/10 text-band-yellow border-band-yellow/30",
  resolved: "bg-conf-high/10 text-conf-high border-conf-high/30",
};

function riskTone(v: number): string {
  if (v >= 45) return "text-band-red";
  if (v >= 30) return "text-band-yellow";
  return "text-conf-high";
}

// --- progress: per-window weaknesses-per-deal as a small bar series ---------
function ProgressTrend({ p }: { p: RepProgress }) {
  const { t } = useT();
  const max = Math.max(0.5, ...p.series.map((s) => s.weaknesses_per_deal));
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-navy">
        <Target className="h-3.5 w-3.5" /> {t("repcoach.progress")}
        <span className="ml-auto font-jp text-[11px] font-normal normal-case text-muted-foreground">
          {p.headline}
        </span>
      </div>
      <div className="mt-3 flex items-end gap-3">
        {p.series.map((s) => (
          <div key={s.window} className="flex flex-1 flex-col items-center gap-1">
            <div className="flex h-20 w-full items-end justify-center">
              <div
                className="w-6 rounded-t bg-navy/70"
                style={{ height: `${Math.max(4, (s.weaknesses_per_deal / max) * 80)}px` }}
                title={`${s.weaknesses_per_deal} / deal`}
              />
            </div>
            <span className="text-[10px] font-mono text-muted-foreground">{s.window}</span>
            <span className="text-[11px] font-medium text-foreground/80">
              {s.weaknesses_per_deal.toFixed(1)}
            </span>
          </div>
        ))}
      </div>
      {Object.keys(p.trends).length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {Object.entries(p.trends).map(([issue, dir]) => {
            const Icon = TREND_ICON[dir];
            return (
              <span
                key={issue}
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[10.5px]",
                  TREND_TONE[dir]
                )}
              >
                <Icon className="h-3 w-3" />
                {t(`coaching.issue.${issue}`)} · {t(`repcoach.trend.${dir}`)}
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ThreadCard({ th }: { th: CoachingThread }) {
  const { t } = useT();
  return (
    <div className="rounded-xl border border-border bg-card px-4 py-3">
      <div className="flex items-center gap-2">
        <span className="font-mono text-[10px] text-muted-foreground">{th.deal_id}</span>
        <span className="text-[12px] font-medium text-foreground">
          {t(`coaching.issue.${th.issue_key}`)}
        </span>
        <span
          className={cn(
            "ml-auto rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
            STATUS_TONE[th.status]
          )}
        >
          {t(`repcoach.status.${th.status}`)}
        </span>
      </div>
      <ul className="mt-2.5 space-y-2">
        {th.messages.map((m, i) => (
          <li key={i} className="flex gap-2 text-[12.5px]">
            <span
              className={cn(
                "mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold",
                m.role === "manager"
                  ? "bg-navy/10 text-navy"
                  : "bg-muted text-muted-foreground"
              )}
            >
              {t(`role.${m.role === "manager" ? "manager" : "junior"}.short`)}
            </span>
            <div>
              <span className="font-jp leading-relaxed text-foreground/85">{m.text}</span>
              <span className="ml-2 font-mono text-[10px] text-muted-foreground">{m.date}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function WeaknessCard({ w }: { w: RepProfile["weaknesses"][number] }) {
  const { t } = useT();
  return (
    <div className="rounded-xl border border-border bg-card px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1 text-[13px] font-medium text-foreground">
          <Flag className="h-3.5 w-3.5 text-band-red" /> {t(`coaching.issue.${w.issue}`)}
        </span>
        <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">
          ×{w.count} · {Math.round(w.share * 100)}%
        </span>
        {w.example_deals.length > 0 && (
          <span className="ml-auto font-mono text-[10px] text-muted-foreground">
            {t("repcoach.examples")}: {w.example_deals.join(", ")}
          </span>
        )}
      </div>
      {w.principle && (
        <p className="mt-2 flex gap-1.5 text-[12px] leading-relaxed text-foreground/75">
          <BookOpen className="mt-0.5 h-3.5 w-3.5 shrink-0 text-navy" />
          <span className="font-jp">
            <span className="font-semibold text-navy">{t("repcoach.principle")}:</span>{" "}
            {w.principle.statement}
          </span>
        </p>
      )}
      {w.case && (
        <p className="mt-1.5 text-[12px] text-muted-foreground">
          <span className="font-semibold">{t("repcoach.case")}:</span>{" "}
          <span className="font-mono">{w.case.deal_id}</span> · {w.case.customer} ·{" "}
          {w.case.outcome}
        </p>
      )}
      {w.action && (
        <p className="mt-1.5 flex gap-1.5 font-jp text-[12.5px] leading-relaxed text-foreground/85">
          <Target className="mt-0.5 h-3.5 w-3.5 shrink-0 text-conf-high" />
          <span>
            <span className="font-semibold text-conf-high">{t("repcoach.action")}:</span>{" "}
            {w.action}
          </span>
        </p>
      )}
    </div>
  );
}

function DetailPanel({
  profile,
  progress,
  threads,
  loading,
}: {
  profile: RepProfile | null;
  progress: RepProgress | null;
  threads: CoachingThread[];
  loading: boolean;
}) {
  const { t } = useT();
  if (loading) {
    return (
      <div className="px-4 py-6 text-[12px] text-muted-foreground">{t("repcoach.loading")}</div>
    );
  }
  if (!profile) return null;
  return (
    <div className="space-y-4 border-t border-border bg-muted/20 px-4 py-4">
      {/* strengths + talking points */}
      <div className="grid gap-4 md:grid-cols-2">
        {profile.strengths.length > 0 && (
          <div className="rounded-xl border border-border bg-card p-4">
            <div className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-conf-high">
              <Sparkles className="h-3.5 w-3.5" /> {t("repcoach.strengths")}
            </div>
            <ul className="mt-2 space-y-1.5">
              {profile.strengths.map((s, i) => (
                <li key={i} className="font-jp text-[12.5px] leading-relaxed text-foreground/85">
                  · {s}
                </li>
              ))}
            </ul>
          </div>
        )}
        {profile.talking_points.length > 0 && (
          <div className="rounded-xl border border-border bg-card p-4">
            <div className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-navy">
              <MessagesSquare className="h-3.5 w-3.5" /> {t("repcoach.talkingPoints")}
            </div>
            <ul className="mt-2 space-y-1.5">
              {profile.talking_points.map((s, i) => (
                <li key={i} className="font-jp text-[12.5px] leading-relaxed text-foreground/85">
                  · {s}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* recurring weaknesses */}
      {profile.weaknesses.length > 0 && (
        <div>
          <div className="eyebrow mb-2 flex items-center gap-1.5">
            <Flag className="h-3.5 w-3.5" /> {t("repcoach.weaknesses")}
          </div>
          <div className="space-y-2.5">
            {profile.weaknesses.map((w) => (
              <WeaknessCard key={w.issue} w={w} />
            ))}
          </div>
        </div>
      )}

      {/* progress + threads */}
      {progress && progress.series.length > 0 && <ProgressTrend p={progress} />}

      <div>
        <div className="eyebrow mb-2 flex items-center gap-1.5">
          <MessagesSquare className="h-3.5 w-3.5" /> {t("repcoach.threads")}
        </div>
        {threads.length === 0 ? (
          <p className="text-[12px] text-muted-foreground">{t("repcoach.noThreads")}</p>
        ) : (
          <div className="space-y-2.5">
            {threads.map((th) => (
              <ThreadCard key={th.thread_id} th={th} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function RepProfiles({ initial }: { initial: RepProfileRow[] }) {
  const { t, lang } = useT();
  const [selected, setSelected] = useState<string | null>(null);
  const [profile, setProfile] = useState<RepProfile | null>(null);
  const [progress, setProgress] = useState<RepProgress | null>(null);
  const [threads, setThreads] = useState<CoachingThread[]>([]);
  const [loading, setLoading] = useState(false);

  async function select(id: string) {
    if (selected === id) {
      setSelected(null);
      return;
    }
    setSelected(id);
    setLoading(true);
    setProfile(null);
    setProgress(null);
    setThreads([]);
    const [p, pr, th] = await Promise.all([
      api.repProfile(id),
      api.repProgress(id),
      api.coachThreads({ repId: id }),
    ]);
    // Ignore stale responses if the user clicked another rep meanwhile.
    setProfile(p.data);
    setProgress(pr.data);
    setThreads(th.data.threads);
    setLoading(false);
  }

  return (
    <section>
      <div className="eyebrow mb-1 flex items-center gap-1.5">
        <Users className="h-3.5 w-3.5" /> {t("repcoach.title")}
      </div>
      <p className="mb-3 text-[12px] text-muted-foreground">{t("repcoach.sub")}</p>

      <div className="overflow-hidden rounded-2xl border border-border bg-card">
        {/* column header */}
        <div className="grid grid-cols-[1.6fr_repeat(4,0.7fr)_1.4fr_auto] gap-2 border-b border-border bg-muted/40 px-4 py-2 text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
          <span>{t("repcoach.col.rep")}</span>
          <span className="text-center">{t("repcoach.col.openDeals")}</span>
          <span className="text-center">{t("repcoach.col.atRisk")}</span>
          <span className="text-center">{t("repcoach.col.avgRisk")}</span>
          <span className="text-center">{t("repcoach.col.actedOn")}</span>
          <span>{t("repcoach.col.focus")}</span>
          <span />
        </div>

        {initial.map((rep) => {
          const open = selected === rep.employee_id;
          return (
            <div key={rep.employee_id} className="border-b border-border last:border-b-0">
              <button
                onClick={() => select(rep.employee_id)}
                className={cn(
                  "grid w-full grid-cols-[1.6fr_repeat(4,0.7fr)_1.4fr_auto] items-center gap-2 px-4 py-3 text-left transition-colors hover:bg-muted/30",
                  open && "bg-muted/40"
                )}
              >
                <span className="font-jp text-[13px] font-medium text-foreground">
                  {repText(lang, rep.name).text}
                </span>
                <span className="text-center text-[12.5px] text-foreground/80">{rep.open_deals}</span>
                <span className="text-center text-[12.5px] font-semibold text-band-red">{rep.at_risk}</span>
                <span className={cn("text-center text-[12.5px] font-semibold", riskTone(rep.avg_risk))}>
                  {rep.avg_risk}
                </span>
                <span className="text-center text-[12px] text-muted-foreground">
                  {rep.acted_on_rate == null ? "—" : `${Math.round(rep.acted_on_rate * 100)}%`}
                </span>
                <span className="truncate text-[12px] text-foreground/75">
                  {rep.development_focus ? t(`coaching.issue.${rep.development_focus}`) : "—"}
                </span>
                <ChevronDown
                  className={cn(
                    "h-4 w-4 text-muted-foreground transition-transform",
                    open && "rotate-180"
                  )}
                />
              </button>
              {open && (
                <DetailPanel
                  profile={profile}
                  progress={progress}
                  threads={threads}
                  loading={loading}
                />
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
