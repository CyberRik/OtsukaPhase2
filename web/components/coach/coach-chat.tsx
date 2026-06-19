"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BookMarked,
  Bot,
  CornerDownLeft,
  Eye,
  GraduationCap,
  Layers,
  Lightbulb,
  type LucideIcon,
  MessagesSquare,
  RotateCcw,
  Route,
  Scale,
  Search,
  Sparkles,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { api, narrateStream } from "@/lib/api";
import type {
  CoachExample,
  CoachResponse,
  Confidence,
  DealRow,
  KnowledgeItem,
  Principle,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { PRINCIPLE_KEYWORDS, principleText, tagText } from "@/lib/content-i18n";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { LiveBadge } from "@/components/site/live-badge";
import { ConfidenceBadge } from "@/components/confidence-badge";
import { SourceChips } from "@/components/source-chip";
import { ProvenanceList } from "@/components/provenance";

const ICONS: Record<string, LucideIcon> = {
  eye: Eye, search: Search, alert: AlertTriangle,
  message: MessagesSquare, route: Route, scale: Scale,
};
const TONES: Record<string, string> = {
  observations: "text-primary bg-primary/10",
  missing_info: "text-conf-low bg-conf-low/10",
  risks: "text-band-red bg-band-red/10",
  questions: "text-navy bg-navy/10",
  next_actions: "text-conf-high bg-conf-high/10",
  decision_factors: "text-band-yellow bg-band-yellow/10",
};

const SENIOR_RE = /^先輩の知見\(出典 (.+?) \/ 確度(.+?)\): ([\s\S]+)$/;

// --- relevance (presentation only) -----------------------------------------
function principleConfidence(p: Principle): Confidence {
  if (p.status === "approved" && p.n_interviews >= 2) return "high";
  if (p.status === "approved") return "low";
  return "unverified";
}

function relevantPrinciples(note: string, principles: Principle[], max = 3): Principle[] {
  const scored = principles.map((p) => {
    const kws = PRINCIPLE_KEYWORDS[p.principle_id] ?? [];
    let score = kws.reduce((s, k) => (note.includes(k) ? s + 1 : s), 0);
    score += p.tags.reduce((s, tg) => (note.includes(tg) ? s + 1 : s), 0);
    if (p.n_interviews >= 2) score += 0.5;
    return { p, score };
  });
  const hits = scored.filter((s) => s.score >= 1).sort((a, b) => b.score - a.score);
  const pool = hits.length
    ? hits
    : scored
        .filter((s) => s.p.status === "approved" && s.p.n_interviews >= 2)
        .sort((a, b) => b.score - a.score);
  return pool.slice(0, max).map((s) => s.p);
}

function similarItems(relIds: string[], items: KnowledgeItem[], max = 2): KnowledgeItem[] {
  const byPrinciple = items.filter((it) => relIds.includes(it.provenance.principle_id));
  return (byPrinciple.length ? byPrinciple : items).slice(0, max);
}

// --- senior tip embedded in a lens item ------------------------------------
function SeniorTip({ raw, label }: { raw: string; label: string }) {
  const m = raw.match(SENIOR_RE);
  if (!m) return <span>{raw}</span>;
  const [, srcs, conf, tip] = m;
  const ids = srcs.split("・").map((s) => s.trim()).filter((s) => s && s !== "—");
  return (
    <div className="rounded-lg border border-primary/20 bg-primary/[0.04] p-3">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.06em] text-primary">
          <Sparkles className="h-3 w-3" /> {label}
        </span>
        <SourceChips ids={ids} />
        <ConfidenceBadge level={(conf.trim() as Confidence) || "unverified"} />
      </div>
      <p className="font-jp text-[13px] leading-relaxed text-foreground/90">{tip}</p>
    </div>
  );
}

