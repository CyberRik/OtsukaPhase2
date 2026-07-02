"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { AdminHeader, StatCard, useFetched, fmt } from "@/components/admin/kit";

export default function AdminOverviewPage() {
  const { data, live } = useFetched(api.adminOverview, {
    reps: 0, managers: 0, juniors: 0, accounts: 0, deals: 0, open_deals: 0,
    communities: 0, knowledge_pending: 0, tokens_total: 0, llm_calls: 0,
  });

  return (
    <div className="space-y-5">
      <AdminHeader
        title="System Overview"
        lead="Everything happening across the platform — people, pipeline, knowledge, and LLM usage — at a glance."
        live={live}
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Salespeople" value={fmt(data.reps)} sub={`${data.managers} managers · ${data.juniors} juniors`} accent />
        <StatCard label="Accounts" value={fmt(data.accounts)} sub="with a login" />
        <StatCard label="Deals" value={fmt(data.deals)} sub={`${fmt(data.open_deals)} open`} />
        <StatCard label="Communities" value={fmt(data.communities)} sub="GraphRAG segments" />
        <StatCard label="Open deals" value={fmt(data.open_deals)} sub="in flight" />
        <StatCard label="Knowledge pending" value={fmt(data.knowledge_pending)} sub="awaiting review" />
        <StatCard label="LLM tokens" value={fmt(data.tokens_total)} sub={`${fmt(data.llm_calls)} inferences`} accent />
        <StatCard label="LLM calls" value={fmt(data.llm_calls)} sub="recorded" />
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        {[
          { href: "/admin/org", title: "Org & Assignments", body: "See every manager's team and move salespeople between managers." },
          { href: "/admin/usage", title: "LLM Usage", body: "Tokens per prompt/response and totals by model and feature." },
          { href: "/admin/visualization", title: "Graph-RAG Showcase", body: "Live, flashy visualization of why graph retrieval beats traditional." },
        ].map((c) => (
          <Link key={c.href} href={c.href} className="rounded-lg border border-border bg-card p-4 shadow-card transition-colors hover:border-primary/40">
            <div className="text-[14px] font-semibold text-foreground">{c.title}</div>
            <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">{c.body}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
