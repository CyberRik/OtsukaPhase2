"use client";

// Senpai Workspace shell (Phase 2).
//
// One conversational surface. A turn is either a user message or a SKILL turn
// that produces a pinned, typed Artifact. Phase 2 wires the `/review` skill:
//   /review <note>  →  api.coach() (deterministic sections, assembled into an
//                      immutable review Artifact)  +  narrateStream() (the
//                      senior's read, streamed live into the card).
//
// The transcript and each card's streamed commentary live in the keyed external
// store (chat-store), so generation survives navigation exactly like the
// standalone Coach and Assistant. This surface ships ALONGSIDE the Coach page —
// nav is not touched until Phase 4.

import React, { useEffect, useRef, useState } from "react";
import {
  Bot,
  Building2,
  ChevronRight,
  CornerDownLeft,
  GraduationCap,
  Sparkles,
  TerminalSquare,
  UserRound,
} from "lucide-react";
import { api, narrateStream, chatStream, accountCommentaryStream, type ResolveCandidate } from "@/lib/api";
import { assembleReviewArtifact, assembleAccountArtifact, assembleResearchArtifact, type Artifact, type ArtifactStatus, type EntityRef, type ResearchSourceLine } from "@/lib/artifacts";
import type { CoachExample, DealRow } from "@/lib/types";
import { useT } from "@/lib/i18n";
import { customerText, coachExampleText } from "@/lib/content-i18n";
import { useCachedState, useCachedConversationId } from "@/lib/chat-store";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { ArtifactCard } from "./artifact-card";
import { parseInput } from "./slash";

// --- thread model -----------------------------------------------------------
type AccountPickCandidate = { customer_id: string; name: string };

type WMsg =
  | { id: number; role: "user"; text: string; dealLabel?: string }
  | { id: number; role: "system"; text: string }
  | { id: number; role: "assistant"; text: string; forcedEntity?: EntityRef }
  | { id: number; role: "loading" }
  | { id: number; role: "account_pick"; query: string; candidates: AccountPickCandidate[]; suggestedId?: string | null }
  | { id: number; role: "skill"; kind: "review"; note: string; dealId?: string; artifact: Artifact }
  | { id: number; role: "skill"; kind: "account_brief"; customerId: string; artifact: Artifact }
  | { id: number; role: "skill"; kind: "research"; query: string; entity?: EntityRef; artifact: Artifact };

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

function Dots() {
  return (
    <span className="flex gap-1">
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.3s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.15s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary" />
    </span>
  );
}

// --- slash command picker ---------------------------------------------------
const SLASH_COMMANDS = [
  {
    cmd: "/review",
    labelEn: "Review a meeting note",
    labelJa: "商談メモをレビュー",
    descEn: "Paste a note — get a senior's structured read",
    descJa: "メモを貼り付け、先輩の視点で読み解く",
  },
  {
    cmd: "/account",
    labelEn: "Account intelligence",
    labelJa: "顧客インテリジェンス",
    descEn: "Pull a customer brief from internal records",
    descJa: "社内記録から顧客ブリーフを取得する",
  },
  {
    cmd: "/research",
    labelEn: "Research a topic",
    labelJa: "トピックをリサーチ",
    descEn: "Search internal data and the web",
    descJa: "社内データとWebを横断して調査する",
  },
] as const;

export interface SlashPickerHandle {
  handleKey: (e: React.KeyboardEvent) => boolean; // returns true if consumed
}

const SlashPicker = React.forwardRef<
  SlashPickerHandle,
  {
    input: string;
    lang: string;
    onSelect: (cmd: string) => void;
    onClose: () => void;
  }
