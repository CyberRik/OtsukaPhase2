"use client";

import { api } from "@/lib/api";
import { AdminHeader, Section, useFetched } from "@/components/admin/kit";
import { cn } from "@/lib/utils";

function Row({ k, v, ok }: { k: string; v: React.ReactNode; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between border-b border-border/40 py-1.5 text-[13px] last:border-0">
      <span className="text-muted-foreground">{k}</span>
      <span className={cn("font-medium", ok === false ? "text-band-red" : ok ? "text-band-green" : "text-foreground")}>{v}</span>
    </div>
  );
}

export default function StatusPage() {
  const { data, live } = useFetched(api.adminSystemStatus, {
    use_llm: false, today: "", retrieval_mode: "unknown",
    endpoints: { primary: { base_url: "", model: "" }, fallback: { base_url: "", model: "" } },
    flags: {}, data: { reps: 0, deals: 0, overlays: [] },
  });

  return (
    <div className="space-y-4">
      <AdminHeader title="System Status" lead="Operational snapshot — is the demo healthy and what is it configured to use." live={live} />

      <div className="grid gap-3 md:grid-cols-2">
        <Section title="Runtime">
          <Row k="LLM enabled" v={data.use_llm ? "yes" : "no (deterministic)"} ok={data.use_llm} />
          <Row k="Pinned date" v={data.today || "—"} />
          <Row k="Retrieval mode" v={data.retrieval_mode} ok={data.retrieval_mode.includes("dense")} />
          <Row k="Reps / Deals" v={`${data.data.reps} / ${data.data.deals}`} />
          <Row k="Ingested overlays" v={data.data.overlays.join(", ") || "none"} />
        </Section>

        <Section title="Model endpoints">
          <Row k="Primary model" v={data.endpoints.primary.model || "—"} />
          <Row k="Primary URL" v={<span className="font-mono text-[11px]">{data.endpoints.primary.base_url}</span>} />
          <Row k="Fallback model" v={data.endpoints.fallback.model || "—"} />
          <Row k="Fallback URL" v={<span className="font-mono text-[11px]">{data.endpoints.fallback.base_url}</span>} />
        </Section>

        <Section title="Feature flags">
          {Object.entries(data.flags).map(([k, v]) => <Row key={k} k={k} v={v ? "on" : "off"} ok={v} />)}
          {Object.keys(data.flags).length === 0 && <div className="text-[12px] text-muted-foreground">No flags.</div>}
        </Section>
      </div>
    </div>
  );
}
