import Link from "next/link";
import {
  ArrowRight,
  GraduationCap,
  Library,
  LayoutDashboard,
  ScrollText,
  ShieldCheck,
  GitBranch,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ConfidenceBadge } from "@/components/confidence-badge";
import { SourceChip } from "@/components/source-chip";

export const dynamic = "force-dynamic";

const FEATURES = [
  {
    href: "/coach",
    icon: GraduationCap,
    title: "Sales Review Coach",
    ja: "営業レビュー・コーチ",
    body: "Paste a meeting note. Get a senior rep's reasoning made explicit — what they'd notice, what's missing, the questions they'd ask, and several possible moves. Never one 'right answer.'",
  },
  {
    href: "/knowledge",
    icon: Library,
    title: "Knowledge Explorer",
    ja: "ナレッジ・エクスプローラー",
    body: "Every principle traces to a verbatim interview sentence and carries a computed confidence. Browse the chain from raw source to coaching scenario.",
  },
  {
    href: "/dashboard",
    icon: LayoutDashboard,
    title: "Manager Dashboard",
    ja: "マネージャー・ダッシュボード",
    body: "Deterministic deal-health — red / yellow / green with a signal-by-signal breakdown, plus reliability flags where a report's optimism contradicts its data.",
  },
];

const LAYERS = [
  { icon: ScrollText, k: "01", title: "Source", ja: "一次情報", body: "Raw interviews, kept immutable. The exact sentence a senior said.", tone: "text-vermilion" },
  { icon: GitBranch, k: "02", title: "Principle", ja: "検証済み原則", body: "A human-validated claim citing its source spans. GenAI may never exceed it.", tone: "text-primary" },
  { icon: ShieldCheck, k: "03", title: "Coaching item", ja: "コーチング教材", body: "An illustration of one principle — shown only after a human approval gate.", tone: "text-conf-high" },
];

