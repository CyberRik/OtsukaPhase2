"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle, BookMarked, Building2, Calendar, Database, ExternalLink,
  FileText, Globe, Layers, Loader2, Mail, Receipt, Route, Search, Send,
  ShieldCheck, Sparkles, UserSearch, Wrench, type LucideIcon,
} from "lucide-react";
import { chatStream, type ChatEvent, type ChatRole, type ChatTurn, type RetrievalTrace } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { RetrievalExplorer } from "@/components/assistant/retrieval-explorer";

type ToolCall = { name: string; args: string; result: string };
type SourceState = {
  key: string; label: string;
  status: "found" | "not_found" | "ambiguous" | "skipped" | "error";
  count?: number; detail?: string;
};
type WebCitation = { title?: string; url?: string };
type Msg = {
  role: "user" | "assistant";
  content: string;
  tools: ToolCall[];
  status?: "running" | "done" | "error";
  research?: boolean;         // turn was routed to the research pipeline
  sources?: SourceState[];    // research source ledger
  webUrls?: WebCitation[];    // external citations
  retrieval?: RetrievalTrace[]; // retrieval explorer trace (per-chunk provenance)
};

// Human labels + icons for each tool, so the grounding ledger reads like
// evidence ("社内ナレッジ照会") rather than a function name. `internal: false`
// marks the only non-grounded source (the open web).
const TOOL_LABEL: Record<string, { ja: string; en: string; icon: LucideIcon; internal?: boolean }> = {
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
  web_search: { ja: "Web検索", en: "Web search", icon: Globe, internal: false },
};

// Role/lang-scoped example prompts (content, so kept here rather than i18n keys).
const EXAMPLES: Record<"junior" | "manager", Record<"ja" | "en", string[]>> = {
  junior: {
    ja: [
      "お客様が値引きを要求。先輩の原則ではどう対応すべき？",
      "アクメ商事について教えて",
      "カラー複合機3000を3台で見積を作って（アクメ商事向け、10%値引き）",
      "D001の健全度を見て",
    ],
    en: [
      "The customer wants a discount. What do the senior principles say?",
      "Tell me about Acme",
      "Build a quote for 3× Color MFP 3000 for Acme, 10% off",
      "Check the health of deal D001",
    ],
  },
  manager: {
    ja: [
      "今週リスクが高い案件を担当別にまとめて",
      "チーム全体のパイプライン状況を教えて",
      "値引き要求への対応、メンバーにどう指導すべき？",
    ],
    en: [
      "Summarize this week's at-risk deals by rep",
      "Show me the team pipeline overview",
      "How should I coach the team on discount requests?",
    ],
  },
};

