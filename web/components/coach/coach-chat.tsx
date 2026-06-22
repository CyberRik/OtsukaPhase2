"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BookMarked,
  Bot,
  ChevronDown,
  CornerDownLeft,
  Database,
  Eye,
  Award,
  Building2,
  ExternalLink,
  Globe,
  GraduationCap,
  History,
  Languages,
  Layers,
  Lightbulb,
  XCircle,
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
import { api, narrateStream, chatStream, type ChatEvent } from "@/lib/api";
import type {
  CoachExample,
  CoachResponse,
  Confidence,
  DealRow,
  KnowledgeItem,
  Principle,
  SimilarCase,
} from "@/lib/types";
import { cn, formatYen } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import {
  PRINCIPLE_KEYWORDS, buildTipMap, pickText,
  customerText, productCategoryText, principleText, tagText, coachLineText, coachExampleText,
} from "@/lib/content-i18n";
import { JpOriginalBadge } from "@/components/jp-original-badge";
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
// The "出典/確度" chrome is parsed into chips; only the tip body is content that
// needs translating. We translate it from approved knowledge items (tipMap);
// when no mapping exists we keep the JA original and flag it with a badge.
function SeniorTip({
  raw, label, lang, tipMap,
}: {
  raw: string; label: string; lang: "ja" | "en"; tipMap: Record<string, string>;
}) {
  const m = raw.match(SENIOR_RE);
  if (!m) {
    const cl = coachLineText(lang, raw);
    return <span className="text-[13px] leading-relaxed text-foreground/90">{cl.text}{cl.fallback && <JpOriginalBadge />}</span>;
  }
  const [, srcs, conf, tip] = m;
  const ids = srcs.split("・").map((s) => s.trim()).filter((s) => s && s !== "—");
  const tipLoc = pickText(lang, tip, tipMap[tip]);
  return (
    <div className="rounded-lg border border-primary/20 bg-primary/[0.04] p-3">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.06em] text-primary">
          <Sparkles className="h-3 w-3" /> {label}
        </span>
        <SourceChips ids={ids} />
        <ConfidenceBadge level={(conf.trim() as Confidence) || "unverified"} />
      </div>
      <span className="text-[13px] leading-relaxed text-foreground/90 block">
        {tipLoc.text}{tipLoc.fallback && <JpOriginalBadge />}
      </span>
    </div>
  );
}

// --- one of the six lenses, collapsible ------------------------------------
function LensSection({
  meta, items, seniorLabel, lang, tipMap,
}: {
  meta: { key: string; ja: string; en: string; icon: string };
  items: string[];
  seniorLabel: string;
  lang: "ja" | "en";
  tipMap: Record<string, string>;
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
            {items.map((it, i) => {
              if (it.startsWith("先輩の知見")) {
                return <li key={i}><SeniorTip raw={it} label={seniorLabel} lang={lang} tipMap={tipMap} /></li>;
              }
              const cl = coachLineText(lang, it);
              return (
                <li key={i} className="flex gap-2.5 text-[13.5px] leading-relaxed text-foreground/90">
                  <span className={cn("mt-[7px] h-1 w-1 shrink-0 rounded-full", tone.split(" ")[0], "bg-current")} />
                  <span className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                    {cl.text}{cl.fallback && <JpOriginalBadge />}
                  </span>
                </li>
              );
            })}
          </ul>
        </AccordionContent>
      </div>
    </AccordionItem>
  );
}

