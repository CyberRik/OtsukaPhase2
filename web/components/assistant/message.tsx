"use client";

// Shared assistant message renderer.
//
// The grounded chat bubble — tool/grounding ledger, retrieval explorer, research
// source ledger, routing badge, web citations and markdown answer — extracted
// from the Assistant so the unified Workspace chat renders identically. One
// renderer, one trust surface: "grounded, not a chatbot" looks the same wherever
// chat appears.

import { useState } from "react";
import {
  AlertTriangle, BookMarked, Brain, Building2, Calendar, Database, Download, ExternalLink,
  FileText, Globe, Layers, Loader2, Mail, Presentation, Receipt, Route, Search,
  ShieldCheck, Sparkles, UserSearch, Wrench, Zap, ChevronRight, ChevronDown, FolderTree, type LucideIcon,
} from "lucide-react";
import { documentUrl, type ResolveCandidate, type RetrievalTrace, type CrawlPage, type CrawlFrame } from "@/lib/api";
import type { GeneratedDocument } from "@/lib/types";
import { cn } from "@/lib/utils";
import { RetrievalExplorer } from "@/components/assistant/retrieval-explorer";
import { CrawlReplay } from "@/components/assistant/crawl-replay";

export type ToolCall = { name: string; args: string; result: string; document?: GeneratedDocument; crawl?: CrawlPage[]; crawlFrames?: CrawlFrame[]; batchId?: string | null; intent?: string; outline?: { title: string }[]; internal?: boolean };
export type SourceState = {
  key: string; label: string;
  status: "found" | "not_found" | "ambiguous" | "skipped" | "error";
  count?: number; detail?: string;
};
export type WebCitation = { title?: string; url?: string };
export type Msg = {
  role: "user" | "assistant";
  content: string;
  tools: ToolCall[];
  status?: "running" | "done" | "error";
  research?: boolean;         // turn was routed to the research pipeline
  sources?: SourceState[];    // research source ledger
  webUrls?: WebCitation[];    // external citations
  retrieval?: RetrievalTrace[]; // retrieval explorer trace (per-chunk provenance)
  routing?: { think: boolean; reason: string; confidence: number; mode: "reasoning" | "fast" };
  candidates?: ResolveCandidate[]; // ambiguous customer — surfaced for the user to pick
  query?: string;                  // the original message, so a pick can re-ask scoped
};

