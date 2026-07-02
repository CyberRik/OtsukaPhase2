"use client";

import { api } from "@/lib/api";
import { AdminHeader, StatCard, Section, useFetched, fmt, pct, winColor } from "@/components/admin/kit";

export default function PipelineHealthPage() {
  const { data, live } = useFetched(api.adminPipelineHealth, {
    totals: { n_deals: 0, n_won: 0, n_lost: 0, n_open: 0 },
    failure_signals: [], lowest_win_segments: [],
  });
  const t = data.totals;
  const closed = t.n_won + t.n_lost;
  const maxSig = Math.max(1, ...data.failure_signals.map((s) => s.count));

  return (
    <div className="space-y-5">
      <AdminHeader
        title="Pipeline Health"
        lead="System-wide deal health from the grounded community layer — where the business is losing, and why."
        live={live}
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Deals (segmented)" value={fmt(t.n_deals)} accent />
        <StatCard label="Won" value={fmt(t.n_won)} sub={closed ? pct(t.n_won / closed) + " win rate" : ""} />
        <StatCard label="Lost" value={fmt(t.n_lost)} />
        <StatCard label="Open" value={fmt(t.n_open)} />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Section title="Lowest win-rate segments — where we lose">
          <div className="space-y-1.5">
            {data.lowest_win_segments.map((s, i) => (
              <div key={i} className="flex items-center gap-2 text-[12.5px]">
                <span className="w-40 shrink-0 truncate text-foreground">{s.category} <span className="text-muted-foreground">× {s.industry || "—"}</span></span>
                <div className="relative h-4 flex-1 overflow-hidden rounded bg-muted">
                  <div className="absolute inset-y-0 left-0 rounded" style={{ width: `${s.win_rate * 100}%`, background: winColor(s.win_rate) }} />
                </div>
                <span className="w-10 shrink-0 text-right tabular-nums font-medium" style={{ color: winColor(s.win_rate) }}>{pct(s.win_rate)}</span>
                <span className="w-16 shrink-0 text-right text-[11px] text-muted-foreground">{s.n_lost} lost</span>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Failure-signal distribution">
          <div className="space-y-1.5">
            {data.failure_signals.map((s, i) => (
              <div key={i} className="flex items-center gap-2 text-[12.5px]">
                <span className="w-32 shrink-0 truncate text-muted-foreground">{s.signal}</span>
                <div className="relative h-4 flex-1 overflow-hidden rounded bg-muted">
                  <div className="absolute inset-y-0 left-0 rounded bg-band-red/70" style={{ width: `${(s.count / maxSig) * 100}%` }} />
                </div>
                <span className="w-12 shrink-0 text-right tabular-nums text-foreground">{fmt(s.count)}</span>
              </div>
            ))}
          </div>
        </Section>
      </div>
    </div>
  );
}