// Stable per-session id for conversation caching (crypto.randomUUID when available).
function makeConversationId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `conv-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function AssistantChat({ role }: { role: "junior" | "manager" }) {
  const { t, lang } = useT();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [model, setModel] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  // One conversation id per chat session, so the backend can keep the account in
  // focus across turns ("what should I do next?" stays scoped to this customer).
  const convIdRef = useRef<string>(makeConversationId());

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  function stop() {
    abortRef.current?.abort();
  }

  async function send(text: string) {
    const msg = text.trim();
    if (!msg || busy) return;
    setInput("");
    setBusy(true);

    // History = completed turns only (the API prepends its own system prompt).
    const history: ChatTurn[] = messages
      .filter((m) => m.content && m.status !== "error")
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [
      ...prev,
      { role: "user", content: msg, tools: [] },
      { role: "assistant", content: "", tools: [], status: "running" },
    ]);

    // Mutate the trailing assistant message as events stream in.
    const patch = (fn: (m: Msg) => Msg) =>
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = fn(next[next.length - 1]);
        return next;
      });

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    let answered = false;
    await chatStream(msg, history, role as ChatRole, (e: ChatEvent) => {
      switch (e.type) {
        case "start":
          if (e.model) setModel(e.model);
          if (e.role === "research") patch((m) => ({ ...m, research: true, sources: [] }));
          break;
        case "tool":
          patch((m) => ({
            ...m,
            tools: [...m.tools, { name: e.name, args: e.args, result: e.result }],
            retrieval: e.retrieval ? [...(m.retrieval ?? []), ...e.retrieval] : m.retrieval,
          }));
          break;
        case "source":
          patch((m) => ({
            ...m,
            research: true,
            sources: [
              ...(m.sources ?? []).filter((s) => s.key !== e.key),
              { key: e.key, label: e.label, status: e.status, count: e.count, detail: e.detail },
            ],
          }));
          break;
        case "web":
          patch((m) => ({
            ...m,
            webUrls: (e.results ?? [])
              .filter((r) => r.url)
              .map((r) => ({ title: r.title, url: r.url })),
          }));
          break;
        case "delta":
          answered = true;
          patch((m) => ({ ...m, content: m.content + e.text, status: "running" }));
          break;
        case "answer":
          answered = true;
          patch((m) => ({ ...m, content: e.text || m.content, status: "done" }));
          break;
        case "done":
          if (e.model) setModel(e.model);
          patch((m) => (m.status === "running" && m.content ? { ...m, status: "done" } : m));
          break;
        case "unavailable":
        case "error":
          patch((m) => ({ ...m, status: "error" }));
          break;
      }
    }, { signal: ctrl.signal, conversationId: convIdRef.current });

    // Stream ended without an answer → surface a clear error.
    patch((m) => (m.status === "running" || (!answered && !m.content)
      ? { ...m, status: m.content ? "done" : "error" } : { ...m, status: m.status ?? "done" }));
    abortRef.current = null;
    setBusy(false);
  }

  return (
    <div className="space-y-5">
      <header className="space-y-1.5">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight">{t(`assistant.title.${role}`)}</h1>
          {model && (
            <span className="rounded-full bg-muted px-2 py-0.5 font-mono text-[10.5px] text-muted-foreground">
              {model}
            </span>
          )}
        </div>
        <p className="max-w-3xl text-[13.5px] leading-relaxed text-muted-foreground">
          {t(`assistant.lead.${role}`)}
        </p>
      </header>

      {/* Conversation */}
      <div
        ref={scrollRef}
        className="max-h-[56vh] min-h-[220px] space-y-4 overflow-y-auto rounded-xl border border-border bg-card p-4"
      >
        {messages.length === 0 ? (
          <p className="py-10 text-center text-[13px] text-muted-foreground">{t("assistant.empty")}</p>
        ) : (
          messages.map((m, i) => <MessageBubble key={i} m={m} t={t} lang={lang} />)
        )}
      </div>

      {/* Examples */}
      <div className="flex flex-wrap gap-2">
        <span className="self-center text-[11.5px] font-medium text-muted-foreground">
          {t("assistant.examplesLabel")}:
        </span>
        {EXAMPLES[role][lang].map((ex) => (
          <button
            key={ex}
            onClick={() => send(ex)}
            disabled={busy}
            className="rounded-full border border-border bg-card px-3 py-1 text-[12px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground disabled:opacity-50"
          >
            {ex}
          </button>
        ))}
      </div>

      {/* Composer */}
      <form
        onSubmit={(e) => { e.preventDefault(); send(input); }}
        className="flex items-end gap-2"
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); }
          }}
          rows={1}
          placeholder={t("assistant.placeholder")}
          className="min-h-[44px] flex-1 resize-none rounded-lg border border-border bg-background px-3.5 py-2.5 text-[14px] outline-none focus:border-primary/50"
        />
        {busy ? (
          <button
            type="button"
            onClick={stop}
            className="inline-flex h-[44px] items-center gap-1.5 rounded-lg border border-border bg-card px-4 text-[13px] font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            <Loader2 className="h-4 w-4 animate-spin" /> {t("assistant.stop")}
          </button>
        ) : (
          <button
            type="submit"
            disabled={!input.trim()}
            className="inline-flex h-[44px] items-center gap-1.5 rounded-lg bg-primary px-4 text-[13px] font-medium text-primary-foreground transition-opacity disabled:opacity-50"
          >
            <Send className="h-4 w-4" /> {t("assistant.send")}
          </button>
        )}
        {messages.length > 0 && (
          <button
            type="button"
            onClick={() => { setMessages([]); setInput(""); convIdRef.current = makeConversationId(); }}
            disabled={busy}
            className="h-[44px] rounded-lg border border-border bg-card px-3 text-[13px] font-medium text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
          >
            {t("assistant.clear")}
          </button>
        )}
      </form>
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
    names.some((n) => TOOL_LABEL[n]?.internal) ||
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
  return {
    icon: Sparkles,
    text: lang === "ja" ? "一般的な回答（ツール未使用）" : "General answer (no tools)",
    cls: "bg-muted text-muted-foreground",
  };
}

function MessageBubble({ m, t, lang }: { m: Msg; t: (k: string) => string; lang: "ja" | "en" }) {
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
      {/* Research source ledger (the "grounded, not a chatbot" view) */}
      {m.research && m.sources && m.sources.length > 0 && (
        <SourceLedger sources={m.sources} />
      )}

      {/* Tool calls (live while running, collapsible once done) */}
      {m.tools.length > 0 && (
        <details open={running} className="w-full max-w-[88%] rounded-lg border border-border bg-muted/40 text-[12px]">
          <summary className="flex cursor-pointer items-center gap-1.5 px-3 py-1.5 font-medium text-muted-foreground">
            <Wrench className="h-3.5 w-3.5" />
            {m.tools.length} {t("assistant.toolsUsed")}
          </summary>
          <div className="space-y-2 px-3 pb-2.5">
            {m.tools.map((tool, i) => {
              const meta = TOOL_LABEL[tool.name];
              const Icon = meta?.icon ?? Wrench;
              const label = meta ? (lang === "ja" ? meta.ja : meta.en) : tool.name;
              return (
                <div key={i} className="rounded-md bg-card p-2">
                  <div className="flex items-center gap-1.5 text-[11.5px] font-medium text-foreground">
                    <Icon className="h-3.5 w-3.5 shrink-0 text-primary/70" />
                    {label}
                    <span className="font-mono text-[10.5px] text-muted-foreground">{tool.args}</span>
                  </div>
                  <div className="mt-1 whitespace-pre-wrap text-[11.5px] text-muted-foreground">{tool.result}</div>
                </div>
              );
            })}
          </div>
        </details>
      )}

      {/* Retrieval Explorer — per-chunk provenance, scope and scores */}
      {m.retrieval && m.retrieval.length > 0 && (
        <RetrievalExplorer traces={m.retrieval} open={running} lang={lang} />
      )}

      {/* Answer */}
      {error ? (
        <div className="rounded-2xl rounded-bl-sm bg-destructive/10 px-3.5 py-2 text-[13px] text-destructive">
          {t("assistant.error")}
        </div>
      ) : m.content ? (
        <div className="w-full max-w-[88%] rounded-2xl rounded-bl-sm bg-muted px-3.5 py-2.5">
          <AnswerMd text={m.content} />
          {running && <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-foreground/40 align-middle" />}
          {badge && !running && (
            <div className="mt-2 flex items-center gap-1.5 border-t border-border/60 pt-1.5">
              <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-semibold", badge.cls)}>
                <badge.icon className="h-3 w-3" /> {badge.text}
              </span>
            </div>
          )}
        </div>
      ) : running ? (
        <div className="inline-flex items-center gap-1.5 rounded-2xl rounded-bl-sm bg-muted px-3.5 py-2 text-[13px] text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> {t("assistant.working")}
        </div>
      ) : null}

      {/* Web citations */}
      {m.webUrls && m.webUrls.length > 0 && (
        <div className="w-full max-w-[88%] rounded-lg border border-border bg-card px-3 py-2">
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
        <Search className="h-3 w-3" /> {/* sources consulted */}
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

function AnswerMd({ text }: { text: string }) {
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
