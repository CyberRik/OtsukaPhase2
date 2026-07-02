"use client";

import type { ComparisonSide } from "@/lib/admin-types";
import { cn } from "@/lib/utils";
import { fmt } from "./kit";

// The MEASURED head-to-head. Ratios are computed from the two measured sides —
// nothing is hardcoded (unlike the old dashboard that faked "2.5x faster").
function ratio(a: number, b: number): string {
  if (a <= 0 || b <= 0) return "—";
  const r = a >= b ? a / b : b / a;
  return `${r.toFixed(1)}×`;
}

function Metric({ label, graph, trad, unit, graphBetterWhenLower }: {
  label: string; graph: number; trad: number; unit: string; graphBetterWhenLower?: boolean;
}) {
  const graphWins = graphBetterWhenLower ? graph < trad : graph > trad;
  return (
    <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 py-2">
      <div className={cn("text-right text-[15px] font-semibold tabular-nums", graphWins ? "text-band-green" : "text-foreground")}>
        {fmt(Math.round(graph))}<span className="ml-0.5 text-[10px] font-normal text-muted-foreground">{unit}</span>
      </div>
      <div className="text-center">
        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
        <div className="text-[11px] font-medium text-primary">{ratio(graph, trad)}</div>
      </div>
      <div className={cn("text-left text-[15px] font-semibold tabular-nums", !graphWins ? "text-band-green" : "text-foreground")}>
        {fmt(Math.round(trad))}<span className="ml-0.5 text-[10px] font-normal text-muted-foreground">{unit}</span>
      </div>
    </div>
  );
}

export function ComparisonScorecard({ graph, traditional }: { graph: ComparisonSide; traditional: ComparisonSide }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 shadow-card">
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 border-b border-border pb-2">
        <div className="text-right text-[13px] font-semibold text-primary">{graph.label}</div>
        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">vs</div>
        <div className="text-left text-[13px] font-semibold text-muted-foreground">{traditional.label}</div>
      </div>

      <Metric label="latency" graph={graph.latency_ms} trad={traditional.latency_ms} unit="ms" graphBetterWhenLower />
      <Metric label="chunks" graph={graph.chunks} trad={traditional.chunks} unit="" />
      <Metric label="context tokens" graph={graph.context_tokens} trad={traditional.context_tokens} unit="tok" />

      <div className="mt-2 grid grid-cols-2 gap-3 border-t border-border pt-2 text-[11px] text-muted-foreground">
        <div className="text-right">{graph.note}</div>
        <div className="text-left">{traditional.note}</div>
      </div>
      <div className="mt-2 text-center text-[10.5px] text-muted-foreground">All figures measured live on the same query — no hardcoded multipliers.</div>
    </div>
  );
}
