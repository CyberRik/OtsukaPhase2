"use client";

import { useMemo, useRef, useState } from "react";
import { api, graphRagStream } from "@/lib/api";
import { AdminHeader, useFetched, KIND_COLOR } from "@/components/admin/kit";
import { ForceGraphView, type FGNode } from "@/components/admin/force-graph";
import { ComparisonScorecard } from "@/components/admin/comparison";
import type { ComparisonSide, GraphRagEvent } from "@/lib/admin-types";
import { cn } from "@/lib/utils";

const CANNED = [
  "製造業のサーバー案件、なぜ負ける？",
  "小売業でPC周辺機器の勝ち筋は？",
  "ネットワーク機器の失注要因は？",
];

interface VisitLog { kind: string; label: string; detail?: string }

export default function LivePage() {
  const { data: graph } = useFetched(api.adminGraph, { nodes: [], links: [], stats: {} }, 0);
  const [query, setQuery] = useState(CANNED[0]);
  const [running, setRunning] = useState(false);
  const [visits, setVisits] = useState<VisitLog[]>([]);
  const [retrieved, setRetrieved] = useState<Record<string, unknown>[]>([]);
  const [highlight, setHighlight] = useState<Set<string>>(new Set());
  const [comparison, setComparison] = useState<{ graph: ComparisonSide; traditional: ComparisonSide } | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const nodes: FGNode[] = useMemo(
    () => graph.nodes.map((n) => ({ ...n, color: KIND_COLOR[n.kind] ?? "#8892b0", val: n.degree })),
    [graph.nodes],
  );

  const run = async () => {
    if (running) return;
    setRunning(true);
    setVisits([]); setRetrieved([]); setComparison(null);
    const hl = new Set<string>();
    setHighlight(new Set());
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    await graphRagStream(query, (e: GraphRagEvent) => {
      if (e.type === "node_visited") {
        const detail = e.kind === "community"
          ? `${e.n_deals ?? ""} deals · ${Math.round(Number(e.win_rate ?? 0) * 100)}%`
          : `${e.won ?? ""}/${e.closed ?? ""} won`;
        setVisits((v) => [...v, { kind: e.kind, label: e.label, detail }]);
        if (e.kind === "rep") { hl.add(e.label); setHighlight(new Set(hl)); }
      } else if (e.type === "edge_traversed") {
        hl.add(e.source); hl.add(e.target); setHighlight(new Set(hl));
      } else if (e.type === "retrieved") {
        setRetrieved((r) => [...r, e as Record<string, unknown>]);
      } else if (e.type === "comparison") {
        setComparison({ graph: e.graph, traditional: e.traditional });
      }
    }, { signal: ctrl.signal });

    setRunning(false);
  };

  return (
    <div className="space-y-3">
      <AdminHeader
        title="Live Graph-RAG"
        lead="Ask a question and watch the engine walk the graph and pull grounded evidence — then compare it to traditional retrieval, measured live."
      />

      <div className="flex flex-wrap items-center gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          className="min-w-[280px] flex-1 rounded-lg border border-border bg-background px-3 py-2 text-[13px] outline-none focus:border-primary"
        />
        <button
          onClick={run}
          disabled={running}
          className="rounded-lg bg-primary px-4 py-2 text-[13px] font-medium text-primary-foreground disabled:opacity-50"
        >
          {running ? "Running…" : "Run"}
        </button>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {CANNED.map((q) => (
          <button key={q} onClick={() => setQuery(q)} className="rounded-full border border-border px-2.5 py-1 text-[11.5px] text-muted-foreground hover:text-foreground">{q}</button>
        ))}
      </div>

      <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
        <ForceGraphView nodes={nodes} links={graph.links} height={480} highlightIds={highlight.size ? highlight : undefined} />

        <div className="space-y-3">
          <div className="rounded-lg border border-border bg-card p-3 shadow-card">
            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Traversal</div>
            <div className="max-h-[220px] space-y-1 overflow-y-auto">
              {visits.map((v, i) => (
                <div key={i} className="flex items-center gap-1.5 text-[12px]">
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: KIND_COLOR[v.kind] ?? "#888" }} />
                  <span className="font-medium text-foreground">{v.label}</span>
                  <span className="ml-auto text-[10.5px] text-muted-foreground">{v.detail}</span>
                </div>
              ))}
              {visits.length === 0 && <div className="text-[12px] text-muted-foreground">Run a query to watch the graph light up.</div>}
            </div>
          </div>

          {retrieved.length > 0 && (
            <div className="rounded-lg border border-border bg-card p-3 shadow-card">
              <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Retrieved (real trace)</div>
              <div className="max-h-[160px] space-y-1 overflow-y-auto text-[11.5px] text-muted-foreground">
                {retrieved.map((r, i) => <div key={i} className="truncate">{JSON.stringify(r)}</div>)}
              </div>
            </div>
          )}
        </div>
      </div>

      {comparison && (
        <div className={cn("transition-opacity")}>
          <ComparisonScorecard graph={comparison.graph} traditional={comparison.traditional} />
        </div>
      )}
    </div>
  );
}