// --- relevant principle with expandable provenance -------------------------
function PrincipleRef({ p }: { p: Principle }) {
  const { t, lang } = useT();
  return (
    <AccordionItem value={p.principle_id} className="border-b-0">
      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <AccordionTrigger className="gap-3 px-4 py-3 hover:no-underline">
          <span className="flex flex-1 flex-col gap-1.5 text-left">
            <span className="flex items-center gap-2">
              <span className="font-mono text-[11px] text-muted-foreground">{p.principle_id}</span>
              <ConfidenceBadge level={principleConfidence(p)} />
            </span>
            <span className="text-[13.5px] font-medium leading-snug text-foreground/90 block">{principleText(lang, p).text}</span>
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

// --- Similar Past Cases (Pillar 2: Experience) -----------------------------
// Real closed deals that rhyme with the current note, each tagged with its
// outcome and the validated principle it teaches. Grounded in the store; the
// "lesson" is an approved, interview-traceable principle, never invented advice.
function CaseCard({ c, principles }: { c: SimilarCase; principles: Principle[] }) {
  const { t, lang } = useT();
  const won = c.outcome === "won";
  const lessons = c.principle_ids
    .map((id) => principles.find((p) => p.principle_id === id))
    .filter((p): p is Principle => Boolean(p));
  return (
    <div className={cn(
      "overflow-hidden rounded-xl border bg-card shadow-[0_1px_2px_rgba(16,24,40,0.04)]",
      won ? "border-conf-high/30" : "border-band-red/30",
    )}>
      <div className={cn(
        "flex items-center justify-between gap-2 px-4 py-2.5",
        won ? "bg-conf-high/[0.06]" : "bg-band-red/[0.05]",
      )}>
        <span className="flex items-center gap-2">
          <span className={cn(
            "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
            won ? "bg-conf-high/15 text-conf-high" : "bg-band-red/15 text-band-red",
          )}>
            {won ? <Award className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
            {won ? t("chat.caseWon") : t("chat.caseLost")}
          </span>
          <span className="font-mono text-[10px] text-muted-foreground">{c.deal_id}</span>
        </span>
        <span className="text-[11px] text-muted-foreground">{formatYen(c.amount)}</span>
      </div>
      <div className="px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-jp text-[13px] font-medium text-foreground">{customerText(lang, c.customer).text}</span>
          <Badge variant="default">{productCategoryText(lang, c.product_category).text}</Badge>
        </div>
        <p className={cn("mt-1.5 text-[13px] leading-snug text-foreground/85", lang === "ja" && "font-jp")}>
          {t(`chat.caseTheme.${c.theme}`)}
        </p>
        {lessons.length > 0 && (
          <div className="mt-3 border-t border-border pt-2.5">
            <div className="eyebrow mb-1.5 flex items-center gap-1"><Lightbulb className="h-3 w-3" /> {t("chat.caseLessons")}</div>
            <ul className="space-y-1.5">
              {lessons.map((p) => {
                return (
                  <li key={p.principle_id} className="flex gap-2">
                    <span className="mt-[3px] font-mono text-[10px] text-muted-foreground">{p.principle_id}</span>
                    <span className="flex-1 text-[12.5px] leading-snug text-foreground/85">
                      {principleText(lang, p).text}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function SimilarCases({ note, principles }: { note: string; principles: Principle[] }) {
  const { t } = useT();
  const [cases, setCases] = useState<SimilarCase[] | null>(null);

  useEffect(() => {
    let alive = true;
    api.similarCases(note).then(({ data }) => { if (alive) setCases(data.cases); });
    return () => { alive = false; };
  }, [note]);

  return (
    <div>
      <div className="eyebrow mb-1 flex items-center gap-1.5"><History className="h-3.5 w-3.5" /> {t("chat.similarCases")}</div>
      <p className="mb-2.5 text-[11.5px] text-muted-foreground">{t("chat.similarCasesSub")}</p>
      {cases === null ? (
        <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-3 text-[13px] text-muted-foreground">
          <span className="flex gap-1">
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.3s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.15s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary" />
          </span>
          {t("chat.caseLoading")}
        </div>
      ) : cases.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-muted/30 p-4 text-[13px] text-muted-foreground">
          {t("chat.caseNone")}
        </div>
      ) : (
        <div className="grid gap-2.5">
          {cases.map((c) => <CaseCard key={c.deal_id} c={c} principles={principles} />)}
        </div>
      )}
    </div>
  );
}

// --- the structured coaching response --------------------------------------
function CoachingCard({
  resp, note, live, dealId, principles, items,
}: {
  resp: CoachResponse; note: string; live: boolean; dealId?: string;
  principles: Principle[]; items: KnowledgeItem[];
}) {
  const { t, lang } = useT();
  const [showSimilar, setShowSimilar] = useState(false);
  const [showJa, setShowJa] = useState(false);
  const [narr, setNarr] = useState<string | null>(null);
  const [narrModel, setNarrModel] = useState<string | null>(null);
  const [narrGrounded, setNarrGrounded] = useState<string | null>(null);
  const [narrating, setNarrating] = useState(false);
  const [narrTried, setNarrTried] = useState(false);
  const [thinking, setThinking] = useState(false);
  // The senior commentary is dynamic model output, so in English mode we
  // generate it in English and lazily fetch the JA original on demand.
  const [narrJa, setNarrJa] = useState<string | null>(null);
  const [narrJaShown, setNarrJaShown] = useState(false);
  const [narrJaLoading, setNarrJaLoading] = useState(false);
  // AI-first: the deterministic six lenses are demoted to a collapsible
  // "supporting evidence" panel, hidden by default.
  const [showEvidence, setShowEvidence] = useState(false);
  const rel = relevantPrinciples(note, principles);
  const tipMap = buildTipMap(items);

  async function explain() {
    if (narrating) return;
    setNarrating(true);
    setThinking(true);
    let acc = "";
    let model: string | null = null;
    await narrateStream(note, dealId, (e) => {
      switch (e.type) {
        case "start":
          model = e.model ?? null;
          setNarrModel(model);
          break;
        case "context":
          setNarrGrounded(e.grounded ? (e.customer ?? null) : null);
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
    }, { lang });
    setThinking(false);
    setNarrTried(true);
    setNarrating(false);
    if (!acc) setNarr(null);
  }

  // Lazily stream the Japanese original of the commentary (English mode only),
  // so the source text stays inspectable without a second call up front.
  async function toggleNarrJa() {
    if (narrJa || narrJaShown) { setNarrJaShown((v) => !v); return; }
    setNarrJaShown(true);
    setNarrJaLoading(true);
    let acc = "";
    await narrateStream(note, dealId, (e) => {
      if (e.type === "delta") { acc += e.text; setNarrJa(acc); }
    }, { lang: "ja" });
    setNarrJaLoading(false);
    if (!acc) setNarrJa(null);
  }

  // AI-first: stream the senior's read as soon as the coaching card mounts,
  // so the grounded interpretation — not the deterministic checklist — leads.
  useEffect(() => {
    explain();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

      {/* Senior's read (AI) — primary, grounded in the corpus + deal record,
          streamed as soon as the card mounts. */}
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
              <span className="flex items-center gap-1.5">
                {narrGrounded && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-conf-high/10 px-2 py-0.5 text-[10px] font-medium text-conf-high">
                    <Database className="h-2.5 w-2.5" /> {t("chat.groundedIn", { customer: narrGrounded })}
                  </span>
                )}
                {narrModel && (
                  <span className="rounded-full bg-muted px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                    {t("chat.poweredBy", { model: narrModel })}
                  </span>
                )}
              </span>
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

            {/* English commentary: the JA original, generated on demand */}
            {lang === "en" && narr && !narrating && (
              <div className="mt-4 border-t border-border pt-3">
                <button
                  onClick={toggleNarrJa}
                  className="inline-flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground transition-colors hover:text-primary"
                >
                  <Languages className="h-3.5 w-3.5" />
                  {narrJaShown ? t("chat.hideJa") : t("chat.viewJaCommentary")}
                </button>
                {narrJaShown && (
                  <div className="animate-fade-up mt-2.5 rounded-lg border border-dashed border-border bg-muted/30 p-3">
                    {narrJaLoading && !narrJa ? (
                      <div className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
                        <span className="flex gap-1">
                          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.3s]" />
                          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.15s]" />
                          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary" />
                        </span>
                        {t("chat.commentaryJaLoading")}
                      </div>
                    ) : narrJa ? (
                      <NarrationMd text={narrJa} />
                    ) : (
                      <p className="text-[12.5px] text-muted-foreground">{t("chat.explainUnavailable")}</p>
                    )}
                  </div>
                )}
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

      {/* Supporting evidence — the deterministic six-lens checklist, demoted to a
          collapsible panel (it's the trust layer beneath the senior's read). */}
      <div>
        <button
          onClick={() => setShowEvidence((v) => !v)}
          className="flex w-full items-center justify-between gap-2 rounded-xl border border-border bg-card px-4 py-2.5 text-left transition-colors hover:border-primary/40"
        >
          <span className="flex items-center gap-1.5 text-[13px] font-medium text-foreground">
            <Layers className="h-3.5 w-3.5 text-muted-foreground" /> {t("chat.supportingEvidence")}
          </span>
          <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", showEvidence && "rotate-180")} />
        </button>
        {showEvidence && (
          <div className="animate-fade-up mt-3">
            <Accordion type="multiple" defaultValue={["observations", "missing_info", "risks"]} className="space-y-2.5">
              {resp.sections.map((meta) => (
                <LensSection
                  key={meta.key}
                  meta={meta}
                  items={resp.result[meta.key] ?? []}
                  seniorLabel={t("coach.seniorDrawer")}
                  lang={lang}
                  tipMap={tipMap}
                />
              ))}
            </Accordion>

            {/* English mode: keep the JA source one click away (provenance) */}
            {lang === "en" && (
              <div className="mt-2.5">
                <button
                  onClick={() => setShowJa((v) => !v)}
                  className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-[12px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
                >
                  <Languages className="h-3.5 w-3.5" />
                  {showJa ? t("chat.hideJa") : t("chat.viewJa")}
                </button>
                {showJa && (
                  <div className="animate-fade-up mt-2.5 rounded-xl border border-dashed border-border bg-muted/30 p-4">
                    <div className="eyebrow mb-2">{t("chat.jaOriginalTitle")}</div>
                    <p className="mb-3 text-[11.5px] leading-snug text-muted-foreground">{t("chat.jaOriginalHint")}</p>
                    <div className="space-y-3">
                      {resp.sections.map((meta) => {
                        const its = resp.result[meta.key] ?? [];
                        if (!its.length) return null;
                        return (
                          <div key={meta.key}>
                            <div className="font-jp text-[12.5px] font-semibold text-foreground/80">{meta.ja}</div>
                            <ul className="mt-1 space-y-1">
                              {its.map((it, i) => (
                                <li key={i} className="flex gap-2 font-jp text-[12.5px] leading-relaxed text-foreground/75">
                                  <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-current" />
                                  <span>{it}</span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Similar past cases — Pillar 2: Experience */}
      <SimilarCases note={note} principles={principles} />

      {/* Relevant principles + provenance (the corpus the read draws on) */}
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
                  <span className="mt-2 line-clamp-3 text-[12.5px] leading-snug text-foreground/85 block">
                    {principleText(lang, { principle_id: it.provenance.principle_id, statement: it.principle_statement }).text}
                  </span>
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

// --- intent routing: research question vs. note coaching --------------------
// Review Coach stays a coaching surface (notes / reports / opportunity reviews).
// Only clearly research-style *questions about a customer* divert to the
// tool-calling assistant — so this never becomes a generic chatbot. Triggers are
// deliberately narrow (phrasings that don't occur in a pasted daily report), and
// long text is treated as a note. A deal attached to the message always = coaching.
const RESEARCH_TRIGGERS: RegExp[] = [
  /tell me about/i,
  /\bresearch\b/i,
  /what (do|does) .*(company|customer|client|they|it) do/i,
  /who are (their|the)\b/i,
  /what should i know/i,
  /before (approaching|i approach|contacting|the meeting|the call|reaching out)/i,
  /background on/i,
  /find out about/i,
  /について教えて/, /を調べて/, /について調べ/, /どんな(会社|企業)/,
  /知っておくべき/, /リサーチ/, /訪問前/, /事業内容/,
  /競合(を教え|は誰|はどこ|を調べ|について教え)/,
];

function isResearchQuestion(text: string): boolean {
  if (text.length > 220) return false; // long = a pasted note → coaching
  return RESEARCH_TRIGGERS.some((re) => re.test(text));
}

// Friendly labels for the tools the research assistant calls.
const TOOL_LABEL: Record<string, { ja: string; en: string; icon: LucideIcon }> = {
  query_spr: { ja: "社内の顧客・案件", en: "Internal records", icon: Database },
  find_similar_deals: { ja: "類似案件", en: "Similar deals", icon: Layers },
  score_deal_health: { ja: "案件健全度", en: "Deal health", icon: AlertTriangle },
  lookup_customer_environment: { ja: "IT環境", en: "IT environment", icon: Building2 },
  get_product_info: { ja: "製品情報", en: "Product info", icon: BookMarked },
  get_seasonal_context: { ja: "時期・予算", en: "Seasonal context", icon: History },
  web_search: { ja: "Web検索", en: "Web search", icon: Globe },
};

type ResearchSourceStatus = "pending" | "found" | "not_found" | "ambiguous" | "skipped" | "error";
type ResearchSourceState = {
  key: string;
  label: string;
  status: ResearchSourceStatus;
  count?: number;
  detail?: string;
};

const RESEARCH_SOURCES: ResearchSourceState[] = [
  { key: "internal_records", label: "Internal Records", status: "pending" },
  { key: "deals", label: "Deals", status: "pending" },
  { key: "activities", label: "Activities", status: "pending" },
  { key: "environment", label: "Environment", status: "pending" },
  { key: "web_search", label: "Web Search", status: "pending" },
];

function sourceStatusLabel(status: ResearchSourceStatus) {
  switch (status) {
    case "found": return "Found";
    case "not_found": return "Not Found";
    case "ambiguous": return "Ambiguous";
    case "error": return "Error";
    case "skipped": return "Skipped";
    default: return "Checking";
  }
}

function sourceStatusClass(status: ResearchSourceStatus) {
  switch (status) {
    case "found": return "bg-conf-high/10 text-conf-high";
    case "ambiguous": return "bg-band-yellow/10 text-band-yellow";
    case "error": return "bg-band-red/10 text-band-red";
    case "not_found":
    case "skipped":
      return "bg-muted text-muted-foreground";
    default:
      return "bg-navy/10 text-navy";
  }
}

// --- Customer Research card (deterministic orchestration, single-turn) -------
// Streams /api/chat with role="research": the model resolves the customer
// (alias-aware), checks internal records FIRST, then web-searches only to fill
// gaps. We surface the tools it consulted and any web sources, so the answer is
// auditable — a grounded research read, not a free chatbot reply.
function ResearchCard({ note }: { note: string }) {
  const { t, lang } = useT();
  const [sources, setSources] = useState<ResearchSourceState[]>(RESEARCH_SOURCES);
  const [web, setWeb] = useState<{ results?: { title?: string; url?: string; content?: string }[] } | null>(null);
  const [answer, setAnswer] = useState("");
  const [model, setModel] = useState<string | null>(null);
  const [status, setStatus] = useState<"running" | "done" | "error">("running");
  const [unavailable, setUnavailable] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const ctrl = new AbortController();
    let acc = "";
    setSources(RESEARCH_SOURCES);
    setWeb(null);
    setAnswer("");
    setUnavailable(null);
    setStatus("running");
    chatStream(
      note,
      [],            // single-turn: each research question stands alone (not a chat)
      "research",
      (e: ChatEvent) => {
        if (!alive) return;
        switch (e.type) {
          case "start":
            setModel(e.model ?? null);
            break;
          case "source":
            setSources((prev) =>
              prev.map((src) =>
                src.key === e.key
                  ? { ...src, label: e.label || src.label, status: e.status, count: e.count, detail: e.detail }
                  : src,
              ),
            );
            break;
          case "web":
            setWeb(e);
            break;
          case "answer":
            acc = e.text;
            setAnswer(acc);
            break;
          case "unavailable":
            setUnavailable(e.reason ?? "unavailable");
            break;
          case "done":
            setModel(e.model ?? model);
            break;
          // error → handled after the stream resolves
        }
      },
      { signal: ctrl.signal },
    ).then(() => {
      if (!alive) return;
      const ok = acc.trim() && acc.trim() !== "(no response)";
      setStatus(ok ? "done" : "error");
    });
    return () => { alive = false; ctrl.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [note]);

  const webSourceUrls = (web?.results ?? [])
    .map((r) => r.url)
    .filter((u): u is string => Boolean(u));
  const tools = webSourceUrls.length
    ? [{ name: "web_search", args: "", result: webSourceUrls.join(" ") }]
    : [];

  // Surface web sources (URLs) pulled by web_search, for citation.
  const webUrls = Array.from(
    new Set(
      tools
        .filter((tl) => tl.name === "web_search")
        .flatMap((tl) => tl.result.match(/https?:\/\/[^\s)）]+/g) ?? []),
    ),
  );

  return (
    <div className="space-y-3 rounded-xl border border-navy/25 bg-navy/[0.02] p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.06em] text-navy">
          <Search className="h-3.5 w-3.5" /> {t("chat.researchTitle")}
          <span className="rounded bg-navy/10 px-1 py-0.5 text-[9px] font-semibold tracking-wide text-navy">AI</span>
          {status === "running" && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-navy" />}
        </span>
        {model && (
          <span className="rounded-full bg-muted px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
            {t("chat.poweredBy", { model })}
          </span>
        )}
      </div>
      <p className="text-[11.5px] leading-snug text-muted-foreground">{t("chat.researchHint")}</p>

      <div className="rounded-lg border border-border bg-card p-3">
        <div className="eyebrow mb-1.5 flex items-center gap-1.5"><Database className="h-3 w-3" /> {t("chat.researchSources")}</div>
        <ul className="space-y-1">
          {sources.map((src) => {
            const Icon =
              src.key === "deals" ? AlertTriangle :
              src.key === "activities" ? History :
              src.key === "environment" ? Building2 :
              src.key === "web_search" ? Globe :
              Database;
            return (
              <li key={src.key} className="flex flex-wrap items-center gap-2 text-[12px] text-foreground/80">
                <Icon className="h-3.5 w-3.5 shrink-0 text-navy/70" />
                <span className="font-medium">{src.label}</span>
                <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", sourceStatusClass(src.status))}>
                  {sourceStatusLabel(src.status)}
                </span>
                {typeof src.count === "number" && <span className="font-mono text-[10.5px] text-muted-foreground">{src.count}</span>}
              </li>
            );
          })}
        </ul>
      </div>

      {/* sources consulted — the tools the model actually called, in order */}
      {false && tools.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-3">
          <div className="eyebrow mb-1.5 flex items-center gap-1.5"><Database className="h-3 w-3" /> {t("chat.researchSources")}</div>
          <ul className="space-y-1">
            {tools.map((tl, i) => {
              const meta = TOOL_LABEL[tl.name];
              const Icon = meta?.icon ?? Search;
              const label = meta ? (lang === "ja" ? meta.ja : meta.en) : tl.name;
              return (
                <li key={i} className="flex items-center gap-2 text-[12px] text-foreground/80">
                  <Icon className="h-3.5 w-3.5 shrink-0 text-navy/70" />
                  <span className="font-medium">{label}</span>
                  {tl.args && <span className="truncate font-mono text-[10.5px] text-muted-foreground">{tl.args}</span>}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* the grounded answer */}
      {answer ? (
        <NarrationMd text={answer} />
      ) : unavailable ? (
        <p className="text-[13px] text-muted-foreground">{t("chat.researchUnavailable")} ({unavailable})</p>
      ) : status === "running" ? (
        <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
          <span className="flex gap-1">
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-navy [animation-delay:-0.3s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-navy [animation-delay:-0.15s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-navy" />
          </span>
          {t("chat.researchingGeneric")}
        </div>
      ) : (
        <p className="text-[13px] text-muted-foreground">{t("chat.researchUnavailable")}</p>
      )}

      {/* web citations */}
      {webUrls.length > 0 && (
        <div className="border-t border-border pt-2.5">
          <div className="eyebrow mb-1.5 flex items-center gap-1.5"><Globe className="h-3 w-3" /> {t("chat.researchWeb")}</div>
          <ul className="space-y-1">
            {webUrls.map((u) => (
              <li key={u}>
                <a href={u} target="_blank" rel="noopener noreferrer"
                   className="inline-flex items-center gap-1 text-[12px] text-primary hover:underline">
                  <ExternalLink className="h-3 w-3 shrink-0" />
                  <span className="truncate">{u}</span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// --- message model ---------------------------------------------------------
type Msg =
  | { id: number; role: "senpai"; kind: "intro" }
  | { id: number; role: "senpai"; kind: "prompt"; text: string }
  | { id: number; role: "user"; kind: "note"; note: string; noteJa?: string; dealLabel?: string; jp?: boolean }
  | { id: number; role: "senpai"; kind: "loading" }
  | { id: number; role: "senpai"; kind: "coaching"; note: string; resp: CoachResponse; live: boolean; dealId?: string }
  | { id: number; role: "senpai"; kind: "research"; note: string };

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

function UserNote({ note, noteJa, dealLabel, jp }: { note: string; noteJa?: string; dealLabel?: string; jp?: boolean }) {
  const { t, lang } = useT();
  return (
    <div className="rounded-xl rounded-tl-sm border border-border bg-card p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      {dealLabel && (
        <Badge variant="accent" className="mb-2 font-jp">
          {customerText(lang, dealLabel).text}
        </Badge>
      )}
      <span className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-foreground/90 block">{note}</span>
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

  // `engineText` always drives the keyword-based coach (Japanese for seed
  // examples); `opts.display` is what the user sees in the bubble. They differ
  // only for the English example cards, so coaching output stays meaningful
  // while the visible note reads natively English.
  async function submit(engineText: string, deal: string, opts?: { display?: string; jp?: boolean }) {
    const clean = engineText.trim();
    if (!clean || busy) return;
    const display = (opts?.display ?? engineText).trim();
    const jp = opts?.jp ?? lang === "ja";
    const dealLabel = deal ? deals.find((d) => d.deal_id === deal)?.customer : undefined;

    // Routing: a research-style question (and no deal attached) goes to the
    // tool-calling assistant; everything else stays the Review Coach. Attaching a
    // deal always means "review this opportunity" → coaching.
    if (!deal && isResearchQuestion(clean)) {
      setMessages((m) => [
        ...m,
        { id: nextId(), role: "user", kind: "note", note: display, noteJa: display !== clean ? clean : undefined, jp },
        { id: nextId(), role: "senpai", kind: "research", note: clean },
      ]);
      setNote("");
      setDealId("");
      return; // ResearchCard streams on its own; no global busy lock
    }

    const loadingId = nextId();
    setMessages((m) => [
      ...m,
      { id: nextId(), role: "user", kind: "note", note: display, noteJa: display !== clean ? clean : undefined, dealLabel, jp },
      { id: loadingId, role: "senpai", kind: "loading" },
    ]);
    setNote("");
    setDealId("");
    setBusy(true);
    const { data, live } = await api.coach(clean, deal || undefined);
    setMessages((m) =>
      m.map((msg) =>
        msg.id === loadingId
          ? { id: loadingId, role: "senpai", kind: "coaching", note: clean, resp: data, live, dealId: deal || undefined }
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
                <UserNote note={m.note} noteJa={m.noteJa} dealLabel={m.dealLabel} jp={m.jp} />
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
                      {examples.map((ex) => {
                        const loc = coachExampleText(lang, ex);
                        return (
                          <button
                            key={ex.title}
                            disabled={busy}
                            onClick={() => submit(loc.engineNote, ex.deal_id ?? "", { display: loc.note, jp: lang === "ja" })}
                            className="rounded-lg border border-border bg-card px-3 py-2.5 text-left transition-colors hover:border-primary/40 hover:bg-primary/[0.03] disabled:opacity-50"
                          >
                            <div className="flex items-center gap-1.5">
                              <Sparkles className="h-3.5 w-3.5 shrink-0 text-primary" />
                              <span className="text-[13px] font-medium text-foreground">{loc.title}</span>
                            </div>
                            <span className="mt-0.5 text-[11px] leading-snug text-muted-foreground block">{loc.hint}</span>
                          </button>
                        );
                      })}
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
          if (m.kind === "research") {
            return (
              <Row key={m.id} who="senpai" name={t("chat.senpai")}>
                <ResearchCard note={m.note} />
              </Row>
            );
          }
          return (
            <Row key={m.id} who="senpai" name={t("chat.senpai")}>
              <CoachingCard resp={m.resp} note={m.note} live={m.live} dealId={m.dealId} principles={principles} items={items} />
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
                <option key={d.deal_id} value={d.deal_id}>
                  {d.deal_id} · {customerText(lang, d.customer).text}
                </option>
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
