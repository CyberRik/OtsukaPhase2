"use client";

import { useMemo, useState } from "react";
import { BookOpen, Check, CheckCircle2, FileText, Loader2, Pencil, Search, Sparkles, Users, X } from "lucide-react";
import type { ItemStatus, KnowledgeItem, Principle, Source } from "@/lib/types";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { PRINCIPLE_EN, TAG_EN, ITEM_EN, sourceNoteText, principleText, tagText, pickText, pickList } from "@/lib/content-i18n";
import { Badge } from "@/components/ui/badge";
import { ConfidenceBadge } from "@/components/confidence-badge";
import { JpOriginalBadge } from "@/components/jp-original-badge";
import { SourceChip, SourceChips } from "@/components/source-chip";
import { ProvenanceList } from "@/components/provenance";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LiveBadge } from "@/components/site/live-badge";
import { AddPrincipleDialog } from "./add-principle-dialog";

function SourceStrip({ sources }: { sources: Source[] }) {
  const { lang } = useT();
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {sources.map((s) => {
        const Icon = s.kind === "interview" ? Users : FileText;
        const sn = sourceNoteText(lang, s.source_id, s.notes);
        return (
          <div key={s.source_id} className="rounded-xl border border-border bg-card p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
            <div className="flex items-center justify-between">
              <SourceChip id={s.source_id} />
              <Icon className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="mt-2 flex items-center gap-1.5 text-[12px] font-medium capitalize text-foreground">
              {s.kind} · {s.participant_role}
            </div>
            <span className="mt-1 line-clamp-2 text-[11px] leading-snug text-muted-foreground block">
              {sn.text}
              {sn.fallback && <JpOriginalBadge />}
            </span>
          </div>
        );
      })}
    </div>
  );
}

const STATUS_TONE: Record<ItemStatus, string> = {
  approved: "border-conf-high/30 bg-conf-high/10 text-conf-high",
  draft: "border-border bg-muted text-muted-foreground",
  needs_edit: "border-band-yellow/30 bg-band-yellow/10 text-band-yellow",
  rejected: "border-band-red/30 bg-band-red/10 text-band-red",
};

function ItemCard({
  item,
  canManage = false,
  onReview,
}: {
  item: KnowledgeItem;
  canManage?: boolean;
  onReview?: (itemId: string, action: "approve" | "request_edit" | "reject") => Promise<boolean>;
}) {
  const { t, lang } = useT();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState(false);
  const status = item.review.status;
  const pending = status === "draft" || status === "needs_edit";

  async function act(action: "approve" | "request_edit" | "reject") {
    if (!onReview) return;
    setBusy(action);
    setErr(false);
    const ok = await onReview(item.item_id, action);
    if (!ok) setErr(true);
    setBusy(null);
  }

  const enItem = ITEM_EN[item.item_id];
  const sc = pickText(lang, item.scenario, enItem?.scenario);
  const facets = [
    { label: t("knowledge.signals"), jaVals: item.signals, enVals: enItem?.signals, tone: "text-primary" },
    { label: t("knowledge.questions"), jaVals: item.questions, enVals: enItem?.questions, tone: "text-navy" },
    { label: t("knowledge.risks"), jaVals: item.risks, enVals: enItem?.risks, tone: "text-band-red" },
    { label: t("knowledge.alternatives"), jaVals: item.alternatives, enVals: enItem?.alternatives, tone: "text-conf-high" },
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
        <span
          className={cn(
            "ml-auto rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
            STATUS_TONE[status],
          )}
        >
          {t(`knowledge.status.${status}`)}
        </span>
      </div>
      <span className="mt-3 text-[14px] leading-relaxed text-foreground/90 block">
        {sc.text}
        {sc.fallback && <JpOriginalBadge />}
      </span>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {facets.map((f) => {
          const { vals, fallback } = pickList(lang, f.jaVals, f.enVals);
          return (
            <div key={f.label}>
              <div className={cn("text-[10px] font-semibold uppercase tracking-[0.06em]", f.tone)}>{f.label}</div>
              <ul className="mt-1.5 space-y-1">
                {vals.map((v, i) => (
                  <li key={i} className="text-[12.5px] leading-snug text-muted-foreground flex items-start gap-1">
                    <span className="shrink-0">·</span>
                    <span>{v}</span>
                  </li>
                ))}
              </ul>
              {fallback && <JpOriginalBadge />}
            </div>
          );
        })}
      </div>

      {canManage && pending && onReview && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
          <button
            onClick={() => act("approve")}
            disabled={busy !== null}
            className="inline-flex items-center gap-1 rounded-lg border border-conf-high/30 bg-conf-high/10 px-2.5 py-1 text-[12px] font-medium text-conf-high transition-colors hover:bg-conf-high/20 disabled:opacity-50"
          >
            {busy === "approve" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
            {t("knowledge.review.approve")}
          </button>
          <button
            onClick={() => act("request_edit")}
            disabled={busy !== null}
            className="inline-flex items-center gap-1 rounded-lg border border-band-yellow/30 bg-band-yellow/10 px-2.5 py-1 text-[12px] font-medium text-band-yellow transition-colors hover:bg-band-yellow/20 disabled:opacity-50"
          >
            {busy === "request_edit" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Pencil className="h-3.5 w-3.5" />}
            {t("knowledge.review.requestEdit")}
          </button>
          <button
            onClick={() => act("reject")}
            disabled={busy !== null}
            className="inline-flex items-center gap-1 rounded-lg border border-band-red/30 bg-band-red/10 px-2.5 py-1 text-[12px] font-medium text-band-red transition-colors hover:bg-band-red/20 disabled:opacity-50"
          >
            {busy === "reject" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <X className="h-3.5 w-3.5" />}
            {t("knowledge.review.reject")}
          </button>
          {err && <span className="text-[11px] text-band-red">{t("knowledge.offlineMutation")}</span>}
        </div>
      )}
    </div>
  );
}

