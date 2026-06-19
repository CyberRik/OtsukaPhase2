"use client";

import { useMemo, useState } from "react";
import { BookOpen, CheckCircle2, FileText, Search, Users } from "lucide-react";
import type { KnowledgeItem, Principle, Source } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { PRINCIPLE_EN, TAG_EN } from "@/lib/content-i18n";
import { Badge } from "@/components/ui/badge";
import { ConfidenceBadge } from "@/components/confidence-badge";
import { JpOriginalBadge } from "@/components/jp-original-badge";
import { SourceChip, SourceChips } from "@/components/source-chip";
import { ProvenanceList } from "@/components/provenance";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LiveBadge } from "@/components/site/live-badge";
import { TranslatedText } from "@/components/site/translated-text";

function SourceStrip({ sources }: { sources: Source[] }) {
  const { lang } = useT();
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {sources.map((s) => {
        const Icon = s.kind === "interview" ? Users : FileText;
        return (
          <div key={s.source_id} className="rounded-xl border border-border bg-card p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
            <div className="flex items-center justify-between">
              <SourceChip id={s.source_id} />
              <Icon className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="mt-2 flex items-center gap-1.5 text-[12px] font-medium capitalize text-foreground">
              {s.kind} · {s.participant_role}
            </div>
            <TranslatedText className="mt-1 line-clamp-2 text-[11px] leading-snug text-muted-foreground block" text={s.notes} />
          </div>
        );
      })}
    </div>
  );
}