// Human labels + icons for each tool, so the grounding ledger reads like
// evidence ("社内ナレッジ照会") rather than a function name. `internal: false`
// marks the only non-grounded source (the open web).
export const TOOL_LABEL: Record<string, { ja: string; en: string; icon: LucideIcon; internal?: boolean }> = {
  query_spr: { ja: "社内の顧客・案件", en: "Internal records", icon: Database, internal: true },
  find_similar_deals: { ja: "類似案件", en: "Similar deals", icon: Layers, internal: true },
  retrieve_playbook: { ja: "プレイブック", en: "Playbook", icon: BookMarked, internal: true },
  search_knowledge: { ja: "社内ナレッジ照会", en: "Internal knowledge", icon: ShieldCheck, internal: true },
  lookup_customer_environment: { ja: "IT環境", en: "IT environment", icon: Building2, internal: true },
  get_product_info: { ja: "製品情報", en: "Product info", icon: BookMarked, internal: true },
  search_products: { ja: "製品検索", en: "Product search", icon: Search, internal: true },
  create_quote: { ja: "見積作成", en: "Quote", icon: Receipt, internal: true },
  score_deal_health: { ja: "案件健全度", en: "Deal health", icon: AlertTriangle, internal: true },
  draft_daily_report: { ja: "日報下書き", en: "Daily report", icon: FileText, internal: true },
  schedule_meeting: { ja: "打合せ調整", en: "Schedule", icon: Calendar, internal: true },
  send_email: { ja: "メール下書き", en: "Email draft", icon: Mail, internal: true },
  get_calendar: { ja: "予定確認", en: "Calendar", icon: Calendar, internal: true },
  route_to_expert: { ja: "専門家へ橋渡し", en: "Route to expert", icon: Route, internal: true },
  get_seasonal_context: { ja: "時期・予算", en: "Seasonal context", icon: Calendar, internal: true },
  list_at_risk_deals: { ja: "リスク案件一覧", en: "At-risk deals", icon: AlertTriangle, internal: true },
  team_pipeline_overview: { ja: "パイプライン概況", en: "Pipeline overview", icon: Database, internal: true },
  team_report_digest: { ja: "日報ダイジェスト", en: "Report digest", icon: FileText, internal: true },
  rep_coaching_focus: { ja: "コーチング対象", en: "Coaching focus", icon: UserSearch, internal: true },
  draft_message: { ja: "メッセージ下書き", en: "Message draft", icon: Mail, internal: true },
  generate_proposal: { ja: "提案書(PPTX)生成", en: "Proposal (PPTX)", icon: Presentation, internal: true },
  generate_ringisho: { ja: "稟議書(DOCX)生成", en: "Ringi-sho (DOCX)", icon: FileText, internal: true },
  // General-purpose authoring tools: NOT inherently grounded in internal data —
  // they build from a free prompt (+ optional web). Only generate_proposal /
  // generate_ringisho are deal-grounded, so don't let these falsely claim
  // "grounded in internal data" on a generic deck.
  generate_pptx: { ja: "プレゼン(PPTX)生成", en: "Slides (PPTX)", icon: Presentation, internal: false },
  generate_docx: { ja: "文書(DOCX)生成", en: "Document (DOCX)", icon: FileText, internal: false },
  web_search: { ja: "Web検索", en: "Web search", icon: Globe, internal: false },
  // The document PLANNER (senpai/planner) emits these stable capability ids as
  // `name` (see _plan_stream in senpai/api/server.py) rather than baking a
  // Japanese label in server-side — same reasoning as every ReAct-loop tool
  // above: one lookup, ja/en picked by the existing `lang` switch, not hardcoded.
  conversation: { ja: "会話の文脈", en: "Conversation context", icon: Sparkles, internal: false },
  workspace: { ja: "ローカル文書", en: "Local documents", icon: FileText, internal: false },
  crm: { ja: "社内記録(SPR)", en: "Internal records (SPR)", icon: Database, internal: true },
  knowledge: { ja: "社内ナレッジ", en: "Internal knowledge", icon: ShieldCheck, internal: true },
  // `documents` (the planner's terminal artifact task) is proposal/pptx/docx
  // depending on the goal — its `internal` grounding actually varies per turn, so
  // the event itself carries an explicit `internal` flag that overrides this
  // static default (see groundingBadge below).
  documents: { ja: "資料生成", en: "Document generation", icon: Presentation, internal: false },
  workspace_organize: { ja: "フォルダ整理", en: "Workspace Organize", icon: FolderTree, internal: false },
  workspace_write: { ja: "メモ保存", en: "Save Note", icon: FileText, internal: false },
};

function getToolHighlight(tool: ToolCall): string {
  try {
    const str = tool.args || "";
    
    // Extract a value formatted as key='value' or key=value
    const extract = (key: string) => {
      const regex = new RegExp(`${key}=(['"]?)(.*?)\\1(?:,|$)`);
      const match = str.match(regex);
      return match ? match[2] : null;
    };

    if (tool.name === "web_search") return extract("query") || "";
    if (tool.name === "search_products") return extract("keyword") || extract("category") || "";
    if (tool.name === "get_product_details") return extract("product_id") || "";
    if (tool.name === "list_recent_emails") return extract("query") || "";
    if (tool.name === "schedule_meeting") return extract("title") || "Meeting";
    
    const title = extract("title");
    if (title) return title;
    
    const prompt = extract("prompt");
    if (prompt) return prompt.substring(0, 50) + (prompt.length > 50 ? "..." : "");
    
    return extract("company_name") || extract("name") || "";
  } catch {
    return "";
  }
}