>(function SlashPicker({ input, lang, onSelect, onClose }, ref) {
  const [active, setActive] = useState(0);

  // Filter commands by what the user has typed after "/"
  const typed = input.startsWith("/") ? input.slice(1).toLowerCase() : "";
  const filtered = SLASH_COMMANDS.filter((c) =>
    c.cmd.slice(1).startsWith(typed)
  );

  // Expose keyboard handler so parent Textarea can delegate without stealing focus
  React.useImperativeHandle(ref, () => ({
    handleKey(e: React.KeyboardEvent): boolean {
      if (filtered.length === 0) return false;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((a) => (a + 1) % filtered.length);
        return true;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((a) => (a - 1 + filtered.length) % filtered.length);
        return true;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        onSelect(filtered[active].cmd + " ");
        return true;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return true;
      }
      return false;
    },
  }), [filtered, active, onSelect, onClose]);

  // Close if nothing matches
  if (filtered.length === 0) return null;

  return (
    <div className="absolute bottom-full left-0 right-0 mb-2 overflow-hidden rounded-xl border border-border bg-card shadow-[0_8px_30px_-12px_rgba(16,24,40,0.35)]">
      <div className="flex items-center gap-1.5 border-b border-border px-3 py-2">
        <TerminalSquare className="h-3.5 w-3.5 text-primary" />
        <span className="text-[11px] font-semibold uppercase tracking-[0.07em] text-muted-foreground">
          {lang === "ja" ? "スキルを選択" : "Select a skill"}
        </span>
      </div>
      {filtered.map((c, i) => (
        <button
          key={c.cmd}
          onClick={() => onSelect(c.cmd + " ")}
          className={[
            "flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors",
            i === active
              ? "bg-primary/[0.07] text-foreground"
              : "text-foreground hover:bg-muted/60",
          ].join(" ")}
          onMouseEnter={() => setActive(i)}
        >
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10">
            <TerminalSquare className="h-3.5 w-3.5 text-primary" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] font-semibold">{c.cmd}</span>
            <span className="block text-[11.5px] text-muted-foreground">
              {lang === "ja" ? c.descJa : c.descEn}
            </span>
          </span>
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/50" />
        </button>
      ))}
      <div className="border-t border-border px-3 py-1.5">
        <span className="text-[10.5px] text-muted-foreground">
          {lang === "ja"
            ? "↑↓ で移動、Enter で選択、Esc で閉じる"
            : "↑↓ navigate · Enter select · Esc close"}
        </span>
      </div>
    </div>
  );
});