function ItemCard({ item }: { item: KnowledgeItem }) {
  const { t, lang } = useT();
  const scenario = item.scenario;
  const facets = [
    { label: t("knowledge.signals"), vals: item.signals, tone: "text-primary" },
    { label: t("knowledge.questions"), vals: item.questions, tone: "text-navy" },
    { label: t("knowledge.risks"), vals: item.risks, tone: "text-band-red" },
    { label: t("knowledge.alternatives"), vals: item.alternatives, tone: "text-conf-high" },
  ];
  return (
    <div className="rounded-xl border border-border bg-card p-5 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11px] text-muted-foreground">{item.item_id}</span>
        <ConfidenceBadge level={item.confidence} />
        {item.provenance.grounding_passed && (
          <span className="inline-flex items-center gap-1 text-[11px] text-conf-high">
            <CheckCircle2 className="h-3.5 w-3.5" /> {t("knowledge.groundingPassed")}
          </span>
        )}
      </div>
      <TranslatedText className="mt-3 text-[14px] leading-relaxed text-foreground/90 block" text={scenario} />
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {facets.map((f) => (
          <div key={f.label}>
            <div className={cn("text-[10px] font-semibold uppercase tracking-[0.06em]", f.tone)}>{f.label}</div>
            <ul className="mt-1.5 space-y-1">
              {f.vals.map((v, i) => (
                <li key={i} className="text-[12.5px] leading-snug text-muted-foreground flex items-start gap-1">
                  <span className="shrink-0">·</span>
                  <TranslatedText text={v} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

export function KnowledgeExplorer({
  principles, items, sources, live,
}: {
  principles: Principle[]; items: KnowledgeItem[]; sources: Source[]; live: boolean;
}) {
  const { t, lang } = useT();
  const [filter, setFilter] = useState<"all" | "approved" | "two">("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string>(
    principles.find((p) => p.n_interviews >= 2)?.principle_id ?? principles[0]?.principle_id ?? "",
  );

  const filtered = useMemo(() => principles.filter((p) => {
    if (filter === "approved" && p.status !== "approved") return false;
    if (filter === "two" && p.n_interviews < 2) return false;
    if (query) {
      const enTags = p.tags.map((tg) => TAG_EN[tg] ?? "").join(" ");
      const hay = (p.statement + " " + (PRINCIPLE_EN[p.principle_id] ?? "") + " " + p.tags.join(" ") + " " + enTags).toLowerCase();
      if (!hay.includes(query.toLowerCase())) return false;
    }
    return true;
  }), [principles, filter, query]);

  const selected = principles.find((p) => p.principle_id === selectedId) ?? filtered[0];
  const derived = items.filter((it) => it.provenance.principle_id === selected?.principle_id);

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="eyebrow flex items-center gap-2"><BookOpen className="h-3.5 w-3.5" /> {t("knowledge.sourceCorpus")}</div>
          <LiveBadge live={live} />
        </div>
        <SourceStrip sources={sources} />
      </section>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,372px)_minmax(0,1fr)]">
        {/* List */}
        <div className="space-y-3 lg:sticky lg:top-24 lg:self-start">
          <Tabs value={filter} onValueChange={(v) => setFilter(v as typeof filter)}>
            <TabsList className="w-full">
              <TabsTrigger value="all" className="flex-1">{t("common.all")}</TabsTrigger>
              <TabsTrigger value="approved" className="flex-1">{t("common.approved")}</TabsTrigger>
              <TabsTrigger value="two" className="flex-1">{t("common.twoSource")}</TabsTrigger>
            </TabsList>
          </Tabs>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("common.search")}
              className="h-10 w-full rounded-lg border border-input bg-card pl-9 pr-3 text-[13px] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
          <div className="max-h-[620px] space-y-2 overflow-y-auto pr-1">
            {filtered.map((p) => {
              const active = p.principle_id === selected?.principle_id;
              return (
                <button
                  key={p.principle_id}
                  onClick={() => setSelectedId(p.principle_id)}
                  className={cn(
                    "w-full rounded-xl border p-3.5 text-left transition-colors",
                    active ? "border-primary/40 bg-primary/[0.04]" : "border-border bg-card hover:bg-muted",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] text-muted-foreground">{p.principle_id}</span>
                    <div className="flex items-center gap-1.5">
                      {p.n_interviews >= 2 && <Badge variant="accent" className="gap-1"><Users className="h-3 w-3" /> 2</Badge>}
                      <Badge variant={p.status === "approved" ? "ink" : "outline"}>
                        {p.status === "approved" ? t("knowledge.statusApproved") : t("knowledge.statusCandidate")}
                      </Badge>
                    </div>
                  </div>
                  <TranslatedText className="mt-2 line-clamp-2 text-[13px] leading-snug text-foreground/90 block" text={p.statement} />
                  <div className="mt-2 flex items-center gap-2">
                    <SourceChips ids={p.interview_ids} />
                  </div>
                </button>
              );
            })}
            {filtered.length === 0 && (
              <div className="rounded-xl border border-dashed border-border p-8 text-center text-[13px] text-muted-foreground">
                {t("knowledge.noMatch")}
              </div>
            )}
          </div>
        </div>

        {/* Detail */}
        <div className="space-y-6">
          {selected ? (
            <>
              <div className="rounded-xl border border-border bg-card p-6 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[12px] text-muted-foreground">{selected.principle_id}</span>
                  {selected.n_interviews >= 2 ? (
                    <Badge variant="accent" className="gap-1"><Users className="h-3 w-3" /> {t("common.twoSource")}</Badge>
                  ) : (
                    <Badge variant="outline">{t("knowledge.singleSource")}</Badge>
                  )}
                  <Badge variant={selected.status === "approved" ? "ink" : "outline"}>
                    {selected.status === "approved" ? t("knowledge.statusApproved") : t("knowledge.statusCandidate")}
                  </Badge>
                </div>
                <div className="mt-3 flex items-start gap-2">
                  <TranslatedText className="text-xl font-semibold leading-snug tracking-tight block" text={selected.statement} />
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {selected.tags.map((tg) => (
                    <Badge key={tg} variant="default">
                      #<TranslatedText text={tg} />
                    </Badge>
                  ))}
                </div>
                <div className="mt-6 border-t border-border pt-5">
                  <ProvenanceList citations={selected.support} />
                </div>
              </div>

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="eyebrow">{t("knowledge.derived")}</div>
                  <span className="text-[11px] text-muted-foreground">{t("knowledge.approvedCount", { n: derived.length })}</span>
                </div>
                {derived.length ? (
                  derived.map((it) => <ItemCard key={it.item_id} item={it} />)
                ) : (
                  <div className="rounded-xl border border-dashed border-border bg-muted/30 p-8 text-center">
                    <p className="font-jp text-[13px] text-muted-foreground">{t("knowledge.noItems")}</p>
                    <p className="mt-1 font-jp text-[11px] text-muted-foreground">{t("knowledge.noItemsSub")}</p>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="rounded-xl border border-dashed border-border p-12 text-center text-muted-foreground">
              {t("knowledge.select")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
