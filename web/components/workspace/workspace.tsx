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
  Building2,
  ChevronRight,
  CornerDownLeft,
  GraduationCap,
  History,
  Loader2,
  Mic,
  Paperclip,
  Square,
  TerminalSquare,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api, narrateStream, chatStream, accountCommentaryStream, type ResolveCandidate, type ChatTurn as ChatHistoryTurn } from "@/lib/api";
import { assembleReviewArtifact, assembleAccountArtifact, assembleResearchArtifact, type Artifact, type ArtifactStatus, type EntityRef, type ResearchSourceLine } from "@/lib/artifacts";
import type { CoachExample, DealRow, Principle } from "@/lib/types";
import { useT } from "@/lib/i18n";
import { customerText, coachExampleText } from "@/lib/content-i18n";
import { useCachedState, useCachedConversationId, getCached, useWorkspaceFocus, snapshotByPrefix, restoreCached, type WorkspaceFocus } from "@/lib/chat-store";
import { useSession } from "@/lib/session";
import { HistoryDrawer } from "./history-drawer";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { ExecutionTimeline, type ExecutionPhase } from "@/components/agent/agent-lane";
import { ArtifactCard } from "./artifact-card";
import { MessageBubble, type Msg } from "@/components/assistant/message";
import { ExperiencePanel } from "@/components/coach/similar-cases";
import { CrewTurn } from "./crew-turn";
import { IntelTurn } from "./intel-turn";
import { parseInput } from "@/components/workspace/slash";

// --- thread model -----------------------------------------------------------
type AccountPickCandidate = { customer_id: string; name: string };

type WMsg =
  | { id: number; role: "user"; text: string; dealLabel?: string }
  | { id: number; role: "system"; text: string }
  | { id: number; role: "assistant"; text: string; history: ChatHistoryTurn[]; answer?: string; runId?: number; context?: string; dealId?: string }
  | { id: number; role: "loading" }
  | { id: number; role: "account_pick"; query: string; candidates: AccountPickCandidate[]; suggestedId?: string | null }
  | { id: number; role: "skill"; kind: "review"; note: string; dealId?: string; artifact: Artifact }
  | { id: number; role: "skill"; kind: "account_brief"; customerId: string; artifact: Artifact }
  | { id: number; role: "skill"; kind: "research"; query: string; entity?: EntityRef; artifact: Artifact }
  | { id: number; role: "crew"; mode: "deal" | "team"; query?: string; label?: string }
  | { id: number; role: "intel"; query: string };

// The serialized shape persisted per conversation (the opaque `blob` the backend
// round-trips). It carries the transcript array PLUS the separately-cached streamed
// strings (assistant text, artifact narration, crew contributions) and the id
// counter, so a reopened chat rehydrates full-fidelity without re-streaming.
type StoredThread = {
  version: 1;
  messages: WMsg[];
  cache: Record<string, unknown>;
  nextId: number;
  focus?: WorkspaceFocus;
};

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
    managerOnly: false,
  },
  {
    cmd: "/account",
    labelEn: "Account intelligence",
    labelJa: "顧客インテリジェンス",
    descEn: "Pull a customer brief from internal records",
    descJa: "社内記録から顧客ブリーフを取得する",
    managerOnly: false,
  },
  {
    cmd: "/research",
    labelEn: "Research a topic",
    labelJa: "トピックをリサーチ",
    descEn: "Search internal data and the web",
    descJa: "社内データとWebを横断して調査する",
    managerOnly: false,
  },
  {
    cmd: "/crew",
    labelEn: "Multi-agent deal analysis",
    labelJa: "エージェントで商談分析",
    descEn: "A Researcher, Coach & Strategist analyse a deal together",
    descJa: "リサーチャー・コーチ・ストラテジストが商談を分析",
    managerOnly: false,
  },
  {
    cmd: "/intel",
    labelEn: "Website intel (crawl a site)",
    labelJa: "サイトインテル（サイトを巡回）",
    descEn: "Paste a company URL — watch it browse, get a pre-call brief",
    descJa: "企業URLを貼り付け、巡回の様子を見て事前準備資料を取得",
    managerOnly: false,
  },
  {
    cmd: "/team",
    labelEn: "Multi-agent team review",
    labelJa: "エージェントでチーム分析",
    descEn: "One analyst per rep, then a team-lead action list",
    descJa: "担当ごとに分析し、今週の優先アクションを提示",
    managerOnly: true,
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
    role: "junior" | "manager";
    onSelect: (cmd: string) => void;
    onClose: () => void;
  }
