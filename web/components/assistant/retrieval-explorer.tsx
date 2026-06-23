"use client";

import { Database, FileSearch, GitGraph, ScanSearch, ShieldCheck, Globe2 } from "lucide-react";
import type { RetrievalTrace } from "@/lib/api";
import { cn } from "@/lib/utils";

// The Retrieval Explorer: the primary surface for debugging grounding. For each
// retrieval event it shows the source, the scope (account-restricted vs all
// customers), and every chunk that came back — id, customer, score — so you can
// see exactly what evidence reached the model and catch cross-customer leakage.

const SOURCE_META: Record<string, { ja: string; en: string; icon: typeof Database }> = {
  notes_semantic: { ja: "日報（意味検索）", en: "Notes (semantic)", icon: FileSearch },
  knowledge_keyword: { ja: "社内ナレッジ（キーワード）", en: "Knowledge (keyword)", icon: ShieldCheck },
  graph: { ja: "関係グラフ", en: "Graph", icon: GitGraph },
};

function scopeAccountId(scope: string): string | null {
  return scope.startsWith("account:") ? scope.slice("account:".length) : null;
}

export function RetrievalExplorer({
  traces, open, lang,
}: {
  traces: RetrievalTrace[]; open?: boolean; lang: "ja" | "en";
}) {
  const totalItems = traces.reduce((n, t) => n + t.items.length, 0);
  return (
    <details open={open} className="w-full max-w-[88%] rounded-lg border border-border bg-background text-[12px]">
      <summary className="flex cursor-pointer items-center gap-1.5 px-3 py-1.5 font-medium text-muted-foreground">
        <ScanSearch className="h-3.5 w-3.5" />
        {lang === "ja" ? "リトリーバル・エクスプローラ" : "Retrieval Explorer"}
        <span className="font-mono text-[10.5px]">· {traces.length} {lang === "ja" ? "検索" : "queries"} / {totalItems} {lang === "ja" ? "件" : "chunks"}</span>
      </summary>
      <div className="space-y-2.5 px-3 pb-3">
        {traces.map((tr, i) => {
          const meta = SOURCE_META[tr.source] ?? { ja: tr.source, en: tr.source, icon: Database };
          const Icon = meta.icon;
          const acct = scopeAccountId(tr.scope);
          const scoped = acct !== null;
          return (
            <div key={i} className="rounded-md border border-border/70 bg-card p-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center gap-1.5 font-medium text-foreground">
                  <Icon className="h-3.5 w-3.5 text-primary/70" />
                  {lang === "ja" ? meta.ja : meta.en}
                </span>
                {/* scope badge: account-scoped is the trustworthy default */}
                <span className={cn(
                  "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold",
                  scoped ? "bg-conf-high/10 text-conf-high" : "bg-band-yellow/10 text-band-yellow",
                )}>
                  {scoped
                    ? <>{lang === "ja" ? "アカウント限定" : "Account-scoped"}{tr.customer ? `: ${tr.customer}` : ""}</>
                    : <><Globe2 className="h-3 w-3" />{lang === "ja" ? "全社横断" : "All customers"}</>}
                </span>
                {tr.mode && <span className="font-mono text-[10px] text-muted-foreground">{tr.mode}</span>}
                {tr.query && <span className="truncate font-mono text-[10px] text-muted-foreground">“{tr.query}”</span>}
              </div>

              {tr.items.length === 0 ? (
                <div className="mt-1.5 text-[11px] text-muted-foreground">
                  {lang === "ja" ? "該当チャンクなし" : "no chunks"}
                </div>
              ) : (
                <ul className="mt-1.5 space-y-1">
                  {tr.items.map((it, j) => {
                    // leakage guard: in a scoped query, any chunk from another
                    // customer is a red flag — surface it loudly.
                    const leak = scoped && it.customer_id != null && acct !== "" && it.customer_id !== acct;
                    return (
                      <li key={j} className="flex items-start gap-2">
                        <span className="mt-[1px] shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
                          {it.score.toFixed(3)}
                        </span>
                        <span className="shrink-0 font-mono text-[10px] text-foreground/70">{it.id}</span>
                        {it.customer && (
                          <span className={cn(
                            "shrink-0 rounded px-1 text-[10px]",
                            leak ? "bg-band-red/15 font-semibold text-band-red" : "text-muted-foreground",
                          )}>
                            {it.customer}{leak ? (lang === "ja" ? " ⚠他社" : " ⚠other") : ""}
                          </span>
                        )}
                        {it.text && <span className="truncate text-[11px] text-foreground/80">{it.text}</span>}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </details>
  );
}