export function KnowledgeExplorer({
  principles, items, sources, live, canManage = false,
}: {
  principles: Principle[]; items: KnowledgeItem[]; sources: Source[]; live: boolean;
  canManage?: boolean;
}) {
  const { t, lang } = useT();
  const [filter, setFilter] = useState<"all" | "approved" | "two">("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string>(
    principles.find((p) => p.n_interviews >= 2)?.principle_id ?? principles[0]?.principle_id ?? "",
  );
  // Items and principles are mutable here (generate appends a draft, review
  // updates status, and a manager can author a new candidate principle), so
  // they live in state rather than being read straight from props.
  const [allItems, setAllItems] = useState<KnowledgeItem[]>(items);
  const [allPrinciples, setAllPrinciples] = useState<Principle[]>(principles);
  const [generating, setGenerating] = useState(false);
  const [genErr, setGenErr] = useState(false);

  function handleAddPrinciple(p: Principle) {
    setAllPrinciples((prev) => [p, ...prev]);
    setSelectedId(p.principle_id);
  }

  async function handleGenerate(principleId: string) {
    setGenerating(true);
    setGenErr(false);
    const { data, live: isLive } = await api.knowledgeGenerate(principleId);
    if (isLive && data.item) {
      setAllItems((prev) => [data.item as KnowledgeItem, ...prev]);
    } else {
      setGenErr(true);
    }
    setGenerating(false);
  }

  async function handleReview(
    itemId: string,
    action: "approve" | "request_edit" | "reject",
  ): Promise<boolean> {
    const { data, live: isLive } = await api.knowledgeReview(itemId, action);
    if (isLive && data.item) {
      const updated = data.item as KnowledgeItem;
      setAllItems((prev) => prev.map((it) => (it.item_id === itemId ? updated : it)));
      return true;
    }
    return false;
  }

  const filtered = useMemo(() => allPrinciples.filter((p) => {
    if (filter === "approved" && p.status !== "approved") return false;
    if (filter === "two" && p.n_interviews < 2) return false;
    if (query) {
      const enTags = p.tags.map((tg) => TAG_EN[tg] ?? "").join(" ");
      const hay = (p.statement + " " + (PRINCIPLE_EN[p.principle_id] ?? "") + " " + p.tags.join(" ") + " " + enTags).toLowerCase();
      if (!hay.includes(query.toLowerCase())) return false;
    }
    return true;
  }), [allPrinciples, filter, query]);

  const selected = allPrinciples.find((p) => p.principle_id === selectedId) ?? filtered[0];
  const derived = allItems.filter((it) => it.provenance.principle_id === selected?.principle_id);

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="eyebrow flex items-center gap-2"><BookOpen className="h-3.5 w-3.5" /> {t("knowledge.sourceCorpus")}</div>
          <div className="flex items-center gap-2">
            {canManage && <AddPrincipleDialog onAdded={handleAddPrinciple} />}
            <LiveBadge live={live} />
          </div>
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
              const st = principleText(lang, p);
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
                  <span className="mt-2 line-clamp-2 text-[13px] leading-snug text-foreground/90 block">
                    {st.text}
                    {st.fallback && <JpOriginalBadge />}
                  </span>
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
                  {(() => { const st = principleText(lang, selected); return (
                    <span className="text-xl font-semibold leading-snug tracking-tight block">
                      {st.text}
                      {st.fallback && <JpOriginalBadge />}
                    </span>
                  ); })()}
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {selected.tags.map((tg) => {
                    const tt = tagText(lang, tg);
                    return (
                      <Badge key={tg} variant="default">
                        #{tt.text}
                      </Badge>
                    );
                  })}
                </div>
                <div className="mt-6 border-t border-border pt-5">
                  <ProvenanceList citations={selected.support} />
                </div>
              </div>

              <div className="space-y-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="eyebrow">{t("knowledge.derived")}</div>
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-muted-foreground">{t("knowledge.approvedCount", { n: derived.length })}</span>
                    {canManage && (
                      <button
                        onClick={() => handleGenerate(selected.principle_id)}
                        disabled={generating || selected.status !== "approved"}
                        title={selected.status !== "approved" ? t("knowledge.generateApprovedOnly") : undefined}
                        className="inline-flex items-center gap-1 rounded-lg border border-navy/30 bg-navy/10 px-2.5 py-1 text-[12px] font-medium text-navy transition-colors hover:bg-navy/20 disabled:opacity-40"
                      >
                        {generating ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                        {generating ? t("knowledge.generating") : t("knowledge.generate")}
                      </button>
                    )}
                  </div>
                </div>
                {canManage && genErr && (
                  <p className="text-[11px] text-band-red">{t("knowledge.offlineMutation")}</p>
                )}
                {derived.length ? (
                  derived.map((it) => (
                    <ItemCard key={it.item_id} item={it} canManage={canManage} onReview={handleReview} />
                  ))
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
