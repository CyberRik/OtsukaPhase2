"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight, Boxes, Building2, ChevronLeft, Factory, Loader2, Receipt,
  ShoppingCart, Sparkles, TrendingDown, TrendingUp, Wrench, type LucideIcon,
} from "lucide-react";
import { api, accountCommentaryStream, type AccountCommentaryEvent } from "@/lib/api";
import type { AccountSummary, AccountHealthDimension, Band, DealRow } from "@/lib/types";
import { useT } from "@/lib/i18n";
import { cn, formatYen } from "@/lib/utils";
import { BandDot } from "@/components/band";
import { Skeleton } from "@/components/ui/skeleton";
import { DealDrawer } from "@/components/dashboard/deal-drawer";

const BAND_TEXT: Record<Band, { ja: string; en: string }> = {
  green: { ja: "良好", en: "Healthy" },
  yellow: { ja: "要注意", en: "Watch" },
  red: { ja: "リスク", en: "At risk" },
};

const DIM_LABEL: Record<string, { ja: string; en: string }> = {
  activity_trend: { ja: "活動トレンド", en: "Activity trend" },
  inactivity: { ja: "接触の鮮度", en: "Recency" },
  pipeline_progression: { ja: "案件の前進", en: "Pipeline progression" },
  win_rate: { ja: "勝率", en: "Win rate" },
  quote_engagement: { ja: "見積エンゲージ", en: "Quote engagement" },
  order_recency: { ja: "受注の鮮度・継続", en: "Order recency & repeat" },
  dm_access: { ja: "決裁者アクセス", en: "Decision-maker access" },
  growth: { ja: "成長", en: "Account growth" },
};

const KIND_META: Record<string, { ja: string; en: string; icon: LucideIcon }> = {
  cross_sell: { ja: "クロスセル", en: "Cross-sell", icon: Boxes },
  upsell: { ja: "アップセル", en: "Upsell", icon: ArrowUpRight },
  growth: { ja: "アカウント成長", en: "Account growth", icon: TrendingUp },
};

function bandClasses(band: Band) {
  return band === "green"
    ? "text-band-green bg-band-green/8 ring-band-green/25"
    : band === "yellow"
    ? "text-band-yellow bg-band-yellow/10 ring-band-yellow/25"
    : "text-band-red bg-band-red/8 ring-band-red/25";
}