function ToolDisclosure({ tool, running, lang, isParallelItem = false }: { tool: ToolCall, running: boolean, lang: "ja" | "en", isParallelItem?: boolean }) {
  const [open, setOpen] = useState(false);
  const meta = TOOL_LABEL[tool.name];
  const Icon = meta?.icon ?? Wrench;
  const baseLabel = meta ? (lang === "ja" ? meta.ja : meta.en) : tool.name;
  const highlight = getToolHighlight(tool);
  
  // Extract sources if applicable (e.g. from web search results returning [1] Source Name)
  let sourcesCount = 0;
  if (tool.result && (tool.name === "web_search" || tool.name === "search_products")) {
    const lines = tool.result.split("\\n");
    sourcesCount = lines.filter(l => l.trim().startsWith("-")).length;
  }
  
  const displayLabel = highlight ? `${highlight} ${sourcesCount > 0 ? `(${sourcesCount} ${lang === "ja" ? "件" : "sources"})` : ""}` : baseLabel;
  const finalLabel = highlight ? `${displayLabel} — ${baseLabel}` : displayLabel;
  
  return (
    <div className={`flex flex-col gap-0.5 ${isParallelItem ? '' : 'rounded-md bg-card p-2'}`}>
      <div 
        className="flex items-center gap-1.5 cursor-pointer hover:bg-black/5 dark:hover:bg-white/5 p-1 -ml-1 rounded transition-colors text-[11.5px]"
        onClick={() => setOpen(!open)}
      >
        {isParallelItem ? (
          <span className="w-3 shrink-0 text-center font-mono text-[10px] text-primary">
            {running ? "●" : (open ? <ChevronDown className="h-3 w-3 inline" /> : <ChevronRight className="h-3 w-3 inline" />)}
          </span>
        ) : (
          <Icon className="h-3.5 w-3.5 shrink-0 text-primary/70" />
        )}
        <span className="text-foreground font-medium truncate flex-1">{finalLabel}</span>
      </div>
      
      {open && (
        <div className="ml-5 mt-1 border-l border-border/40 pl-3 py-1 flex flex-col gap-2 text-[11px]">
          <div>
            <div className="font-semibold text-foreground/80 mb-0.5">Query / Args</div>
            <div className="text-muted-foreground font-mono bg-muted/30 p-1.5 rounded break-all">{tool.args}</div>
          </div>
          <div>
            <div className="font-semibold text-foreground/80 mb-0.5">Result</div>
            <div className="text-muted-foreground whitespace-pre-wrap max-h-[300px] overflow-y-auto">{tool.result}</div>
          </div>
          {tool.outline && tool.outline.length > 0 && (
            <div>
              <div className="font-semibold text-foreground/80 mb-0.5">
                {lang === "ja" ? "構成案" : "Outline"}
              </div>
              <ol className="list-decimal list-inside text-muted-foreground bg-muted/30 rounded p-1.5 space-y-0.5">
                {tool.outline.map((s, i) => (
                  <li key={i} className="truncate">{s.title || (lang === "ja" ? "(無題)" : "(untitled)")}</li>
                ))}
              </ol>
            </div>
          )}
          {tool.document && (
            <a
              href={documentUrl(tool.document.download_url)}
              download={tool.document.filename}
              className="mt-1 inline-flex w-fit items-center gap-1.5 rounded-md border border-primary/40 bg-primary/[0.06] px-2.5 py-1 text-[11px] font-medium text-primary transition-colors hover:bg-primary/10"
            >
              <Download className="h-3.5 w-3.5" />
              {lang === "ja" ? "ダウンロード" : "Download"}
              <span className="font-mono text-[10px] text-muted-foreground">{tool.document.filename}</span>
            </a>
          )}
        </div>
      )}
    </div>
  );
}

