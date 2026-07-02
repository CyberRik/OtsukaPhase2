"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { AdminHeader, useFetched, KIND_COLOR, fmt } from "@/components/admin/kit";
import { ForceGraphView, type FGNode } from "@/components/admin/force-graph";
import { cn } from "@/lib/utils";

const KINDS = ["all", "rep", "customer", "deal", "product", "category", "industry"] as const;

export default function NetworkPage() {
  const { data, live } = useFetched(api.adminGraph, { nodes: [], links: [], stats: {} });
  const [filter, setFilter] = useState<(typeof KINDS)[number]>("all");
  const [selected, setSelected] = useState<FGNode | null>(null);

  const nodes: FGNode[] = useMemo(
    () => data.nodes
      .filter((n) => filter === "all" || n.kind === filter)
      .map((n) => ({ ...n, color: KIND_COLOR[n.kind] ?? "#8892b0", val: n.degree })),
    [data.nodes, filter],
  );
  const keep = useMemo(() => new Set(nodes.map((n) => n.id)), [nodes]);
  const links = useMemo(
    () => data.links.filter((l) => keep.has(l.source as string) && keep.has(l.target as string)),
    [data.links, keep],
  );

  return (
    <div className="space-y-3">
      <AdminHeader
        title="Network Graph"
        lead={`The real knowledge graph — ${fmt(data.nodes.length)} nodes, ${fmt(data.links.length)} edges. Drag to explore; click a node for detail.`}
        live={live}
      />

      <div className="flex flex-wrap items-center gap-2">
        {KINDS.map((k) => (
          <button
            key={k}
            onClick={() => setFilter(k)}
            className={cn(
              "rounded-md px-2.5 py-1 text-[12px] font-medium capitalize transition-colors",
              filter === k ? "text-primary-foreground" : "border border-border text-muted-foreground hover:text-foreground",
            )}
            style={filter === k ? { background: k === "all" ? "hsl(var(--primary))" : (KIND_COLOR[k] ?? "hsl(var(--primary))") } : undefined}
          >
            {k}
          </button>
        ))}
        <span className="ml-auto text-[12px] text-muted-foreground">{fmt(nodes.length)} shown</span>
      </div>

      <ForceGraphView nodes={nodes} links={links} onNodeClick={setSelected} />

      {selected && (
        <div className="rounded-lg border border-border bg-card p-3 text-[13px] shadow-card">
          <span className="font-semibold text-foreground">{selected.label}</span>
          <span className="ml-2 rounded-full px-1.5 py-0.5 text-[10.5px]" style={{ background: (KIND_COLOR[selected.kind] ?? "#888") + "22", color: KIND_COLOR[selected.kind] }}>{selected.kind}</span>
          <span className="ml-2 text-muted-foreground">degree {selected.degree}{selected.outcome ? ` · ${selected.outcome}` : ""}{selected.category ? ` · ${selected.category}` : ""}{selected.industry ? ` · ${selected.industry}` : ""}</span>
        </div>
      )}

      <div className="flex flex-wrap gap-3 text-[11.5px] text-muted-foreground">
        {Object.entries(KIND_COLOR).filter(([k]) => k !== "community").map(([k, c]) => (
          <span key={k} className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full" style={{ background: c }} />{k}</span>
        ))}
      </div>
    </div>
  );
}
