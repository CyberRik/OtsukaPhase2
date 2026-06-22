"use client";

import { useState } from "react";
import {
  AlertTriangle,
  Award,
  BarChart3,
  BookMarked,
  ChevronDown,
  Database,
  FileSearch,
  Lightbulb,
  Target,
  XCircle,
} from "lucide-react";
import type { Explanation } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { ConfidenceBadge } from "@/components/confidence-badge";

// ---------------------------------------------------------------------------
// Outcome bar — a horizontal stacked bar showing win/loss ratio
// ---------------------------------------------------------------------------
function OutcomeBar({ won, lost }: { won: number; lost: number }) {
  const total = won + lost;
  if (!total) return null;
  const wonPct = Math.round((won / total) * 100);
  const lostPct = 100 - wonPct;
  return (
    <div className="flex h-4 w-full overflow-hidden rounded-full bg-muted">
      {won > 0 && (
        <div
          className="flex items-center justify-center bg-conf-high/70 text-[9px] font-bold text-white transition-all"
          style={{ width: `${wonPct}%` }}
        >
          {wonPct}%
        </div>
      )}
      {lost > 0 && (
        <div
          className="flex items-center justify-center bg-band-red/70 text-[9px] font-bold text-white transition-all"
          style={{ width: `${lostPct}%` }}
        >
          {lostPct}%
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single explanation card — progressive disclosure
// ---------------------------------------------------------------------------
export function ExplainabilityCard({ explanation }: { explanation: Explanation }) {
  const { t, lang } = useT();
  const [open, setOpen] = useState(false);

  const hasTriggers = explanation.triggers.length > 0;
  const hasEvidence = explanation.evidence.length > 0;
  const hasCases = explanation.similar_cases.length > 0;
  const hasStats = explanation.outcome_stats != null;

  if (!hasTriggers && !hasEvidence && !hasCases && !hasStats) return null;

  return (
    <div className="overflow-hidden rounded-xl border border-primary/15 bg-primary/[0.02]">
      {/* Toggle header */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-3.5 py-2 text-left transition-colors hover:bg-primary/[0.04]"
      >
        <span className="flex items-center gap-2 text-[12.5px] font-medium text-primary">
          <Lightbulb className="h-3.5 w-3.5" />
          {t("expl.why")}
        </span>
        <span className="flex items-center gap-2">
          <ConfidenceBadge level={explanation.confidence} />
          <ChevronDown
            className={cn(
              "h-3.5 w-3.5 text-muted-foreground transition-transform",
              open && "rotate-180",
            )}
          />
        </span>
      </button>

      {/* Expanded body */}
      {open && (
        <div className="animate-fade-up space-y-3.5 border-t border-primary/10 px-3.5 py-3">
          {/* Trigger conditions */}
          {hasTriggers && (
            <Section icon={Target} title={t("expl.triggers")}>
              {explanation.triggers.map((tr, i) => (
                <div key={i} className="flex gap-2 text-[12.5px] leading-relaxed text-foreground/85">
                  <span className="mt-[6px] h-1.5 w-1.5 shrink-0 rounded-full bg-primary/60" />
                  <span>{lang === "ja" ? tr.description : tr.description_en}</span>
                </div>
              ))}
            </Section>
          )}

          {/* Supporting evidence */}
          {hasEvidence && (
            <Section icon={Database} title={t("expl.evidence")}>
              {explanation.evidence.map((ev, i) => (
                <div key={i} className="flex gap-2 text-[12.5px] leading-relaxed text-foreground/85">
                  <span className="mt-[6px] h-1.5 w-1.5 shrink-0 rounded-full bg-navy/60" />
                  <span>
                    <span className="font-mono text-[11px] text-muted-foreground">{ev.field}:</span>{" "}
                    <span className="text-foreground/70">{ev.value}</span>
                    <span className="block text-foreground/85">
                      {lang === "ja" ? ev.interpretation : ev.interpretation_en}
                    </span>
                  </span>
                </div>
              ))}
            </Section>
          )}

          {/* Similar historical cases */}
          {hasCases && (
            <Section icon={FileSearch} title={t("expl.cases")}>
              <div className="space-y-1.5">
                {explanation.similar_cases.map((c, i) => {
                  const won = c.outcome === "won";
                  return (
                    <div
                      key={i}
                      className={cn(
                        "rounded-lg border px-3 py-2",
                        won
                          ? "border-conf-high/20 bg-conf-high/[0.03]"
                          : "border-band-red/20 bg-band-red/[0.03]",
                      )}
                    >
                      <div className="flex items-center gap-2">
                        <span
                          className={cn(
                            "inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold",
                            won
                              ? "bg-conf-high/15 text-conf-high"
                              : "bg-band-red/15 text-band-red",
                          )}
                        >
                          {won ? <Award className="h-2.5 w-2.5" /> : <XCircle className="h-2.5 w-2.5" />}
                          {won ? t("chat.caseWon") : t("chat.caseLost")}
                        </span>
                        <span className="font-jp text-[12px] font-medium text-foreground">
                          {c.customer}
                        </span>
                        <span className="font-mono text-[10px] text-muted-foreground">{c.deal_id}</span>
                      </div>
                      <p className="mt-1 text-[11.5px] text-foreground/70">
                        {lang === "ja" ? c.relevance : c.relevance_en}
                      </p>
                      {c.lesson && (
                        <p className="mt-1 border-t border-border pt-1 text-[11px] text-foreground/60">
                          {c.lesson}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </Section>
          )}

          {/* Outcome statistics */}
          <Section icon={BarChart3} title={t("expl.outcomes")}>
            {hasStats && explanation.outcome_stats ? (
              <div className="space-y-2">
                <OutcomeBar won={explanation.outcome_stats.won} lost={explanation.outcome_stats.lost} />
                <div className="flex flex-wrap gap-2 text-[11.5px]">
                  <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">
                    {t("expl.totalDeals", { n: explanation.outcome_stats.total_similar })}
                  </span>
                  <span className="rounded-full bg-conf-high/10 px-2 py-0.5 text-conf-high">
                    {t("expl.wonCount", { n: explanation.outcome_stats.won })}
                  </span>
                  <span className="rounded-full bg-band-red/10 px-2 py-0.5 text-band-red">
                    {t("expl.lostCount", { n: explanation.outcome_stats.lost })}
                  </span>
                </div>
                <p className="text-[11px] text-muted-foreground">
                  <span className="font-medium">{t("expl.conditions")}:</span>{" "}
                  {lang === "ja"
                    ? explanation.outcome_stats.conditions_desc
                    : explanation.outcome_stats.conditions_desc_en}
                </p>
              </div>
            ) : (
              <p className="text-[12px] text-muted-foreground italic">{t("expl.insufficient")}</p>
            )}
          </Section>

          {/* Principle citation */}
          {explanation.principle_id && explanation.principle_statement && (
            <div className="flex gap-2 rounded-lg border border-primary/15 bg-primary/[0.03] px-3 py-2">
              <BookMarked className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
              <div>
                <span className="text-[10px] font-medium uppercase tracking-wide text-primary">
                  {t("expl.principle")} — {explanation.principle_id}
                </span>
                <p className="mt-0.5 font-jp text-[12px] leading-snug text-foreground/85">
                  {explanation.principle_statement}
                </p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ExplainabilityPanel — renders all explanations for a coach review
// ---------------------------------------------------------------------------
export function ExplainabilityPanel({ explanations }: { explanations: Explanation[] }) {
  if (!explanations || explanations.length === 0) return null;

  return (
    <div className="space-y-2">
      {explanations.map((exp, i) => (
        <ExplainabilityCard key={exp.recommendation_id || i} explanation={exp} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline "Why?" chip for coaching cards (manager workspace)
// ---------------------------------------------------------------------------
export function ExplainabilityChip({ explanation }: { explanation: Explanation }) {
  const { t, lang } = useT();
  const [open, setOpen] = useState(false);

  const hasStats = explanation.outcome_stats != null;

  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 rounded-full border border-primary/20 bg-primary/[0.04] px-2 py-0.5 text-[11px] font-medium text-primary transition-colors hover:bg-primary/[0.08]"
      >
        <Lightbulb className="h-3 w-3" />
        {t("expl.why")}
        <ChevronDown
          className={cn(
            "h-2.5 w-2.5 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div className="animate-fade-up mt-2 space-y-2.5 rounded-lg border border-primary/10 bg-primary/[0.02] p-3">
          {/* Triggers */}
          {explanation.triggers.length > 0 && (
            <div>
              <div className="mb-1 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-primary">
                <Target className="h-3 w-3" /> {t("expl.triggers")}
              </div>
              {explanation.triggers.map((tr, i) => (
                <p key={i} className="text-[11.5px] leading-relaxed text-foreground/80">
                  {lang === "ja" ? tr.description : tr.description_en}
                </p>
              ))}
            </div>
          )}

          {/* Evidence */}
          {explanation.evidence.length > 0 && (
            <div>
              <div className="mb-1 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-primary">
                <Database className="h-3 w-3" /> {t("expl.evidence")}
              </div>
              {explanation.evidence.map((ev, i) => (
                <p key={i} className="text-[11.5px] text-foreground/75">
                  <span className="font-mono text-[10px] text-muted-foreground">{ev.field}:</span>{" "}
                  {ev.value}
                </p>
              ))}
            </div>
          )}

          {/* Outcome stats compact */}
          {hasStats && explanation.outcome_stats && (
            <div>
              <div className="mb-1 flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-primary">
                <BarChart3 className="h-3 w-3" /> {t("expl.outcomes")}
              </div>
              <OutcomeBar won={explanation.outcome_stats.won} lost={explanation.outcome_stats.lost} />
              <p className="mt-1 text-[10.5px] text-muted-foreground">
                {t("expl.totalDeals", { n: explanation.outcome_stats.total_similar })}
                {" · "}
                {t("expl.lossRate", { rate: Math.round(explanation.outcome_stats.loss_rate * 100) })}
              </p>
            </div>
          )}

          {/* Confidence + principle */}
          <div className="flex flex-wrap items-center gap-2">
            <ConfidenceBadge level={explanation.confidence} />
            {explanation.principle_id && (
              <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                {explanation.principle_id}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section helper
// ---------------------------------------------------------------------------
function Section({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.06em] text-primary">
        <Icon className="h-3 w-3" /> {title}
      </div>
      <div className="space-y-1.5 pl-[18px]">{children}</div>
    </div>
  );
}