// --- grounding badge --------------------------------------------------------
// Honest, at-a-glance provenance for every answer: green when ≥1 internal tool
// fired, web when the open web was consulted, neutral when the model answered
// with no tools at all (the case you *want* visible).
function groundingBadge(m: Msg, lang: "ja" | "en") {
  const names = m.tools.map((tl) => tl.name);
  const usedInternal =
    // The ReAct chat loop's tools are keyed by function name (query_spr, ...) and
    // classified via TOOL_LABEL; the planner (document generation) instead emits
    // Japanese display labels as `name` with its own explicit `internal` flag per
    // event — check both, since neither pipeline's tool names are in the other's
    // lookup.
    names.some((n) => TOOL_LABEL[n]?.internal) ||
    m.tools.some((tl) => tl.internal === true) ||
    (m.sources?.some((s) => s.status === "found") ?? false);
  const usedWeb = names.includes("web_search") || (m.webUrls?.length ?? 0) > 0;

  if (usedInternal) {
    return {
      icon: ShieldCheck,
      text: lang === "ja" ? (usedWeb ? "社内データ＋外部情報" : "社内データに基づく") : (usedWeb ? "Internal data + web" : "Grounded in internal data"),
      cls: "bg-conf-high/10 text-conf-high",
    };
  }
  if (usedWeb) {
    return {
      icon: Globe,
      text: lang === "ja" ? "外部情報（Web）" : "External (web)",
      cls: "bg-band-yellow/10 text-band-yellow",
    };
  }
  // A tool ran but none of them retrieve internal facts (e.g. a generic PPTX from
  // a free prompt) → say so honestly instead of "no tools" or "internal data".
  const ranTools = m.tools.length > 0;
  return {
    icon: Sparkles,
    text: lang === "ja"
      ? (ranTools ? "一般的な生成（社内データ非依存）" : "一般的な回答（ツール未使用）")
      : (ranTools ? "General output (not internal data)" : "General answer (no tools)"),
    cls: "bg-muted text-muted-foreground",
  };
}