export default async function HomePage() {
  const [{ data: pr }, { data: it }, { data: db }] = await Promise.all([
    api.principles(),
    api.items(),
    api.dashboard(),
  ]);

  const stats = [
    { value: "2", label: "Senior interviews", sub: "the entire source corpus" },
    { value: String(pr.counts.total ?? 11), label: "Validated principles", sub: `${pr.counts.two_source ?? 4} backed by both seniors` },
    { value: String(it.counts.approved ?? 4), label: "Approved coaching items", sub: "human-gated, high confidence" },
    { value: String(db.kpis.open_deals ?? 49), label: "Deals scored", sub: "fully explainable, GPU-free" },
  ];

  return (
    <div className="space-y-20">
      {/* Hero */}
      <section className="relative">
        <div className="texture-grid pointer-events-none absolute inset-x-0 -top-12 h-72" />
        <div className="relative max-w-3xl space-y-6">
          <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-[11px] text-muted-foreground">
            <span className="h-1.5 w-1.5 rounded-full bg-vermilion" />
            Onboarding &amp; knowledge transfer for sales teams
          </div>
          <h1 className="font-serif text-[40px] font-semibold leading-[1.08] tracking-tight text-foreground md:text-[56px]">
            Turn one senior&apos;s reasoning into every rep&apos;s instinct.
          </h1>
          <p className="max-w-2xl text-lg leading-relaxed text-muted-foreground">
            Senpai captures how experienced salespeople <em className="not-italic text-foreground">think</em> —
            the questions they ask, the gaps they spot — and teaches it to new hires.
            Grounded in real interviews, never invented, with provenance and confidence on every claim.
          </p>
          <div className="flex flex-wrap items-center gap-3 pt-2">
            <Button asChild variant="seal" size="lg">
              <Link href="/coach">
                Open the Review Coach <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
            <Button asChild variant="outline" size="lg">
              <Link href="/knowledge">Explore the knowledge base</Link>
            </Button>
          </div>
        </div>
      </section>

      {/* Stat band */}
      <section className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border lg:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="bg-card p-6">
            <div className="font-serif text-4xl font-semibold tracking-tight text-foreground">{s.value}</div>
            <div className="mt-2 text-sm font-medium text-foreground">{s.label}</div>
            <div className="text-[12px] text-muted-foreground">{s.sub}</div>
          </div>
        ))}
      </section>

      {/* The three-layer model */}
      <section className="space-y-8">
        <div className="max-w-2xl space-y-2">
          <div className="eyebrow">How trust is built</div>
          <h2 className="font-serif text-2xl font-semibold tracking-tight">
            GenAI may only derive <span className="text-vermilion">down</span>, never invent up.
          </h2>
          <p className="text-[15px] leading-relaxed text-muted-foreground">
            Three layers, each constrained by the one above it. The model can illustrate a principle
            with a fresh scenario — but it can never add advice the principle doesn&apos;t already contain.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {LAYERS.map((l, i) => {
            const Icon = l.icon;
            return (
              <div key={l.k} className="relative rounded-lg border border-border bg-card p-6 shadow-card">
                <div className="flex items-center justify-between">
                  <Icon className={`h-5 w-5 ${l.tone}`} />
                  <span className="font-mono text-xs text-muted-foreground">{l.k}</span>
                </div>
                <div className="mt-4 font-serif text-lg font-semibold">{l.title}</div>
                <div className="text-[11px] uppercase tracking-eyebrow text-muted-foreground">{l.ja}</div>
                <p className="mt-3 text-[13px] leading-relaxed text-muted-foreground">{l.body}</p>
                {i < LAYERS.length - 1 && (
                  <ArrowRight className="absolute -right-3 top-1/2 hidden h-5 w-5 -translate-y-1/2 text-border md:block" />
                )}
              </div>
            );
          })}
        </div>
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed border-border bg-muted/40 px-5 py-4">
          <span className="text-[13px] text-muted-foreground">Confidence is computed, never authored:</span>
          <ConfidenceBadge level="high" />
          <ConfidenceBadge level="medium" />
          <ConfidenceBadge level="low" />
          <ConfidenceBadge level="unverified" />
        </div>
      </section>

      {/* Product surfaces */}
      <section className="space-y-6">
        <div className="eyebrow">Three surfaces, one source of truth</div>
        <div className="grid gap-4 md:grid-cols-3">
          {FEATURES.map((f) => {
            const Icon = f.icon;
            return (
              <Link
                key={f.href}
                href={f.href}
                className="group flex flex-col rounded-lg border border-border bg-card p-6 shadow-card transition-shadow hover:shadow-lift"
              >
                <Icon className="h-6 w-6 text-primary" />
                <h3 className="mt-4 font-serif text-lg font-semibold tracking-tight">{f.title}</h3>
                <div className="text-[11px] uppercase tracking-eyebrow text-muted-foreground">{f.ja}</div>
                <p className="mt-3 flex-1 text-[13px] leading-relaxed text-muted-foreground">{f.body}</p>
                <span className="mt-4 inline-flex items-center gap-1.5 text-[13px] font-medium text-foreground">
                  Open <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
                </span>
              </Link>
            );
          })}
        </div>
      </section>

      {/* Provenance teaser */}
      <section className="rounded-xl border border-border bg-card p-8 shadow-card">
        <div className="grid gap-8 md:grid-cols-[1.1fr_1fr] md:items-center">
          <div className="space-y-3">
            <div className="eyebrow">Why a manager can trust it</div>
            <h2 className="font-serif text-2xl font-semibold tracking-tight">
              Every claim shows the sentence it came from.
            </h2>
            <p className="text-[15px] leading-relaxed text-muted-foreground">
              When the Coach surfaces senior advice, it carries the interview it traces to and a
              confidence level. Nothing is a black box; nothing is invented.
            </p>
          </div>
          <figure className="space-y-2 rounded-lg border border-border bg-paper p-5">
            <blockquote className="quote-jp">
              初回訪問では、お客様との関係構築が最重要と考えており、業務内容や興味・関心事項をヒアリングしたいため。
            </blockquote>
            <figcaption className="flex items-center gap-2 pl-4 text-[11px] text-muted-foreground">
              <SourceChip id="I02" /> <span className="font-mono">Q5</span> · principle P008 · <ConfidenceBadge level="high" />
            </figcaption>
          </figure>
        </div>
      </section>
    </div>
  );
}
