"use client";

import { api } from "@/lib/api";
import { AdminHeader, StatCard, Section, useFetched, fmt } from "@/components/admin/kit";
import type { UsageBucket } from "@/lib/admin-types";

function BreakdownTable({ rows, keyName }: { rows: ({ [k: string]: string } & UsageBucket)[]; keyName: string }) {
  const max = Math.max(1, ...rows.map((r) => r.total_tokens));
  return (
    <div className="space-y-1.5">
      {rows.map((r, i) => (
        <div key={i} className="flex items-center gap-2 text-[12.5px]">
          <span className="w-32 shrink-0 truncate text-muted-foreground">{r[keyName]}</span>
          <div className="relative h-4 flex-1 overflow-hidden rounded bg-muted">
            <div className="absolute inset-y-0 left-0 rounded bg-primary/70" style={{ width: `${(r.total_tokens / max) * 100}%` }} />
          </div>
          <span className="w-20 shrink-0 text-right tabular-nums text-foreground">{fmt(r.total_tokens)}</span>
          <span className="w-14 shrink-0 text-right tabular-nums text-muted-foreground">{fmt(r.calls)}×</span>
        </div>
      ))}
      {rows.length === 0 && <div className="text-[12px] text-muted-foreground">No data yet.</div>}
    </div>
  );
}

export default function UsagePage() {
  const { data, live } = useFetched(api.adminUsage, {
    totals: { calls: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, estimated_calls: 0, est_cost: 0 },
    cost_per_1k: 0, by_day: [], by_model: [], by_label: [], recent: [],
  });
  const t = data.totals;

  return (
    <div className="space-y-5">
      <AdminHeader
        title="LLM Usage"
        lead="Real, server-reported token counts for every local-model inference — tracked so we know how much we use the LLM."
        live={live}
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Total tokens" value={fmt(t.total_tokens)} sub={`${fmt(t.prompt_tokens)} in · ${fmt(t.completion_tokens)} out`} accent />
        <StatCard label="Inferences" value={fmt(t.calls)} sub={t.estimated_calls > 0 ? `${t.estimated_calls} estimated` : "all measured"} />
        <StatCard label="Avg / call" value={t.calls ? fmt(Math.round(t.total_tokens / t.calls)) : "0"} sub="tokens" />
        <StatCard label="Est. cost" value={data.cost_per_1k > 0 ? `$${t.est_cost}` : "free"} sub={data.cost_per_1k > 0 ? `@ $${data.cost_per_1k}/1K` : "local model"} />
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <Section title="By feature">
          <BreakdownTable rows={data.by_label as never} keyName="label" />
        </Section>
        <Section title="By model">
          <BreakdownTable rows={data.by_model as never} keyName="model" />
        </Section>
      </div>

      <Section title="Recent inferences — tokens per prompt/response">
        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="border-b border-border text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
                <th className="px-2 py-1.5 font-medium">Time</th>
                <th className="px-2 py-1.5 font-medium">Feature</th>
                <th className="px-2 py-1.5 font-medium">Model</th>
                <th className="px-2 py-1.5 font-medium text-right">Prompt</th>
                <th className="px-2 py-1.5 font-medium text-right">Response</th>
                <th className="px-2 py-1.5 font-medium text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {data.recent.map((r, i) => (
                <tr key={i} className="border-b border-border/40 last:border-0">
                  <td className="px-2 py-1.5 font-mono text-[11px] text-muted-foreground">{r.ts.slice(11, 19) || r.ts.slice(0, 10)}</td>
                  <td className="px-2 py-1.5">{r.label}{r.estimated && <span className="ml-1 text-[9px] text-band-yellow">est</span>}{r.streamed && <span className="ml-1 text-[9px] text-muted-foreground">stream</span>}</td>
                  <td className="px-2 py-1.5 text-muted-foreground">{r.model} <span className="text-[10px]">({r.endpoint})</span></td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmt(r.prompt_tokens)}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmt(r.completion_tokens)}</td>
                  <td className="px-2 py-1.5 text-right font-medium tabular-nums">{fmt(r.total_tokens)}</td>
                </tr>
              ))}
              {data.recent.length === 0 && (
                <tr><td colSpan={6} className="px-2 py-4 text-center text-[12px] text-muted-foreground">No inferences recorded yet. Use the app (chat, coaching, agents) to populate this.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}
