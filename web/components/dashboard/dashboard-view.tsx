"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, ChevronRight } from "lucide-react";
import type { DashboardData } from "@/lib/types";
import { cn, compactYen, formatYen } from "@/lib/utils";
import { BandDot, BandPill } from "@/components/band";
import { Badge } from "@/components/ui/badge";
import { LiveBadge } from "@/components/site/live-badge";
import { DealDrawer } from "./deal-drawer";

const SEV_ORDER = { high: 0, medium: 1, low: 2 } as const;
const SEV_TONE: Record<string, string> = {
  high: "text-band-red",
  medium: "text-band-yellow",
  low: "text-muted-foreground",
};

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="bg-card p-5">
      <div className="eyebrow">{label}</div>
      <div className={cn("mt-1.5 font-serif text-3xl font-semibold tracking-tight", tone)}>{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}

export function DashboardView({ initial, live }: { initial: DashboardData; live: boolean }) {
  const [rep, setRep] = useState("(all)");
  const [openId, setOpenId] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(false);

  const deals = useMemo(
    () => (rep === "(all)" ? initial.deals : initial.deals.filter((d) => d.rep === rep)),
    [initial.deals, rep],
  );
  const flags = useMemo(
    () => [...(rep === "(all)" ? initial.flags : initial.flags.filter((f) => f.rep === rep))].sort(
      (a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity],
    ),
    [initial.flags, rep],
  );

  const k = {
    open: deals.length,
    red: deals.filter((d) => d.band === "red").length,
    yellow: deals.filter((d) => d.band === "yellow").length,
    green: deals.filter((d) => d.band === "green").length,
    pipeline: deals.reduce((s, d) => s + d.amount, 0),
  };
  const total = Math.max(1, k.open);

  function openDeal(id: string) {
    setOpenId(id);
    setDrawer(true);
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <label className="eyebrow">担当者 · Rep</label>
          <select
            value={rep}
            onChange={(e) => setRep(e.target.value)}
            className="h-9 rounded-md border border-input bg-card px-3 text-[13px] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="(all)">全員 (all)</option>
            {initial.reps.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
          <span className="text-[12px] text-muted-foreground">as of {initial.today}</span>
        </div>
        <LiveBadge live={live} />
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border md:grid-cols-4">
        <Kpi label="Open deals" value={String(k.open)} sub="in pipeline" />
        <Kpi label="At risk" value={String(k.red)} sub="band red" tone="text-band-red" />
        <Kpi label="Reliability flags" value={String(flags.length)} sub="reports vs. reality" tone="text-band-yellow" />
        <Kpi label="Pipeline" value={compactYen(k.pipeline)} sub={formatYen(k.pipeline)} />
      </div>

      {/* Pipeline health bar */}
      <div className="space-y-2">
        <div className="eyebrow">Pipeline health</div>
        <div className="flex h-3 w-full overflow-hidden rounded-full bg-muted">
          <div className="bg-band-red" style={{ width: `${(k.red / total) * 100}%` }} />
          <div className="bg-band-yellow" style={{ width: `${(k.yellow / total) * 100}%` }} />
          <div className="bg-band-green" style={{ width: `${(k.green / total) * 100}%` }} />
        </div>
        <div className="flex flex-wrap gap-4 text-[12px] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5"><BandDot band="red" /> {k.red} 要注意</span>
          <span className="inline-flex items-center gap-1.5"><BandDot band="yellow" /> {k.yellow} 注視</span>
          <span className="inline-flex items-center gap-1.5"><BandDot band="green" /> {k.green} 健全</span>
        </div>
      </div>

      {/* Deal table */}
      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-card">
        <table className="w-full text-left text-[13px]">
          <thead>
            <tr className="border-b border-border text-[11px] uppercase tracking-eyebrow text-muted-foreground">
              <th className="px-4 py-3 font-medium">Deal</th>
              <th className="hidden px-4 py-3 font-medium md:table-cell">Rep</th>
              <th className="hidden px-4 py-3 font-medium sm:table-cell">Stage</th>
              <th className="px-4 py-3 text-right font-medium">Amount</th>
              <th className="px-4 py-3 font-medium">Health</th>
              <th className="hidden px-4 py-3 text-right font-medium lg:table-cell">Stale</th>
              <th className="px-4 py-3 text-right font-medium">Flags</th>
              <th className="px-2 py-3" />
            </tr>
          </thead>
          <tbody>
            {deals.map((d) => (
              <tr
                key={d.deal_id}
                onClick={() => openDeal(d.deal_id)}
                className="cursor-pointer border-b border-border/60 transition-colors last:border-0 hover:bg-muted/50"
              >
                <td className="px-4 py-3">
                  <div className="font-medium text-foreground">{d.customer}</div>
                  <div className="font-mono text-[11px] text-muted-foreground">{d.deal_id}</div>
                </td>
                <td className="hidden px-4 py-3 text-muted-foreground md:table-cell">{d.rep}</td>
                <td className="hidden px-4 py-3 capitalize text-muted-foreground sm:table-cell">{d.stage}</td>
                <td className="px-4 py-3 text-right font-mono tabular-nums">{compactYen(d.amount)}</td>
                <td className="px-4 py-3"><BandPill band={d.band} score={d.score} /></td>
                <td className="hidden px-4 py-3 text-right font-mono tabular-nums text-muted-foreground lg:table-cell">
                  {d.days_stale != null ? `${d.days_stale}d` : "—"}
                </td>
                <td className="px-4 py-3 text-right">
                  {d.n_flags > 0 ? (
                    <span className="inline-flex items-center gap-1 font-mono text-[12px] text-band-yellow">
                      <AlertTriangle className="h-3.5 w-3.5" /> {d.n_flags}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </td>
                <td className="px-2 py-3 text-muted-foreground"><ChevronRight className="h-4 w-4" /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {deals.length === 0 && (
          <div className="p-10 text-center text-[13px] text-muted-foreground">この担当者の案件はありません。</div>
        )}
      </div>

      {/* Reliability flags */}
      <section className="space-y-3">
        <div className="eyebrow flex items-center gap-2">
          <AlertTriangle className="h-3.5 w-3.5" /> Report-reliability flags · 信頼性フラグ
        </div>
        {flags.length ? (
          <div className="grid gap-2 md:grid-cols-2">
            {flags.map((f, i) => (
              <button
                key={i}
                onClick={() => openDeal(f.deal_id)}
                className="flex items-start gap-3 rounded-lg border border-border bg-card p-3.5 text-left shadow-card transition-colors hover:bg-muted/50"
              >
                <AlertTriangle className={cn("mt-0.5 h-4 w-4 shrink-0", SEV_TONE[f.severity])} />
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                    <span className="font-medium text-foreground">{f.customer}</span>
                    <span className="font-mono">{f.deal_id}</span>
                    <Badge variant="outline">{f.severity}</Badge>
                  </div>
                  <p className="mt-1 font-jp text-[13px] leading-snug text-foreground/90">{f.message}</p>
                </div>
              </button>
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-band-green/30 bg-band-green/5 p-6 text-center text-[13px] text-band-green">
            この絞り込みでは信頼性フラグはありません。
          </div>
        )}
      </section>

      <DealDrawer dealId={openId} open={drawer} onOpenChange={setDrawer} />
    </div>
  );
}