export function MessageBubble({ m, t, lang, onPick }: {
  m: Msg; t: (k: string) => string; lang: "ja" | "en"; onPick: (c: ResolveCandidate) => void;
}) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-primary px-3.5 py-2 text-[13.5px] text-primary-foreground">
          {m.content}
        </div>
      </div>
    );
  }

  const running = m.status === "running";
  const error = m.status === "error";
  const badge = !error && (m.content || m.tools.length || m.sources?.length) ? groundingBadge(m, lang) : null;

  return (
    <div className="flex w-full flex-col items-start gap-1.5">
      {/* 1. Thinking or Answer */}
      {error ? (
        <div className="rounded-xl bg-destructive/10 px-3.5 py-2 text-[13px] text-destructive">
          {t("assistant.error")}
        </div>
      ) : running && !m.content ? (
        <div className="inline-flex items-center gap-2 py-1 text-[13px] font-medium text-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> 
          {lang === "ja" ? "考え中..." : "Thinking..."}
        </div>
      ) : m.content ? (
        <div className="w-full pt-1.5">
          <AnswerMd text={m.content} />
          {running && <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-foreground/40 align-middle" />}
        </div>
      ) : null}

      {/* 1b. Generated document downloads — surfaced at the RESPONSE level (not
           buried inside the collapsed tool card) so the deliverable is one click. */}
      {(() => {
        const docs = m.tools.map((tl) => tl.document).filter(Boolean) as GeneratedDocument[];
        if (docs.length === 0) return null;
        return (
          <div className="flex w-full max-w-[88%] flex-wrap gap-2 pt-1">
            {docs.map((doc, i) => (
              <a
                key={doc.doc_id ?? `${doc.filename}-${i}`}
                href={documentUrl(doc.download_url)}
                download={doc.filename}
                className="inline-flex items-center gap-2 rounded-lg border border-primary/40 bg-primary/[0.06] px-3 py-2 text-[12.5px] font-medium text-primary transition-colors hover:bg-primary/10"
              >
                <Download className="h-4 w-4 shrink-0" />
                {lang === "ja" ? "ダウンロード" : "Download"}
                <span className="font-mono text-[11px] text-muted-foreground">{doc.filename}</span>
              </a>
            ))}
          </div>
        );
      })()}

      {/* 2. Execution Timeline (Level 2) */}
      {m.tools.length > 0 && (
        <details open={running} className="w-full max-w-[88%] text-[12px] group">
          <summary className="flex cursor-pointer items-center gap-1.5 py-1.5 font-medium text-muted-foreground select-none hover:text-foreground transition-colors list-none [&::-webkit-details-marker]:hidden">
            <span className="flex items-center justify-center w-4 h-4 shrink-0 transition-transform group-open:rotate-90">
              <ChevronRight className="h-4 w-4" />
            </span>
            {running 
              ? (lang === "ja" ? `実行中 (${m.tools.length} 操作)` : `Execution (${m.tools.length} operations)`)
              : (lang === "ja" ? `✓ 調査完了 (${m.tools.length} 操作)` : `✓ Investigation complete (${m.tools.length} operations)`)}
          </summary>
          <div className="space-y-2 border-l border-border/60 ml-2 pl-3 mt-1 pb-2.5">
            {(() => {
              const groups: { batchId: string | null; tools: ToolCall[] }[] = [];
              for (const tl of m.tools) {
                const last = groups[groups.length - 1];
                if (tl.batchId && last && last.batchId === tl.batchId) {
                  last.tools.push(tl);
                } else {
                  groups.push({ batchId: tl.batchId || null, tools: [tl] });
                }
              }

              return groups.map((g, gi) => {
                if (g.batchId && g.tools.length > 1) {
                  const firstTool = g.tools[0];
                  let batchLabel = firstTool.intent;
                  if (!batchLabel) {
                    const meta = TOOL_LABEL[firstTool.name];
                    batchLabel = meta ? (lang === "ja" ? meta.ja : meta.en) : firstTool.name;
                  }

                  return (
                    <div key={`batch-${gi}`} className="flex flex-col gap-1.5 rounded-md bg-card p-2.5 shadow-sm border border-border/40">
                      <div className="flex items-center gap-2 text-[11.5px] font-medium text-foreground">
                        <span className="w-3 shrink-0 text-center font-mono text-[11px] text-foreground/40">{running ? "□" : "✓"}</span>
                        <span>{batchLabel}</span>
                        {running && <span className="execution-pulse inline-block h-1.5 w-1.5 rounded-full bg-primary/70 shrink-0" />}
                      </div>
                      <div className="flex flex-col gap-1.5 pl-[22px]">
                        {g.tools.map((tool, i) => (
                          <ToolDisclosure key={i} tool={tool} running={running} lang={lang} isParallelItem={true} />
                        ))}
                      </div>
                    </div>
                  );
                }

                return g.tools.map((tool, i) => (
                  <ToolDisclosure key={`single-${gi}-${i}`} tool={tool} running={running} lang={lang} isParallelItem={false} />
                ));
              });
            })()}
          </div>
        </details>
      )}

      {/* Browser replay — when web_research crawled sites this turn, play back the
          captured scroll feed (the /intel path streams the same frames live). */}
      {(() => {
        const frames = m.tools.flatMap((t) => t.crawlFrames ?? []);
        const pages = m.tools.flatMap((t) => t.crawl ?? []);
        if (frames.length === 0 && !pages.some((p) => p.screenshot_b64)) return null;
        return <CrawlReplay frames={frames} pages={pages} lang={lang} />;
      })()}

      {/* Research source ledger */}
      {m.research && m.sources && m.sources.length > 0 && (
        <SourceLedger sources={m.sources} />
      )}

      {/* Retrieval Explorer */}
      {m.retrieval && m.retrieval.length > 0 && (
        <RetrievalExplorer traces={m.retrieval} open={running} lang={lang} />
      )}

      {/* Ambiguous candidates */}
      {m.candidates && m.candidates.length > 0 && (
        <div className="w-full max-w-[88%] rounded-lg border border-band-yellow/40 bg-band-yellow/[0.06] p-3">
          <div className="mb-1.5 flex items-center gap-1.5 text-[11.5px] font-semibold text-band-yellow">
            <UserSearch className="h-3.5 w-3.5" />
            {lang === "ja"
              ? `「${m.query ?? ""}」は複数の顧客に一致します。どの顧客ですか？`
              : `"${m.query ?? ""}" matches several customers — which one?`}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {m.candidates.map((c) => (
              <button
                key={c.customer_id}
                onClick={() => onPick(c)}
                className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-[12px] text-foreground transition-colors hover:border-primary/40 hover:text-primary"
              >
                <Building2 className="h-3 w-3 text-muted-foreground" />
                {c.name}
                {c.deal_id && <span className="font-mono text-[10px] text-muted-foreground">{c.deal_id}</span>}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Badges / Routing */}
      {(badge || m.routing) && !running && m.content && (
        <div className="mt-1 flex flex-wrap items-center gap-1.5 pt-1.5">
          {badge && (
            <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-semibold", badge.cls)}>
              <badge.icon className="h-3 w-3" /> {badge.text}
            </span>
          )}
          {m.routing && (
            <span
              title={`${m.routing.reason} (${Math.round(m.routing.confidence * 100)}%)`}
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-semibold",
                m.routing.think ? "bg-navy/10 text-navy" : "bg-muted text-muted-foreground",
              )}
            >
              {m.routing.think
                ? <><Brain className="h-3 w-3" /> {lang === "ja" ? "推論モード" : "Reasoning"}</>
                : <><Zap className="h-3 w-3" /> {lang === "ja" ? "高速モード" : "Fast"}</>}
            </span>
          )}
        </div>
      )}

      {/* Web citations */}
      {m.webUrls && m.webUrls.length > 0 && (
        <div className="w-full max-w-[88%] rounded-lg border border-border bg-card px-3 py-2 mt-2">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            <Globe className="h-3 w-3" /> {lang === "ja" ? "参照（Web）" : "Web sources"}
          </div>
          <ul className="space-y-1">
            {m.webUrls.map((c, i) => (
              <li key={i}>
                <a href={c.url} target="_blank" rel="noopener noreferrer"
                   className="inline-flex items-center gap-1 text-[12px] text-primary hover:underline">
                  <ExternalLink className="h-3 w-3 shrink-0" />
                  <span className="truncate">{c.title || c.url}</span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// --- research source ledger -------------------------------------------------
function SourceLedger({ sources }: { sources: SourceState[] }) {
  const ICONS: Record<string, LucideIcon> = {
    internal_records: Database, deals: AlertTriangle, activities: FileText,
    environment: Building2, web_search: Globe,
  };
  return (
    <div className="w-full max-w-[88%] rounded-lg border border-primary/25 bg-primary/[0.03] p-3">
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-primary">
        <Search className="h-3 w-3" />
        {sources.length} sources
      </div>
      <ul className="space-y-1">
        {sources.map((s) => {
          const Icon = ICONS[s.key] ?? Database;
          return (
            <li key={s.key} className="flex flex-wrap items-center gap-2 text-[12px] text-foreground/80">
              <Icon className="h-3.5 w-3.5 shrink-0 text-primary/70" />
              <span className="font-medium">{s.label}</span>
              <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", sourceStatusClass(s.status))}>
                {s.status}
              </span>
              {typeof s.count === "number" && <span className="font-mono text-[10.5px] text-muted-foreground">{s.count}</span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function sourceStatusClass(status: SourceState["status"]) {
  switch (status) {
    case "found": return "bg-conf-high/10 text-conf-high";
    case "ambiguous": return "bg-band-yellow/10 text-band-yellow";
    case "error": return "bg-band-red/10 text-band-red";
    default: return "bg-muted text-muted-foreground"; // not_found / skipped
  }
}

// --- lightweight markdown for answers ---------------------------------------
function inlineBold(s: string) {
  return s.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**")
      ? <strong key={i} className="font-semibold text-foreground">{p.slice(2, -2)}</strong>
      : <span key={i}>{p}</span>,
  );
}

export function AnswerMd({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  return (
    <div className="space-y-1.5 text-[13.5px] leading-relaxed text-foreground">
      {lines.map((ln, i) => {
        const tx = ln.trim();
        if (!tx) return <div key={i} className="h-1" />;
        if (/^---+$/.test(tx)) return <div key={i} className="my-1 border-t border-border" />;
        if (/^#{1,6}\s/.test(tx)) {
          return (
            <h4 key={i} className="pt-1 text-[12px] font-semibold uppercase tracking-[0.04em] text-primary">
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