// --- one of the six lenses, collapsible ------------------------------------
function LensSection({
  meta, items, seniorLabel, lang,
}: {
  meta: { key: string; ja: string; en: string; icon: string };
  items: string[];
  seniorLabel: string;
  lang: "ja" | "en";
}) {
  const Icon = ICONS[meta.icon] ?? Lightbulb;
  const tone = TONES[meta.key] ?? "text-primary bg-primary/10";
  const count = items.length;
  return (
    <AccordionItem value={meta.key} className="border-b-0">
      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
        <AccordionTrigger className="px-4 py-3 hover:no-underline hover:text-foreground">
          <span className="flex items-center gap-2.5">
            <span className={cn("flex h-7 w-7 items-center justify-center rounded-lg", tone)}>
              <Icon className="h-4 w-4" />
            </span>
            <span className={cn("text-[14px] font-medium text-foreground", lang === "ja" && "font-jp")}>
              {lang === "ja" ? meta.ja : meta.en}
            </span>
            <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">{count}</span>
          </span>
        </AccordionTrigger>
        <AccordionContent className="px-4">
          <ul className="space-y-2.5">
            {count === 0 && <li className="text-[13px] text-muted-foreground">—</li>}
            {items.map((it, i) =>
              it.startsWith("先輩の知見") ? (
                <li key={i}><SeniorTip raw={it} label={seniorLabel} /></li>
              ) : (
                <li key={i} className="flex gap-2.5 font-jp text-[13.5px] leading-relaxed text-foreground/90">
                  <span className={cn("mt-[7px] h-1 w-1 shrink-0 rounded-full", tone.split(" ")[0], "bg-current")} />
                  <span>{it}</span>
                </li>
              ),
            )}
          </ul>
        </AccordionContent>
      </div>
    </AccordionItem>
  );
}

// --- relevant principle with expandable provenance -------------------------
function PrincipleRef({ p }: { p: Principle }) {
  const { t, lang } = useT();
  const st = principleText(lang, p);
  return (
    <AccordionItem value={p.principle_id} className="border-b-0">
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <AccordionTrigger className="gap-3 px-4 py-3 hover:no-underline">
          <span className="flex flex-1 flex-col gap-1.5 text-left">
            <span className="flex items-center gap-2">
              <span className="font-mono text-[11px] text-muted-foreground">{p.principle_id}</span>
              <ConfidenceBadge level={principleConfidence(p)} />
            </span>
            <span className={cn("text-[13.5px] font-medium leading-snug text-foreground/90", lang === "ja" && "font-jp")}>
              {st.text}
            </span>
            <span className="flex flex-wrap gap-1">
              {p.tags.slice(0, 3).map((tg) => (
                <Badge key={tg} variant="default">#{tagText(lang, tg).text}</Badge>
              ))}
            </span>
          </span>
        </AccordionTrigger>
        <AccordionContent className="px-4">
          <div className="border-t border-border pt-4">
            <ProvenanceList citations={p.support} />
          </div>
          <Link
            href="/junior/knowledge"
            className="mt-4 inline-flex items-center gap-1 text-[12px] font-medium text-primary hover:underline"
          >
            {t("chat.viewPrinciples")} <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </AccordionContent>
      </div>
    </AccordionItem>
  );
}

// --- lightweight markdown for the senior's narration -----------------------
function inlineBold(s: string) {
  return s.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**")
      ? <strong key={i} className="font-semibold text-foreground">{p.slice(2, -2)}</strong>
      : <span key={i}>{p}</span>,
  );
}

