"use client";

import type { ComparisonSide } from "@/lib/admin-types";
import { cn } from "@/lib/utils";
import { fmt } from "./kit";

// MEASURED three-way head-to-head. Every figure is computed live on the same query
// across all three retrievers — nothing hardcoded (unlike the old dashboard's faked
// "2.5x faster"). The winner per row is the measured best, not a preordained one.

type Dir = "lower" | "none";

// Index of the best (green) side for a metric, or -1 when the metric isn't a contest.
function bestIndex(values: number[], dir: Dir): number {
  if (dir === "none") return -1;
  let best = -1;
  let bestVal = Infinity;
  values.forEach((v, i) => {
    if (v > 0 && v < bestVal) {
      bestVal = v;
      best = i;
    }
  });
  return best;
}

function MetricRow({ label, values, unit, dir }: {
  label: string; values: number[]; unit: string; dir: Dir;
}) {
  const win = bestIndex(values, dir);
  return (
    <div className="grid grid-cols-[110px_repeat(3,1fr)] items-center gap-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      {values.map((v, i) => (
        <div
          key={i}
          className={cn(
            "text-center text-[15px] font-semibold tabular-nums",
            i === win ? "text-band-green" : "text-foreground",
          )}
        >
          {fmt(Math.round(v))}
          {unit && <span className="ml-0.5 text-[10px] font-normal text-muted-foreground">{unit}</span>}
        </div>
      ))}
    </div>
  );
}

export function ComparisonScorecard(
  { graph, networkx, traditional }: {
    graph: ComparisonSide; networkx: ComparisonSide; traditional: ComparisonSide;
  },
) {
  // Order left→right, hero first: grounded Graph RAG, naive NetworkX, vector RAG.
  const sides = [graph, networkx, traditional];
  const tone = ["text-primary", "text-foreground", "text-muted-foreground"];

  return (
    <div className="rounded-lg border border-border bg-card p-4 shadow-card">
      <div className="grid grid-cols-[110px_repeat(3,1fr)] items-end gap-3 border-b border-border pb-2">
        <div />
        {sides.map((s, i) => (
          <div key={i} className={cn("text-center text-[12.5px] font-semibold leading-tight", tone[i])}>
            {s.label}
          </div>
        ))}
      </div>

      <MetricRow label="latency" unit="ms" dir="lower"
        values={sides.map((s) => s.latency_ms)} />
      <MetricRow label="chunks" unit="" dir="none"
        values={sides.map((s) => s.chunks)} />
      <MetricRow label="context tokens" unit="tok" dir="lower"
        values={sides.map((s) => s.context_tokens)} />

      <div className="mt-2 grid grid-cols-[110px_repeat(3,1fr)] gap-3 border-t border-border pt-2 text-[11px] text-muted-foreground">
        <div />
        {sides.map((s, i) => (
          <div key={i} className="text-center">{s.note}</div>
        ))}
      </div>
      <div className="mt-2 text-center text-[10.5px] text-muted-foreground">
        All figures measured live on the same query — no hardcoded multipliers. Green = measured best (lower latency / fewer tokens).
      </div>
    </div>
  );
}
