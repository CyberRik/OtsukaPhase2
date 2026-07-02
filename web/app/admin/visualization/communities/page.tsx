"use client";

import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { AdminHeader, useFetched, fmt, pct, winColor } from "@/components/admin/kit";
import type { Community } from "@/lib/admin-types";
import { cn } from "@/lib/utils";

export default function CommunitiesPage() {
  const { data, live } = useFetched(api.adminCommunities, { communities: [] }, 0);
  const [sel, setSel] = useState<Community | null>(null);

  const { categories, leavesByCat } = useMemo(() => {
    const cats = data.communities.filter((c) => c.level === "category").sort((a, b) => b.n_deals - a.n_deals);
    const leaves = data.communities.filter((c) => c.level === "leaf");
    const byCat = new Map<string, Community[]>();
    for (const l of leaves) {
      if (!byCat.has(l.category)) byCat.set(l.category, []);
      byCat.get(l.category)!.push(l);
    }
    for (const arr of byCat.values()) arr.sort((a, b) => a.win_rate - b.win_rate);
    return { categories: cats, leavesByCat: byCat };
  }, [data.communities]);

  // leaf tile size scales with deal count
  const maxDeals = Math.max(1, ...data.communities.filter((c) => c.level === "leaf").map((c) => c.n_deals));

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
      <div className="space-y-4">
        <AdminHeader
          title="Community Map"
          lead={`${fmt(data.communities.length)} grounded communities (7 category rollups + 37 thick leaves). Tile size = deals, color = win rate. Click any tile.`}
          live={live}
        />

        <div className="space-y-4">
          {categories.map((cat) => (
            <div key={cat.id}>
              <div className="mb-1.5 flex items-center gap-2">
                <span className="text-[13.5px] font-semibold text-foreground">{cat.category}</span>
                <span className="text-[11.5px] text-muted-foreground">{fmt(cat.n_deals)} deals</span>
                <span className="text-[11.5px] font-medium" style={{ color: winColor(cat.win_rate) }}>{pct(cat.win_rate)} win</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {(leavesByCat.get(cat.category) ?? []).map((leaf) => {
                  const size = 40 + (leaf.n_deals / maxDeals) * 60;
                  return (
                    <button
                      key={leaf.id}
                      onClick={() => setSel(leaf)}
                      title={`${leaf.industry} · ${leaf.n_deals} deals · ${pct(leaf.win_rate)}`}
                      className={cn("flex flex-col items-center justify-center rounded-md border p-1 text-center transition-transform hover:scale-105",
                        sel?.id === leaf.id ? "border-foreground" : "border-border/40")}
                      style={{ width: size, height: size, background: winColor(leaf.win_rate) + "26" }}
                    >
                      <span className="truncate text-[10px] font-medium text-foreground" style={{ maxWidth: size - 8 }}>{leaf.industry}</span>
                      <span className="text-[10px] font-semibold" style={{ color: winColor(leaf.win_rate) }}>{pct(leaf.win_rate)}</span>
                    </button>
                  );
                })}
                {(leavesByCat.get(cat.category) ?? []).length === 0 && (
                  <span className="text-[11.5px] text-muted-foreground">thin — rolls up into category</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="lg:sticky lg:top-2 lg:self-start">
        <div className="rounded-lg border border-border bg-card p-4 shadow-card">
          {sel ? (
            <div className="space-y-3">
              <div>
                <div className="text-[15px] font-semibold text-foreground">{sel.category}</div>
                <div className="text-[12.5px] text-muted-foreground">× {sel.industry}</div>
              </div>
              <div className="grid grid-cols-4 gap-2 text-center">
                {[["deals", sel.n_deals], ["won", sel.n_won], ["lost", sel.n_lost], ["open", sel.n_open]].map(([k, v]) => (
                  <div key={k as string} className="rounded-md bg-muted/50 py-1.5">
                    <div className="text-[15px] font-semibold tabular-nums text-foreground">{v as number}</div>
                    <div className="text-[10px] text-muted-foreground">{k as string}</div>
                  </div>
                ))}
              </div>
              <div className="text-center text-[13px] font-medium" style={{ color: winColor(sel.win_rate) }}>{pct(sel.win_rate)} win rate</div>
              {(sel.top_failure_signals?.length ?? 0) > 0 && (
                <div>
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Top failure signals</div>
                  <div className="flex flex-wrap gap-1">
                    {sel.top_failure_signals?.map((s, i) => (
                      <span key={i} className="rounded-full bg-band-red/10 px-2 py-0.5 text-[11px] text-band-red">{s.signal} ({s.count})</span>
                    ))}
                  </div>
                </div>
              )}
              {sel.narrative_ja && (
                <div>
                  <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Summary
                    <span className={cn("rounded-full px-1.5 text-[9px]", sel.narrative_source === "llm" ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground")}>
                      {sel.narrative_source === "llm" ? "LLM · grounded" : "template"}
                    </span>
                  </div>
                  <p className="text-[12.5px] leading-relaxed text-foreground">{sel.narrative_ja}</p>
                </div>
              )}
              {(sel.recommended_principle_ids?.length ?? 0) > 0 && (
                <div className="text-[11.5px] text-muted-foreground">Principles: {sel.recommended_principle_ids?.join(", ")}</div>
              )}
            </div>
          ) : (
            <div className="py-8 text-center text-[13px] text-muted-foreground">Select a community to see its grounded summary.</div>
          )}
        </div>
      </div>
    </div>
  );
}
