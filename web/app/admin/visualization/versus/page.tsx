"use client";

import { useState } from "react";
import { graphRagStream } from "@/lib/api";
import { AdminHeader } from "@/components/admin/kit";
import { ComparisonScorecard } from "@/components/admin/comparison";
import type { ComparisonSide, GraphRagEvent } from "@/lib/admin-types";

const CANNED = [
  "製造業のサーバー案件、なぜ負ける？",
  "小売業でPC周辺機器の勝ち筋は？",
  "ネットワーク機器の失注要因は？",
];

interface Sample { customer?: string; deal?: string; score?: number; snippet?: string; label?: string; n_deals?: number; win_rate?: number }

export default function VersusPage() {
  const [query, setQuery] = useState(CANNED[0]);
  const [running, setRunning] = useState(false);
  const [cmp, setCmp] = useState<{ graph: ComparisonSide; traditional: ComparisonSide } | null>(null);

  const run = async () => {
    if (running) return;
    setRunning(true);
    setCmp(null);
    await graphRagStream(query, (e: GraphRagEvent) => {
      if (e.type === "comparison") setCmp({ graph: e.graph, traditional: e.traditional });
    });
    setRunning(false);
  };

  const graphSample = (cmp?.graph.sample ?? []) as Sample[];
  const tradSample = (cmp?.traditional.sample ?? []) as Sample[];

  return (
    <div className="space-y-4">
      <AdminHeader
        title="Graph-RAG vs Traditional"
        lead="The same question, both ways. Traditional retrieval dumps raw daily-report chunks; Graph RAG answers from grounded communities. Every number is measured live."
      />

      <div className="flex flex-wrap items-center gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          className="min-w-[280px] flex-1 rounded-lg border border-border bg-background px-3 py-2 text-[13px] outline-none focus:border-primary"
        />
        <button onClick={run} disabled={running} className="rounded-lg bg-primary px-4 py-2 text-[13px] font-medium text-primary-foreground disabled:opacity-50">
          {running ? "Measuring…" : "Compare"}
        </button>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {CANNED.map((q) => (
          <button key={q} onClick={() => setQuery(q)} className="rounded-full border border-border px-2.5 py-1 text-[11.5px] text-muted-foreground hover:text-foreground">{q}</button>
        ))}
      </div>

      {!cmp && <div className="rounded-lg border border-dashed border-border py-10 text-center text-[13px] text-muted-foreground">Run a comparison to see the measured head-to-head.</div>}

      {cmp && (
        <>
          <ComparisonScorecard graph={cmp.graph} traditional={cmp.traditional} />

          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg border border-primary/30 bg-primary/[0.03] p-3">
              <div className="mb-2 text-[12px] font-semibold text-primary">Graph RAG retrieved — grounded communities</div>
              <div className="space-y-1">
                {graphSample.map((s, i) => (
                  <div key={i} className="flex items-center justify-between rounded-md bg-card px-2 py-1.5 text-[12px]">
                    <span className="font-medium text-foreground">{s.label}</span>
                    <span className="text-muted-foreground">{s.n_deals} deals · {Math.round((s.win_rate ?? 0) * 100)}%</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-border bg-card p-3">
              <div className="mb-2 text-[12px] font-semibold text-muted-foreground">Traditional retrieved — raw report chunks</div>
              <div className="space-y-1">
                {tradSample.map((s, i) => (
                  <div key={i} className="rounded-md bg-muted/50 px-2 py-1.5 text-[11.5px]">
                    <div className="flex justify-between text-muted-foreground">
                      <span className="font-mono">{s.customer} · {s.deal}</span>
                      <span>score {s.score}</span>
                    </div>
                    <div className="truncate text-foreground">{s.snippet}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