function NarrationMd({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  return (
    <div className="space-y-1.5 font-jp text-[13.5px] leading-relaxed text-foreground/90">
      {lines.map((ln, i) => {
        const tx = ln.trim();
        if (!tx) return <div key={i} className="h-1" />;
        if (/^---+$/.test(tx)) return <div key={i} className="my-1 border-t border-border" />;
        if (/^#{1,6}\s/.test(tx)) {
          return (
            <h4 key={i} className="pt-2 text-[12px] font-semibold uppercase tracking-[0.04em] text-primary">
              {tx.replace(/^#{1,6}\s+/, "")}
            </h4>
          );
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

// --- the structured coaching response --------------------------------------
function CoachingCard({
  resp, note, live, principles, items,
}: {
  resp: CoachResponse; note: string; live: boolean;
  principles: Principle[]; items: KnowledgeItem[];
}) {
  const { t, lang } = useT();
  const [showSimilar, setShowSimilar] = useState(false);
  const [narr, setNarr] = useState<string | null>(null);
  const [narrModel, setNarrModel] = useState<string | null>(null);
  const [narrating, setNarrating] = useState(false);
  const [narrTried, setNarrTried] = useState(false);
  const [thinking, setThinking] = useState(false);
  const rel = relevantPrinciples(note, principles);

  async function explain() {
    if (narrating) return;
    setNarrating(true);
    setThinking(true);
    let acc = "";
    let model: string | null = null;
    await narrateStream(note, undefined, (e) => {
      switch (e.type) {
        case "start":
          model = e.model ?? null;
          setNarrModel(model);
          break;
        case "thinking":
          setThinking(true);
          break;
        case "delta":
          setThinking(false);
          acc += e.text;
          setNarr(acc);
          break;
        case "done":
          model = e.model ?? model;
          setNarrModel(model);
          break;
        // fallback | unavailable | error → acc stays empty → fallback message
      }
    });
    setThinking(false);
    setNarrTried(true);
    setNarrating(false);
    if (!acc) setNarr(null);
  }
  const relIds = rel.map((p) => p.principle_id);
  const similar = similarItems(relIds, items);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-primary/25 bg-primary/[0.03] px-4 py-2.5">
        <span className="text-[12.5px] leading-relaxed text-foreground/80">
          <span className="font-semibold text-primary">{t("coach.teachLead")}</span> — {t("coach.teach")}
        </span>
        <LiveBadge live={live} />
      </div>

      {/* 1–6: the six lenses, each collapsible */}
      <div>
        <div className="eyebrow mb-2 flex items-center gap-1.5"><Layers className="h-3.5 w-3.5" /> {t("chat.lenses")}</div>
        <Accordion type="multiple" defaultValue={["observations", "missing_info", "risks"]} className="space-y-2.5">
          {resp.sections.map((meta) => (
            <LensSection
              key={meta.key}
              meta={meta}
              items={resp.result[meta.key] ?? []}
              seniorLabel={t("coach.seniorDrawer")}
              lang={lang}
            />
          ))}
        </Accordion>
      </div>

      {/* The senior's explanation — on-demand, streamed token-by-token */}
      <div>
        {!narrTried && !narrating && (
          <button
            onClick={explain}
            className="flex w-full items-center justify-between gap-3 rounded-xl border border-primary/25 bg-primary/[0.03] px-4 py-3 text-left transition-colors hover:bg-primary/[0.06]"
          >
            <span className="flex items-center gap-2.5">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-primary"><Bot className="h-4 w-4" /></span>
              <span>
                <span className="flex items-center gap-1.5 text-[14px] font-medium text-foreground">
                  {t("chat.explain")}
                  <span className="rounded bg-primary/10 px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-primary">AI</span>
                </span>
                <span className="text-[11.5px] leading-snug text-muted-foreground">{t("chat.explainHint")}</span>
              </span>
            </span>
            <ArrowRight className="h-4 w-4 text-primary" />
          </button>
        )}

        {(narrating || narr) && (
          <div className="animate-fade-up rounded-xl border border-primary/25 bg-primary/[0.02] p-5">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.06em] text-primary">
                <Bot className="h-3.5 w-3.5" /> {t("chat.explainTitle")}
                {narrating && (
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
                )}
              </span>
              {narrModel && (
                <span className="rounded-full bg-muted px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                  {t("chat.poweredBy", { model: narrModel })}
                </span>
              )}
            </div>
            {narr ? (
              <NarrationMd text={narr} />
            ) : (
              <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
                <span className="flex gap-1">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.3s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.15s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary" />
                </span>
                {thinking ? t("chat.thinking") : t("chat.explaining")}
              </div>
            )}
          </div>
        )}

        {narrTried && !narrating && !narr && (
          <div className="rounded-xl border border-dashed border-border bg-muted/30 p-4 text-[13px] text-muted-foreground">
            {t("chat.explainUnavailable")}
          </div>
        )}
      </div>

      {/* 6: relevant principles + 7: provenance (expandable) */}
      <div>
        <div className="eyebrow mb-2 flex items-center gap-1.5"><BookMarked className="h-3.5 w-3.5" /> {t("chat.relevantPrinciples")}</div>
        {rel.length ? (
          <Accordion type="multiple" defaultValue={rel[0] ? [rel[0].principle_id] : []} className="space-y-2.5">
            {rel.map((p) => <PrincipleRef key={p.principle_id} p={p} />)}
          </Accordion>
        ) : (
          <div className="rounded-xl border border-dashed border-border bg-muted/30 p-4 text-[13px] text-muted-foreground">
            {t("chat.noPrinciples")}
          </div>
        )}
      </div>

      {/* similar situations (revealed on demand) */}
      {showSimilar && similar.length > 0 && (
        <div className="animate-fade-up">
          <div className="eyebrow mb-2 flex items-center gap-1.5"><Layers className="h-3.5 w-3.5" /> {t("chat.similarTitle")}</div>
          <div className="grid gap-2.5 sm:grid-cols-2">
            {similar.map((it) => {
              const sc = principleText(lang, { principle_id: it.provenance.principle_id, statement: it.principle_statement });
              return (
                <Link
                  key={it.item_id}
                  href="/junior/knowledge"
                  className="rounded-xl border border-border bg-card p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-colors hover:bg-muted/40"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[11px] text-muted-foreground">{it.item_id}</span>
                    <ConfidenceBadge level={it.confidence} />
                  </div>
                  <p className={cn("mt-2 line-clamp-3 text-[12.5px] leading-snug text-foreground/85", lang === "ja" && "font-jp")}>
                    {sc.text}
                  </p>
                </Link>
              );
            })}
          </div>
        </div>
      )}

      {/* follow-up actions */}
      <div className="rounded-xl border border-border bg-muted/30 p-3">
        <div className="eyebrow mb-2">{t("chat.followUps")}</div>
        <div className="flex flex-wrap gap-2">
          <FollowUp icon={RotateCcw} label={t("chat.reviewAnother")} onClick={() => window.dispatchEvent(new CustomEvent("senpai:review-another"))} />
          <FollowUp icon={Layers} label={t("chat.similar")} active={showSimilar} onClick={() => setShowSimilar((v) => !v)} />
          <Link
            href="/junior/knowledge"
            className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-[12.5px] font-medium text-foreground transition-colors hover:border-primary/40 hover:text-primary"
          >
            <BookMarked className="h-3.5 w-3.5" /> {t("chat.viewPrinciples")}
          </Link>
        </div>
      </div>
    </div>
  );
}

function FollowUp({ icon: Icon, label, onClick, active }: { icon: LucideIcon; label: string; onClick: () => void; active?: boolean }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12.5px] font-medium transition-colors",
        active ? "border-primary/40 bg-primary/[0.06] text-primary" : "border-border bg-card text-foreground hover:border-primary/40 hover:text-primary",
      )}
    >
      <Icon className="h-3.5 w-3.5" /> {label}
    </button>
  );
}

// --- message model ---------------------------------------------------------
type Msg =
  | { id: number; role: "senpai"; kind: "intro" }
  | { id: number; role: "senpai"; kind: "prompt"; text: string }
  | { id: number; role: "user"; kind: "note"; note: string; dealLabel?: string }
  | { id: number; role: "senpai"; kind: "loading" }
  | { id: number; role: "senpai"; kind: "coaching"; note: string; resp: CoachResponse; live: boolean };

function Avatar({ who }: { who: "senpai" | "user" }) {
  return who === "senpai" ? (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-navy text-white">
      <GraduationCap className="h-[18px] w-[18px]" />
    </div>
  ) : (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
      <UserRound className="h-[18px] w-[18px]" />
    </div>
  );
}

function Row({ who, name, children }: { who: "senpai" | "user"; name: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <Avatar who={who} />
      <div className="min-w-0 flex-1 space-y-2">
        <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">{name}</div>
        {children}
      </div>
    </div>
  );
}

export function CoachChat({
  examples, deals, principles, items,
}: {
  examples: CoachExample[]; deals: DealRow[]; principles: Principle[]; items: KnowledgeItem[];
}) {
  const { t, lang } = useT();
  const [messages, setMessages] = useState<Msg[]>([{ id: 0, role: "senpai", kind: "intro" }]);
  const [note, setNote] = useState("");
  const [dealId, setDealId] = useState("");
  const [busy, setBusy] = useState(false);
  const idRef = useRef(1);
  const bottomRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);

  const nextId = () => idRef.current++;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  useEffect(() => {
    const onAnother = () => {
      setMessages((m) => [...m, { id: nextId(), role: "senpai", kind: "prompt", text: t("chat.nextPrompt") }]);
      composerRef.current?.focus();
    };
    window.addEventListener("senpai:review-another", onAnother);
    return () => window.removeEventListener("senpai:review-another", onAnother);
  }, [t]);

  async function submit(text: string, deal: string) {
    const clean = text.trim();
    if (!clean || busy) return;
    const dealLabel = deal ? deals.find((d) => d.deal_id === deal)?.customer : undefined;
    const loadingId = nextId();
    setMessages((m) => [
      ...m,
      { id: nextId(), role: "user", kind: "note", note: clean, dealLabel },
      { id: loadingId, role: "senpai", kind: "loading" },
    ]);
    setNote("");
    setDealId("");
    setBusy(true);
    const { data, live } = await api.coach(clean, deal || undefined);
    setMessages((m) =>
      m.map((msg) =>
        msg.id === loadingId
          ? { id: loadingId, role: "senpai", kind: "coaching", note: clean, resp: data, live }
          : msg,
      ),
    );
    setBusy(false);
  }

  return (
    <div className="mx-auto flex min-h-[calc(100vh-9rem)] max-w-3xl flex-col">
      {/* transcript */}
      <div className="flex-1 space-y-8 pb-6">
        {messages.map((m) => {
          if (m.role === "user") {
            return (
              <Row key={m.id} who="user" name={t("chat.you")}>
                <div className="rounded-xl rounded-tl-sm border border-border bg-card p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
                  {m.dealLabel && (
                    <Badge variant="accent" className="mb-2 font-jp">{m.dealLabel}</Badge>
                  )}
                  <p className="whitespace-pre-wrap font-jp text-[13.5px] leading-relaxed text-foreground/90">{m.note}</p>
                </div>
              </Row>
            );
          }
          if (m.kind === "intro") {
            return (
              <Row key={m.id} who="senpai" name={t("chat.senpai")}>
                <div className="rounded-xl rounded-tl-sm border border-border bg-card p-5 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
                  <h2 className="text-[16px] font-semibold tracking-tight">{t("chat.greeting.title")}</h2>
                  <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">{t("chat.greeting")}</p>
                  <div className="mt-4">
                    <div className="eyebrow mb-2">{t("chat.startExample")}</div>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {examples.map((ex) => (
                        <button
                          key={ex.title}
                          disabled={busy}
                          onClick={() => submit(ex.note, "")}
                          className="rounded-lg border border-border bg-card px-3 py-2.5 text-left transition-colors hover:border-primary/40 hover:bg-primary/[0.03] disabled:opacity-50"
                        >
                          <div className="flex items-center gap-1.5">
                            <Sparkles className="h-3.5 w-3.5 text-primary" />
                            <span className="font-jp text-[13px] font-medium text-foreground">{ex.title}</span>
                          </div>
                          <div className="mt-0.5 font-jp text-[11px] leading-snug text-muted-foreground">{ex.hint}</div>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </Row>
            );
          }
          if (m.kind === "prompt") {
            return (
              <Row key={m.id} who="senpai" name={t("chat.senpai")}>
                <div className="rounded-xl rounded-tl-sm border border-border bg-card p-4 text-[13.5px] leading-relaxed text-foreground/90 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
                  {m.text}
                </div>
              </Row>
            );
          }
          if (m.kind === "loading") {
            return (
              <Row key={m.id} who="senpai" name={t("chat.senpai")}>
                <div className="inline-flex items-center gap-2 rounded-xl rounded-tl-sm border border-border bg-card px-4 py-3 text-[13px] text-muted-foreground shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
                  <span className="flex gap-1">
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.3s]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.15s]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary" />
                  </span>
                  {t("chat.thinking")}
                </div>
              </Row>
            );
          }
          return (
            <Row key={m.id} who="senpai" name={t("chat.senpai")}>
              <CoachingCard resp={m.resp} note={m.note} live={m.live} principles={principles} items={items} />
            </Row>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {/* composer */}
      <div className="sticky bottom-0 -mx-1 border-t border-border bg-background/85 px-1 pb-4 pt-3 backdrop-blur">
        <div className="rounded-2xl border border-border bg-card p-2.5 shadow-[0_8px_30px_-22px_rgba(16,24,40,0.45)] focus-within:border-primary/40">
          <Textarea
            ref={composerRef}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(note, dealId);
              }
            }}
            placeholder={t("chat.placeholder")}
            className="min-h-[64px] resize-none border-0 bg-transparent font-jp shadow-none focus-visible:ring-0"
          />
          <div className="flex items-center justify-between gap-2 px-1 pt-1">
            <select
              value={dealId}
              onChange={(e) => setDealId(e.target.value)}
              className="h-8 max-w-[60%] rounded-lg border border-input bg-card px-2 text-[12px] text-muted-foreground shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="">{t("coach.none")}</option>
              {deals.map((d) => (
                <option key={d.deal_id} value={d.deal_id}>{d.deal_id} · {d.customer}</option>
              ))}
            </select>
            <Button variant="seal" size="sm" disabled={busy || !note.trim()} onClick={() => submit(note, dealId)} className="gap-1.5">
              {t("chat.send")} <CornerDownLeft className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
