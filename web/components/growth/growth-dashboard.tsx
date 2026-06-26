"use client";

import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  BookMarked,
  Building2,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Flame,
  GraduationCap,
  Layers,
  type LucideIcon,
  MessageCircle,
  MessagesSquare,
  Minus,
  Sparkles,
  Star,
} from "lucide-react";
import type {
  CoachingThread,
  CoachingThreadMessage,
  DealRow,
  GrowthResponse,
  SkillEvidence,
} from "@/lib/types";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { tagText, repText, departmentText, customerText } from "@/lib/content-i18n";
import { Badge } from "@/components/ui/badge";
import { useState } from "react";
import { DealDrawer } from "@/components/dashboard/deal-drawer";

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function monthLabel(ym: string, lang: "ja" | "en"): string {
  const [y, m] = ym.split("-").map(Number);
  if (!y || !m) return ym;
  return new Date(y, m - 1, 1).toLocaleString(lang === "ja" ? "ja-JP" : "en-US", { month: "short" });
}

// Tailwind class (for legend dots) and actual CSS color (for SVG strokes)
const SKILL_COLORS: Record<string, string> = {
  relationship_building: "bg-blue-400",
  decision_maker_discovery: "bg-violet-400",
  customer_discovery: "#2dd4bf",
  closing_discipline: "bg-rose-400",
  proposal_pricing: "bg-amber-400",
};
const SKILL_STROKE: Record<string, string> = {
  relationship_building: "#60a5fa",
  decision_maker_discovery: "#a78bfa",
  customer_discovery: "#2dd4bf",
  closing_discipline: "#fb7185",
  proposal_pricing: "#fbbf24",
};

const STATUS_TONE: Record<string, string> = {
  open: "bg-band-red/10 text-band-red border-band-red/30",
  acknowledged: "bg-band-yellow/10 text-band-yellow border-band-yellow/30",
  resolved: "bg-conf-high/10 text-conf-high border-conf-high/30",
};

const STATUS_ORDER: Record<string, number> = { open: 0, acknowledged: 1, resolved: 2 };

const BAND_CHIP: Record<string, string> = { red: "🔴", yellow: "🟡", green: "🟢" };
const BAND_BG: Record<string, string> = {
  red: "border-band-red/20 bg-band-red/[0.03]",
  yellow: "border-band-yellow/20 bg-band-yellow/[0.03]",
  green: "border-conf-high/20 bg-conf-high/[0.03]",
};

// ---------------------------------------------------------------------------
// sub-components
// ---------------------------------------------------------------------------

function StatCard({ icon: Icon, value, label, sub, tone }: {
  icon: LucideIcon; value: number; label: string; sub?: string; tone: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      <span className={cn("inline-flex h-8 w-8 items-center justify-center rounded-lg", tone)}>
        <Icon className="h-4 w-4" />
      </span>
      <div className="mt-3 flex items-baseline gap-1.5">
        <span className="text-[26px] font-semibold leading-none tracking-tight text-foreground">{value}</span>
        {sub && <span className="text-[11px] text-muted-foreground">{sub}</span>}
      </div>
      <div className="mt-1 text-[12px] text-muted-foreground">{label}</div>
    </div>
  );
}

function JourneyStat({ n, label }: { n: number; label: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-[28px] font-semibold leading-none tracking-tight text-primary">{n}</span>
      <span className="text-[12.5px] text-foreground/70">{label}</span>
    </div>
  );
}

function Stars({ n }: { n: number }) {
  return (
    <span className="flex gap-0.5">
      {Array.from({ length: 5 }).map((_, i) => (
        <Star key={i} className={cn("h-4 w-4", i < n ? "fill-band-yellow text-band-yellow" : "fill-none text-muted-foreground/30")} />
      ))}
    </span>
  );
}

