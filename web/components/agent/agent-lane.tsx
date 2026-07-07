"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Execution model ──────────────────────────────────────────────────────────
// One intelligent system investigating a customer. The timeline tells a story:
//   □  Understanding the account    ← pending (dim, preview only)
//   □  Building recommendations     ← pending
//   ●  Reviewing deal dynamics       ← running (prominent)
//      ✓  Retrieved customer history
//      ✓  Compared similar customers
//      ●  Evaluating account health  ← current step (pulse)
//   ✓  Research complete             ← done (collapsed to summary)
//
// Phase IDs → user-centric labels (client-side; backend agent names stay stable)
export interface PhaseTool {
  name: string;
  summary: string;
}
export interface ExecutionPhase {
  id: string;
  label: string;  // backend label — overridden by PHASE_LABELS map below
  emoji: string;  // kept on type for event contract; never rendered
  status: "pending" | "running" | "done";
  tools: PhaseTool[];
  resultHint?: string;
  contribution?: string;
  group?: string;          // task DAG group (e.g. "gather" | "documents") — which lanes ran in parallel
  citationCount?: number;  // real evidence citation count for this phase, for the receipt line / bundle node
  startedAt?: number;      // Date.now() when the phase started — client-received, honest elapsed-time proxy
  endedAt?: number;        // Date.now() when the phase settled to "done"
}

// "アウトライン生成: N枚" | "スライドN: title" | "セクションN: title" | "レンダリング中"
// → a structured step, so the document-generation hero can render a real
// slide/section list instead of re-parsing the Japanese progress string itself.
export type DocumentProgressStep =
  | { kind: "outline"; total: number }
  | { kind: "slide" | "section"; index: number; title: string }
  | { kind: "rendering" }
  | { kind: "other"; text: string };

export function parseDocumentProgress(summary: string): DocumentProgressStep {
  let m = summary.match(/^アウトライン生成:\s*(\d+)枚/);
  if (m) return { kind: "outline", total: Number(m[1]) };
  m = summary.match(/^スライド(\d+):\s*(.*)$/);
  if (m) return { kind: "slide", index: Number(m[1]), title: m[2] };
  m = summary.match(/^セクション(\d+):\s*(.*)$/);
  if (m) return { kind: "section", index: Number(m[1]), title: m[2] };
  if (/^レンダリング中/.test(summary)) return { kind: "rendering" };
  return { kind: "other", text: summary };
}

// ─── Narrative label maps ─────────────────────────────────────────────────────
// Maps backend agent ids → user-centric language.
// The backend labels stay stable; the FE owns the story.
export const PHASE_LABELS_EN: Record<string, string> = {
  researcher:  "Understanding the account",
  coach:       "Reviewing deal dynamics",
  strategist:  "Building recommendations",
  analyst:     "Analysing representative",
  team_lead:   "Synthesising team view",
  // Document-planner capability ids (senpai/planner/capabilities.py _GATHER_ORDER
  // + terminal tasks) — same ids TOOL_LABEL already keys off in message.tsx.
  conversation: "Reading conversation context",
  workspace:    "Checking local documents",
  crm:          "Checking internal records",
  knowledge:    "Searching internal knowledge",
  solutions:    "Searching solutions & products",
  web:          "Searching the web",
  documents:    "Generating document",
  workspace_write:    "Saving note",
  workspace_organize: "Organizing workspace",
};
export const PHASE_LABELS_JA: Record<string, string> = {
  researcher:  "アカウントを調査中",
  coach:       "商談を評価中",
  strategist:  "戦略を立案中",
  analyst:     "担当者を分析中",
  team_lead:   "チームを俯瞰中",
  conversation: "会話の文脈を確認中",
  workspace:    "ローカル文書を確認中",
  crm:          "社内記録を確認中",
  knowledge:    "社内ナレッジを検索中",
  solutions:    "ソリューション・製品情報を検索中",
  web:          "Web検索中",
  documents:    "資料を生成中",
  workspace_write:    "メモを保存中",
  workspace_organize: "フォルダを整理中",
};

// ─── Tool summary translations ────────────────────────────────────────────────
// Maps Japanese backend summaries → English user-centric phrasing.
const TOOL_SUMMARY_EN: Record<string, string> = {
  // researcher tools
  "類似の成約事例を照合":           "Comparing similar customers",
  "関連する日報の課題シグナル":      "Reviewing recent activity",
  "顧客のIT環境":                  "Checking IT environment",
  // coach tools
  "健全性スコアとリスク信号":        "Evaluating account health",
  // rep analyst tools
  "要注意案件の抽出":               "Identifying at-risk deals",
};

// Handles "D001 の案件サマリーと直近活動" → "Retrieved customer history"
export function translateToolSummary(summary: string, lang: "ja" | "en"): string {
  if (lang === "ja") return summary;
  // Exact match first
  if (TOOL_SUMMARY_EN[summary]) return TOOL_SUMMARY_EN[summary];
  // Dynamic: "X の案件サマリーと直近活動"
  if (summary.includes("案件サマリーと直近活動")) return "Retrieved customer history";
  // Dynamic: "X のパイプライン概況"
  if (summary.includes("パイプライン概況")) return "Reviewing pipeline status";
  return summary;
}