>(function SlashPicker({ input, lang, role, onSelect, onClose }, ref) {
  const [active, setActive] = useState(0);

  // Filter commands by what the user has typed after "/" (and hide manager-only
  // skills like /team from the junior workspace).
  const typed = input.startsWith("/") ? input.slice(1).toLowerCase() : "";
  const filtered = SLASH_COMMANDS.filter((c) =>
    c.cmd.slice(1).startsWith(typed) && (!c.managerOnly || role === "manager")
  );

  // `active` can outrun a shrinking `filtered` (the user typed more and fewer
  // commands match). Clamp the index everywhere so we never read past the end,
  // and snap it back into range when the filter changes.
  const activeIdx = active < filtered.length ? active : 0;
  useEffect(() => {
    if (active !== 0 && active >= filtered.length) setActive(0);
  }, [filtered.length, active]);

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
        const sel = filtered[activeIdx];
        if (sel) onSelect(sel.cmd + " ");
        return true;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return true;
      }
      return false;
    },
  }), [filtered, activeIdx, onSelect, onClose]);

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
            i === activeIdx
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
  turnId, artifact, note, dealId, principles, onPick,
}: {
  turnId: number; artifact: Artifact; note: string; dealId?: string;
  principles: Principle[];
  onPick: (turnId: number, dealId: string, name: string) => void;
}) {
  const { lang } = useT();
  const key = artifact.id;
  const [commentary, setCommentary] = useCachedState<string | null>(`ws:art:${key}:narr`, null);
  const [done, setDone] = useCachedState<boolean>(`ws:art:${key}:done`, false);
  const [started, setStarted] = useCachedState<boolean>(`ws:art:${key}:started`, false);
  const [groundedName, setGroundedName] = useCachedState<string | null>(`ws:art:${key}:gname`, null);
  const [groundedDeal, setGroundedDeal] = useCachedState<string | null>(`ws:art:${key}:gdeal`, null);
  const [candidates, setCandidates] = useCachedState<ResolveCandidate[]>(`ws:art:${key}:cands`, []);
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
    }, { lang, conversationId: artifact.threadId }).then(() => {
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

  // Customer still ambiguous → the rep must pick BEFORE we read anything. Show
  // only the picker (no card, no senior's read — the backend hasn't generated
  // one). Picking resolves THIS turn in place (re-runs grounded on the choice),
  // so the conversation stays in the same thread instead of spawning a new one.
  if (candidates.length > 0) {
    return (
      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-[0_4px_20px_-10px_rgba(16,24,40,0.2)]">
        <div className="flex items-center gap-1.5 border-b border-border px-3 py-2 text-[12px] font-medium text-muted-foreground">
          <UserRound className="h-3.5 w-3.5" />
          {candidates.length === 1
            ? (lang === "ja"
                ? "メモの社名は次の顧客に近い表記です。この顧客で合っていますか？"
                : "The name in the note is close to this customer — did you mean them?")
            : (lang === "ja"
                ? "メモの社名が複数の顧客に一致しました。どの顧客ですか？"
                : "The name in the note matches several customers — which one?")}
        </div>
        <div className="flex flex-col">
          {candidates.map((c) => (
            <button
              key={c.customer_id}
              onClick={() => onPick(turnId, c.deal_id ?? "", c.name)}
              className="flex items-center gap-2.5 px-3 py-2 text-left text-[13px] transition-colors hover:bg-muted/60"
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                <Building2 className="h-3 w-3 text-primary" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-medium text-foreground">{customerText(lang, c.name).text}</span>
                {c.deal_id && <span className="block font-mono text-[10.5px] text-muted-foreground">{c.deal_id}</span>}
              </span>
            </button>
          ))}
        </div>
        <div className="border-t border-border px-3 py-1.5 bg-muted/10">
          <p className="text-[11px] text-muted-foreground">
            {lang === "ja"
              ? "選択するとこのレビューがその顧客で読み込まれます。"
              : "Pick one and this same review fills in for that customer."}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <ArtifactCard artifact={merged} />
      {/* Experience pillar — past cases + relevant principles (collapsed, lazy).
          Only meaningful once grounded on a customer; matches the standalone
          Review Coach's "Similar Past Cases" + principle provenance. */}
      {principles.length > 0 && <ExperiencePanel note={note} dealId={dealId} principles={principles} />}
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
    }, { lang, conversationId: artifact.threadId }).then(() => {
      setDone(true);
      if (!acc) setCommentary(null);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const status: ArtifactStatus = done ? "ready" : "building";
  const merged: Artifact = { ...artifact, commentary, status };

  return <ArtifactCard artifact={merged} />;
}

function ResearchTurn({
  turnId, artifact, query, entity, onPick,
}: {
  turnId: number; artifact: Artifact; query: string; entity?: EntityRef;
  onPick: (turnId: number, c: ResolveCandidate) => void;
}) {
  const { lang } = useT();
  const key = artifact.id;
  const [commentary, setCommentary] = useCachedState<string | null>(`ws:art:${key}:ans`, null);
  const [sources, setSources] = useCachedState<ResearchSourceLine[]>(`ws:art:${key}:src`, []);
  const [webUrls, setWebUrls] = useCachedState<string[]>(`ws:art:${key}:web`, []);
  const [candidates, setCandidates] = useCachedState<ResolveCandidate[]>(`ws:art:${key}:cands`, []);
  const [dealIds, setDealIds] = useCachedState<string[]>(`ws:art:${key}:deals`, []);
  const [done, setDone] = useCachedState<boolean>(`ws:art:${key}:done`, false);
  const [started, setStarted] = useCachedState<boolean>(`ws:art:${key}:started`, false);
  const [collapsed, setCollapsed] = useCachedState<boolean>(`ws:art:${key}:coll`, false);
  const [showArtifact, setShowArtifact] = useCachedState<boolean>(`ws:art:${key}:showart`, false);
  const startedRef = useRef(false);
  const collapseRef = useRef<NodeJS.Timeout | undefined>(undefined);

  useEffect(() => () => { if (collapseRef.current) clearTimeout(collapseRef.current); }, []);

  useEffect(() => {
    if (startedRef.current || started) return;
    startedRef.current = true;
    setStarted(true);
    let acc = "";
    let curSources: ResearchSourceLine[] = [];
    let curWebUrls: string[] = [];
    let curDealIds: string[] = [];

    chatStream(query, [], "research", (e) => {
      switch (e.type) {
        case "resolve":
          // Ambiguous customer → surface candidates; the rep picks BEFORE we
          // research, so we never summarize the wrong company's records.
          if (e.status === "ambiguous" && e.candidates?.length) setCandidates(e.candidates);
          break;
        case "deal_ids":
          curDealIds = [...curDealIds, ...e.deal_ids];
          setDealIds(curDealIds);
          break;
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
        case "answer":
          // The research pipeline emits its synthesis as ONE answer event (not a
          // delta stream). Without this the card showed sources but no read.
          acc = e.text || acc;
          setCommentary(acc);
          break;
        case "unavailable":
        case "error":
          // Don't leave the card silent when the synthesis can't run — say so.
          if (!acc) setCommentary(lang === "ja"
            ? "（要約を生成できませんでした。ソースは上記のとおりです。）"
            : "(Couldn't generate the summary — sources are listed above.)");
          break;
      }
    }, { conversationId: artifact.threadId }).then(() => {
      setDone(true);
      setTimeout(() => setShowArtifact(true), 300);
      if (!collapsed) {
        collapseRef.current = setTimeout(() => setCollapsed(true), 1100);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Still ambiguous and nothing summarized yet → show ONLY the picker. Picking
  // resolves THIS turn in place (re-runs research grounded on the choice), so the
  // conversation stays in the same turn — same as the /review and /account picks.
  if (candidates.length > 0 && !commentary) {
    return (
      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-[0_4px_20px_-10px_rgba(16,24,40,0.2)]">
        <div className="flex items-center gap-1.5 border-b border-border px-3 py-2 text-[12px] font-medium text-muted-foreground">
          <Building2 className="h-3.5 w-3.5" />
          {candidates.length === 1
            ? (lang === "ja" ? "この顧客で合っていますか？" : "Did you mean this customer?")
            : (lang === "ja"
                ? "複数の顧客に一致しました。どの顧客を調べますか？"
                : "Several customers match — which one should I research?")}
        </div>
        <div className="flex flex-col">
          {candidates.map((c) => (
            <button
              key={c.customer_id}
              onClick={() => onPick(turnId, c)}
              className="flex items-center gap-2.5 px-3 py-2 text-left text-[13px] transition-colors hover:bg-muted/60"
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                <Building2 className="h-3 w-3 text-primary" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-medium text-foreground">{customerText(lang, c.name).text}</span>
                <span className="block font-mono text-[10.5px] text-muted-foreground">{c.customer_id}</span>
              </span>
            </button>
          ))}
        </div>
        <div className="border-t border-border px-3 py-1.5 bg-muted/10">
          <p className="text-[11px] text-muted-foreground">
            {lang === "ja"
              ? "選択するとこのリサーチがその顧客で読み込まれます。"
              : "Pick one and this same research fills in for that customer."}
          </p>
        </div>
      </div>
    );
  }

  // Prevent flashing before the first stream event arrives.
  if (candidates.length === 0 && sources.length === 0 && !commentary && !done) {
    return null;
  }

  const phases: ExecutionPhase[] = [];
  if (started || sources.length > 0) {
    phases.push({
      id: "researcher",
      label: lang === "ja" ? "データを収集・分析中" : "Gathering and analyzing data",
      emoji: "🔍",
      status: done ? "done" : "running",
      tools: sources.map(s => {
        let hint = "";
        if (s.status === "found") hint = lang === "ja" ? `${s.count ?? 1}件` : `Found ${s.count ?? 1}`;
        else if (s.status === "skipped") hint = lang === "ja" ? "スキップ" : "Skipped";
        else if (s.status === "not_found") hint = lang === "ja" ? "見つかりません" : "Not found";
        else if (s.status === "ambiguous") hint = lang === "ja" ? "複数該当" : "Ambiguous";
        else hint = s.status;
        return { name: s.label, summary: `${s.label}: ${hint}` };
      })
    });
  }

  const status: ArtifactStatus = done ? "ready" : "building";
  const merged = assembleResearchArtifact({
    threadId: artifact.threadId, turnId: artifact.turnId, live: artifact.live, lang,
    answer: commentary ?? "", sources, webUrls, entity, dealIds
  });
  merged.status = status;
  merged.id = artifact.id;

  return (
    <div className="flex flex-col gap-3 relative">
      <ExecutionTimeline
        phases={phases}
        collapsed={collapsed}
        onToggle={() => setCollapsed(!collapsed)}
        lang={lang}
      />
      {(showArtifact || done || commentary) && (
        <div className={cn("transition-all duration-700", !commentary ? "opacity-0" : "opacity-100 animate-fade-up")}>
          <ArtifactCard artifact={merged} />
        </div>
      )}
    </div>
  );
}

// A general chat turn. Streams one assistant reply over the SHARED thread
// conversation id, with the real prior turns threaded as history — so "what
// should I do about this?" sees the conversation (and the account a /review or
// /account brief put in focus on the server). No regex follow-up heuristic and
// no fake "[Context: …]" line: continuity is real conversation, not a guess.
//
// Renders the SAME grounded bubble as the standalone Assistant (tool ledger,
// grounding/routing badges, retrieval explorer, research source ledger, web
// citations, markdown) by capturing the full event stream into a Msg — so the
// Workspace chat is the Assistant, not a stripped single-shot.
const EMPTY_MSG: Msg = { role: "assistant", content: "", tools: [], status: "running" };

function ChatTurn({
  turnId, runId, message, history, role, conversationId, context, dealId, onDone, onPick,
}: {
  turnId: number; runId: number; message: string; history: ChatHistoryTurn[];
  role: "junior" | "manager"; conversationId: string; context?: string; dealId?: string;
  onDone: (text: string) => void;
  onPick: (c: ResolveCandidate, query: string) => void;
}) {
  const { t, lang } = useT();
  // Cache keys are namespaced by the CONVERSATION id, not just the integer
  // turnId. After Clear, thread.reset() mints a fresh conversation id and the
  // transcript empties, so turn ids restart from 1 — without the conversation
  // prefix a new turn id=1 would read the PREVIOUS thread's cached msg (with its
  // `started=true` flag) and render a stale answer instead of streaming a new one.
  // `runId` is bumped when an ambiguous turn is resolved by a pick, so the SAME
  // turn re-streams (grounded on the chosen customer) with a fresh cache slot.
  const [msg, setMsg] = useCachedState<Msg>(`ws:chat:${conversationId}:${turnId}:${runId}:msg`, EMPTY_MSG);
  const [started, setStarted] = useCachedState<boolean>(`ws:chat:${conversationId}:${turnId}:${runId}:started`, false);
  const startedRef = useRef(false);
  const ctrlRef = useRef<AbortController | null>(null);
  const abortedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current || started) return;
    startedRef.current = true;
    setStarted(true);
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;
    const patch = (fn: (m: Msg) => Msg) => setMsg((prev) => fn(prev));
    chatStream(message, history, role, (e) => {
      switch (e.type) {
        case "start":
          if (e.role === "research") patch((m) => ({ ...m, research: true, sources: [] }));
          break;
        case "tool":
          patch((m) => ({
            ...m,
            tools: [...m.tools, { name: e.name, args: e.args, result: e.result, document: e.document, batchId: e.batchId, intent: e.intent }],
            retrieval: e.retrieval ? [...(m.retrieval ?? []), ...e.retrieval] : m.retrieval,
          }));
          break;
        case "source":
          patch((m) => ({
            ...m, research: true,
            sources: [...(m.sources ?? []).filter((s) => s.key !== e.key),
              { key: e.key, label: e.label, status: e.status, count: e.count, detail: e.detail }],
          }));
          break;
        case "web":
          patch((m) => ({ ...m, webUrls: (e.results ?? []).filter((r) => r.url).map((r) => ({ title: r.title, url: r.url })) }));
          break;
        case "routing":
          patch((m) => ({ ...m, routing: { think: e.think, reason: e.reason, confidence: e.confidence, mode: e.mode } }));
          break;
        case "resolve":
          if (e.status === "ambiguous" && e.candidates?.length)
            patch((m) => ({ ...m, candidates: e.candidates, query: e.query }));
          break;
        case "delta":
          patch((m) => ({ ...m, content: m.content + e.text, status: "running" }));
          break;
        case "answer":
          patch((m) => ({ ...m, content: e.text || m.content, status: "done" }));
          break;
        case "done":
          // A turn that surfaced ambiguity candidates is a valid terminal state
          // even with no answer text — the picker IS the response, so it must not
          // be treated as an empty/failed turn.
          patch((m) => (m.status === "running" && (m.content || m.candidates?.length) ? { ...m, status: "done" } : m));
          break;
        case "unavailable":
        case "error":
          // An intentional stop ends the stream as an error too — keep whatever
          // streamed so far and mark it done, not failed. Candidates also count as
          // a successful end (the rep just needs to pick).
          patch((m) => ({ ...m, status: m.candidates?.length ? "done" : (abortedRef.current ? (m.content ? "done" : "error") : "error") }));
          break;
      }
    }, { conversationId, signal: ctrl.signal, context, dealId }).then(() => {
      ctrlRef.current = null;
      setMsg((prev) => {
        const final: Msg = prev.status === "running"
          ? { ...prev, status: (prev.content || prev.candidates?.length) ? "done" : "error" } : prev;
        onDone(final.content);
        return final;
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stop = () => { abortedRef.current = true; ctrlRef.current?.abort(); };
  const running = msg.status === "running";

  if (!msg.content && !msg.tools.length && !msg.sources?.length && running) {
    return (
      <div className="flex items-center gap-2">
        <div className="inline-flex items-center gap-2 rounded-xl rounded-tl-sm border border-border bg-card px-4 py-3 text-[13px] text-muted-foreground shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
          <Dots /> {t(role === "manager" ? "chat.thinking.manager" : "chat.thinking")}
        </div>
        {ctrlRef.current && (
          <button onClick={stop} className="inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2.5 py-1.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground">
            <Square className="h-3 w-3" /> {t("assistant.stop")}
          </button>
        )}
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      <MessageBubble m={msg} t={t} lang={lang} onPick={(c) => onPick(c, msg.query ?? message)} />
      {running && ctrlRef.current && (
        <button onClick={stop} className="inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2.5 py-1.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground">
          <Square className="h-3 w-3" /> {t("assistant.stop")}
        </button>
      )}
    </div>
  );
}

// Build the chat history the model sees from the visible transcript. User turns
// and prior chat answers go in verbatim; a skill turn contributes the senior's
// actual streamed read (labelled with its entity), so chat that follows a review
// or account brief has the real prior content — not a synthetic breadcrumb.
function buildChatHistory(messages: WMsg[]): ChatHistoryTurn[] {
  const h: ChatHistoryTurn[] = [];
  for (const m of messages) {
    if (m.role === "user") {
      h.push({ role: "user", content: m.text });
    } else if (m.role === "assistant" && m.answer) {
      h.push({ role: "assistant", content: m.answer });
    } else if (m.role === "skill") {
      const name = m.artifact.entity?.name;
      const head = m.kind === "review" ? "Review" : m.kind === "account_brief" ? "Account brief" : "Research";
      const label = name ? `${head} — ${name}` : head;
      const body =
        getCached<string>(`ws:art:${m.artifact.id}:narr`) ??
        getCached<string>(`ws:art:${m.artifact.id}:ans`) ?? "";
      h.push({ role: "assistant", content: body ? `[${label}]\n${body}` : `[${label}]` });
    }
  }
  return h;
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
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-[0_4px_20px_-10px_rgba(16,24,40,0.2)]">
      <div className="flex items-center gap-1.5 border-b border-border px-3 py-2 text-[12px] font-medium text-muted-foreground">
        <Building2 className="h-3.5 w-3.5" />
        {lang === "ja"
          ? "複数の候補が見つかりました。どの会社ですか？"
          : "Several customers match — which one did you mean?"}
      </div>
      <div className="flex flex-col">
        {candidates.map((c) => {
          const isSuggested = c.customer_id === suggestedId;
          return (
            <button
              key={c.customer_id}
              onClick={() => onPick(c.customer_id)}
              className={cn(
                "flex items-center gap-2.5 px-3 py-2 text-left text-[13px] transition-colors",
                isSuggested ? "bg-primary/[0.07] hover:bg-primary/[0.12]" : "hover:bg-muted/60"
              )}
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                <Building2 className="h-3 w-3 text-primary" />
              </span>
              <span className="min-w-0 flex-1">
                <span className={cn("block font-medium", isSuggested ? "text-primary" : "text-foreground")}>
                  {c.name}
                  {isSuggested && (
                    <span className="ml-2 rounded-full bg-primary/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-primary">
                      {lang === "ja" ? "AI候補" : "AI pick"}
                    </span>
                  )}
                </span>
                <span className="block font-mono text-[10.5px] text-muted-foreground">{c.customer_id}</span>
              </span>
            </button>
          );
        })}
      </div>
      {suggestedId && (
        <div className="border-t border-border px-3 py-1.5 bg-muted/10">
          <p className="text-[11px] text-muted-foreground">
            {lang === "ja"
              ? "強調表示されているのはAIが最も可能性が高いと判断した候補です"
              : "The highlighted option is the AI's best guess — click to confirm"}
          </p>
        </div>
      )}
    </div>
  );
}

export function Workspace({
  examples, deals, principles = [], role = "junior", wide = false,
}: {
  examples: CoachExample[]; deals: DealRow[]; principles?: Principle[]; role?: "junior" | "manager";
  // When embedded in the Command Center we let the thread fill the available
  // width instead of the standalone reading column (max-w-3xl).
  wide?: boolean;
}) {
  const { t, lang } = useT();
  // The assistant's name differs by role: a junior gets a seasoned mentor
  // ("Senpai Coach"); a manager gets a peer staff voice ("Sales Analyst") — a
  // "senior coach" would talk down to someone who is already senior.
  const assistantName = t(role === "manager" ? "chat.assistant.manager" : "chat.assistant.junior");
  const [messages, setMessages] = useCachedState<WMsg[]>(`workspace:${role}:thread`, () => []);
  const [input, setInput] = useState("");
  const [dealId, setDealId] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPicker, setShowPicker] = useState(false);
  // An attached file's extracted text, pending until the next message is sent.
  // The chat is NOT a data-ingestion surface — the attachment is just context
  // the assistant answers over (structured ingestion lives on the Ingestion tab).
  const [attached, setAttached] = useState<{ fileName: string; text: string } | null>(null);
  const [attaching, setAttaching] = useState(false);
  // Mic dictation: record from the mic, then transcribe straight into the
  // composer (same /api/extract → Whisper path the audio-file attach uses).
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const thread = useCachedConversationId(`workspace:${role}:thread:id`);
  // Persistent chat history: the acting user (for per-user storage), the History
  // drawer's open state, and a tick bumped after each autosave so an open drawer
  // refreshes to show the live conversation.
  const { employeeId } = useSession();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [savedTick, setSavedTick] = useState(0);

  // Shared focus from the Command Center's Context pane. When the rep clicks a
  // deal on the left, that deal becomes the grounding for the next turn — they
  // never have to touch the Deal selector below. We only mirror focus → the
  // local `dealId` when it actually changes, so the standalone Workspace (no
  // Context pane writing focus) behaves exactly as before, and a manual pick in
  // the selector isn't fought over on every render.
  const { focus, setFocus } = useWorkspaceFocus(role);
  const lastFocusDeal = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (focus.dealId && focus.dealId !== lastFocusDeal.current) {
      lastFocusDeal.current = focus.dealId;
      setDealId(focus.dealId);
    }
  }, [focus.dealId]);

  const idRef = useRef<number>(-1);
  if (idRef.current < 0) idRef.current = messages.reduce((mx, m) => Math.max(mx, m.id), 0) + 1;
  const nextId = () => idRef.current++;

  // --- Persistent chat history -------------------------------------------------
  const histRole: "junior" | "manager" = role === "manager" ? "manager" : "junior";

  // Serialize the whole conversation into the opaque blob the backend stores: the
  // transcript array plus every per-turn cache entry (streamed assistant text under
  // ws:chat:<cid>:, crew contributions under ws:crew:<cid>:, and each skill card's
  // artifact narration under ws:art:<artifactId>:) so a reopened chat rehydrates
  // full-fidelity. See the cache-key sites at workspace.tsx (ArtifactCard) and
  // crew-turn.tsx.
  function serializeThread(): string {
    const cid = thread.current;
    const prefixes = [`ws:chat:${cid}:`, `ws:crew:${cid}:`, `ws:intel:${cid}:`];
    for (const m of messages) {
      if (m.role === "skill" && m.artifact) prefixes.push(`ws:art:${m.artifact.id}:`);
    }
    const payload: StoredThread = {
      version: 1,
      messages,
      cache: snapshotByPrefix(prefixes),
      nextId: idRef.current,
      focus,
    };
    return JSON.stringify(payload);
  }

  function deriveTitle(): string {
    const first = messages.find((m) => m.role === "user") as { text?: string } | undefined;
    const text = (first?.text ?? "").trim().replace(/\s+/g, " ");
    if (!text) return lang === "ja" ? "無題のチャット" : "New chat";
    return text.length > 60 ? `${text.slice(0, 60)}…` : text;
  }

  // Autosave (debounced) after each completed turn. Skips while a turn is streaming
  // (busy) and skips transcripts without a real exchange. Failures are swallowed —
  // if the backend is down the chat still works ephemerally, just isn't persisted.
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!employeeId || busy) return;
    const hasUser = messages.some((m) => m.role === "user");
    const hasReply = messages.some(
      (m) => m.role === "assistant" || m.role === "skill" || m.role === "crew" || m.role === "intel",
    );
    if (!hasUser || !hasReply) return;
    const cid = thread.current;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      api
        .saveConversation(cid, {
          employee_id: employeeId,
          role: histRole,
          title: deriveTitle(),
          blob: serializeThread(),
          message_count: messages.length,
        })
        .then(({ live }) => {
          if (live) setSavedTick((n) => n + 1);
        });
    }, 800);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages, busy, employeeId, histRole]);

  // Reopen a saved conversation: rehydrate the transcript + all cached streamed
  // strings, adopt its id, and restore the id counter and focus.
  async function loadConversation(id: string) {
    if (busy) return;
    const { data } = await api.getConversation(id);
    if (!data) return;
    let parsed: StoredThread;
    try {
      parsed = JSON.parse(data.blob) as StoredThread;
    } catch {
      return;
    }
    if (!parsed || parsed.version !== 1) return;
    restoreCached(parsed.cache ?? {});
    thread.set(id);
    idRef.current =
      typeof parsed.nextId === "number"
        ? parsed.nextId
        : (parsed.messages ?? []).reduce((mx, m) => Math.max(mx, m.id), 0) + 1;
    setMessages(parsed.messages ?? []);
    setFocus(parsed.focus ?? {});
    setInput("");
    setDealId("");
    setHistoryOpen(false);
  }

  const bottomRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const pickerRef = useRef<SlashPickerHandle>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  // Attach a file as chat context — extract its text (voice→transcript,
  // image→OCR, or a plain-text file read client-side) and hold it as a pending
  // chip. On the next send, the text rides along as context the assistant
  // answers over. No structured ingestion here — that's the Ingestion tab.
  async function attachFile(file: File) {
    if (attaching || busy) return;
    setAttaching(true);
    let payload: { audio?: File; image?: File; text?: string };
    if (file.type.startsWith("audio")) payload = { audio: file };
    else if (file.type.startsWith("image")) payload = { image: file };
    else payload = { text: await file.text() };  // .txt/.md/.csv etc.
    const { data } = await api.extract(payload);
    setAttaching(false);
    if (data?.raw_text) {
      setAttached({ fileName: file.name, text: data.raw_text });
      composerRef.current?.focus();
    } else {
      setAttached({ fileName: file.name, text: "" });
    }
  }

  // Start/stop mic dictation. On stop, the recorded clip is sent to
  // /api/extract (Whisper) and the transcript is appended to the composer so
  // the user can review/edit before sending — no auto-send.
  async function toggleRecording() {
    if (transcribing || busy || attaching) return;
    if (recording) {
      recorderRef.current?.stop();  // fires onstop → transcribe
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setAttached({ fileName: t("mic.denied"), text: "" });
      return;
    }
    // Pick a container the browser actually supports (Safari lacks webm).
    const mime = ["audio/webm", "audio/mp4", "audio/ogg"].find(
      (m) => typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(m),
    );
    const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
    recorder.onstop = async () => {
      stream.getTracks().forEach((tk) => tk.stop());  // release the mic
      setRecording(false);
      const type = recorder.mimeType || "audio/webm";
      const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
      const blob = new Blob(chunks, { type });
      if (blob.size === 0) return;
      setTranscribing(true);
      const file = new File([blob], `dictation.${ext}`, { type });
      const { data } = await api.extract({ audio: file });
      setTranscribing(false);
      const text = data?.raw_text?.trim();
      if (text) {
        setInput((prev) => (prev ? `${prev} ${text}` : text));
        composerRef.current?.focus();
      }
    };
    recorderRef.current = recorder;
    recorder.start();
    setRecording(true);
  }

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

  // Trigger an inline multi-agent crew the way you'd invoke a sub-agent: a single
  // contained turn that streams the agents working. /crew <customer|deal> analyses
  // one deal; /team (manager) fans out one analyst per rep. No new endpoint round
  // trip here — CrewTurn opens the stream itself and caches its own state.
  function runCrew(body: string, deal: string) {
    const clean = body.trim();
    const d = deal ? deals.find((x) => x.deal_id === deal) : undefined;
    const query = clean || (d ? `${d.deal_id} ${d.customer}` : "");
    if (!query) return;
    const id = nextId();
    setMessages((m) => [
      ...m,
      { id: nextId(), role: "user", text: `/crew ${query}` },
      { id, role: "crew", mode: "deal", query, label: d?.customer },
    ]);
    setInput("");
    setDealId("");
  }

  function runTeam() {
    const id = nextId();
    setMessages((m) => [
      ...m,
      { id: nextId(), role: "user", text: "/team" },
      { id, role: "crew", mode: "team" },
    ]);
    setInput("");
    setDealId("");
  }

  function runIntel(query: string) {
    const clean = query.trim();
    if (!clean || busy) return;
    const id = nextId();
    setMessages((m) => [
      ...m,
      { id: nextId(), role: "user", text: `/intel ${clean}` },
      { id, role: "intel", query: clean },
    ]);
    setInput("");
  }

  function runChat(text: string, deal?: string) {
     const clean = text.trim();
     if (!clean || busy) return;
     // Snapshot the conversation BEFORE appending this turn, so the assistant
     // turn carries the real prior history (shared thread context lives on the
     // server, keyed by thread.current).
     const history = buildChatHistory(messages);
     const replyId = nextId();
     // An attached file's text rides along as context for THIS turn only, then
     // the chip clears (it is not persisted into thread history).
     const ctx = attached?.text || undefined;
     // A deal picked from the Deal selector grounds the turn as a STRUCTURED field
     // (dealId), not by appending prose to the message. The backend scopes to that
     // exact deal directly — the model never has to re-resolve it from prose, and
     // the message it reasons over stays clean. The user bubble shows a deal badge.
     const d = deal ? deals.find((x) => x.deal_id === deal) : undefined;
     const userText = attached ? `📎 ${attached.fileName} — ${clean}` : clean;
     setMessages((m) => [
       ...m,
       { id: nextId(), role: "user", text: userText, dealLabel: d?.customer },
       { id: replyId, role: "assistant", text: clean, history, context: ctx, dealId: d?.deal_id },
     ]);
     setInput("");
     setAttached(null);
  }

  // Clear the conversation: empty the transcript and mint a fresh thread id so
  // the server-side conversation context (account in focus, history) starts clean.
  function clearThread() {
    if (busy) return;
    setMessages([]);
    setInput("");
    setDealId("");
    thread.reset();
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
    } else if (p.command === "crew") {
      runCrew(p.body, deal);
    } else if (p.command === "team") {
      runTeam();
    } else if (p.command === "intel") {
      runIntel(p.body);
    } else {
      runChat(p.body || raw.trim(), deal);
    }
    setDealId("");
  }

  // Picking an ambiguous candidate resolves the SAME review turn in place: re-run
  // the coach grounded on the chosen deal (or, if it has no open deal, on the full
  // name so it resolves uniquely) and swap in the grounded artifact. Because the
  // artifact id changes, ReviewTurn (keyed on it) remounts and streams the senior's
  // read for the chosen customer — no new user bubble, no second card, same thread.
  async function onPick(turnId: number, deal: string, name: string) {
    if (busy) return;
    const target = messages.find(
      (m): m is Extract<WMsg, { role: "skill"; kind: "review" }> =>
        m.id === turnId && m.role === "skill" && m.kind === "review",
    );
    const baseNote = target?.note ?? "";
    const groundNote = deal ? baseNote : `${name} ${baseNote}`.trim();
    setBusy(true);
    const { data, live } = await api.coach(groundNote, deal || undefined);
    const d = deals.find((x) => x.deal_id === deal);
    const entity: EntityRef | undefined = deal ? { type: "deal", id: deal, name: d?.customer } : undefined;
    const artifact = assembleReviewArtifact(data, {
      threadId: thread.current, turnId: String(turnId), live, entity,
    });
    setMessages((m) =>
      m.map((msg) =>
        msg.id === turnId && msg.role === "skill" && msg.kind === "review"
          ? { id: turnId, role: "skill", kind: "review", note: groundNote, dealId: deal || undefined, artifact }
          : msg,
      ),
    );
    setBusy(false);
  }

  // Picking an ambiguous candidate on a CHAT turn resolves in place: re-run the
  // same assistant turn grounded on the chosen customer (name prefixed so it
  // resolves uniquely) by bumping `runId` — ChatTurn is keyed on it, so it
  // remounts with a fresh cache slot and streams the grounded answer into the
  // same turn. No new user bubble; mirrors the /review, /account, /research picks.
  function onPickChat(turnId: number, c: ResolveCandidate, query: string) {
    setMessages((m) =>
      m.map((msg) =>
        msg.id === turnId && msg.role === "assistant"
          ? { ...msg, text: `${c.name} ${query}`.trim(), answer: undefined, runId: (msg.runId ?? 0) + 1 }
          : msg,
      ),
    );
  }

  // Picking a research candidate resolves the SAME research turn in place: re-run
  // grounded on the chosen customer (name prefixed so it resolves uniquely) and
  // swap in a fresh artifact. The artifact id changes, so ResearchTurn (keyed on
  // it) remounts and re-streams — no new user bubble, same thread/turn. Mirrors
  // the /review and /account in-place picks.
  function onPickResearch(turnId: number, c: ResolveCandidate) {
    const target = messages.find(
      (m): m is Extract<WMsg, { role: "skill"; kind: "research" }> =>
        m.id === turnId && m.role === "skill" && m.kind === "research",
    );
    const baseQuery = target?.query ?? "";
    const groundQuery = `${c.name} ${baseQuery}`.trim();
    const entity: EntityRef = { type: "account", id: c.customer_id, name: c.name };
    const artifact = assembleResearchArtifact({
      threadId: thread.current, turnId: String(turnId), live: true, lang,
      answer: "", sources: [], webUrls: [], entity,
    });
    setMessages((m) =>
      m.map((msg) =>
        msg.id === turnId && msg.role === "skill" && msg.kind === "research"
          ? { id: turnId, role: "skill", kind: "research", query: groundQuery, entity, artifact }
          : msg,
      ),
    );
  }

  return (
    <div className={cn("mx-auto flex h-full w-full flex-col min-h-0", wide ? "max-w-5xl" : "max-w-3xl")}>
      {/* Conversation controls pinned to the top-right of the chat pane, where
          they are immediately discoverable — instead of being buried inside the
          composer toolbar next to Mic/Attach/Send. */}
      <div className="flex items-center justify-end gap-1.5 shrink-0 pt-3 pb-2 pr-1">
        <button
          onClick={() => setHistoryOpen(true)}
          title={lang === "ja" ? "チャット履歴" : "Chat history"}
          className="inline-flex h-8 items-center gap-1 rounded-lg border border-border bg-card px-2.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground"
        >
          <History className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">{lang === "ja" ? "履歴" : "History"}</span>
        </button>
        {messages.length > 0 && (
          <button
            onClick={clearThread}
            disabled={busy}
            title={lang === "ja" ? "新しい会話" : "New chat"}
            className="inline-flex h-8 items-center gap-1 rounded-lg border border-border bg-card px-2.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
          >
            <Trash2 className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{lang === "ja" ? "新規" : "New chat"}</span>
          </button>
        )}
      </div>
      <div className="flex-1 overflow-y-auto space-y-8 pb-6 pr-1 pt-1 min-h-0">
        {messages.length === 0 && (
          <div className="pt-1.5 pb-6">
            <p className="text-[15px] font-medium tracking-tight text-foreground">
              {lang === "ja" ? "Senpai ワークスペース" : "Senpai Workspace"}
            </p>
            <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">
              {lang === "ja"
                ? "顧客を調査する、商談をレビューする、戦略を立案する。"
                : "Investigate a customer, review a deal, build a strategy."}
            </p>

            <div className="mt-6">
              <div className="eyebrow mb-2.5">
                {lang === "ja" ? "スキルのショートカット" : "Skill shortcuts"}
              </div>
              <div className="flex flex-col gap-1">
                {[
                  {
                    chip: "/review",
                    hint: lang === "ja" ? "商談メモを貼り付けてレビュー" : "Paste a meeting note and review it",
                    value: "/review ",
                  },
                  {
                    chip: "/account Matsuda Office",
                    hint: lang === "ja" ? "松田事務所の顧客ブリーフを取得" : "Pull account brief for Matsuda Office",
                    value: "/account Matsuda Office",
                  },
                  {
                    chip: "/research discount strategy",
                    hint: lang === "ja" ? "値引き戦略を社内記録+Webで調査" : "Research discount strategy across internal + web",
                    value: "/research discount strategy",
                  },
                  {
                    chip: "/crew D168",
                    hint: lang === "ja" ? "案件D168の攻略プランを作成" : "Build a strategy for deal D168",
                    value: "/crew D168",
                  },
                  {
                    chip: "/team",
                    hint: lang === "ja" ? "要注意案件とパイプライン概況を確認" : "Review at-risk deals and pipeline status",
                    value: "/team",
                  },
                ].filter(s => role === "manager" || s.chip !== "/team").map((s) => (
                  <button
                    key={s.chip}
                    disabled={busy}
                    onClick={() => {
                      setInput(s.value);
                      setShowPicker(false);
                      composerRef.current?.focus();
                    }}
                    className="flex items-center gap-2.5 rounded-lg border border-border bg-card px-3 py-2 text-left font-mono text-[12.5px] transition-colors hover:border-primary/40 hover:bg-primary/[0.03] disabled:opacity-50 shadow-sm"
                  >
                    <span className="font-semibold text-foreground">{s.chip}</span>
                    <span className="ml-auto text-[11px] font-sans text-muted-foreground">{s.hint}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {messages.map((m) => {
          if (m.role === "user") {
            return (
              <Row key={m.id} who="user" name={t("chat.you")}>
                <div className="py-0.5">
                  {m.dealLabel && (
                    <Badge variant="accent" className="mb-2 font-jp">{m.dealLabel}</Badge>
                  )}
                  <span className="block whitespace-pre-wrap text-[13.5px] leading-relaxed text-foreground/90">{m.text}</span>
                </div>
              </Row>
            );
          }
          if (m.role === "system") {
            return (
              <Row key={m.id} who="senpai" name={assistantName}>
                <p className="py-0.5 text-[13px] leading-relaxed text-muted-foreground">
                  {m.text}
                </p>
              </Row>
            );
          }
          if (m.role === "loading") {
            return (
              <Row key={m.id} who="senpai" name={assistantName}>
                <div className="inline-flex items-center gap-2 py-1.5 text-[13px] text-muted-foreground">
                  <Dots /> {t(role === "manager" ? "chat.thinking.manager" : "chat.thinking")}
                </div>
              </Row>
            );
          }
          if (m.role === "assistant") {
            return (
              <Row key={m.id} who="senpai" name={assistantName}>
                <ChatTurn
                  key={`${m.id}:${m.runId ?? 0}`}
                  turnId={m.id}
                  runId={m.runId ?? 0}
                  message={m.text}
                  history={m.history}
                  role={role}
                  conversationId={thread.current}
                  context={m.context}
                  dealId={m.dealId}
                  onDone={(text) =>
                    setMessages((prev) => prev.map((msg) => (msg.id === m.id ? { ...msg, answer: text } : msg)))
                  }
                  onPick={(c, q) => onPickChat(m.id, c, q)}
                />
              </Row>
            );
          }
          if (m.role === "account_pick") {
            return (
              <Row key={m.id} who="senpai" name={assistantName}>
                <AccountPickTurn
                  candidates={m.candidates}
                  suggestedId={m.suggestedId}
                  lang={lang}
                  onPick={(customerId) => {
                    if (busy) return;
                    setBusy(true);
                    // Resolve in place: turn THIS picker turn into the loading →
                    // account brief, with no new "/account <id>" user bubble and
                    // no extra turn — mirrors the in-place /review candidate pick
                    // so the conversation stays in the same turn for both skills.
                    setMessages((prev) => prev.map((msg) =>
                      msg.id === m.id ? { id: m.id, role: "loading" as const } : msg));
                    _loadAccountById(customerId, m.id);
                  }}
                />
              </Row>
            );
          }
          if (m.role === "skill") {
            return (
              <Row key={m.id} who="senpai" name={assistantName}>
                {m.kind === "review" && <ReviewTurn key={m.artifact.id} turnId={m.id} artifact={m.artifact} note={m.note} dealId={m.dealId} principles={principles} onPick={onPick} />}
                {m.kind === "account_brief" && <AccountTurn key={m.artifact.id} artifact={m.artifact} customerId={m.customerId} />}
                {m.kind === "research" && <ResearchTurn key={m.artifact.id} turnId={m.id} artifact={m.artifact} query={m.query} entity={m.entity} onPick={onPickResearch} />}
              </Row>
            );
          }
          if (m.role === "crew") {
            return (
              <CrewTurn key={m.id} turnId={m.id} conversationId={thread.current} mode={m.mode} query={m.query} label={m.label} />
            );
          }
          if (m.role === "intel") {
            return (
              <IntelTurn key={m.id} turnId={m.id} conversationId={thread.current} query={m.query} />
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
              role={role}
              onSelect={(cmd) => {
                setInput(cmd);
                setShowPicker(false);
                composerRef.current?.focus();
              }}
              onClose={() => setShowPicker(false)}
            />
          )}
          <div className="rounded-2xl border border-border bg-card p-2.5 shadow-[0_8px_30px_-22px_rgba(16,24,40,0.45)] focus-within:border-primary/40">
            {attached && (
              <div className="mb-2 flex items-center gap-2 rounded-lg border border-border bg-muted/50 px-2.5 py-1.5">
                <Paperclip className="h-3.5 w-3.5 shrink-0 text-navy" />
                <span className="truncate font-mono text-[11px] text-foreground">{attached.fileName}</span>
                {attached.text
                  ? <span className="shrink-0 text-[10.5px] text-muted-foreground">{t("attach.chars", { n: String(attached.text.length) })}</span>
                  : <span className="shrink-0 text-[10.5px] text-band-red">{t("attach.empty")}</span>}
                <button
                  onClick={() => setAttached(null)}
                  title={t("attach.remove")}
                  className="ml-auto inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
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
              {/* Grounds /review (and /research) on a deal. Single source of
                  truth with the Context pane via shared focus: a deal clicked on
                  the left shows here as one chip; ✕ drops the grounding. When
                  nothing is focused, a compact picker lets standalone callers
                  (e.g. the Manager workspace, which has no Context pane) attach
                  one — and that selection writes focus too, so they stay synced. */}
              {dealId ? (
                <span className="flex h-8 max-w-[62%] items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/[0.06] pl-2.5 pr-1 text-[12px] text-primary">
                  <Paperclip className="h-3.5 w-3.5 shrink-0" />
                  {/* Canonical Japanese company name regardless of UI lang. */}
                  <span className="truncate font-jp">{deals.find((d) => d.deal_id === dealId)?.customer ?? dealId}</span>
                  <button
                    type="button"
                    title={lang === "ja" ? "対象の案件を解除" : "Clear focused deal"}
                    onClick={() => {
                      setDealId("");
                      setFocus({});
                      lastFocusDeal.current = undefined;
                    }}
                    className="ml-0.5 shrink-0 rounded p-1 transition-colors hover:bg-primary/10"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </span>
              ) : (
                <label
                  title={lang === "ja" ? "レビュー対象の案件を指定（任意）" : "Attach a deal to ground /review (optional)"}
                  className="flex h-8 max-w-[62%] items-center gap-1.5 rounded-lg border border-input bg-muted/40 pl-2.5 pr-1 text-[12px] text-muted-foreground transition-colors focus-within:border-primary/50"
                >
                  <Building2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
                  <span className="hidden shrink-0 sm:inline">{lang === "ja" ? "案件" : "Deal"}</span>
                  <select
                    value=""
                    onChange={(e) => {
                      const id = e.target.value;
                      if (!id) return;
                      const d = deals.find((x) => x.deal_id === id);
                      setDealId(id);
                      setFocus({ dealId: id, customerId: d?.customer_id, customerName: d?.customer });
                      lastFocusDeal.current = id;
                    }}
                    className="h-8 min-w-0 flex-1 cursor-pointer bg-transparent pr-1 text-[12px] outline-none [&>option]:text-foreground"
                  >
                    <option value="">{lang === "ja" ? "案件を指定（任意）" : "Attach a deal…"}</option>
                    {deals.map((d) => (
                      <option key={d.deal_id} value={d.deal_id}>
                        {d.deal_id} · {d.customer}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <div className="flex items-center gap-2">
                {/* Attach a file as context — its text is extracted (POST
                    /api/extract) and the assistant answers over it. Structured
                    data ingestion is a separate flow (Data Ingestion tab). */}
                <input
                  ref={fileRef}
                  type="file"
                  accept="audio/*,image/*,text/*,.txt,.md,.csv"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) attachFile(f);
                    e.target.value = "";
                  }}
                />
                {/* Mic dictation — record, then transcribe straight into the
                    composer via the same Whisper path as the audio attach. */}
                <button
                  onClick={toggleRecording}
                  disabled={busy || attaching || transcribing}
                  title={recording ? t("mic.stop") : t("mic.start")}
                  className={cn(
                    "inline-flex h-8 items-center gap-1 rounded-lg border px-2.5 text-[12px] transition-colors disabled:opacity-50",
                    recording
                      ? "border-band-red/40 bg-band-red/10 text-band-red"
                      : "border-border bg-card text-muted-foreground hover:text-foreground",
                  )}
                >
                  {transcribing
                    ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    : recording
                      ? <Square className="h-3.5 w-3.5 animate-pulse fill-current" />
                      : <Mic className="h-3.5 w-3.5" />}
                  <span className="hidden sm:inline">
                    {transcribing ? t("mic.transcribing") : recording ? t("mic.stop") : t("mic.short")}
                  </span>
                </button>
                <button
                  onClick={() => fileRef.current?.click()}
                  disabled={busy || attaching}
                  title={t("attach.title")}
                  className="inline-flex h-8 items-center gap-1 rounded-lg border border-border bg-card px-2.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
                >
                  {attaching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Paperclip className="h-3.5 w-3.5" />}
                  <span className="hidden sm:inline">{t("attach.short")}</span>
                </button>
                <Button variant="seal" size="sm" disabled={busy || !input.trim()} onClick={() => submit(input, dealId)} className="gap-1.5">
                  {t(role === "manager" ? "chat.send.manager" : "chat.send")} <CornerDownLeft className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        employeeId={employeeId}
        role={histRole}
        activeId={thread.current}
        reloadSignal={savedTick}
        onSelect={loadConversation}
        onDeletedActive={clearThread}
      />
    </div>
  );
}