function TrendBadge({ trend }: { trend: string }) {
  const { t } = useT();
  if (trend === "improving") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded-full bg-conf-high/10 px-2 py-0.5 text-[10px] font-semibold text-conf-high">
        <ArrowUp className="h-3 w-3" />{t("growth.skill.trend.improving")}
      </span>
    );
  }
  if (trend === "needs_work") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded-full bg-band-red/10 px-2 py-0.5 text-[10px] font-semibold text-band-red">
        <ArrowDown className="h-3 w-3" />{t("growth.skill.trend.needs_work")}
      </span>
    );
  }
  return null;
}

function EvidenceChip({ ev }: { ev: SkillEvidence }) {
  const { t } = useT();
  const sourceLabel = t(`growth.skill.evidence.${ev.source}`);
  return (
    <div className={cn(
      "flex items-start gap-2 rounded-lg border px-3 py-2 text-[11.5px]",
      ev.positive
        ? "border-conf-high/25 bg-conf-high/[0.04] text-foreground/80"
        : "border-band-yellow/30 bg-band-yellow/[0.04] text-foreground/80",
    )}>
      {ev.positive
        ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-conf-high" />
        : <Minus className="mt-0.5 h-3.5 w-3.5 shrink-0 text-band-yellow" />}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="text-[9.5px] font-semibold uppercase tracking-wide text-muted-foreground">{sourceLabel}</span>
          {ev.deal_id && <span className="font-mono text-[9.5px] text-muted-foreground/60">{ev.deal_id}</span>}
          <span className="text-[9.5px] text-muted-foreground/50">{ev.date}</span>
        </div>
        <p className="mt-0.5 font-jp leading-snug">{ev.text}</p>
      </div>
    </div>
  );
}