export function phaseLabel(phase: ExecutionPhase, lang: "ja" | "en"): string {
  const map = lang === "ja" ? PHASE_LABELS_JA : PHASE_LABELS_EN;
  return map[phase.id] ?? phase.label;
}

// ─── ExecutionTimeline — exported, collapsible ────────────────────────────────
export function ExecutionTimeline({
  phases,
  collapsed,
  onToggle,
  lang = "en",
}: {
  phases: ExecutionPhase[];
  collapsed: boolean;
  onToggle: () => void;
  lang?: "ja" | "en";
}) {
  if (phases.length === 0) return null;

  if (collapsed) {
    return (
      <div className="flex items-center gap-2">
        <span className="font-mono text-[11px] text-foreground/30">✓</span>
        <span className="text-[12.5px] text-foreground/50">
          {lang === "ja" ? "調査完了" : "Investigation complete"}
        </span>
        <button
          onClick={onToggle}
          className="ml-1 inline-flex items-center gap-1 text-[11.5px] text-muted-foreground/60 transition-colors hover:text-muted-foreground"
        >
          <ChevronDown className="h-3 w-3" />
          {lang === "ja" ? "詳細を表示" : "View details"}
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {phases.map((phase) => (
        <PhaseSection key={phase.id} phase={phase} lang={lang} />
      ))}
      {/* Collapse handle — only once all done */}
      {phases.every((p) => p.status === "done") && (
        <button
          onClick={onToggle}
          className="mt-1 inline-flex items-center gap-1 self-start text-[11.5px] text-muted-foreground/50 transition-colors hover:text-muted-foreground"
        >
          <ChevronDown className="h-3 w-3 rotate-180" />
          {lang === "ja" ? "折りたたむ" : "Collapse"}
        </button>
      )}
    </div>
  );
}

// ─── Legacy export (crew-turn.tsx uses this during migration) ─────────────────
export function ExecutionLog({ phases }: { phases: ExecutionPhase[] }) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <ExecutionTimeline
      phases={phases}
      collapsed={collapsed}
      onToggle={() => setCollapsed((v) => !v)}
    />
  );
}

// ─── Phase section ────────────────────────────────────────────────────────────
function PhaseSection({ phase, lang }: { phase: ExecutionPhase; lang: "ja" | "en" }) {
  const label = phaseLabel(phase, lang);
  const isPending = phase.status === "pending";
  const isRunning = phase.status === "running";
  const isDone    = phase.status === "done";

  return (
    <div
      className={cn(
        "flex flex-col gap-1 transition-opacity duration-500",
        isPending && "opacity-35",
      )}
    >
      {/* Phase header */}
      <div className="flex items-center gap-2.5">
        <span
          className={cn(
            "w-3 shrink-0 select-none text-center font-mono text-[11px] leading-none",
            isDone    && "text-foreground/35",
            isRunning && "text-primary/80",
            isPending && "text-foreground/25",
          )}
        >
          {isDone ? "✓" : "□"}
        </span>
        <span
          className={cn(
            "text-[13px] leading-snug transition-colors duration-300",
            isDone    && "font-normal text-foreground/50",
            isRunning && "font-medium text-foreground",
            isPending && "font-normal text-foreground/40",
          )}
        >
          {label}
        </span>
        {/* Running indicator — subtle pulse dot next to the active phase label */}
        {isRunning && (
          <span className="execution-pulse inline-block h-1.5 w-1.5 rounded-full bg-primary/70 shrink-0" />
        )}
      </div>

      {/* Tool steps — only shown when running or done; hidden for pending */}
      {!isPending && phase.tools.length > 0 && (
        <div className="flex flex-col gap-[3px] pl-[22px]">
          {phase.tools.map((tl, i) => {
            const isCurrentStep = isRunning && i === phase.tools.length - 1;
            const isCompleted   = isDone || (!isCurrentStep);
            return (
              <div
                key={`${tl.name}-${i}`}
                className="animate-in fade-in slide-in-from-top-1 flex items-baseline gap-2.5 duration-300"
              >
                <span
                  className={cn(
                    "w-3 shrink-0 select-none text-center font-mono text-[11px] leading-none transition-colors duration-400",
                    isCurrentStep ? "text-primary"           : "text-foreground/30",
                  )}
                >
                  {isCurrentStep
                    ? <span className="execution-pulse inline-block">●</span>
                    : <span className="animate-checkmark-pop inline-block">✓</span>
                  }
                </span>
                <span
                  className={cn(
                    "min-w-0 text-[12.5px] leading-snug transition-colors duration-400",
                    isCurrentStep ? "text-foreground"      : "text-foreground/45",
                  )}
                >
                  {translateToolSummary(tl.summary || tl.name, lang)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
