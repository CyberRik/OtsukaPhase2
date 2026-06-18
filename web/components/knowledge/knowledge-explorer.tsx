"use client";

import { useMemo, useState } from "react";
import { BookOpen, CheckCircle2, FileText, Search, Users } from "lucide-react";
import type { KnowledgeItem, Principle, Source } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { ConfidenceBadge } from "@/components/confidence-badge";
import { SourceChip, SourceChips } from "@/components/source-chip";
import { ProvenanceList } from "@/components/provenance";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LiveBadge } from "@/components/site/live-badge";

function SourceStrip({ sources }: { sources: Source[] }) {
  const icon = (kind: string) => (kind === "interview" ? Users : FileText);
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {sources.map((s) => {
        const Icon = icon(s.kind);
        return (
          <div key={s.source_id} className="rounded-lg border border-border bg-card p-4 shadow-card">
            <div className="flex items-center justify-between">
              <SourceChip id={s.source_id} />
              <Icon className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="mt-2 text-[12px] font-medium capitalize text-foreground">
              {s.kind} · {s.participant_role}
            </div>
            <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-muted-foreground">{s.notes}</p>
          </div>
        );
      })}
    </div>
  );
}

function ItemCard({ item }: { item: KnowledgeItem }) {
  const facets: { label: string; vals: string[]; tone: string }[] = [
    { label: "気づき · Signals", vals: item.signals, tone: "text-primary" },
    { label: "質問 · Questions", vals: item.questions, tone: "text-vermilion" },
    { label: "リスク · Risks", vals: item.risks, tone: "text-band-red" },
    { label: "別の見方 · Alternatives", vals: item.alternatives, tone: "text-conf-high" },
  ];
  return (
    <div className="rounded-lg border border-border bg-card p-5 shadow-card">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11px] text-muted-foreground">{item.item_id}</span>
        <ConfidenceBadge level={item.confidence} />
        {item.provenance.grounding_passed && (
          <span className="inline-flex items-center gap-1 text-[11px] text-conf-high">
            <CheckCircle2 className="h-3.5 w-3.5" /> 根拠チェック通過
          </span>
        )}
      </div>
      <p className="mt-3 font-jp text-[14px] leading-relaxed text-foreground/90">{item.scenario}</p>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {facets.map((f) => (
          <div key={f.label}>
            <div className={cn("text-[10px] uppercase tracking-eyebrow", f.tone)}>{f.label}</div>
            <ul className="mt-1.5 space-y-1">
              {f.vals.map((v, i) => (
                <li key={i} className="font-jp text-[12.5px] leading-snug text-muted-foreground">
                  · {v}
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
  principles,
  items,
  sources,
  live,
}: {
  principles: Principle[];
  items: KnowledgeItem[];
  sources: Source[];
  live: boolean;
}) {
  const [filter, setFilter] = useState<"all" | "approved" | "two">("all");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string>(
    principles.find((p) => p.n_interviews >= 2)?.principle_id ?? principles[0]?.principle_id ?? "",
  );

  const filtered = useMemo(() => {
    return principles.filter((p) => {
      if (filter === "approved" && p.status !== "approved") return false;
      if (filter === "two" && p.n_interviews < 2) return false;
      if (query) {
        const hay = (p.statement + " " + p.tags.join(" ")).toLowerCase();
        if (!hay.includes(query.toLowerCase())) return false;
      }
      return true;
    });
  }, [principles, filter, query]);

  const selected = principles.find((p) => p.principle_id === selectedId) ?? filtered[0];
  const derived = items.filter((it) => it.provenance.principle_id === selected?.principle_id);

  return (
    <div className="space-y-8">
      {/* Source corpus */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="eyebrow flex items-center gap-2">
            <BookOpen className="h-3.5 w-3.5" /> Source corpus · 一次情報
          </div>
          <LiveBadge live={live} />
        </div>
        <SourceStrip sources={sources} />
      </section>

      {/* Master-detail */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
        {/* Principle list */}
        <div className="space-y-3 lg:sticky lg:top-6 lg:self-start">
          <Tabs value={filter} onValueChange={(v) => setFilter(v as typeof filter)}>
            <TabsList className="w-full">
              <TabsTrigger value="all" className="flex-1">すべて</TabsTrigger>
              <TabsTrigger value="approved" className="flex-1">承認済み</TabsTrigger>
              <TabsTrigger value="two" className="flex-1">2名一致</TabsTrigger>
            </TabsList>
          </Tabs>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="原則・タグを検索…"
              className="h-10 w-full rounded-md border border-input bg-card pl-9 pr-3 text-[13px] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          <div className="max-h-[640px] space-y-2 overflow-y-auto pr-1">
            {filtered.map((p) => {
              const active = p.principle_id === selected?.principle_id;
              return (
                <button
                  key={p.principle_id}
                  onClick={() => setSelectedId(p.principle_id)}
                  className={cn(
                    "w-full rounded-lg border p-3.5 text-left transition-colors",
                    active ? "border-vermilion/40 bg-vermilion/[0.04] shadow-card" : "border-border bg-card hover:bg-muted",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-[11px] text-muted-foreground">{p.principle_id}</span>
                    <div className="flex items-center gap-1.5">
                      {p.n_interviews >= 2 && (
                        <Badge variant="accent" className="gap-1">
                          <Users className="h-3 w-3" /> 2名
                        </Badge>
                      )}
                      <Badge variant={p.status === "approved" ? "ink" : "outline"}>
                        {p.status === "approved" ? "承認済" : "候補"}
                      </Badge>
                    </div>
                  </div>
                  <p className="mt-2 line-clamp-2 font-jp text-[13px] leading-snug text-foreground/90">{p.statement}</p>
                  <div className="mt-2">
                    <SourceChips ids={p.interview_ids} />
                  </div>
                </button>
              );
            })}
            {filtered.length === 0 && (
              <div className="rounded-lg border border-dashed border-border p-8 text-center text-[13px] text-muted-foreground">
                条件に合う原則がありません。
              </div>
            )}
          </div>
        </div>

        {/* Detail */}
        <div className="space-y-6">
          {selected ? (
            <>
              <div className="rounded-lg border border-border bg-card p-6 shadow-card">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[12px] text-muted-foreground">{selected.principle_id}</span>
                  {selected.n_interviews >= 2 ? (
                    <Badge variant="accent" className="gap-1"><Users className="h-3 w-3" /> 2名一致</Badge>
                  ) : (
                    <Badge variant="outline">単一出典</Badge>
                  )}
                  <Badge variant={selected.status === "approved" ? "ink" : "outline"}>
                    {selected.status === "approved" ? "承認済み" : "候補（未承認）"}
                  </Badge>
                </div>
                <h2 className="mt-3 font-serif text-xl font-semibold leading-snug tracking-tight">
                  {selected.statement}
                </h2>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {selected.tags.map((t) => (
                    <Badge key={t} variant="default">#{t}</Badge>
                  ))}
                </div>
                <div className="mt-6 hairline pt-5">
                  <ProvenanceList citations={selected.support} />
                </div>
              </div>

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="eyebrow">Derived coaching items · 派生コーチング教材</div>
                  <span className="text-[11px] text-muted-foreground">{derived.length} approved</span>
                </div>
                {derived.length ? (
                  derived.map((it) => <ItemCard key={it.item_id} item={it} />)
                ) : (
                  <div className="rounded-lg border border-dashed border-border bg-muted/30 p-8 text-center">
                    <p className="text-[13px] text-muted-foreground">
                      この原則からはまだ承認済みのコーチング教材がありません。
                    </p>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      承認済み原則のみ生成可能。人手レビューを経て初めてコーチに反映されます。
                    </p>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="rounded-lg border border-dashed border-border p-12 text-center text-muted-foreground">
              原則を選択してください。
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
