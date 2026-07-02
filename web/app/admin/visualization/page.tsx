"use client";

import Link from "next/link";
import { Activity, BarChart3, Network, Sparkles } from "lucide-react";
import { AdminHeader } from "@/components/admin/kit";

const CARDS = [
  { href: "/admin/visualization/network", icon: Network, title: "Network Graph", body: "The whole knowledge graph — 745 nodes, 3,674 edges — reps, customers, deals, products, categories and industries, force-directed and alive." },
  { href: "/admin/visualization/communities", icon: Sparkles, title: "Community Map", body: "How GraphRAG partitions 520 deals into 44 grounded communities, colored by win rate so you see exactly where the business wins and loses." },
  { href: "/admin/visualization/live", icon: Activity, title: "Live Graph-RAG", body: "Ask a question and watch the system traverse the graph and retrieve grounded evidence in real time." },
  { href: "/admin/visualization/versus", icon: BarChart3, title: "vs Traditional", body: "A measured head-to-head: graph retrieval vs traditional vector search on the same question. Real numbers, no theatre." },
];

export default function VizLandingPage() {
  return (
    <div className="space-y-5">
      <AdminHeader
        title="Graph-RAG Showcase"
        lead="An internal, demo-only visualization of our Graph RAG engine — built to show Otsuka Shokai leadership why graph retrieval beats traditional retrieval. Every number on these pages is measured from the real system."
      />
      <div className="grid gap-3 md:grid-cols-2">
        {CARDS.map((c) => {
          const Icon = c.icon;
          return (
            <Link key={c.href} href={c.href} className="group rounded-lg border border-border bg-card p-5 shadow-card transition-colors hover:border-primary/40">
              <div className="flex items-center gap-2.5">
                <span className="rounded-lg bg-primary/10 p-2 text-primary"><Icon className="h-5 w-5" /></span>
                <div className="text-[15px] font-semibold text-foreground">{c.title}</div>
              </div>
              <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">{c.body}</p>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