export function AccountView({ customerId, role }: { customerId: string; role: "junior" | "manager" }) {
  const { t, lang } = useT();
  const [acct, setAcct] = useState<AccountSummary | null>(null);
  const [live, setLive] = useState(true);
  const [loading, setLoading] = useState(true);
  const [openDeals, setOpenDeals] = useState<DealRow[]>([]);
  const [drawerDeal, setDrawerDeal] = useState<string | null>(null);
  const L = (o: { ja: string; en: string }) => (lang === "ja" ? o.ja : o.en);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([api.account(customerId), api.dashboard()]).then(([a, d]) => {
      if (!alive) return;
      setAcct(a.data);
      setLive(a.live);
      setOpenDeals(d.data.deals.filter((x) => x.customer_id === customerId));
      setLoading(false);
    });
    return () => { alive = false; };
  }, [customerId]);

  if (loading) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (!acct) {
    return (
      <div className="space-y-4">
        <BackLink role={role} t={t} />
        <p className="rounded-xl border border-border bg-card p-6 text-center text-[13.5px] text-muted-foreground">
          {lang === "ja" ? "このアカウントは見つかりませんでした。" : "Account not found."}
        </p>
      </div>
    );
  }

  const h = acct.health;
  const positives = acct.expansion_signals.filter((s) => s.polarity === "positive");
  const opps = acct.expansion_signals.filter((s) => s.kind);

  return (
    <div className="space-y-6">
      <BackLink role={role} t={t} />

      {/* HEADER + HEALTH GAUGE */}
      <header className="flex flex-wrap items-start justify-between gap-4 rounded-2xl border border-border bg-card p-5">
        <div className="space-y-2">
          <h1 className="font-jp text-2xl font-semibold tracking-tight">{acct.customer}</h1>
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
            <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-1"><Factory className="h-3.5 w-3.5" /> {acct.industry}</span>
            <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2.5 py-1"><Building2 className="h-3.5 w-3.5" /> {acct.size}</span>
            <span className="font-mono text-[11px] text-muted-foreground/70">{acct.customer_id}</span>
            {!live && <span className="rounded-full bg-band-yellow/10 px-2 py-0.5 text-[10.5px] text-band-yellow">offline</span>}
          </div>
          <div className="flex flex-wrap gap-x-5 gap-y-1 pt-1 text-[12.5px]">
            <Metric label={lang === "ja" ? "進行中" : "Active"} value={`${acct.active_deals}`} />
            <Metric label={lang === "ja" ? "成約" : "Won"} value={`${acct.won_deals}`} />
            <Metric label={lang === "ja" ? "失注" : "Lost"} value={`${acct.lost_deals}`} />
            <Metric label={lang === "ja" ? "パイプライン" : "Pipeline"} value={formatYen(acct.total_pipeline)} />
            <Metric label={lang === "ja" ? "累計売上" : "Historical"} value={formatYen(acct.historical_revenue)} />
          </div>
        </div>
        <HealthGauge score={h.score} band={h.band} label={L(BAND_TEXT[h.band])} />
      </header>

      {/* ACCOUNT HEALTH — dimensions / explainability */}
      <section className="rounded-2xl border border-border bg-card p-5">
        <SectionTitle ja="アカウント健全度" en="Account Health" sub={lang === "ja" ? "スコアの内訳（高いほど健全）" : "How the score breaks down (higher = healthier)"} />
        <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
          {h.dimensions.map((d) => <DimensionBar key={d.name} d={d} label={L(DIM_LABEL[d.name] ?? { ja: d.name, en: d.name })} />)}
        </div>
      </section>

      {/* RELATIONSHIP TRAJECTORY */}
      {(acct.risk_signals.length > 0 || positives.length > 0) && (
        <section className="rounded-2xl border border-border bg-card p-5">
          <SectionTitle ja="関係性のトレンド" en="Relationship Trajectory" sub={lang === "ja" ? "検出されたパターンと根拠" : "Detected patterns and their evidence"} />
          <div className="mt-3 space-y-2">
            {acct.risk_signals.map((p) => (
              <TrajectoryChip key={p.id} polarity="risk" label={L({ ja: p.label_ja, en: p.label_en })} evidence={p.evidence} />
            ))}
            {positives.map((p, i) => (
              <TrajectoryChip key={`pos-${i}`} polarity="positive" label={L({ ja: p.label_ja ?? "", en: p.label_en ?? "" })} evidence={p.evidence ?? ""} />
            ))}
          </div>
        </section>
      )}

      {/* EXPANSION OPPORTUNITIES */}
      {opps.length > 0 && (
        <section className="rounded-2xl border border-border bg-card p-5">
          <SectionTitle ja="拡大の機会" en="Expansion Opportunities" sub={lang === "ja" ? "クロスセル・アップセル・成長余地" : "Cross-sell, upsell and growth"} />
          <div className="mt-3 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
            {opps.map((o, i) => {
              const meta = KIND_META[o.kind ?? "growth"];
              const Icon = meta.icon;
              return (
                <div key={i} className="rounded-xl border border-primary/20 bg-primary/[0.03] p-3.5">
                  <div className="flex items-center justify-between">
                    <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-primary">
                      <Icon className="h-3.5 w-3.5" /> {L(meta)}
                    </span>
                    {o.confidence && <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{o.confidence}</span>}
                  </div>
                  <div className="mt-1.5 font-jp text-[14px] font-medium text-foreground">{o.target}</div>
                  <p className="mt-0.5 text-[12px] leading-snug text-muted-foreground">{o.rationale}</p>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* SENIOR ACCOUNT COMMENTARY (streamed) */}
      <AccountCommentary customerId={customerId} band={h.band} score={h.score} />

      {/* OPEN DEALS — navigate back to deals */}
      {openDeals.length > 0 && (
        <section className="rounded-2xl border border-border bg-card p-5">
          <SectionTitle ja="進行中の案件" en="Open Deals" sub={lang === "ja" ? "クリックで案件の詳細へ" : "Click a deal for its detail"} />
          <ul className="mt-3 divide-y divide-border">
            {openDeals.map((d) => (
              <li key={d.deal_id}>
                <button onClick={() => setDrawerDeal(d.deal_id)} className="flex w-full items-center justify-between gap-3 py-2.5 text-left hover:opacity-80">
                  <span className="flex items-center gap-2.5">
                    <BandDot band={d.band} />
                    <span className="font-mono text-[11px] text-muted-foreground">{d.deal_id}</span>
                    <span className="text-[13px] text-foreground">{d.stage}</span>
                  </span>
                  <span className="flex items-center gap-3 text-[12.5px] text-muted-foreground">
                    {formatYen(d.amount)} <ArrowUpRight className="h-3.5 w-3.5" />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <DealDrawer dealId={drawerDeal} open={!!drawerDeal} onOpenChange={(o) => !o && setDrawerDeal(null)} />
    </div>
  );
}

function BackLink({ role, t }: { role: "junior" | "manager"; t: (k: string) => string }) {
  const home = role === "manager" ? "/manager" : "/junior";
  return (
    <Link href={home} className="inline-flex items-center gap-1 text-[12.5px] text-muted-foreground hover:text-foreground">
      <ChevronLeft className="h-4 w-4" /> {t("nav.home")}
    </Link>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="font-mono text-[13px] font-semibold text-foreground">{value}</span>
    </span>
  );
}

function SectionTitle({ ja, en, sub }: { ja: string; en: string; sub?: string }) {
  const { lang } = useT();
  return (
    <div>
      <h2 className="text-[15px] font-semibold tracking-tight">{lang === "ja" ? ja : en}</h2>
      {sub && <p className="mt-0.5 text-[11.5px] text-muted-foreground">{sub}</p>}
    </div>
  );
}

function HealthGauge({ score, band, label }: { score: number; band: Band; label: string }) {
  const { lang } = useT();
  return (
    <div className={cn("flex min-w-[150px] flex-col items-center gap-1 rounded-xl px-5 py-3 ring-1", bandClasses(band))}>
      <span className="text-[10.5px] font-semibold uppercase tracking-wide opacity-80">{lang === "ja" ? "健全度" : "Health"}</span>
      <div className="flex items-baseline gap-1">
        <span className="text-4xl font-bold tabular-nums">{score}</span>
        <span className="text-[13px] opacity-70">/100</span>
      </div>
      <span className="inline-flex items-center gap-1.5 text-[12px] font-medium"><BandDot band={band} /> {label}</span>
    </div>
  );
}

function DimensionBar({ d, label }: { d: AccountHealthDimension; label: string }) {
  const frac = d.max ? d.points / d.max : 0;
  const color = frac >= 0.66 ? "bg-band-green" : frac >= 0.4 ? "bg-band-yellow" : "bg-band-red";
  return (
    <div className="rounded-lg border border-border bg-background px-3 py-2">
      <div className="flex items-center justify-between text-[12px]">
        <span className="font-medium text-foreground">{label}</span>
        <span className="font-mono text-[11px] text-muted-foreground">{d.points}/{d.max}</span>
      </div>
      <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", color)} style={{ width: `${Math.max(3, frac * 100)}%` }} />
      </div>
      <p className="mt-1 font-jp text-[11px] leading-snug text-muted-foreground">{d.reason}</p>
    </div>
  );
}

function TrajectoryChip({ polarity, label, evidence }: { polarity: "risk" | "positive"; label: string; evidence: string }) {
  const risk = polarity === "risk";
  const Icon = risk ? TrendingDown : TrendingUp;
  return (
    <div className={cn("flex items-start gap-2.5 rounded-lg border px-3 py-2", risk ? "border-band-red/25 bg-band-red/[0.04]" : "border-band-green/25 bg-band-green/[0.04]")}>
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", risk ? "text-band-red" : "text-band-green")} />
      <div>
        <div className={cn("text-[13px] font-medium", risk ? "text-band-red" : "text-band-green")}>{label}</div>
        <p className="font-jp text-[12px] leading-snug text-muted-foreground">{evidence}</p>
      </div>
    </div>
  );
}

// --- streamed senior account commentary -------------------------------------
function AccountCommentary({ customerId, band, score }: { customerId: string; band: Band; score: number }) {
  const { lang } = useT();
  const [text, setText] = useState("");
  const [status, setStatus] = useState<"running" | "done" | "unavailable">("running");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    let acc = "";
    accountCommentaryStream(customerId, (e: AccountCommentaryEvent) => {
      if (e.type === "delta") { acc += e.text; setText(acc); }
      else if (e.type === "done") setStatus("done");
      else if (e.type === "unavailable") setStatus("unavailable");
    }, { lang });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [customerId]);

  return (
    <section className={cn("rounded-2xl border bg-card p-5 ring-1", bandClasses(band))}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-[15px] font-semibold tracking-tight text-foreground">
            {lang === "ja" ? "シニア・アカウント所見" : "Senior Account Commentary"}
          </h2>
          <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-primary">AI</span>
        </div>
        <span className="inline-flex items-center gap-1.5 text-[12px] font-medium"><BandDot band={band} /> {score}/100</span>
      </div>

      <div className="mt-3">
        {text ? (
          <AccountMd text={text} />
        ) : status === "running" ? (
          <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> {lang === "ja" ? "アカウント全体を読み込み中…" : "Reading the whole account…"}
          </div>
        ) : (
          <p className="text-[13px] text-muted-foreground">
            {lang === "ja" ? "所見は現在利用できません（モデル接続を確認してください）。" : "Commentary unavailable (check the model connection)."}
          </p>
        )}
        {status === "running" && text && <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-foreground/40 align-middle" />}
      </div>
    </section>
  );
}

// --- lightweight markdown (headings / bullets / bold) -----------------------
function inlineBold(s: string) {
  return s.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**")
      ? <strong key={i} className="font-semibold text-foreground">{p.slice(2, -2)}</strong>
      : <span key={i}>{p}</span>,
  );
}

function AccountMd({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  return (
    <div className="space-y-1.5 font-jp text-[13.5px] leading-relaxed text-foreground/90">
      {lines.map((ln, i) => {
        const tx = ln.trim();
        if (!tx) return <div key={i} className="h-1" />;
        if (/^#{1,6}\s/.test(tx) || (tx.startsWith("**") && tx.endsWith("**") && tx.length < 40)) {
          return <h4 key={i} className="pt-1.5 text-[12px] font-semibold uppercase tracking-[0.04em] text-primary">{tx.replace(/^#{1,6}\s+/, "").replace(/\*\*/g, "")}</h4>;
        }
        if (/^[-*]\s/.test(tx)) {
          return (
            <div key={i} className="flex gap-2 pl-1">
              <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-primary/60" />
              <span>{inlineBold(tx.replace(/^[-*]\s+/, ""))}</span>
            </div>
          );
        }
        return <p key={i}>{inlineBold(tx)}</p>;
      })}
    </div>
  );
}
