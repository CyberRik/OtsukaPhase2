"use client";

import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { LiveBadge } from "@/components/site/live-badge";
import type { Fetched } from "@/lib/api";

// Small shared building blocks for the internal admin portal. Deliberately plain
// (English labels, no i18n) — this is an internal ops surface, not the product.

/** Fetch an api.* method that returns Fetched<T>; expose data + live + loading +
 *  a refetch. Polls every `intervalMs` (default 5s) so a page left open reflects new
 *  activity — e.g. LLM usage rows written as you chat — without a manual reload; pass
 *  intervalMs=0 to fetch once (used by the force-graph views, which must not re-layout
 *  on a poll). Keeps the offline-fixture story (live=false → LiveBadge greys). */
export function useFetched<T>(fn: () => Promise<Fetched<T>>, initial: T, intervalMs = 5000) {
  const [data, setData] = useState<T>(initial);
  const [live, setLive] = useState(false);
  const [loading, setLoading] = useState(true);
  // Manual refetch (e.g. after an admin edit) — sets state directly.
  const load = useCallback(async () => {
    const r = await fn();
    setData(r.data);
    setLive(r.live);
    setLoading(false);
  }, [fn]);
  useEffect(() => {
    let alive = true;               // one guard for the initial fetch + every poll tick
    const tick = () => fn().then((r) => {
      if (!alive) return;           // don't setState after unmount / dep change
      setData(r.data);
      setLive(r.live);
      setLoading(false);
    });
    tick();                          // fetch immediately on mount (no wait for first interval)
    const id = intervalMs > 0 ? setInterval(tick, intervalMs) : undefined;
    return () => { alive = false; if (id) clearInterval(id); };
  }, [fn, intervalMs]);
  return { data, live, loading, refetch: load };
}

export function AdminHeader({ title, lead, live, children }: {
  title: string; lead?: string; live?: boolean; children?: React.ReactNode;
}) {
  return (
    <header className="flex flex-col gap-3 pb-4 md:flex-row md:items-end md:justify-between">
      <div className="max-w-2xl space-y-1.5">
        <div className="eyebrow text-primary">Admin · 管理</div>
        <h1 className="text-[24px] font-semibold leading-tight tracking-tight text-foreground md:text-[28px]">{title}</h1>
        {lead && <p className="text-[13.5px] leading-relaxed text-muted-foreground">{lead}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {children}
        {live !== undefined && <LiveBadge live={live} />}
      </div>
    </header>
  );
}

export function StatCard({ label, value, sub, accent }: {
  label: string; value: React.ReactNode; sub?: string; accent?: boolean;
}) {
  return (
    <div className={cn(
      "rounded-lg border bg-card p-4 shadow-card",
      accent ? "border-primary/30 bg-primary/[0.03]" : "border-border",
    )}>
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-[26px] font-semibold leading-none tracking-tight text-foreground tabular-nums">{value}</div>
      {sub && <div className="mt-1 text-[11.5px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

export function Section({ title, children, right }: {
  title: string; children: React.ReactNode; right?: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-border bg-card shadow-card">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <h2 className="text-[13.5px] font-semibold text-foreground">{title}</h2>
        {right}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

/** number formatting */
export const fmt = (n: number) => n.toLocaleString("en-US");
export const pct = (n: number) => `${Math.round(n * 100)}%`;

/** win-rate → color (red low, amber mid, green high) using the app's band tokens */
export function winColor(rate: number): string {
  if (rate >= 0.7) return "hsl(var(--band-green))";
  if (rate >= 0.5) return "hsl(var(--band-yellow))";
  return "hsl(var(--band-red))";
}

/** node kind → stable color for the graph views */
export const KIND_COLOR: Record<string, string> = {
  rep: "#6366f1",
  customer: "#0ea5e9",
  deal: "#22c55e",
  product: "#f59e0b",
  category: "#ec4899",
  industry: "#8b5cf6",
  acttype: "#64748b",
  community: "#ec4899",
};