function SkillCard({ skill, lang, selected, onSelect }: {
  skill: { key: string; stars: number; trend: string; evidence: SkillEvidence[]; insight: string };
  lang: "ja" | "en";
  selected: boolean;
  onSelect: (key: string | null) => void;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const stroke = SKILL_STROKE[skill.key];

  return (
    <div className={cn(
      "rounded-xl border bg-card shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-all",
      selected ? "border-[var(--sk-color)] shadow-[0_0_0_1px_var(--sk-color)]" : "border-border",
    )} style={{ "--sk-color": stroke } as React.CSSProperties}>
      <button
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
        onClick={() => {
          const next = !open;
          setOpen(next);
          onSelect(next ? skill.key : null);
        }}
      >
        {/* colour swatch */}
        <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: stroke }} />
        <span className="flex-1 text-[13px] font-medium text-foreground">{t(`skill.${skill.key}`)}</span>
        <TrendBadge trend={skill.trend} />
        <Stars n={skill.stars} />
        <ArrowRight className={cn(
          "ml-1 h-3.5 w-3.5 shrink-0 text-muted-foreground/40 transition-transform",
          open && "rotate-90",
        )} />
      </button>

      {open && (
        <div className="border-t border-border px-4 pb-4 pt-3 space-y-2">
          {skill.insight && (
            <p className="font-jp text-[12px] text-muted-foreground">{skill.insight}</p>
          )}
          {(skill.evidence ?? []).length > 0 ? (
            <div className="space-y-1.5 pt-1">
              {(skill.evidence ?? []).map((ev, i) => (
                <EvidenceChip key={i} ev={ev} />
              ))}
            </div>
          ) : (
            <p className="text-[11.5px] text-muted-foreground/50">
              {lang === "ja" ? "まだ記録された根拠がありません。" : "No recorded evidence yet."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ msg, t }: { msg: CoachingThreadMessage; t: (k: string) => string }) {
  const isManager = msg.role === "manager";
  return (
    <div className={cn("rounded-lg px-3 py-2.5", isManager ? "bg-muted/50" : "border border-primary/20 bg-primary/[0.03]")}>
      <div className="mb-1 flex items-center gap-2">
        <span className={cn(
          "text-[10px] font-semibold uppercase tracking-[0.06em]",
          isManager ? "text-muted-foreground" : "text-primary/70",
        )}>
          {isManager ? t("growth.thread.manager") : t("growth.thread.you")}
        </span>
        <span className="text-[10px] text-muted-foreground/50">{msg.date}</span>
      </div>
      <p className="font-jp text-[13px] leading-relaxed text-foreground/85">{msg.text}</p>
    </div>
  );
}

function ThreadCard({ thread }: { thread: CoachingThread }) {
  const { t } = useT();
  const [expanded, setExpanded] = useState(false);
  const preview = thread.messages.slice(0, 2);
  const hasMore = thread.messages.length > 2;

  return (
    <div className={cn(
      "rounded-xl border bg-card shadow-[0_1px_2px_rgba(16,24,40,0.04)]",
      thread.status === "resolved" && "opacity-75",
    )}>
      {/* header — always visible */}
      <button
        className="flex w-full items-start justify-between gap-2 p-4 text-left"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[11px] text-muted-foreground">{thread.deal_id}</span>
          <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-[11px] font-medium text-primary">
            {t(`coaching.issue.${thread.issue_key}`)}
          </span>
          {hasMore && !expanded && (
            <span className="text-[10px] text-muted-foreground">
              {thread.messages.length} messages
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className={cn(
            "rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
            STATUS_TONE[thread.status] ?? "bg-muted text-muted-foreground border-border",
          )}>
            {t(`repcoach.status.${thread.status}`)}
          </span>
          {expanded
            ? <ChevronUp className="h-3.5 w-3.5 text-muted-foreground/50" />
            : <ChevronDown className="h-3.5 w-3.5 text-muted-foreground/50" />}
        </div>
      </button>

      {/* messages */}
      <div className="space-y-2 px-4 pb-4">
        {(expanded ? thread.messages : preview).map((msg, i) => (
          <MessageBubble key={i} msg={msg} t={t} />
        ))}
        {!expanded && hasMore && (
          <button
            onClick={() => setExpanded(true)}
            className="w-full rounded-lg border border-dashed border-border py-2 text-[11.5px] text-muted-foreground transition-colors hover:border-primary/30 hover:text-primary"
          >
            {thread.messages.length - 2} more message{thread.messages.length - 2 !== 1 ? "s" : ""} — tap to expand
          </button>
        )}
      </div>

      <div className="border-t border-border px-4 py-2 text-[10px] text-muted-foreground">
        {thread.created_at}
      </div>
    </div>
  );
}

function DealCard({ deal, onOpen }: { deal: DealRow; onOpen: (id: string) => void }) {
  const { t, lang } = useT();
  return (
    <button
      className={cn(
        "flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left transition-all",
        "hover:shadow-[0_4px_20px_-8px_rgba(16,24,40,0.18)] hover:border-primary/30",
        BAND_BG[deal.band] ?? "border-border bg-card",
      )}
      onClick={() => onOpen(deal.deal_id)}
    >
      <span className="text-base leading-none">{BAND_CHIP[deal.band] ?? "⚪"}</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="font-jp truncate text-[13px] font-medium text-foreground">
            {customerText(lang, deal.customer).text}
          </span>
          <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{deal.deal_id}</span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
          <span>¥{deal.amount.toLocaleString("ja-JP")}</span>
          <span>{deal.stage}</span>
          {deal.days_stale != null && deal.days_stale > 0 && (
            <span className="text-band-yellow">{t("growth.stale", { n: String(deal.days_stale) })}</span>
          )}
          {deal.n_flags > 0 && (
            <span className="text-band-red">{deal.n_flags} flags</span>
          )}
        </div>
      </div>
      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40" />
    </button>
  );
}

function SkillProgressionChart({
  monthly,
  lang,
  highlighted,
}: {
  monthly: { month: string; count: number; skill_scores?: Partial<Record<string, number | null>> }[];
  lang: "ja" | "en";
  highlighted: string | null;
}) {
  const { t } = useT();
  const [tab, setTab] = useState<"skills" | "activity">("skills");
  // closing_discipline has no per-month ratio so it never appears as a line
  const skillKeys = Object.keys(SKILL_STROKE).filter((k) => k !== "closing_discipline");
  const n = monthly.length;
  const W = 300;
  const H = 88;
  const PX = 16;
  const PY = 8;

  const xOf = (i: number) => PX + (i / Math.max(n - 1, 1)) * (W - 2 * PX);
  const yOf = (v: number) => PY + (1 - v) * (H - 2 * PY);
  const maxCount = Math.max(1, ...monthly.map((m) => m.count));

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      {/* tab strip */}
      <div className="flex border-b border-border">
        {(["skills", "activity"] as const).map((tb) => (
          <button
            key={tb}
            onClick={() => setTab(tb)}
            className={cn(
              "flex-1 py-2.5 text-[11px] font-medium tracking-wide transition-colors",
              tab === tb
                ? "border-b-2 border-primary text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {tb === "skills"
              ? (lang === "ja" ? "スキル推移" : "Skill trends")
              : (lang === "ja" ? "活動量" : "Activity")}
          </button>
        ))}
      </div>

      {tab === "skills" ? (
        <div className="p-4">
          {/* SVG chart area */}
          <div className="relative" style={{ height: 120 }}>
            {/* Y-axis labels — HTML, not SVG, so no fill-class issues */}
            <div className="absolute left-0 top-0 flex h-full flex-col justify-between">
              {["100%", "50%", "0%"].map((l) => (
                <span key={l} className="text-[9px] leading-none text-muted-foreground/40">{l}</span>
              ))}
            </div>
            <svg
              viewBox={`0 0 ${W} ${H}`}
              preserveAspectRatio="none"
              xmlns="http://www.w3.org/2000/svg"
              style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
            >
              {/* horizontal guides */}
              <line x1={0} y1={yOf(1)} x2={W} y2={yOf(1)} stroke="#888" strokeOpacity="0.15" strokeWidth="0.8" />
              <line x1={0} y1={yOf(0.5)} x2={W} y2={yOf(0.5)} stroke="#888" strokeOpacity="0.2" strokeWidth="0.8" strokeDasharray="3 3" />
              <line x1={0} y1={yOf(0)} x2={W} y2={yOf(0)} stroke="#888" strokeOpacity="0.15" strokeWidth="0.8" />

              {skillKeys.map((sk) => {
                const color = SKILL_STROKE[sk];
                const pts: { x: number; y: number; v: number; lbl: string }[] = [];
                monthly.forEach((m, i) => {
                  const v = m.skill_scores?.[sk];
                  if (v != null) pts.push({ x: xOf(i), y: yOf(v), v, lbl: monthLabel(m.month, lang) });
                });
                if (pts.length === 0) return null;
                const dim = highlighted !== null && highlighted !== sk;
                const bold = highlighted === sk;
                const pathD = pts.map((p, j) => `${j === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");

                return (
                  <g key={sk} opacity={dim ? 0.12 : 1} style={{ transition: "opacity 0.2s" }}>
                    {pts.length > 1 && (
                      <path
                        d={pathD}
                        fill="none"
                        stroke={color}
                        strokeWidth={bold ? 3 : 2}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    )}
                    {pts.map((p, j) => (
                      <circle key={j} cx={p.x} cy={p.y} r={bold ? 4 : 3} fill={color} stroke="white" strokeWidth="1">
                        <title>{t(`skill.${sk}`)}: {Math.round(p.v * 100)}% ({p.lbl})</title>
                      </circle>
                    ))}
                  </g>
                );
              })}
            </svg>
          </div>

          {/* X-axis labels */}
          <div className="mt-1 flex justify-between">
            {monthly.map((m) => (
              <span key={m.month} className="flex-1 text-center text-[9.5px] text-muted-foreground/60">
                {monthLabel(m.month, lang)}
              </span>
            ))}
          </div>

          {/* Legend */}
          <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1.5 border-t border-border pt-2.5">
            {skillKeys.map((sk) => (
              <span
                key={sk}
                className="flex items-center gap-1.5 text-[10.5px] transition-opacity"
                style={{ opacity: highlighted !== null && highlighted !== sk ? 0.25 : 1 }}
              >
                <span className="inline-block h-[3px] w-4 rounded-full" style={{ backgroundColor: SKILL_STROKE[sk] }} />
                <span className="text-muted-foreground">{t(`skill.${sk}`)}</span>
              </span>
            ))}
          </div>
        </div>
      ) : (
        /* ── Activity bars tab ── */
        <div className="p-4">
          <div className="relative flex h-32 items-end justify-between gap-1.5">
            {monthly.map((m) => {
              const ratio = maxCount > 0 ? m.count / maxCount : 0;
              const pct = m.count === 0 ? 0 : Math.max(6, ratio * 100);
              const opacity = m.count === 0 ? 0.15 : 0.35 + ratio * 0.65;
              const isCurrent = m.month === monthly[monthly.length - 1].month;
              const barH = pct === 0 ? "3px" : `${pct}%`;
              return (
                <div key={m.month} className="relative flex h-full flex-1 items-end">
                  {m.count > 0 && (
                    <span
                      className={cn(
                        "absolute left-1/2 -translate-x-1/2 text-[10px] tabular-nums",
                        isCurrent ? "font-bold text-primary" : "font-medium text-muted-foreground",
                      )}
                      style={{ bottom: `calc(${pct}% + 4px)` }}
                    >
                      {m.count}
                    </span>
                  )}
                  <div
                    className="w-full rounded-t-md bg-primary transition-all"
                    style={{ height: barH, opacity }}
                    title={`${monthLabel(m.month, lang)}: ${m.count}`}
                  />
                </div>
              );
            })}
          </div>
          {/* avg line */}
          {maxCount > 0 && (() => {
            const avg = monthly.reduce((s, m) => s + m.count, 0) / monthly.length;
            const avgPct = (avg / maxCount) * 100;
            return (
              <div className="relative -mt-[calc(theme(spacing.32))]" style={{ height: "128px", pointerEvents: "none" }}>
                <div
                  className="absolute w-full border-t border-dashed border-muted-foreground/25"
                  style={{ bottom: `${avgPct}%` }}
                />
              </div>
            );
          })()}
          <div className="mt-2 flex justify-between">
            {monthly.map((m, i) => (
              <span
                key={m.month}
                className={cn(
                  "flex-1 text-center text-[9.5px]",
                  i === monthly.length - 1 ? "font-semibold text-primary" : "text-muted-foreground/60",
                )}
              >
                {monthLabel(m.month, lang)}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export function GrowthDashboard({
  initial,
  threads,
  deals,
}: {
  initial: GrowthResponse;
  threads: CoachingThread[];
  deals: DealRow[];
}) {
  const { t, lang } = useT();
  const g = initial.growth;
  const [drawerDealId, setDrawerDealId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null);

  function openDeal(id: string) {
    setDrawerDealId(id);
    setDrawerOpen(true);
  }

  const sortedThreads = [...threads].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 3) - (STATUS_ORDER[b.status] ?? 3),
  );

  return (
    <div className="space-y-6">
      {/* identity card */}
      <div className="flex items-center gap-3 rounded-xl border border-border bg-card p-4">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-navy text-white">
          <GraduationCap className="h-5 w-5" />
        </span>
        <div>
          <div className="font-jp text-[15px] font-semibold text-foreground">
            {repText(lang, g.rep.name).text}
          </div>
          <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
            <span className="font-jp">{departmentText(lang, g.rep.department).text}</span>
            {g.rep.specialty_tags.map((tg) => (
              <Badge key={tg} variant="default">#{tagText(lang, tg).text}</Badge>
            ))}
          </div>
        </div>
      </div>

      {/* headline stats */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard icon={MessagesSquare} value={g.totals.reviews} label={t("growth.stat.reviews")} tone="bg-primary/10 text-primary" />
        <StatCard icon={BookMarked} value={g.totals.principles} label={t("growth.stat.principles")} tone="bg-navy/10 text-navy" />
        <StatCard icon={Layers} value={g.totals.scenarios} label={t("growth.stat.scenarios")} tone="bg-conf-high/15 text-conf-high" />
        <StatCard icon={Flame} value={g.totals.streak_weeks} label={t("growth.stat.streak")} sub={t("growth.weeks", { n: String(g.totals.streak_weeks) })} tone="bg-band-yellow/15 text-band-yellow" />
      </div>

      {/* coaching journey */}
      <div className="rounded-2xl border border-primary/25 bg-gradient-to-br from-primary/[0.06] to-primary/[0.01] p-5">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-primary">
          <Sparkles className="h-3.5 w-3.5" /> {t("growth.journeyTitle")}
        </div>
        <div className="mt-1 text-[12px] text-muted-foreground">
          {t("growth.journeyLead")} · {monthLabel(g.this_month.label, lang)}
        </div>
        <div className="mt-4 flex flex-wrap gap-x-8 gap-y-3">
          <JourneyStat n={g.this_month.reviews} label={t("growth.journey.reviews")} />
          <JourneyStat n={g.this_month.new_principles} label={t("growth.journey.principles")} />
          <JourneyStat n={g.this_month.strengths} label={t("growth.journey.strengths")} />
        </div>
        <p className="mt-4 text-[13px] leading-relaxed text-foreground/80">{t("growth.encourage")}</p>
      </div>

      {/* manager coaching feedback */}
      <section>
        <div className="eyebrow mb-1 flex items-center gap-1.5">
          <MessageCircle className="h-3.5 w-3.5" />
          {t("repcoach.threads")}
        </div>
        <p className="mb-3 text-[11.5px] text-muted-foreground">{t("growth.coaching.sub")}</p>
        {sortedThreads.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border p-6 text-center text-[13px] text-muted-foreground">
            {t("repcoach.noThreads")}
          </div>
        ) : (
          <div className="space-y-3">
            {sortedThreads.map((thread) => (
              <ThreadCard key={thread.thread_id} thread={thread} />
            ))}
          </div>
        )}
      </section>

      {/* my deals */}
      <section>
        <div className="eyebrow mb-1 flex items-center gap-1.5">
          <Building2 className="h-3.5 w-3.5" />
          {t("growth.myDeals")}
        </div>
        <p className="mb-3 text-[11.5px] text-muted-foreground">{t("growth.myDeals.sub")}</p>
        {deals.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border p-6 text-center text-[13px] text-muted-foreground">
            {t("growth.myDeals.noDeals")}
          </div>
        ) : (
          <div className="space-y-2">
            {deals.map((deal) => (
              <DealCard key={deal.deal_id} deal={deal} onOpen={openDeal} />
            ))}
          </div>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* skill progression — expandable cards with real evidence */}
        <section>
          <div className="eyebrow mb-1">{t("growth.skillsTitle")}</div>
          <p className="mb-3 text-[11.5px] text-muted-foreground">{t("growth.skillsSub")}</p>
          <div className="space-y-2">
            {g.skills.map((s) => (
              <SkillCard
                key={s.key}
                skill={s}
                lang={lang}
                selected={selectedSkill === s.key}
                onSelect={setSelectedSkill}
              />
            ))}
          </div>
        </section>

        {/* monthly activity + skill overlay */}
        <section>
          <div className="eyebrow mb-1">{t("growth.monthlyTitle")}</div>
          <p className="mb-3 text-[11.5px] text-muted-foreground">{t("growth.monthlySkills")}</p>
          <SkillProgressionChart monthly={g.monthly} lang={lang} highlighted={selectedSkill} />
        </section>
      </div>

      <DealDrawer
        dealId={drawerDealId}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />
    </div>
  );
}