// --- a review skill turn: holds the immutable artifact, streams its commentary
// The structured artifact is fixed at assembly; the senior's read streams into a
// SEPARATE keyed store entry, so switching tabs and returning restores it
// instead of re-streaming. Auto-start fires exactly once per card (cached
// `started` across navigation; a ref guards StrictMode's double-invoked effect).
function ReviewTurn({
  artifact, note, dealId, onPick,
}: {
  artifact: Artifact; note: string; dealId?: string;
  onPick: (note: string, dealId: string, name: string) => void;
}) {
  const { lang } = useT();
  const key = artifact.id;
  const [commentary, setCommentary] = useCachedState<string | null>(`ws:art:${key}:narr`, null);
  const [done, setDone] = useCachedState<boolean>(`ws:art:${key}:done`, false);
  const [started, setStarted] = useCachedState<boolean>(`ws:art:${key}:started`, false);
  const [groundedName, setGroundedName] = useCachedState<string | null>(`ws:art:${key}:gname`, null);
  const [groundedDeal, setGroundedDeal] = useCachedState<string | null>(`ws:art:${key}:gdeal`, null);
  const [candidates, setCandidates] = useCachedState<ResolveCandidate[]>(`ws:art:${key}:cands`, []);
  const convId = useCachedConversationId(`ws:art:${key}:conv`);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current || started) return;
    startedRef.current = true;
    setStarted(true);
    let acc = "";
    narrateStream(note, dealId, (e) => {
      switch (e.type) {
        case "context":
          if (e.grounded) {
            setGroundedName(e.customer ?? null);
            if (e.deal_id) setGroundedDeal(e.deal_id);
          }
          if (e.candidates?.length) setCandidates(e.candidates);
          break;
        case "delta":
          acc += e.text;
          setCommentary(acc);
          break;
        // done | unavailable | error → handled after the stream resolves
      }
    }, { lang, conversationId: convId.current }).then(() => {
      setDone(true);
      if (!acc) setCommentary(null);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const status: ArtifactStatus = done ? "ready" : "building";
  const entity: EntityRef | undefined =
    artifact.entity ??
    (groundedName
      ? { type: "deal", id: dealId ?? groundedDeal ?? "", name: groundedName }
      : undefined);
  const merged: Artifact = { ...artifact, commentary, status, entity };

  return (
    <div className="space-y-3">
      {/* Ambiguous customer — the note's name matched several accounts. Surface
          them so the rep picks one (re-runs the review grounded on that deal),
          rather than the system guessing one company's facts. */}
      {candidates.length > 0 && (
        <div className="rounded-xl border border-band-yellow/40 bg-band-yellow/[0.06] p-4">
          <div className="mb-2 flex items-center gap-1.5 text-[12.5px] font-semibold text-band-yellow">
            <UserRound className="h-3.5 w-3.5" />
            {lang === "ja"
              ? "メモの社名が複数の顧客に一致しました。どの顧客ですか？"
              : "The name in the note matches several customers — which one?"}
          </div>
          <div className="flex flex-wrap gap-2">
            {candidates.map((c) => (
              <button
                key={c.customer_id}
                onClick={() => onPick(note, c.deal_id ?? "", c.name)}
                className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-[12.5px] font-medium text-foreground transition-colors hover:border-primary/40 hover:text-primary"
              >
                <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
                {customerText(lang, c.name).text}
                {c.deal_id && <span className="font-mono text-[10px] text-muted-foreground">{c.deal_id}</span>}
              </button>
            ))}
          </div>
        </div>
      )}
      <ArtifactCard artifact={merged} />
    </div>
  );
}

function AccountTurn({ artifact, customerId }: { artifact: Artifact; customerId: string }) {
  const { lang } = useT();
  const key = artifact.id;
  const [commentary, setCommentary] = useCachedState<string | null>(`ws:art:${key}:narr`, null);
  const [done, setDone] = useCachedState<boolean>(`ws:art:${key}:done`, false);
  const [started, setStarted] = useCachedState<boolean>(`ws:art:${key}:started`, false);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current || started) return;
    startedRef.current = true;
    setStarted(true);
    let acc = "";
    accountCommentaryStream(customerId, (e) => {
      switch (e.type) {
        case "delta":
          acc += e.text;
          setCommentary(acc);
          break;
      }
    }, { lang }).then(() => {
      setDone(true);
      if (!acc) setCommentary(null);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const status: ArtifactStatus = done ? "ready" : "building";
  const merged: Artifact = { ...artifact, commentary, status };

  return <ArtifactCard artifact={merged} />;
}

function ResearchTurn({ artifact, query, entity }: { artifact: Artifact; query: string; entity?: EntityRef }) {
  const { lang } = useT();
  const key = artifact.id;
  const [commentary, setCommentary] = useCachedState<string | null>(`ws:art:${key}:ans`, null);
  const [sources, setSources] = useCachedState<ResearchSourceLine[]>(`ws:art:${key}:src`, []);
  const [webUrls, setWebUrls] = useCachedState<string[]>(`ws:art:${key}:web`, []);
  const [done, setDone] = useCachedState<boolean>(`ws:art:${key}:done`, false);
  const [started, setStarted] = useCachedState<boolean>(`ws:art:${key}:started`, false);
  const convId = useCachedConversationId(`ws:art:${key}:conv`);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current || started) return;
    startedRef.current = true;
    setStarted(true);
    let acc = "";
    let curSources: ResearchSourceLine[] = [];
    let curWebUrls: string[] = [];
    
    chatStream(query, [], "research", (e) => {
      switch (e.type) {
        case "source":
          curSources = [...curSources, { label: e.label, status: e.status, count: e.count }];
          setSources(curSources);
          break;
        case "web":
          if (e.results) {
            curWebUrls = [...curWebUrls, ...e.results.map(r => r.url).filter((u): u is string => !!u)];
            setWebUrls(curWebUrls);
          }
          break;
        case "delta":
          acc += e.text;
          setCommentary(acc);
          break;
      }
    }, { conversationId: convId.current }).then(() => {
      setDone(true);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const status: ArtifactStatus = done ? "ready" : "building";
  const merged = assembleResearchArtifact({
    threadId: artifact.threadId, turnId: artifact.turnId, live: artifact.live, lang,
    answer: commentary ?? "", sources, webUrls, entity
  });
  merged.status = status;
  merged.id = artifact.id; 

  return <ArtifactCard artifact={merged} />;
}

function ChatTurn({ message, forcedEntity, onContext }: { message: string; forcedEntity?: EntityRef; onContext: (label: string) => void }) {
  const [commentary, setCommentary] = useCachedState<string | null>(`ws:chat:${message}:ans`, null);
  const [started, setStarted] = useCachedState<boolean>(`ws:chat:${message}:started`, false);
  const convId = useCachedConversationId(`ws:chat:${message}:conv`);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current || started) return;
    startedRef.current = true;
    setStarted(true);
    let acc = "";
    
    const history: import("@/lib/api").ChatTurn[] = [];
    if (forcedEntity) {
      history.push({ role: "assistant", content: `[Context: currently discussing ${forcedEntity.name}]` });
    }
    
    chatStream(message, history, "junior", (e) => {
      switch (e.type) {
        case "context":
          if (e.status === "active" && e.customer) {
            onContext(e.customer as string);
          }
          break;
        case "delta":
          acc += e.text;
          setCommentary(acc);
          break;
        case "answer":
          if (!acc && e.text) {
             acc = e.text;
             setCommentary(acc);
          }
          break;
      }
    }, { conversationId: convId.current });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!commentary && !started) return null;
  return (
    <div className="rounded-xl border border-primary/20 bg-card p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)] text-[13.5px] leading-relaxed text-foreground/90 whitespace-pre-wrap">
       {commentary || <Dots />}
    </div>
  );
}

const FOLLOWUP_RE = /^(what|who|when|why|how|which|are|is|do|does|should)\b|\b(risk|risks|decision maker|last meeting|products?|next|happened|activity|activities)\b|(次|今後|何を|どう|なぜ|いつ|誰|リスク|決裁|直近|前回|製品|案件|べき|他には|では)/i;
function isClearFollowup(text: string): boolean {
  if (text.length > 150) return false;
  return FOLLOWUP_RE.test(text);
}

// --- account ambiguity picker -----------------------------------------------
// Mirrors ReviewTurn's candidate button UI exactly: yellow warning banner +
// clickable pill buttons. The LLM-suggested best match is highlighted.
function AccountPickTurn({
  candidates,
  suggestedId,
  lang,
  onPick,
}: {
  candidates: AccountPickCandidate[];
  suggestedId?: string | null;
  lang: string;
  onPick: (customerId: string) => void;
}) {
  return (
    <div className="rounded-xl border border-band-yellow/40 bg-band-yellow/[0.06] p-4">
      <div className="mb-3 flex items-center gap-1.5 text-[12.5px] font-semibold text-band-yellow">
        <Building2 className="h-3.5 w-3.5" />
        {lang === "ja"
          ? "複数の候補が見つかりました。どの会社ですか？"
          : "Several customers match — which one did you mean?"}
      </div>
      <div className="flex flex-wrap gap-2">
        {candidates.map((c) => {
          const isSuggested = c.customer_id === suggestedId;
          return (
            <button
              key={c.customer_id}
              onClick={() => onPick(c.customer_id)}
              className={[
                "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12.5px] font-medium transition-colors",
                isSuggested
                  ? "border-primary/60 bg-primary/[0.07] text-primary hover:bg-primary/[0.14]"
                  : "border-border bg-card text-foreground hover:border-primary/40 hover:text-primary",
              ].join(" ")}
            >
              <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
              {c.name}
              <span className="font-mono text-[10px] text-muted-foreground">{c.customer_id}</span>
              {isSuggested && (
                <span className="ml-0.5 rounded-full bg-primary/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-primary">
                  {lang === "ja" ? "AI候補" : "AI pick"}
                </span>
              )}
            </button>
          );
        })}
      </div>
      {suggestedId && (
        <p className="mt-2.5 text-[11px] text-muted-foreground">
          {lang === "ja"
            ? "強調表示されているのはAIが最も可能性が高いと判断した候補です"
            : "The highlighted option is the AI's best guess — click to confirm"}
        </p>
      )}
    </div>
  );
}

export function Workspace({
  examples, deals, role = "junior",
}: {
  examples: CoachExample[]; deals: DealRow[]; role?: "junior" | "manager";
}) {
  const { t, lang } = useT();
  const [messages, setMessages] = useCachedState<WMsg[]>(`workspace:${role}:thread`, () => []);
  const [input, setInput] = useState("");
  const [dealId, setDealId] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPicker, setShowPicker] = useState(false);
  const thread = useCachedConversationId(`workspace:${role}:thread:id`);

  const idRef = useRef<number>(-1);
  if (idRef.current < 0) idRef.current = messages.reduce((mx, m) => Math.max(mx, m.id), 0) + 1;
  const nextId = () => idRef.current++;

  const bottomRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const pickerRef = useRef<SlashPickerHandle>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  async function runReview(note: string, deal: string) {
    const clean = note.trim();
    if (!clean || busy) return;
    const dealLabel = deal ? deals.find((d) => d.deal_id === deal)?.customer : undefined;
    const loadingId = nextId();
    setMessages((m) => [
      ...m,
      { id: nextId(), role: "user", text: clean, dealLabel },
      { id: loadingId, role: "loading" },
    ]);
    setInput("");
    setBusy(true);
    const { data, live } = await api.coach(clean, deal || undefined);
    const d = deals.find((x) => x.deal_id === deal);
    const entity: EntityRef | undefined = deal
      ? { type: "deal", id: deal, name: d?.customer }
      : undefined;
    const artifact = assembleReviewArtifact(data, {
      threadId: thread.current, turnId: String(loadingId), live, entity,
    });
    setMessages((m) =>
      m.map((msg) =>
        msg.id === loadingId
          ? { id: loadingId, role: "skill", kind: "review", note: clean, dealId: deal || undefined, artifact }
          : msg,
      ),
    );
    setBusy(false);
  }

  async function runAccount(nameOrId: string) {
    const clean = nameOrId.trim();
    if (!clean || busy) return;
    const loadingId = nextId();
    setMessages((m) => [
      ...m,
      { id: nextId(), role: "user", text: `/account ${clean}` },
      { id: loadingId, role: "loading" },
    ]);
    setInput("");
    setBusy(true);

    // Smart resolve: deterministic → fuzzy near-miss → LLM ranking in one call.
    // Progressive prefix stripping is still applied first so "C06 tell me more"
    // gets the right query token ("C06") before hitting the smart resolver.
    const words = clean.split(/\s+/);
    let smartRes: { status: string; customer?: { customer_id: string }; candidates?: { customer_id: string; name: string }[]; suggested_id?: string | null } | null = null;
    let resolvedWith = clean;

    for (let len = words.length; len >= 1; len--) {
      const query = words.slice(0, len).join(" ");
      // Use fast deterministic resolve first; only call smart-resolve if ambiguous/not_found
      const { data: quick } = await api.resolveCustomer(query);
      if (quick.status === "resolved") {
        smartRes = quick;
        resolvedWith = query;
        break;
      }
      if (quick.status === "ambiguous" || len === 1) {
        // Hit ambiguous or exhausted prefixes → use smart-resolve for LLM ranking
        const { data: smart } = await api.smartResolveCustomer(query, lang);
        smartRes = smart;
        resolvedWith = query;
        break;
      }
    }

    if (!smartRes || smartRes.status === "not_found") {
      setMessages((m) => m.map(msg => msg.id === loadingId
        ? { id: loadingId, role: "system" as const, text: lang === "ja" ? `「${clean}」は見つかりませんでした` : `Customer not found: ${clean}` }
        : msg));
      setBusy(false);
      return;
    }

    if (smartRes.status === "ambiguous" && smartRes.candidates?.length) {
      // Show clickable picker instead of a dead-end text message
      setMessages((m) => m.map(msg => msg.id === loadingId
        ? { id: loadingId, role: "account_pick" as const, query: resolvedWith, candidates: smartRes!.candidates!, suggestedId: smartRes!.suggested_id }
        : msg));
      setBusy(false);
      return;
    }

    const customerId = smartRes.customer?.customer_id || smartRes.candidates?.[0]?.customer_id || resolvedWith;
    await _loadAccountById(customerId, loadingId);
  }

  async function _loadAccountById(customerId: string, loadingId: number) {
    const { data: acct, live } = await api.account(customerId);
    if (!acct) {
      setMessages((m) => m.map(msg => msg.id === loadingId
        ? { id: loadingId, role: "system" as const, text: lang === "ja" ? "アカウント情報の取得に失敗しました" : "Error loading account" }
        : msg));
      setBusy(false);
      return;
    }
    const artifact = assembleAccountArtifact(acct, { threadId: thread.current, turnId: String(loadingId), live, lang });
    setMessages((m) => m.map(msg => msg.id === loadingId
      ? { id: loadingId, role: "skill" as const, kind: "account_brief", customerId, artifact }
      : msg));
    setBusy(false);
  }

  async function runResearch(query: string, deal: string) {
    const clean = query.trim();
    if (!clean || busy) return;
    const loadingId = nextId();
    setMessages((m) => [
      ...m,
      { id: nextId(), role: "user", text: `/research ${clean}` },
      { id: loadingId, role: "loading" },
    ]);
    setInput("");
    setBusy(true);
    
    const d = deals.find((x) => x.deal_id === deal);
    const entity: EntityRef | undefined = deal
      ? { type: "deal", id: deal, name: d?.customer }
      : undefined;
      
    const artifact = assembleResearchArtifact({
      threadId: thread.current, turnId: String(loadingId), live: true, lang,
      answer: "", sources: [], webUrls: [], entity
    });
    
    setMessages((m) => m.map(msg => msg.id === loadingId ? { id: loadingId, role: "skill", kind: "research", query: clean, entity, artifact } : msg));
    setBusy(false);
  }

  async function runChat(text: string, deal: string) {
     const clean = text.trim();
     if (!clean || busy) return;
     const loadingId = nextId();
     
     let contextEntity: EntityRef | undefined;
     for (let i = messages.length - 1; i >= 0; i--) {
        const msg = messages[i];
        if (msg.role === "skill" && msg.artifact.entity) {
           contextEntity = msg.artifact.entity;
           break;
        }
     }
     
     const forceContext = contextEntity && isClearFollowup(clean);
     const contextLabel = forceContext ? contextEntity?.name : undefined;
     
     setMessages((m) => [
       ...m,
       { id: nextId(), role: "user", text: clean, dealLabel: contextLabel },
       { id: loadingId, role: "assistant", text: clean, forcedEntity: forceContext ? contextEntity : undefined }
     ]);
     setInput("");
  }

  function submit(raw: string, deal: string) {
    const p = parseInput(raw);
    if (p.command && !p.known) {
      setMessages((m) => [
        ...m,
        { id: nextId(), role: "user", text: raw.trim() },
        {
          id: nextId(), role: "system",
          text: lang === "ja"
            ? `/${p.command} は見つかりません。`
            : `/${p.command} is unknown.`,
        },
      ]);
      setInput("");
      return;
    }
    
    if (p.command === "review") {
      runReview(p.body, deal);
    } else if (p.command === "account") {
      runAccount(p.body);
    } else if (p.command === "research") {
      runResearch(p.body, deal);
    } else {
      runChat(p.body || raw.trim(), deal);
    }
    setDealId("");
  }

  // Picking an ambiguous candidate re-runs the review grounded on that deal (or,
  // if it has no open deal, with the full name so it resolves uniquely).
  const onPick = (note: string, deal: string, name: string) => {
    if (deal) runReview(note, deal);
    else runReview(`${name} ${note}`, "");
  };

  return (
    <div className="mx-auto flex min-h-[calc(100vh-9rem)] max-w-3xl flex-col">
      <div className="flex-1 space-y-8 pb-6">
        {messages.length === 0 && (
          <Row who="senpai" name={t("chat.senpai")}>
            <div className="rounded-xl rounded-tl-sm border border-border bg-card p-5 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
              <h2 className="flex items-center gap-2 text-[16px] font-semibold tracking-tight">
                <Bot className="h-4 w-4 text-primary" />
                {lang === "ja" ? "Senpai ワークスペース" : "Senpai Workspace"}
              </h2>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">
                {lang === "ja"
                  ? "メモを貼り付けるか /review を使うと、構造化されたレビューがこのスレッドに固定されます。"
                  : "Paste a note or type /review to pin a structured review into this thread."}
              </p>
              <div className="mt-4">
                <div className="eyebrow mb-2">{t("chat.startExample")}</div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {examples.map((ex) => {
                    const loc = coachExampleText(lang, ex);
                    return (
                      <button
                        key={ex.title}
                        disabled={busy}
                        onClick={() => runReview(loc.engineNote, ex.deal_id ?? "")}
                        className="rounded-lg border border-border bg-card px-3 py-2.5 text-left transition-colors hover:border-primary/40 hover:bg-primary/[0.03] disabled:opacity-50"
                      >
                        <div className="flex items-center gap-1.5">
                          <Sparkles className="h-3.5 w-3.5 shrink-0 text-primary" />
                          <span className="text-[13px] font-medium text-foreground">{loc.title}</span>
                        </div>
                        <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground">{loc.hint}</span>
                      </button>
                    );
                  })}
                </div>

                {/* P1: skill shortcut chips — real seed customers */}
                <div className="eyebrow mb-2 mt-5">
                  {lang === "ja" ? "スキルのショートカット" : "Skill shortcuts"}
                </div>
                <div className="flex flex-col gap-1.5">
                  {[
                    {
                      chip: "/review",
                      hint: lang === "ja" ? "商談メモを貼り付けてレビュー" : "Paste a meeting note and review it",
                      value: "/review ",
                    },
                    {
                      chip: "/account Matsuda Office",
                      hint: lang === "ja" ? "松田事務所の顧客ブリーフを取得" : "Pull account brief for Matsuda Office (C25)",
                      value: "/account Matsuda Office",
                    },
                    {
                      chip: "/research discount strategy",
                      hint: lang === "ja" ? "値引き戦略を社内記録+Webで調査" : "Research discount strategy across internal + web",
                      value: "/research discount strategy",
                    },
                  ].map((s) => (
                    <button
                      key={s.chip}
                      disabled={busy}
                      onClick={() => {
                        setInput(s.value);
                        setShowPicker(false);
                        composerRef.current?.focus();
                      }}
                      className="flex items-center gap-2.5 rounded-lg border border-border bg-muted/30 px-3 py-2 text-left font-mono text-[12.5px] transition-colors hover:border-primary/40 hover:bg-primary/[0.04] disabled:opacity-50"
                    >
                      <TerminalSquare className="h-3.5 w-3.5 shrink-0 text-primary" />
                      <span className="font-semibold text-foreground">{s.chip}</span>
                      <span className="ml-auto text-[11px] font-sans text-muted-foreground">{s.hint}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </Row>
        )}

        {messages.map((m) => {
          if (m.role === "user") {
            return (
              <Row key={m.id} who="user" name={t("chat.you")}>
                <div className="rounded-xl rounded-tl-sm border border-border bg-card p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
                  {m.dealLabel && (
                    <Badge variant="accent" className="mb-2 font-jp">{customerText(lang, m.dealLabel).text}</Badge>
                  )}
                  <span className="block whitespace-pre-wrap text-[13.5px] leading-relaxed text-foreground/90">{m.text}</span>
                </div>
              </Row>
            );
          }
          if (m.role === "system") {
            return (
              <Row key={m.id} who="senpai" name={t("chat.senpai")}>
                <div className="rounded-xl rounded-tl-sm border border-dashed border-border bg-muted/30 p-4 text-[13px] leading-relaxed text-muted-foreground">
                  {m.text}
                </div>
              </Row>
            );
          }
          if (m.role === "loading") {
            return (
              <Row key={m.id} who="senpai" name={t("chat.senpai")}>
                <div className="inline-flex items-center gap-2 rounded-xl rounded-tl-sm border border-border bg-card px-4 py-3 text-[13px] text-muted-foreground shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
                  <Dots /> {t("chat.thinking")}
                </div>
              </Row>
            );
          }
          if (m.role === "assistant") {
            return (
              <Row key={m.id} who="senpai" name={t("chat.senpai")}>
                <ChatTurn message={m.text} forcedEntity={m.forcedEntity} onContext={(label) => {
                  setMessages((prev) => prev.map((msg) => msg.id === m.id - 1 ? { ...msg, dealLabel: label } : msg));
                }} />
              </Row>
            );
          }
          if (m.role === "account_pick") {
            return (
              <Row key={m.id} who="senpai" name={t("chat.senpai")}>
                <AccountPickTurn
                  candidates={m.candidates}
                  suggestedId={m.suggestedId}
                  lang={lang}
                  onPick={(customerId) => {
                    if (busy) return;
                    const loadingId = nextId();
                    setMessages((prev) => [
                      ...prev,
                      { id: nextId(), role: "user", text: `/account ${customerId}` },
                      { id: loadingId, role: "loading" },
                    ]);
                    setBusy(true);
                    _loadAccountById(customerId, loadingId);
                  }}
                />
              </Row>
            );
          }
          if (m.role === "skill") {
            return (
              <Row key={m.id} who="senpai" name={t("chat.senpai")}>
                {m.kind === "review" && <ReviewTurn artifact={m.artifact} note={m.note} dealId={m.dealId} onPick={onPick} />}
                {m.kind === "account_brief" && <AccountTurn artifact={m.artifact} customerId={m.customerId} />}
                {m.kind === "research" && <ResearchTurn artifact={m.artifact} query={m.query} entity={m.entity} />}
              </Row>
            );
          }
          return null;
        })}

        <div ref={bottomRef} />
      </div>

      {/* composer */}
      <div className="sticky bottom-0 -mx-1 border-t border-border bg-background/85 px-1 pb-4 pt-3 backdrop-blur">
        <div className="relative">
          {showPicker && (
            <SlashPicker
              ref={pickerRef}
              input={input}
              lang={lang}
              onSelect={(cmd) => {
                setInput(cmd);
                setShowPicker(false);
                composerRef.current?.focus();
              }}
              onClose={() => setShowPicker(false)}
            />
          )}
          <div className="rounded-2xl border border-border bg-card p-2.5 shadow-[0_8px_30px_-22px_rgba(16,24,40,0.45)] focus-within:border-primary/40">
            <Textarea
              ref={composerRef}
              value={input}
              onChange={(e) => {
                const v = e.target.value;
                setInput(v);
                // Show picker whenever the input looks like a partial slash command
                // (starts with "/" and no space after the command word yet).
                const isPartialSlash = /^\/[a-z]*$/i.test(v.trim());
                setShowPicker(isPartialSlash);
              }}
              onKeyDown={(e) => {
                if (showPicker && pickerRef.current) {
                  const consumed = pickerRef.current.handleKey(e);
                  if (consumed) return;
                }
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit(input, dealId);
                }
              }}
              placeholder={lang === "ja" ? "/review, /account, /research … または質問を入力" : "Type / to pick a skill, or ask a question…"}
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
              <Button variant="seal" size="sm" disabled={busy || !input.trim()} onClick={() => submit(input, dealId)} className="gap-1.5">
                {t("chat.send")} <CornerDownLeft className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
