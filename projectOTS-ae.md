]


# --- Documents capability consumes the bundle (does not re-gather) ---------------
def _ctx(deps: dict) -> ExecContext:
    return ExecContext(task_id="documents", inputs={}, deps=deps,
                       emit=lambda _m: None, expand=lambda _t: None,
                       cancel=threading.Event(), deadline=9e18)


def test_documents_grounding_assembles_deps_in_order():
    cap = DocumentsCapability()
    deps = {
        "web": Evidence(status="ok", data={"text": "W", "label": "Web検索"}, capability="web"),
        "conversation": Evidence(status="ok", data={"text": "C", "label": "会話"},
                                 capability="conversation"),
        "crm": Evidence(status="ok", data={"text": "R", "label": "社内データ"}, capability="crm"),
    }
    g = cap._grounding(_ctx(deps))
    # Most-specific first: conversation, then crm, then web (workspace/knowledge absent).
    assert g.index("会話") < g.index("社内データ") < g.index("Web検索")


# --- chat routing: document goals go to the planner, everything else doesn't ----
def test_document_goal_router_precision():
    from senpai.api.server import _is_document_goal
    routed = [
        "make a proposal for Murata Printing", "create a deck on gaming laptops",
        "generate a pptx for D168", "村田印刷の提案書を作って", "スライドを作成して",
        "write me a report on Q4 trends", "put together a slide deck for the client",
    ]
    not_routed = [
        "draft an email to the client", "make a quote for 3 monitors",
        "tell me about Murata Printing", "what did we quote yamato in my files?",
        "schedule a meeting with endo", "D168 のリスクを教えて",
        "稟議書を作成して", "make a ringisho for D001",   # ringisho keeps its own tool
    ]
    assert all(_is_document_goal(m) for m in routed)
    assert not any(_is_document_goal(m) for m in not_routed)


def test_selector_deal_id_is_authoritative():
    # A deal picked in the selector overrides text resolution and forces a proposal.
    from senpai.planner.selection import heuristic_selection
    sel = heuristic_selection("make a deck about our storage solutions", deal_hint="D001")
    assert sel.deal_id == "D001"
    assert sel.doc_kind == "proposal"


def test_authored_deck_degrades_without_model(_tmp_generated):
    # pptx authoring needs a model; with SENPAI_USE_LLM off it must return a clean
    # error fragment (no crash, no file).
    cap = DocumentsCapability()
    ev = cap.run("pptx", {"goal": "best gaming laptops"}, _ctx({}))
    assert ev.status == "error"
    assert not _tmp_generated.exists() or not list(_tmp_generated.glob("*.pptx"))


# --- workspace WRITE terminals: note + organize (hermetic, GPU-free) -------------
def test_organize_previews_then_applies(tmp_path, monkeypatch):
    from senpai import config
    from senpai.planner import run_document_goal

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "murata_見積書.txt").write_text("q", encoding="utf-8")
    (ws / "yamato_proposal.md").write_text("p", encoding="utf-8")
    (ws / "endo_議事録.md").write_text("m", encoding="utf-8")
    monkeypatch.setattr(config, "WORKSPACE_ROOT", ws)

    # Preview never moves anything.
    prev = run_document_goal("organize my files")
    assert prev["selection"]["doc_kind"] == "organize"
    assert {p.name for p in ws.iterdir() if p.is_file()} == {
        "murata_見積書.txt", "yamato_proposal.md", "endo_議事録.md"}

    # Apply files each loose doc into some topic subfolder, leaving nothing at the
    # root. (Assert the behaviour, not specific folder names — the classifier's
    # taxonomy is config that may be tuned.)
    run_document_goal("organize my files and apply")
    assert not [p for p in ws.iterdir() if p.is_file()]          # nothing loose at the root
    moved = {q.name for sub in ws.iterdir() if sub.is_dir() for q in sub.iterdir()}
    assert {"murata_見積書.txt", "yamato_proposal.md", "endo_議事録.md"} <= moved


def test_organize_apply_continuation(tmp_path, monkeypatch):
    """The confirm flow: 'organize my files' previews; a following affirmation ('go
    ahead' / 'yes') with the preview in history APPLIES it — it must NOT be re-routed
    to document generation (the docx-hallucination bug)."""
    from senpai import config
    from senpai.planner import run_document_goal
    from senpai.planner.selection import is_planner_goal, heuristic_selection

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "murata_quote.txt").write_text("q", encoding="utf-8")
    monkeypatch.setattr(config, "WORKSPACE_ROOT", ws)
    monkeypatch.setattr(config, "GENERATED_DIR", tmp_path / "gen")

    r1 = run_document_goal("organize my files")
    assert r1["selection"]["doc_kind"] == "organize"
    assert not any(p.is_dir() for p in ws.iterdir())         # preview moved nothing

    convo = [
        {"role": "user", "content": "organize my files"},
        {"role": "assistant", "content": r1["text"]},        # carries 【整理プレビュー
        {"role": "user", "content": "go ahead"},
    ]
    # Router keeps it in the planner (prior turns end with the preview)...
    assert is_planner_goal("go ahead", convo[:-1])
    # ...and selection resolves to an organize APPLY, never a document.
    sel = heuristic_selection("go ahead", history=convo)
    assert sel.doc_kind == "organize" and sel.confirm is True

    r2 = run_document_goal("go ahead", conversation=convo)
    assert r2["selection"]["doc_kind"] == "organize"
    assert r2["document"] is None                             # NOT a generated doc
    assert not [p for p in ws.iterdir() if p.is_file()]       # the file was moved
    assert any(p.is_dir() for p in ws.iterdir())

    # A bare 'go ahead' with no pending preview must NOT hit the planner.
    assert not is_planner_goal("go ahead", [])


def test_organize_move_is_sandbox_safe_and_no_overwrite(tmp_path, monkeypatch):
    from senpai import config
    from senpai.workspace import sandbox
    monkeypatch.setattr(config, "WORKSPACE_ROOT", tmp_path)
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_text("2", encoding="utf-8")
    with pytest.raises(sandbox.SandboxError):
        sandbox.move_within("a.txt", "../escape.txt")         # can't leave the root
    with pytest.raises(sandbox.SandboxError):
        sandbox.move_within("a.txt", "sub/a.txt")             # never overwrites


def test_note_write_persists_grounded_file(tmp_path, monkeypatch):
    from senpai import config
    from senpai.planner import run_document_goal

    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(config, "WORKSPACE_ROOT", ws)
    monkeypatch.setattr(config, "GENERATED_DIR", tmp_path / "gen")
    convo = [
        {"role": "assistant", "content": "村田印刷は¥204,000の見積を提示済み。"},
        {"role": "user", "content": "save this as a note to murata_followup.md"},
    ]
    r = run_document_goal("save this as a note to murata_followup.md", conversation=convo)
    assert r["selection"]["doc_kind"] == "note"
    saved = ws / "murata_followup.md"
    assert saved.is_file()
    assert "204,000" in saved.read_text(encoding="utf-8")     # grounded on the conversation


# --- opt-in integration: exercise the REAL configured workspace (skipped if absent) --
def test_real_workspace_is_searchable_if_configured():
    """Unit tests are hermetic on purpose; this one intentionally hits the *configured*
    WORKSPACE_ROOT so 'does it see my real folder' is covered — skipped when that folder
    doesn't exist (CI / another machine), so it never makes the suite fragile."""
    from senpai.workspace import sandbox
    root = sandbox.workspace_root()
    if not root.is_dir():
        pytest.skip(f"configured WORKSPACE_ROOT does not exist: {root}")
    docs = sandbox.list_documents()
    # Whatever is there, discovery must stay inside the root and never surface our own
    # generated output (the feedback-loop guard).
    assert all("generated" not in sandbox.rel(p).lower().split("/")[0] for p in docs)
````

## File: web/app/login/page.tsx
````typescript
"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, KeyRound, LayoutDashboard, UserRound } from "lucide-react";
import { useT } from "@/lib/i18n";
import { demoCreds, useSession, type Role } from "@/lib/session";
import { Brand } from "@/components/site/brand";
import { ClientBadge } from "@/components/site/client-badge";
import { LangToggle } from "@/components/site/lang-toggle";
import { Button } from "@/components/ui/button";

function LoginForm() {
  const { t } = useT();
  const router = useRouter();
  const { login } = useSession();
  const params = useSearchParams();
  const role: Role = params.get("role") === "manager" ? "manager" : "junior";
  const creds = demoCreds(role);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(false);

  const Icon = role === "manager" ? LayoutDashboard : UserRound;
  const accent = role === "manager" ? "text-navy" : "text-primary";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const resolved = await login(role, username, password);
    if (resolved) {
      router.replace(resolved === "manager" ? "/manager" : "/junior");
    } else {
      setError(true);
    }
  }

  return (
    <div className="hero-wash flex min-h-screen flex-col">
      <header className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-5">
        <Brand fullMark tagline={t("app.tagline")} />
        <div className="flex items-center gap-3 sm:gap-4">
          <ClientBadge />
          <div className="hidden h-5 w-px bg-border sm:block" />
          <LangToggle />
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center px-6 pb-16">
        <div className="w-full max-w-sm">
          <Link href="/" className="mb-6 inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground">
            <ArrowLeft className="h-3.5 w-3.5" /> {t("login.switchRole")}
          </Link>

          <div className="rounded-2xl border border-border bg-card p-7 shadow-[0_8px_40px_-24px_rgba(16,24,40,0.4)]">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted">
                <Icon className={`h-5 w-5 ${accent}`} />
              </div>
              <div>
                <h1 className="text-lg font-semibold tracking-tight">
                  {t("login.title", { role: t(role === "manager" ? "role.manager" : "role.junior") })}
                </h1>
                <p className="text-[12px] text-muted-foreground">{t("login.subtitle")}</p>
              </div>
            </div>

            <form onSubmit={submit} className="mt-6 space-y-3">
              <div className="space-y-1.5">
                <label className="eyebrow">{t("login.username")}</label>
                <input
                  value={username}
                  onChange={(e) => { setUsername(e.target.value); setError(false); }}
                  className="h-10 w-full rounded-lg border border-input bg-card px-3 text-[14px] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  autoComplete="off"
                />
              </div>
              <div className="space-y-1.5">
                <label className="eyebrow">{t("login.password")}</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); setError(false); }}
                  className="h-10 w-full rounded-lg border border-input bg-card px-3 text-[14px] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  autoComplete="off"
                />
              </div>
              {error && <p className="text-[12px] text-band-red">{t("login.error")}</p>}
              <Button type="submit" variant="seal" className="w-full">{t("login.submit")}</Button>
            </form>

            <div className="mt-5 rounded-lg border border-dashed border-border bg-muted/40 p-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                  <KeyRound className="h-3.5 w-3.5" /> {t("login.demo")}
                </div>
                <button
                  onClick={() => { setUsername(creds.username); setPassword(creds.password); setError(false); }}
                  className="text-[11px] font-medium text-primary hover:underline"
                >
                  {t("login.useThese")}
                </button>
              </div>
              <div className="mt-2 font-mono text-[12px] text-foreground">
                {creds.username} / {creds.password}
              </div>
            </div>

            {role === "junior" && (
              <p className="mt-5 text-center text-[12px] text-muted-foreground">
                {t("login.noAccount")}{" "}
                <Link href="/signup" className="font-medium text-primary hover:underline">
                  {t("login.createAccount")}
                </Link>
              </p>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
````

## File: web/app/manager/page.tsx
````typescript
import { api } from "@/lib/api";
import { currentEmployeeId } from "@/lib/server-session";
import { PageHeader } from "@/components/site/page-header";
import { ManagerDashboard } from "@/components/manager/manager-dashboard";

export const dynamic = "force-dynamic";

// Overview-first home: the full-width team dashboard (Overview / All deals /
// Flags), scoped to the logged-in manager's coachees. The Copilot is its own
// tab; "Ask the Copilot" on a deal jumps there pre-grounded.
export default async function ManagerHomePage() {
  const { data, live } = await api.dashboard(undefined, await currentEmployeeId());
  return (
    <div className="space-y-8">
      <PageHeader eyebrowKey="nav.home" titleKey="dash.title" leadKey="dash.lead" />
      <ManagerDashboard dashboard={data} live={live} />
    </div>
  );
}
````

## File: web/components/agent/agent-lane.tsx
````typescript
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
}

// ─── Narrative label maps ─────────────────────────────────────────────────────
// Maps backend agent ids → user-centric language.
// The backend labels stay stable; the FE owns the story.
const PHASE_LABELS_EN: Record<string, string> = {
  researcher:  "Understanding the account",
  coach:       "Reviewing deal dynamics",
  strategist:  "Building recommendations",
  analyst:     "Analysing representative",
  team_lead:   "Synthesising team view",
};
const PHASE_LABELS_JA: Record<string, string> = {
  researcher:  "アカウントを調査中",
  coach:       "商談を評価中",
  strategist:  "戦略を立案中",
  analyst:     "担当者を分析中",
  team_lead:   "チームを俯瞰中",
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
function translateToolSummary(summary: string, lang: "ja" | "en"): string {
  if (lang === "ja") return summary;
  // Exact match first
  if (TOOL_SUMMARY_EN[summary]) return TOOL_SUMMARY_EN[summary];
  // Dynamic: "X の案件サマリーと直近活動"
  if (summary.includes("案件サマリーと直近活動")) return "Retrieved customer history";
  // Dynamic: "X のパイプライン概況"
  if (summary.includes("パイプライン概況")) return "Reviewing pipeline status";
  return summary;
}

function phaseLabel(phase: ExecutionPhase, lang: "ja" | "en"): string {
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
````

## File: web/components/growth/growth-dashboard.tsx
````typescript
"use client";

import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  BookMarked,
  Building2,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Flame,
  GraduationCap,
  Layers,
  type LucideIcon,
  MessageCircle,
  MessagesSquare,
  Minus,
  Sparkles,
  Star,
} from "lucide-react";
import type {
  CoachingThread,
  CoachingThreadMessage,
  DealRow,
  GrowthResponse,
  SkillEvidence,
} from "@/lib/types";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { tagText, repText, departmentText, customerText } from "@/lib/content-i18n";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useState } from "react";
import { DealDrawer } from "@/components/dashboard/deal-drawer";

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function monthLabel(ym: string, lang: "ja" | "en"): string {
  const [y, m] = ym.split("-").map(Number);
  if (!y || !m) return ym;
  return new Date(y, m - 1, 1).toLocaleString(lang === "ja" ? "ja-JP" : "en-US", { month: "short" });
}

// Tailwind class (for legend dots) and actual CSS color (for SVG strokes)
const SKILL_COLORS: Record<string, string> = {
  relationship_building: "bg-blue-400",
  decision_maker_discovery: "bg-violet-400",
  customer_discovery: "#2dd4bf",
  closing_discipline: "bg-rose-400",
  proposal_pricing: "bg-amber-400",
};
const SKILL_STROKE: Record<string, string> = {
  relationship_building: "#60a5fa",
  decision_maker_discovery: "#a78bfa",
  customer_discovery: "#2dd4bf",
  closing_discipline: "#fb7185",
  proposal_pricing: "#fbbf24",
};

const STATUS_TONE: Record<string, string> = {
  open: "bg-band-red/10 text-band-red border-band-red/30",
  acknowledged: "bg-band-yellow/10 text-band-yellow border-band-yellow/30",
  resolved: "bg-conf-high/10 text-conf-high border-conf-high/30",
};

const STATUS_ORDER: Record<string, number> = { open: 0, acknowledged: 1, resolved: 2 };

const BAND_CHIP: Record<string, string> = { red: "🔴", yellow: "🟡", green: "🟢" };
const BAND_BG: Record<string, string> = {
  red: "border-band-red/20 bg-band-red/[0.03]",
  yellow: "border-band-yellow/20 bg-band-yellow/[0.03]",
  green: "border-conf-high/20 bg-conf-high/[0.03]",
};

// ---------------------------------------------------------------------------
// sub-components
// ---------------------------------------------------------------------------

function StatCard({ icon: Icon, value, label, sub, tone }: {
  icon: LucideIcon; value: number; label: string; sub?: string; tone: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      <span className={cn("inline-flex h-8 w-8 items-center justify-center rounded-lg", tone)}>
        <Icon className="h-4 w-4" />
      </span>
      <div className="mt-3 flex items-baseline gap-1.5">
        <span className="text-[26px] font-semibold leading-none tracking-tight text-foreground">{value}</span>
        {sub && <span className="text-[11px] text-muted-foreground">{sub}</span>}
      </div>
      <div className="mt-1 text-[12px] text-muted-foreground">{label}</div>
    </div>
  );
}

function JourneyStat({ n, label }: { n: number; label: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-[28px] font-semibold leading-none tracking-tight text-primary">{n}</span>
      <span className="text-[12.5px] text-foreground/70">{label}</span>
    </div>
  );
}

function Stars({ n }: { n: number }) {
  return (
    <span className="flex gap-0.5">
      {Array.from({ length: 5 }).map((_, i) => (
        <Star key={i} className={cn("h-4 w-4", i < n ? "fill-band-yellow text-band-yellow" : "fill-none text-muted-foreground/30")} />
      ))}
    </span>
  );
}

function TrendBadge({ trend }: { trend: string }) {
  const { t } = useT();
  if (trend === "improving") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded-full bg-conf-high/10 px-2 py-0.5 text-[10px] font-semibold text-conf-high">
        <ArrowUp className="h-3 w-3" />{t("growth.skill.trend.improving")}
      </span>
    );
  }
  if (trend === "needs_work") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded-full bg-band-red/10 px-2 py-0.5 text-[10px] font-semibold text-band-red">
        <ArrowDown className="h-3 w-3" />{t("growth.skill.trend.needs_work")}
      </span>
    );
  }
  return null;
}

function EvidenceChip({ ev }: { ev: SkillEvidence }) {
  const { t } = useT();
  const sourceLabel = t(`growth.skill.evidence.${ev.source}`);
  return (
    <div className={cn(
      "flex items-start gap-2 rounded-lg border px-3 py-2 text-[11.5px]",
      ev.positive
        ? "border-conf-high/25 bg-conf-high/[0.04] text-foreground/80"
        : "border-band-yellow/30 bg-band-yellow/[0.04] text-foreground/80",
    )}>
      {ev.positive
        ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-conf-high" />
        : <Minus className="mt-0.5 h-3.5 w-3.5 shrink-0 text-band-yellow" />}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="text-[9.5px] font-semibold uppercase tracking-wide text-muted-foreground">{sourceLabel}</span>
          {ev.deal_id && <span className="font-mono text-[9.5px] text-muted-foreground/60">{ev.deal_id}</span>}
          <span className="text-[9.5px] text-muted-foreground/50">{ev.date}</span>
        </div>
        <p className="mt-0.5 font-jp leading-snug">{ev.text}</p>
      </div>
    </div>
  );
}

function SkillCard({ skill, lang, selected, onSelect }: {
  skill: { key: string; stars: number; trend: string; evidence: SkillEvidence[]; insight: string };
  lang: "ja" | "en";
  selected: boolean;
  onSelect: (key: string | null) => void;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const stroke = SKILL_STROKE[skill.key];

  return (
    <div className={cn(
      "rounded-xl border bg-card shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-all",
      selected ? "border-[var(--sk-color)] shadow-[0_0_0_1px_var(--sk-color)]" : "border-border",
    )} style={{ "--sk-color": stroke } as React.CSSProperties}>
      <button
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
        onClick={() => {
          const next = !open;
          setOpen(next);
          onSelect(next ? skill.key : null);
        }}
      >
        {/* colour swatch */}
        <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: stroke }} />
        <span className="flex-1 text-[13px] font-medium text-foreground">{t(`skill.${skill.key}`)}</span>
        <TrendBadge trend={skill.trend} />
        <Stars n={skill.stars} />
        <ArrowRight className={cn(
          "ml-1 h-3.5 w-3.5 shrink-0 text-muted-foreground/40 transition-transform",
          open && "rotate-90",
        )} />
      </button>

      {open && (
        <div className="border-t border-border px-4 pb-4 pt-3 space-y-2">
          {skill.insight && (
            <p className="font-jp text-[12px] text-muted-foreground">{skill.insight}</p>
          )}
          {(skill.evidence ?? []).length > 0 ? (
            <div className="space-y-1.5 pt-1">
              {(skill.evidence ?? []).map((ev, i) => (
                <EvidenceChip key={i} ev={ev} />
              ))}
            </div>
          ) : (
            <p className="text-[11.5px] text-muted-foreground/50">
              {lang === "ja" ? "まだ記録された根拠がありません。" : "No recorded evidence yet."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function MessageBubble({ msg, t }: { msg: CoachingThreadMessage; t: (k: string) => string }) {
  const isManager = msg.role === "manager";
  return (
    <div className={cn("rounded-lg px-3 py-2.5", isManager ? "bg-muted/50" : "border border-primary/20 bg-primary/[0.03]")}>
      <div className="mb-1 flex items-center gap-2">
        <span className={cn(
          "text-[10px] font-semibold uppercase tracking-[0.06em]",
          isManager ? "text-muted-foreground" : "text-primary/70",
        )}>
          {isManager ? t("growth.thread.manager") : t("growth.thread.you")}
        </span>
        <span className="text-[10px] text-muted-foreground/50">{msg.date}</span>
      </div>
      <p className="font-jp text-[13px] leading-relaxed text-foreground/85">{msg.text}</p>
    </div>
  );
}

function ThreadCard({ thread }: { thread: CoachingThread }) {
  const { t } = useT();
  const [expanded, setExpanded] = useState(false);
  const preview = thread.messages.slice(0, 2);
  const hasMore = thread.messages.length > 2;

  return (
    <div className={cn(
      "rounded-xl border bg-card shadow-[0_1px_2px_rgba(16,24,40,0.04)]",
      thread.status === "resolved" && "opacity-75",
    )}>
      {/* header — always visible */}
      <button
        className="flex w-full items-start justify-between gap-2 p-4 text-left"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[11px] text-muted-foreground">{thread.deal_id}</span>
          <span className="rounded-full bg-primary/10 px-2.5 py-0.5 text-[11px] font-medium text-primary">
            {t(`coaching.issue.${thread.issue_key}`)}
          </span>
          {hasMore && !expanded && (
            <span className="text-[10px] text-muted-foreground">
              {thread.messages.length} messages
            </span>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className={cn(
            "rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
            STATUS_TONE[thread.status] ?? "bg-muted text-muted-foreground border-border",
          )}>
            {t(`repcoach.status.${thread.status}`)}
          </span>
          {expanded
            ? <ChevronUp className="h-3.5 w-3.5 text-muted-foreground/50" />
            : <ChevronDown className="h-3.5 w-3.5 text-muted-foreground/50" />}
        </div>
      </button>

      {/* messages */}
      <div className="space-y-2 px-4 pb-4">
        {(expanded ? thread.messages : preview).map((msg, i) => (
          <MessageBubble key={i} msg={msg} t={t} />
        ))}
        {!expanded && hasMore && (
          <button
            onClick={() => setExpanded(true)}
            className="w-full rounded-lg border border-dashed border-border py-2 text-[11.5px] text-muted-foreground transition-colors hover:border-primary/30 hover:text-primary"
          >
            {thread.messages.length - 2} more message{thread.messages.length - 2 !== 1 ? "s" : ""} — tap to expand
          </button>
        )}
      </div>

      <div className="border-t border-border px-4 py-2 text-[10px] text-muted-foreground">
        {thread.created_at}
      </div>
    </div>
  );
}

function DealCard({ deal, onOpen }: { deal: DealRow; onOpen: (id: string) => void }) {
  const { t, lang } = useT();
  return (
    <button
      className={cn(
        "flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left transition-all",
        "hover:shadow-[0_4px_20px_-8px_rgba(16,24,40,0.18)] hover:border-primary/30",
        BAND_BG[deal.band] ?? "border-border bg-card",
      )}
      onClick={() => onOpen(deal.deal_id)}
    >
      <span className="text-base leading-none">{BAND_CHIP[deal.band] ?? "⚪"}</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="font-jp truncate text-[13px] font-medium text-foreground">
            {customerText(lang, deal.customer).text}
          </span>
          <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{deal.deal_id}</span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground">
          <span>¥{deal.amount.toLocaleString("ja-JP")}</span>
          <span>{deal.stage}</span>
          {deal.days_stale != null && deal.days_stale > 0 && (
            <span className="text-band-yellow">{t("growth.stale", { n: String(deal.days_stale) })}</span>
          )}
          {deal.n_flags > 0 && (
            <span className="text-band-red">{deal.n_flags} flags</span>
          )}
        </div>
      </div>
      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40" />
    </button>
  );
}

function SkillProgressionChart({
  monthly,
  lang,
  highlighted,
}: {
  monthly: { month: string; count: number; skill_scores?: Partial<Record<string, number | null>> }[];
  lang: "ja" | "en";
  highlighted: string | null;
}) {
  const { t } = useT();
  const [tab, setTab] = useState<"skills" | "activity">("skills");
  // closing_discipline has no per-month ratio so it never appears as a line
  const skillKeys = Object.keys(SKILL_STROKE).filter((k) => k !== "closing_discipline");
  const n = monthly.length;
  const W = 300;
  const H = 88;
  const PX = 16;
  const PY = 8;

  const xOf = (i: number) => PX + (i / Math.max(n - 1, 1)) * (W - 2 * PX);
  const yOf = (v: number) => PY + (1 - v) * (H - 2 * PY);
  const maxCount = Math.max(1, ...monthly.map((m) => m.count));

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      {/* tab strip */}
      <div className="flex border-b border-border">
        {(["skills", "activity"] as const).map((tb) => (
          <button
            key={tb}
            onClick={() => setTab(tb)}
            className={cn(
              "flex-1 py-2.5 text-[11px] font-medium tracking-wide transition-colors",
              tab === tb
                ? "border-b-2 border-primary text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {tb === "skills"
              ? (lang === "ja" ? "スキル推移" : "Skill trends")
              : (lang === "ja" ? "活動量" : "Activity")}
          </button>
        ))}
      </div>

      {tab === "skills" ? (
        <div className="p-4">
          {/* SVG chart area */}
          <div className="relative" style={{ height: 120 }}>
            {/* Y-axis labels — HTML, not SVG, so no fill-class issues */}
            <div className="absolute left-0 top-0 flex h-full flex-col justify-between">
              {["100%", "50%", "0%"].map((l) => (
                <span key={l} className="text-[9px] leading-none text-muted-foreground/40">{l}</span>
              ))}
            </div>
            <svg
              viewBox={`0 0 ${W} ${H}`}
              preserveAspectRatio="none"
              xmlns="http://www.w3.org/2000/svg"
              style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
            >
              {/* horizontal guides */}
              <line x1={0} y1={yOf(1)} x2={W} y2={yOf(1)} stroke="#888" strokeOpacity="0.15" strokeWidth="0.8" />
              <line x1={0} y1={yOf(0.5)} x2={W} y2={yOf(0.5)} stroke="#888" strokeOpacity="0.2" strokeWidth="0.8" strokeDasharray="3 3" />
              <line x1={0} y1={yOf(0)} x2={W} y2={yOf(0)} stroke="#888" strokeOpacity="0.15" strokeWidth="0.8" />

              {skillKeys.map((sk) => {
                const color = SKILL_STROKE[sk];
                const pts: { x: number; y: number; v: number; lbl: string }[] = [];
                monthly.forEach((m, i) => {
                  const v = m.skill_scores?.[sk];
                  if (v != null) pts.push({ x: xOf(i), y: yOf(v), v, lbl: monthLabel(m.month, lang) });
                });
                if (pts.length === 0) return null;
                const dim = highlighted !== null && highlighted !== sk;
                const bold = highlighted === sk;
                const pathD = pts.map((p, j) => `${j === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");

                return (
                  <g key={sk} opacity={dim ? 0.12 : 1} style={{ transition: "opacity 0.2s" }}>
                    {pts.length > 1 && (
                      <path
                        d={pathD}
                        fill="none"
                        stroke={color}
                        strokeWidth={bold ? 3 : 2}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    )}
                    {pts.map((p, j) => (
                      <circle key={j} cx={p.x} cy={p.y} r={bold ? 4 : 3} fill={color} stroke="white" strokeWidth="1">
                        <title>{t(`skill.${sk}`)}: {Math.round(p.v * 100)}% ({p.lbl})</title>
                      </circle>
                    ))}
                  </g>
                );
              })}
            </svg>
          </div>

          {/* X-axis labels */}
          <div className="mt-1 flex justify-between">
            {monthly.map((m) => (
              <span key={m.month} className="flex-1 text-center text-[9.5px] text-muted-foreground/60">
                {monthLabel(m.month, lang)}
              </span>
            ))}
          </div>

          {/* Legend */}
          <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1.5 border-t border-border pt-2.5">
            {skillKeys.map((sk) => (
              <span
                key={sk}
                className="flex items-center gap-1.5 text-[10.5px] transition-opacity"
                style={{ opacity: highlighted !== null && highlighted !== sk ? 0.25 : 1 }}
              >
                <span className="inline-block h-[3px] w-4 rounded-full" style={{ backgroundColor: SKILL_STROKE[sk] }} />
                <span className="text-muted-foreground">{t(`skill.${sk}`)}</span>
              </span>
            ))}
          </div>
        </div>
      ) : (
        /* ── Activity bars tab ── */
        <div className="p-4">
          <div className="relative flex h-32 items-end justify-between gap-1.5">
            {monthly.map((m) => {
              const ratio = maxCount > 0 ? m.count / maxCount : 0;
              const pct = m.count === 0 ? 0 : Math.max(6, ratio * 100);
              const opacity = m.count === 0 ? 0.15 : 0.35 + ratio * 0.65;
              const isCurrent = m.month === monthly[monthly.length - 1].month;
              const barH = pct === 0 ? "3px" : `${pct}%`;
              return (
                <div key={m.month} className="relative flex h-full flex-1 items-end">
                  {m.count > 0 && (
                    <span
                      className={cn(
                        "absolute left-1/2 -translate-x-1/2 text-[10px] tabular-nums",
                        isCurrent ? "font-bold text-primary" : "font-medium text-muted-foreground",
                      )}
                      style={{ bottom: `calc(${pct}% + 4px)` }}
                    >
                      {m.count}
                    </span>
                  )}
                  <div
                    className="w-full rounded-t-md bg-primary transition-all"
                    style={{ height: barH, opacity }}
                    title={`${monthLabel(m.month, lang)}: ${m.count}`}
                  />
                </div>
              );
            })}
          </div>
          {/* avg line */}
          {maxCount > 0 && (() => {
            const avg = monthly.reduce((s, m) => s + m.count, 0) / monthly.length;
            const avgPct = (avg / maxCount) * 100;
            return (
              <div className="relative -mt-[calc(theme(spacing.32))]" style={{ height: "128px", pointerEvents: "none" }}>
                <div
                  className="absolute w-full border-t border-dashed border-muted-foreground/25"
                  style={{ bottom: `${avgPct}%` }}
                />
              </div>
            );
          })()}
          <div className="mt-2 flex justify-between">
            {monthly.map((m, i) => (
              <span
                key={m.month}
                className={cn(
                  "flex-1 text-center text-[9.5px]",
                  i === monthly.length - 1 ? "font-semibold text-primary" : "text-muted-foreground/60",
                )}
              >
                {monthLabel(m.month, lang)}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export function GrowthDashboard({
  initial,
  threads,
  deals,
}: {
  initial: GrowthResponse;
  threads: CoachingThread[];
  deals: DealRow[];
}) {
  const { t, lang } = useT();
  const g = initial.growth;
  const [drawerDealId, setDrawerDealId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null);

  function openDeal(id: string) {
    setDrawerDealId(id);
    setDrawerOpen(true);
  }

  const sortedThreads = [...threads].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 3) - (STATUS_ORDER[b.status] ?? 3),
  );
  const openThreads = threads.filter((th) => th.status === "open").length;

  return (
    <div className="space-y-6">
      {/* identity card */}
      <div className="flex items-center gap-3 rounded-xl border border-border bg-card p-4">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-navy text-white">
          <GraduationCap className="h-5 w-5" />
        </span>
        <div>
          <div className="font-jp text-[15px] font-semibold text-foreground">
            {repText(lang, g.rep.name).text}
          </div>
          <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
            <span className="font-jp">{departmentText(lang, g.rep.department).text}</span>
            {g.rep.specialty_tags.map((tg) => (
              <Badge key={tg} variant="default">#{tagText(lang, tg).text}</Badge>
            ))}
          </div>
        </div>
      </div>

      {/* headline stats */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard icon={MessagesSquare} value={g.totals.reviews} label={t("growth.stat.reviews")} tone="bg-primary/10 text-primary" />
        <StatCard icon={BookMarked} value={g.totals.principles} label={t("growth.stat.principles")} tone="bg-navy/10 text-navy" />
        <StatCard icon={Layers} value={g.totals.scenarios} label={t("growth.stat.scenarios")} tone="bg-conf-high/15 text-conf-high" />
        <StatCard icon={Flame} value={g.totals.streak_weeks} label={t("growth.stat.streak")} sub={t("growth.weeks", { n: String(g.totals.streak_weeks) })} tone="bg-band-yellow/15 text-band-yellow" />
      </div>

      {/* coaching journey */}
      <div className="rounded-2xl border border-primary/25 bg-gradient-to-br from-primary/[0.06] to-primary/[0.01] p-5">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-primary">
          <Sparkles className="h-3.5 w-3.5" /> {t("growth.journeyTitle")}
        </div>
        <div className="mt-1 text-[12px] text-muted-foreground">
          {t("growth.journeyLead")} · {monthLabel(g.this_month.label, lang)}
        </div>
        <div className="mt-4 flex flex-wrap gap-x-8 gap-y-3">
          <JourneyStat n={g.this_month.reviews} label={t("growth.journey.reviews")} />
          <JourneyStat n={g.this_month.new_principles} label={t("growth.journey.principles")} />
          <JourneyStat n={g.this_month.strengths} label={t("growth.journey.strengths")} />
        </div>
        <p className="mt-4 text-[13px] leading-relaxed text-foreground/80">{t("growth.encourage")}</p>
      </div>

      {/* Deep-dive lenses — one at a time so the page stays scannable instead
          of stacking every section on top of the summary above. */}
      <Tabs defaultValue="skills">
        <TabsList>
          <TabsTrigger value="skills" className="gap-1.5">
            <Sparkles className="h-3.5 w-3.5" /> {t("growth.skillsTitle")}
          </TabsTrigger>
          <TabsTrigger value="coaching" className="gap-1.5">
            <MessageCircle className="h-3.5 w-3.5" /> {t("repcoach.threads")}
            {openThreads > 0 && (
              <span className="rounded-full bg-band-red/15 px-1.5 text-[10px] font-semibold text-band-red">{openThreads}</span>
            )}
          </TabsTrigger>
          <TabsTrigger value="deals" className="gap-1.5">
            <Building2 className="h-3.5 w-3.5" /> {t("growth.myDeals")}
            {deals.length > 0 && (
              <span className="rounded-full bg-muted px-1.5 text-[10px] font-semibold text-muted-foreground">{deals.length}</span>
            )}
          </TabsTrigger>
        </TabsList>

        {/* Skills + monthly progression */}
        <TabsContent value="skills" className="mt-4">
          <p className="mb-3 text-[11.5px] text-muted-foreground">{t("growth.skillsSub")}</p>
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="space-y-2">
              {g.skills.map((s) => (
                <SkillCard
                  key={s.key}
                  skill={s}
                  lang={lang}
                  selected={selectedSkill === s.key}
                  onSelect={setSelectedSkill}
                />
              ))}
            </div>
            <div>
              <div className="eyebrow mb-1">{t("growth.monthlyTitle")}</div>
              <p className="mb-3 text-[11.5px] text-muted-foreground">{t("growth.monthlySkills")}</p>
              <SkillProgressionChart monthly={g.monthly} lang={lang} highlighted={selectedSkill} />
            </div>
          </div>
        </TabsContent>

        {/* Manager coaching feedback */}
        <TabsContent value="coaching" className="mt-4">
          <p className="mb-3 text-[11.5px] text-muted-foreground">{t("growth.coaching.sub")}</p>
          {sortedThreads.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border p-6 text-center text-[13px] text-muted-foreground">
              {t("repcoach.noThreads")}
            </div>
          ) : (
            <div className="space-y-3">
              {sortedThreads.map((thread) => (
                <ThreadCard key={thread.thread_id} thread={thread} />
              ))}
            </div>
          )}
        </TabsContent>

        {/* My deals */}
        <TabsContent value="deals" className="mt-4">
          <p className="mb-3 text-[11.5px] text-muted-foreground">{t("growth.myDeals.sub")}</p>
          {deals.length === 0 ? (
            <div className="rounded-xl border border-dashed border-border p-6 text-center text-[13px] text-muted-foreground">
              {t("growth.myDeals.noDeals")}
            </div>
          ) : (
            <div className="space-y-2">
              {deals.map((deal) => (
                <DealCard key={deal.deal_id} deal={deal} onOpen={openDeal} />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      <DealDrawer
        dealId={drawerDealId}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />
    </div>
  );
}
````

## File: web/components/workspace/cards/artifact-body.tsx
````typescript
"use client";

// Unified artifact renderer for every skill output (review / account_brief /
// research). One component, driven by a small per-kind config — replaces the
// three near-identical card files that had begun to drift. The shape is always:
//
//   header (kind label + entity + band)
//   [alert section]            ← red intercept (review: reality_check, account: risk)
//   [commentary]               ← streamed senior read / answer (position varies)
//   sections                   ← the deterministic lenses
//   evidence / provenance      ← collapsible, deterministic IDs only
//
// The structured `sections` are the deterministic record; `commentary` is the
// streamed presentation layer. Evidence carries source IDs only, never names.

import { useState } from "react";
import {
  AlertTriangle, Bot, Building2, ChevronDown, Database, Eye,
  FileSpreadsheet, Layers, Lightbulb, MessagesSquare, Route, Scale, Search, Sparkles, Target, type LucideIcon,
} from "lucide-react";
import type { Artifact, ArtifactKind, EvidenceRef } from "@/lib/artifacts";
import type { Confidence } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { downloadArtifact } from "@/lib/artifact-export";
import { SourceChips } from "@/components/source-chip";
import { ConfidenceBadge } from "@/components/confidence-badge";

const ICONS: Record<string, LucideIcon> = {
  eye: Eye, search: Search, alert: AlertTriangle,
  message: MessagesSquare, route: Route, scale: Scale, target: Target,
};

const BAND_CHIP: Record<string, string> = {
  red: "bg-band-red/10 text-band-red",
  yellow: "bg-band-yellow/10 text-band-yellow",
  green: "bg-conf-high/10 text-conf-high",
};

const EVIDENCE_LABEL: Record<EvidenceRef["kind"], string> = {
  deal: "Deal", spr: "SPR", principle: "Principle", playbook: "Playbook", web: "Web",
};

// Per-kind presentation. `alertKey` is the section rendered as a red intercept;
// `commentaryAfter` puts the streamed block below the sections (research reads
// "sources, then answer"); the rest is the header + commentary labelling.
type KindMeta = {
  icon: LucideIcon;
  labelJa: string; labelEn: string;
  alertKey: string | null;
  commentaryAfter: boolean;
  commentaryJa: string; commentaryEn: string;
};
const KIND_META: Record<ArtifactKind, KindMeta> = {
  review: {
    icon: Bot, labelJa: "レビュー", labelEn: "Review",
    alertKey: "reality_check", commentaryAfter: false,
    commentaryJa: "先輩の見立て", commentaryEn: "Senior's read",
  },
  account_brief: {
    icon: Building2, labelJa: "アカウント概要", labelEn: "Account Brief",
    alertKey: "risk", commentaryAfter: false,
    commentaryJa: "先輩の見立て", commentaryEn: "Senior's read",
  },
  research: {
    icon: Search, labelJa: "リサーチ", labelEn: "Research",
    alertKey: null, commentaryAfter: true,
    commentaryJa: "回答", commentaryEn: "Answer",
  },
};

// --- lightweight inline markdown (bold labels: **状況:** …) ------------------
function inlineBold(s: string) {
  return s.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**")
      ? <strong key={i} className="font-semibold text-foreground">{p.slice(2, -2)}</strong>
      : <span key={i}>{p}</span>,
  );
}

function Markdown({ text }: { text: string }) {
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

// A senior-tip line carries its provenance inline:
//   先輩の知見(出典 PB12・P03 / 確度high): <tip>
// Parse the 出典/確度 chrome into source chips + a confidence badge so the tip
// reads as grounded evidence, not a raw string (parity with the Review Coach).
const SENIOR_RE = /^先輩の知見\(出典 (.+?) \/ 確度(.+?)\): ([\s\S]+)$/;

function SeniorTip({ raw, label }: { raw: string; label: string }) {
  const m = raw.match(SENIOR_RE);
  if (!m) return <span className="flex-1">{inlineBold(raw)}</span>;
  const [, srcs, conf, tip] = m;
  const ids = srcs.split("・").map((s) => s.trim()).filter((s) => s && s !== "—");
  return (
    <div className="flex-1 rounded-lg border border-primary/20 bg-primary/[0.04] p-2.5">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.06em] text-primary">
          <Sparkles className="h-3 w-3" /> {label}
        </span>
        <SourceChips ids={ids} />
        <ConfidenceBadge level={(conf.trim() as Confidence) || "unverified"} />
      </div>
      <span className="block text-[13px] leading-relaxed text-foreground/90">{inlineBold(tip)}</span>
    </div>
  );
}

function SectionBlock({
  titleJa, titleEn, icon, body, lang, seniorLabel,
}: { titleJa: string; titleEn: string; icon?: string; body: string[]; lang: "ja" | "en"; seniorLabel: string }) {
  const Icon = (icon && ICONS[icon]) || Lightbulb;
  if (!body.length) return null;
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="mb-2 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="h-3.5 w-3.5" />
        </span>
        <span className={cn("text-[13.5px] font-medium text-foreground", lang === "ja" && "font-jp")}>
          {lang === "ja" ? titleJa : titleEn}
        </span>
      </div>
      <ul className="space-y-2">
        {body.map((it, i) =>
          it.startsWith("先輩の知見") ? (
            <li key={i} className="flex">
              <SeniorTip raw={it} label={seniorLabel} />
            </li>
          ) : (
            <li key={i} className="flex items-start gap-2 text-[13px] leading-relaxed text-foreground/90">
              <span className="mt-[6px] h-1 w-1 shrink-0 rounded-full bg-primary/50" />
              <span className="flex-1">{inlineBold(it)}</span>
            </li>
          ),
        )}
      </ul>
    </div>
  );
}

function CommentaryBlock({ artifact, label }: { artifact: Artifact; label: string }) {
  if (!artifact.commentary && artifact.status !== "building") return null;
  return (
    <div className="border-l-2 border-primary/40 pl-4 py-1">
      <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.06em] text-primary">
        <Bot className="h-3.5 w-3.5" /> {label}
        {artifact.status === "building" && (
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
        )}
      </div>
      {artifact.commentary ? (
        <Markdown text={artifact.commentary} />
      ) : (
        <div className="space-y-2 mt-3 w-3/4 opacity-40">
          <div className="h-3 w-full animate-pulse rounded-full bg-muted-foreground/30" />
          <div className="h-3 w-5/6 animate-pulse rounded-full bg-muted-foreground/30" />
          <div className="h-3 w-4/6 animate-pulse rounded-full bg-muted-foreground/30" />
        </div>
      )}
    </div>
  );
}

function EvidenceDrawer({ artifact, lang }: { artifact: Artifact; lang: "ja" | "en" }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 rounded-xl border border-border bg-card px-4 py-2.5 text-left transition-colors hover:border-primary/40"
      >
        <span className="flex items-center gap-1.5 text-[13px] font-medium text-foreground">
          <Layers className="h-3.5 w-3.5 text-muted-foreground" />
          {lang === "ja" ? "根拠・出典" : "Evidence / Provenance"}
          <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            {artifact.evidence.length}
          </span>
        </span>
        <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="animate-fade-up mt-3 rounded-xl border border-border bg-muted/20 p-3">
          {artifact.evidence.length === 0 ? (
            <p className="text-[12.5px] text-muted-foreground">
              {lang === "ja" ? "構造化された出典はありません。" : "No structured sources."}
            </p>
          ) : (
            <ul className="flex flex-wrap gap-2">
              {artifact.evidence.map((e) => {
                const inner = (
                  <>
                    <Database className="h-3 w-3 text-muted-foreground" />
                    <span className="text-muted-foreground">{EVIDENCE_LABEL[e.kind]}</span>
                    <span className="font-mono text-foreground">{e.id}</span>
                  </>
                );
                return (
                  <li key={`${e.kind}:${e.id}`}>
                    {e.url ? (
                      <a href={e.url} target="_blank" rel="noopener noreferrer"
                         className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-[11.5px] hover:border-primary/40">
                        {inner}
                      </a>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-[11.5px]">
                        {inner}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export function ArtifactBody({ artifact }: { artifact: Artifact }) {
  const { lang } = useT();
  const meta = KIND_META[artifact.kind];
  const HeaderIcon = meta.icon;

  const alert = meta.alertKey
    ? artifact.sections.find((s) => s.key === meta.alertKey)
    : undefined;
  const sections = artifact.sections.filter((s) => s.key !== meta.alertKey);
  const commentary = (
    <CommentaryBlock artifact={artifact} label={lang === "ja" ? meta.commentaryJa : meta.commentaryEn} />
  );

  return (
    <div className="space-y-4 rounded-xl border border-border bg-card p-5">
      {/* header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
        <span className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <HeaderIcon className="h-4 w-4" />
          </span>
          <span className="text-[14px] font-semibold tracking-tight">
            {lang === "ja" ? meta.labelJa : meta.labelEn}
          </span>
          {artifact.entity?.name && (
            <span className="inline-flex items-center gap-1 font-jp text-[12.5px] text-muted-foreground">
              <Building2 className="h-3.5 w-3.5" />
              {artifact.entity.name}
              {artifact.entity.type === "deal" && (
                <span className="font-mono text-[10.5px]">{artifact.entity.id}</span>
              )}
            </span>
          )}
        </span>
        <span className="flex items-center gap-2">
          {artifact.band && (
            <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase", BAND_CHIP[artifact.band])}>
              {artifact.band}
            </span>
          )}
          {artifact.status === "ready" && (
            <button
              onClick={() => { void downloadArtifact(artifact, lang); }}
              title={lang === "ja" ? "Excel (.xlsx) で書き出す" : "Export to Excel (.xlsx)"}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-[11.5px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
            >
              <FileSpreadsheet className="h-3.5 w-3.5" />
              {lang === "ja" ? "書き出し" : "Export"}
            </button>
          )}
        </span>
      </div>

      {/* alert intercept (review reality_check / account risk) */}
      {alert && alert.body.length > 0 && (
        <div className="rounded-xl border border-band-red/40 bg-band-red/5 p-4">
          <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold text-band-red">
            <AlertTriangle className="h-4 w-4" />
            {lang === "ja" ? alert.titleJa : alert.titleEn}
          </div>
          <ul className="space-y-1.5">
            {alert.body.map((it, i) => (
              <li key={i} className="text-[12.5px] leading-snug text-foreground/90">{inlineBold(it)}</li>
            ))}
          </ul>
        </div>
      )}

      {!meta.commentaryAfter && commentary}

      <div className="space-y-3">
        {sections.map((s) => (
          <SectionBlock key={s.key} titleJa={s.titleJa} titleEn={s.titleEn}
            icon={s.icon} body={s.body} lang={lang}
            seniorLabel={lang === "ja" ? "先輩の知見" : "Senior's insight"} />
        ))}
      </div>

      {meta.commentaryAfter && commentary}

      <EvidenceDrawer artifact={artifact} lang={lang} />
    </div>
  );
}
````

## File: docs/tool-calling-intelligence.md
````markdown
# Intelligent Tool Calling & Loop Prevention

In standard ReAct-style LLM agents, it is extremely common for the model to get stuck in a "tool loop" — rephrasing the same failed search, repeating an action, or burning turns with throwaway answers until it hits the hard limit (e.g., `MAX_TOOL_ROUNDS = 10`) and crashes.

To prevent this and keep latency low, `senpai/llm/client.py` implements a series of intelligent control-flow defenses. This guarantees the model safely exits the loop and synthesizes an answer without exhausting its context window or API limits.

---

## 1. The `finish` Sentinel (Zero Throwaway Answers)
Typically, if a model wants to stop using tools, it generates a plain text answer. If you enforce `tool_choice="required"` to prevent premature answering, the model often invents a fake tool call or hallucinates.

**How we solve this:**
We inject a sentinel tool called `finish` and force a tool call on the **first** round.
- On the first round `tool_choice="required"` — the model *must* gather before it can answer, and can't burn the round on a throwaway reply.
- When it has enough information, it calls `finish` (or, on later rounds, simply emits no tool call).
- We intercept `finish` (it is never dispatched to the engine) and instantly break the loop, advancing to the final synthesis round. This saves the latency and context of a "dummy" turn.

> **Once evidence exists, `tool_choice` relaxes to `"auto"`** (`tool_choice = "required" if not tool_log else "auto"`). Forcing `required` on *every* round is what pressures the model into contorting its final answer into a bogus tool argument instead of finishing cleanly — see §6. Round-0 stays `"required"` for the gather guarantee; the parallelism this costs is not real here anyway (see §7).

## 2. Anti-Spiraling (`_TOOL_ROUND_CAP`)
A model might search for `X`, not find it, and try searching for `Y`, `Z`, `W` across multiple rounds. This burns through the 10-call limit quickly.

**How we solve this:**
We track how many *rounds* a specific tool has been used in. If a tool (e.g., `search_notes`) appears in more than `_TOOL_ROUND_CAP` (default 2) rounds, it is considered a spiral.
- The next time the model calls it, the call is **intercepted and short-circuited**.
- We return a nudge to the model: `（取得済み。これ以上検索せず、収集済みの情報で回答してください。）` ("Already obtained. Do not search further, answer with collected info").
- *Note: This limits rounds, not fan-out. A single round can still parallel-call `web_search` 4 times successfully.*

## 3. Terminal Actions
When a model is asked to "create a deck", it might successfully generate the PPTX on round 1, but then decide to check its work and call `generate_pptx` *again* on round 2, producing duplicates.

**How we solve this:**
`_is_terminal_action()` flags tools that produce deliverables (`schedule_meeting`, `create_quote`, `send_email`, `generate_*`).
- If an action tool successfully commits (i.e., not a dry-run preview, and not an error), the tool loop **hard-terminates immediately**.
- The turn ends and the deliverable's success message is streamed to the user, bypassing the redundant synthesis round completely.

## 4. Exact Deduplication
If the model calls the exact same tool with the exact same arguments in the same turn, it wastes backend resources and context space.
- We use `_canon_args()` to normalize JSON arguments (sorting keys and normalizing whitespace).
- Duplicate calls are skipped and instantly fed the cached result from the first execution.

## 5. Context Truncation & Fallbacks
10 tool calls—especially parallel searches—can easily blow up a 32k context window, causing the final synthesis round to OOM or emit a blank answer.
- **Truncation**: Any single tool result exceeding 1500 characters is aggressively truncated on a natural boundary (`_truncate_on_boundary`, so a company name or ¥ figure is never severed mid-token), keeping the context buffer safe.
- **Substantive Fallback**: The loop tracks `substantive` tool results (ignoring errors or "not found"). If the final synthesis round fails or emits an empty `<think>` block, the agent automatically surfaces the last substantive tool output (e.g., the raw data from the CRM) so the user never sees a blank `(no response)`.

## 6. The Answer-as-Arg Leak Guard (`_is_finish_leak`)
Under forced `tool_choice="required"`, a reasoning-distill model that is *ready to answer* but obliged to emit a tool call will sometimes **pack its entire final answer into a tool argument** — e.g. `query_spr(customer="**結論：…**\n| table |\n…<tool_call>\n<function=finish>")`. Observed live on a "compare D016 vs D100" turn. This is doubly expensive: it dispatches a bogus query (that giant string fuzzy-matched *all* deals for the customer), **and** the turn generates the full answer twice — once as the leaked argument, once at real synthesis.

**How we solve this:**
- Relaxing `tool_choice` to `"auto"` after the first round (§1) removes most of the pressure that causes the leak — the model can just stop.
- As a belt-and-braces guard, `_is_finish_leak(name, args)` drops any call whose arguments carry a stray finish/think/tool_call marker (`function=finish`, `<tool_call>`, `</think>`, `</function>`) or an answer-sized argument blob (>600 chars; real args like `{"deal_id":"D016"}` are tiny). If nothing real remains after filtering, the model is effectively done → the loop routes to **one clean synthesis** instead of a wasted round plus a double generation.

## 7. Parallel Fan-Out — capability, prompt suppression, and where it actually pays off
Parallelism exists in the infrastructure: the `AdaptiveScheduler` builds a DAG where every `parallel_safe` **read** runs concurrently and only WRITE/EXTERNAL tools serialize behind a barrier (`senpai/orchestration/scheduler.py`), and the engine fans out all fresh calls from a round in one plan. This helps *only* when the model emits several `tool_calls` **in a single response**.

**The model *can* batch — in isolation (measured).** A direct probe of atlas-35b on an explicit "call BOTH D016 and D100 now":

| `tool_choice` | thinking | tool_calls returned |
| :-- | :-- | :-- |
| `auto` | off | **2** (D016 + D100) |
| `auto` | on | 1 |
| `required` | off | 1 |
| `required` | on | 1 |

So batching needs `tool_choice="auto"` + thinking-off; `required` triggers XGrammar structural enforcement that caps output at a single `<tool_call>`.

**But the full operational prompt suppresses it — and that's decisive.** Mirroring the real round-0 request (same query, `auto`, thinking-off) but varying the system prompt:

| system prompt | tool_calls |
| :-- | :-- |
| minimal | **2** |
| full `_junior_system()` | **1** |

The junior prompt *already contains* an explicit "batch independent lookups in one turn" instruction, and adding a stronger one changed nothing — the weight of the full grounding-first prompt makes the model emit one call regardless. Batching only reappears if you strip the prompt down, which would sacrifice the gather/grounding guarantees the prompt exists to enforce. **That trade — gutting a correctness-critical prompt to save ~1 round — is not worth it**, so we do not chase in-chat batching. (This is also why round-0 stays `"required"`: the parallelism it "costs" isn't obtainable here anyway.)

**Where deterministic parallelism is available today:** the orchestration / LLM-planner path, plus a scoped in-chat expander (below). A plan can declare multiple independent tasks up front, which the engine runs concurrently — independent of the model's in-chat batching behavior.

## 8. Scoped Multi-Entity Expander (`_multi_entity_gather_calls`)
Because the model won't batch (§7) and dribbles one lookup per round, a "compare D133, D012, D168" turn used to take one round *per deal* — and worse, the anti-spiral cap (§2) blocked the 3rd lookup entirely, making the model hallucinate "couldn't retrieve D168". Both are now fixed:

- **§2's cap counts *unproductive* rounds, not total** — so a tool fetching distinct entities (each returning real data) never trips it; only sustained dry repetition does.
- **The expander deterministically fans out the compare pattern.** On the **first** round, if the user's message names **≥2 distinct, known** entity ids (deals `D###` / customers `C##`, validated against the store — the same id discipline as `SessionFocus`), we synthesize the whole **gather bundle** *ourselves* instead of asking the model: for every deal both `score_deal_health` and `query_spr`, plus `query_spr` for each standalone customer. The bundle is **grouped by tool** (all health, then all records) but since every call is a `parallel_safe` read the `AdaptiveScheduler` runs the entire bundle in **one** parallel round — no need to phase health before records, as there is no dependency between them. The normal loop then proceeds to synthesis.

Measured on "compare D133, D012, D168": three sequential `query_spr` rounds (~75s) → **one parallel round of 6 calls** (3 health + 3 records, ~28s), all three deals fully gathered.

It is intentionally **narrow**: explicit ids only, the compare pattern only, first round only. Customers get records only (deal health needs a deal id). If the pattern doesn't match it returns `[]` and the normal loop runs unchanged — no behavior change for ordinary/single-entity turns. Broader / free-text multi-entity planning belongs in the orchestration path, not here.
````

## File: senpai/agent/crew.py
````python
"""Multi-agent crew — three specialists analyse one deal together.

This is the "not a chatbot" surface: instead of one model answering, a small crew
of role-specialised agents work a single deal and the rep watches them do it.

  🔍 Researcher (リサーチャー) — gathers the grounded facts: the deal snapshot,
     comparable won deals, related daily-report risk signals, the IT environment.
  🩺 Coach (コーチ) — reads the deal's health: risk band, the specific signals,
     what the rep should be careful about.
  ♟️ Strategist (ストラテジスト) — merges the Researcher's facts and the Coach's
     read into an actionable plan: talking points, objection handling, next move.

Researcher and Coach are independent, so they run in PARALLEL on worker threads;
the Strategist depends on both and runs once they finish. Each agent's tool calls
and its written contribution stream to the UI as they happen (via a shared queue),
so the rep sees a team working — not a single reply appearing.

Every fact comes from the deterministic store / scoring engine through the existing
tool impls; only each agent's prose is LLM-written. No numbers are invented.
"""
from __future__ import annotations

import queue
import re
import threading
import time
from typing import Callable, Iterator

from senpai.agent.gather import run_agent_gather
from senpai.agent.plan import coach_plan, rep_analyst_plan, researcher_plan
from senpai.data import store
from senpai.health.scoring import score_deal
from senpai.llm import client
from senpai.tools import impl

# The crew roster — sent to the UI first so it can lay out one lane per agent.
AGENTS = [
    {"id": "researcher", "label": "リサーチャー", "role": "事実収集", "emoji": ""},
    {"id": "coach", "label": "コーチ", "role": "健全性診断", "emoji": ""},
    {"id": "strategist", "label": "ストラテジスト", "role": "戦略立案", "emoji": ""},
]

_RESEARCHER_SYS = (
    "あなたは大塚商会の営業チームのリサーチャーです。与えられた社内データ（案件情報・"
    "類似事例・日報・IT環境）だけを根拠に、この商談の事実関係を簡潔に整理します。"
    "推測や創作は禁止。金額・日付・固有名詞はデータのとおりに引用してください。"
    "注意：絵文字（アイコン）は一切使用しないでください。"
)
_COACH_SYS = (
    "あなたは大塚商会のベテラン営業コーチです。健全性スコアとリスク信号を読み解き、"
    "この商談で担当者が見落としがちな点・リスクの本質を、根拠とともに簡潔に指摘します。"
    "注意：絵文字（アイコン）は一切使用しないでください。"
)
_STRATEGIST_SYS = (
    "あなたは大塚商会の営業戦略家です。リサーチャーの事実とコーチの診断を統合し、"
    "次の打ち合わせに向けた具体的で実行可能な作戦を立てます。指定のMarkdown構成で出力。"
    "注意：絵文字（アイコン）は一切使用しないでください。"
)

# A tool-call callback: each agent reports the tools it runs so the lane shows them.
Emit = Callable[[dict], None]


def _run_researcher(d: dict, customer: str, emit: Emit) -> tuple[str, dict]:
    deal_id = d["deal_id"]
    cust = store.get_customer(d["customer_id"]) or {}
    industry = cust.get("industry", "")

    # Gather runs on the orchestration engine (four tools in parallel); the engine
    # emits the same agent_tool events, in the same order, via the gather adapter.
    g = run_agent_gather(researcher_plan(deal_id, customer, industry), "researcher", emit)
    snapshot, comparables, notes, env = g["snapshot"], g["comparables"], g["notes"], g["env"]

    grounding = (f"【案件】\n{snapshot}\n\n【類似事例】\n{comparables}\n\n"
                 f"【日報の課題】\n{notes}\n\n【IT環境】\n{env}")
    contribution = client.simple_complete(
        [{"role": "system", "content": _RESEARCHER_SYS},
         {"role": "user", "content":
             f"対象: {customer} / {d.get('deal_name', '')}\n\n"
             "以下の社内データだけを根拠に、この商談の事実関係を3〜5個の箇条書きで"
             f"簡潔に整理してください。\n\n{grounding}"}],
        no_think=True, max_tokens=400, fast_decomp=True)
    return contribution, {"snapshot": snapshot, "comparables": comparables,
                          "notes": notes, "env": env}


def _run_coach(d: dict, customer: str, emit: Emit) -> tuple[str, dict]:
    deal_id = d["deal_id"]
    health = run_agent_gather(coach_plan(deal_id), "coach", emit)["health"]

    res = score_deal(d, store.activities_for_deal(deal_id))
    reasons = res.top_reasons(5)
    reason_block = "\n".join(f"- {r}" for r in reasons) or "- 目立った信号なし"
    contribution = client.simple_complete(
        [{"role": "system", "content": _COACH_SYS},
         {"role": "user", "content":
             f"対象: {customer} / {d.get('deal_name', '')}\n\n"
             f"健全性: {health}\n\nリスク要因:\n{reason_block}\n\n"
             "この商談で担当者が特に注意すべき点とリスクの本質を、3点以内で"
             "簡潔に指摘してください。"}],
        no_think=True, max_tokens=350, fast_decomp=True)
    return contribution, {"health": health, "reasons": reasons}


def _run_strategist(d: dict, customer: str, researcher_md: str, coach_md: str) -> str:
    return client.simple_complete(
        [{"role": "system", "content": _STRATEGIST_SYS},
         {"role": "user", "content":
             f"対象商談: {customer} / {d.get('deal_name', '')}"
             f"（{d.get('product_category', '')}）\n\n"
             f"【リサーチャーの所見】\n{researcher_md}\n\n"
             f"【コーチの診断】\n{coach_md}\n\n"
             "上記を統合し、次の打ち合わせに向けた作戦を以下のMarkdown構成でまとめてください。\n"
             "### トークの要点\n（3点・箇条書き）\n"
             "### 想定される反論と切り返し\n（2点・箇条書き）\n"
             "### 次の一手\n（1〜2個の具体的アクション）"}],
        no_think=True, max_tokens=1200)  # the user-facing brief — must not truncate


def _worker(agent_id: str, run: Callable[[Emit], tuple[str, dict]],
            q: "queue.Queue", results: dict) -> None:
    """Run one independent agent on its own thread, streaming its lifecycle to the
    shared queue. `run(emit)` returns (contribution, facts). Used for both the deal
    crew (Researcher/Coach) and the manager fan-out (one analyst per rep)."""
    t0 = time.time()
    q.put({"type": "agent", "id": agent_id, "status": "running"})
    try:
        contribution, facts = run(lambda ev: q.put(ev))
        results[agent_id] = (contribution, facts)
        q.put({"type": "agent", "id": agent_id, "status": "done",
               "contribution": contribution, "elapsed": round(time.time() - t0, 1)})
    except Exception as e:  # noqa: BLE001 — one agent failing must not kill the crew
        results[agent_id] = (f"（{agent_id} は分析を完了できませんでした: {e}）", {})
        q.put({"type": "agent", "id": agent_id, "status": "error", "reason": str(e),
               "elapsed": round(time.time() - t0, 1)})
    finally:
        q.put({"type": "_worker_done", "id": agent_id})


def _drain_parallel(q: "queue.Queue", n_workers: int) -> Iterator[dict]:
    """Yield every streamed event from `n_workers` agent threads until all finish."""
    finished = 0
    while finished < n_workers:
        ev = q.get()
        if ev.get("type") == "_worker_done":
            finished += 1
            continue
        yield ev


def run_crew(deal_id: str) -> Iterator[dict]:
    """Stream a full multi-agent analysis of one deal as typed event dicts:
      crew      — the roster (one lane per agent), with the deal in focus
      agent     — an agent's status: running | done | error (+ contribution on done)
      agent_tool— a tool an agent ran (name + human summary)
      final     — the Strategist's merged brief (Markdown)
      done      — terminal
    Researcher + Coach run in parallel; Strategist runs after both."""
    d = store.get_deal(deal_id)
    if not d:
        yield {"type": "error", "reason": "deal_not_found"}
        return
    customer = store.customer_name(d["customer_id"])
    yield {"type": "crew", "deal_id": deal_id, "customer": customer,
           "deal_name": d.get("deal_name") or customer,
           "product_category": d.get("product_category", ""),
           "agents": AGENTS}

    q: "queue.Queue" = queue.Queue()
    results: dict[str, tuple[str, dict]] = {}
    threads = [
        threading.Thread(target=_worker, args=(
            "researcher", lambda emit: _run_researcher(d, customer, emit), q, results), daemon=True),
        threading.Thread(target=_worker, args=(
            "coach", lambda emit: _run_coach(d, customer, emit), q, results), daemon=True),
    ]
    for t in threads:
        t.start()
    yield from _drain_parallel(q, len(threads))

    # Both fact-gatherers are done — the Strategist synthesises over their findings.
    yield {"type": "agent", "id": "strategist", "status": "running"}
    t0 = time.time()
    researcher_md = results.get("researcher", ("", {}))[0]
    coach_md = results.get("coach", ("", {}))[0]
    try:
        final_md = _run_strategist(d, customer, researcher_md, coach_md)
    except Exception as e:  # noqa: BLE001
        yield {"type": "agent", "id": "strategist", "status": "error", "reason": str(e)}
        yield {"type": "done"}
        return
    yield {"type": "agent", "id": "strategist", "status": "done",
           "contribution": final_md, "elapsed": round(time.time() - t0, 1)}
    yield {"type": "final", "markdown": final_md}
    yield {"type": "done"}


# --- Manager fan-out: one analyst agent per rep, in parallel -----------------
_REP_ANALYST_SYS = (
    "あなたは大塚商会の営業マネージャーを補佐するアナリストです。担当者一人の"
    "パイプライン概況と要注意案件を読み、マネージャーが今週コーチングで重点を置く"
    "べき点を、具体的な案件IDを挙げて簡潔に示します。推測や創作は禁止。"
)
_TEAM_LEAD_SYS = (
    "あなたは大塚商会の営業マネージャーです。各担当のパイプラインと要注意案件を統合し、"
    "チーム全体で今週優先すべきアクションを、指定のMarkdown構成で簡潔にまとめます。"
)


def _rep_roster(limit: int = 5) -> list[str]:
    """Reps with open deals, ranked by risk exposure (most red deals first, then
    pipeline size) — the manager's attention should fan out to them in that order."""
    by_rep: dict[str, list] = {}
    for d, res, _flags in impl._score_open_deals():
        by_rep.setdefault(store.deal_rep_id(d), []).append((d, res))
    ranked = sorted(
        by_rep.items(),
        key=lambda kv: (sum(1 for _, r in kv[1] if r.band == "red"), len(kv[1])),
        reverse=True)
    return [rid for rid, _ in ranked[:limit] if rid]


def _run_rep_analyst(rep_id: str, emit: Emit) -> tuple[str, dict]:
    name = store.rep_name(rep_id)
    g = run_agent_gather(rep_analyst_plan(rep_id, name), rep_id, emit)
    pipeline, at_risk = g["pipeline"], g["at_risk"]
    contribution = f"【パイプライン概況】\n{pipeline}\n\n【要注意案件】\n{at_risk}"
    return contribution, {"pipeline": pipeline, "at_risk": at_risk}


def _run_team_lead(cards: dict[str, str]) -> str:
    joined = "\n\n".join(f"【{store.rep_name(rid)}】\n{md}" for rid, md in cards.items())
    return client.simple_complete(
        [{"role": "system", "content": _TEAM_LEAD_SYS},
         {"role": "user", "content":
             f"各担当の状況（パイプライン・要注意案件）:\n\n{joined}\n\n"
             "チーム全体で、マネージャーが今週優先すべきアクションを以下の構成でまとめてください。\n"
             "### 🚩 最優先（今日対応）\n（1〜2件・担当と案件IDを明記）\n"
             "### 📋 今週のコーチング重点\n（2〜3点）\n"
             "### 💪 良い兆候\n（1点）"}],
        no_think=True, max_tokens=1200)  # the user-facing brief — must not truncate


def run_team(limit: int = 5) -> Iterator[dict]:
    """Stream a manager fan-out: one analyst agent per rep runs in PARALLEL, each
    producing a coaching card for that rep; then the manager (team lead) synthesises
    a prioritised action list. Same event contract as run_crew — `agents` is dynamic
    (one lane per rep) and the merged plan lands in `final`."""
    reps = _rep_roster(limit)
    if not reps:
        yield {"type": "error", "reason": "no_reps"}
        return
    yield {"type": "crew", "mode": "team",
           "agents": [{"id": rid, "label": store.rep_name(rid), "role": "担当分析", "emoji": "👤"}
                      for rid in reps]}

    q: "queue.Queue" = queue.Queue()
    results: dict[str, tuple[str, dict]] = {}
    threads = [
        threading.Thread(target=_worker, args=(
            rid, (lambda r: lambda emit: _run_rep_analyst(r, emit))(rid), q, results), daemon=True)
        for rid in reps
    ]
    for t in threads:
        t.start()
    yield from _drain_parallel(q, len(threads))

    # All rep analysts done — the manager prioritises across the team.
    t0 = time.time()
    try:
        final_md = _run_team_lead({rid: results.get(rid, ("", {}))[0] for rid in reps})
    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "reason": str(e)}
        yield {"type": "done"}
        return
    yield {"type": "final", "markdown": final_md, "elapsed": round(time.time() - t0, 1)}
    yield {"type": "done"}


def _key_deal_for_customer(cid: str) -> dict | None:
    """The deal a rep most needs to prep for: worst-health OPEN deal, else any deal."""
    open_scored = [(d, res) for d, res, _ in impl._score_open_deals() if d["customer_id"] == cid]
    if open_scored:
        return max(open_scored, key=lambda t: t[1].score)[0]
    deals = store.deals_for_customer(cid)
    return deals[0] if deals else None


def resolve_crew_target(query: str) -> dict:
    """Resolve a typed `/crew fujimoto` (customer name, romaji, or deal id) to the
    one deal the crew should analyse — PRESERVING ambiguity as a first-class state,
    exactly like the chat/research resolvers. Returns one of:
      {"status": "resolved",  "deal_id", "customer"}
      {"status": "ambiguous", "candidates": [{customer_id, name, deal_id}]}
      {"status": "not_found"}
    An explicit deal id wins; a unique customer resolves to their key deal; a vague
    stem ('fujimoto' → several 藤本 companies) surfaces the same picker the user
    already knows, so the rep chooses instead of the system guessing."""
    q = (query or "").strip()
    m = re.search(r"\bD\d{3,}\b", q, re.IGNORECASE)
    if m:
        d = store.get_deal(m.group(0).upper())
        if d:
            return {"status": "resolved", "deal_id": d["deal_id"],
                    "customer": store.customer_name(d["customer_id"])}

    cust = store.match_customer_in_text(q)
    if cust:
        d = _key_deal_for_customer(cust["customer_id"])
        if d:
            return {"status": "resolved", "deal_id": d["deal_id"],
                    "customer": store.customer_name(cust["customer_id"])}
        return {"status": "not_found"}

    amb = store.ambiguous_match_in_text(q)
    if amb:
        candidates = []
        for c in amb:
            d = _key_deal_for_customer(c["customer_id"])
            candidates.append({"customer_id": c["customer_id"], "name": c.get("name", ""),
                               "deal_id": d["deal_id"] if d else None})
        # The matched stem (longest ambiguous alias actually present) — shown in the
        # picker instead of the whole "/crew plan me a meet with fujimoto" sentence.
        low = q.lower()
        stem = max((k for k, ids in store._alias_index().items()
                    if len(ids) > 1 and store._key_in_text(k, low)),
                   key=len, default=q)
        return {"status": "ambiguous", "stem": stem, "candidates": candidates}

    return {"status": "not_found"}
````

## File: senpai/documents/proposal.py
````python
"""generate_proposal — a persuasive PPTX sales proposal, grounded in a deal's SPR data.

Follows Otsuka's proposal arc: (1) 表紙, (2) 背景/なぜ今, (3) 課題 (pain points from SPR
customer_challenge), (4) ソリューション (matched catalog products), (5) 投資対効果 (the
deal's real financials + comparable deals), (6) 次のステップ. Every number, product,
price, and comparable comes straight from context.py; the persuasive FRAMING is layered
by narrative.proposal_prose (LLM when available, grounded templated fallback otherwise),
so nothing is invented. Renders via render.py.

Smoke:  python -m senpai.documents.proposal D001
"""
from __future__ import annotations

from pathlib import Path

from senpai.documents import narrative
from senpai.documents.context import DocumentContext, build_document_context
from senpai.documents.render import output_path, render_pptx


def _yen(n) -> str:
    try:
        return f"¥{int(n):,}"
    except (TypeError, ValueError):
        return "¥0"


def build_proposal_spec(ctx: DocumentContext, lang: str = "ja") -> dict:
    """Build a persuasive, grounded proposal deck from a DocumentContext.

    Follows Otsuka's proposal arc (表紙 → 背景/なぜ今 → 課題 → ソリューション →
    投資対効果 → 次のステップ). Persuasive FRAMING comes from narrative.proposal_prose
    (LLM when available, grounded templated fallback otherwise); every NUMBER, product,
    price, and comparable stays deterministic from ctx, so nothing is invented."""
    prose = narrative.proposal_prose(ctx, lang=lang)

    # Slide 1 — 表紙
    title_slide = {
        "layout": "title",
        "title": f"{ctx.customer}様 ご提案",
        "subtitle": f"{prose['catch']}\n{ctx.product_category}　|　{ctx.today}　|　担当: {ctx.rep}",
    }

    slides = [title_slide]

    # Slide (multi-deal only) — 対象案件一覧: which deals this deck merges, so a
    # "cover all of their deals" proposal never leaves the rep guessing which
    # deals fed the numbers on the slides that follow.
    if len(ctx.deals) > 1:
        deal_lines = [f"{x['deal_id']} {x['deal_name']}（{x['product_category']}）"
                      f"— {_yen(x['amount'])}・{x['rank']}" for x in ctx.deals]
        slides.append({
            "layout": "content",
            "title": "対象案件一覧",
            "icon": "summary",
            "bullets": deal_lines,
            "notes": f"{len(ctx.deals)}件の案件を統合したご提案です。",
        })

    # Slide 2 (New) — 提案のサマリー
    exec_summary_slide = {
        "layout": "content",
        "title": "提案のサマリー",
        "icon": "summary",
        "bullets": ["本提案の目的と目指す姿", "主要なソリューション", "期待される効果と投資対効果"],
        "notes": "提案の全体像を簡潔に記載。",
    }

    # Slide 3 — 背景・なぜ今
    background_slide = {
        "layout": "content",
        "title": "背景 — なぜ今、取り組むべきか",
        "icon": "background",
        "bullets": prose["why_now"],
        "notes": "業界動向とタイミングの整理（顧客の課題に基づく framing）。",
    }

    # Slide 4 (New) — 現状のIT環境とアセスメント
    env = ctx.environment or {}
    env_bullets = [
        f"業種: {ctx.industry} / 規模: {ctx.size}",
    ]
    if env:
        for k, v in env.items():
            env_bullets.append(f"{k}: {v}")
    else:
        env_bullets.append("現行システムの課題・制約事項")
        
    assessment_slide = {
        "layout": "content",
        "title": "現状のIT環境とアセスメント",
        "icon": "assessment",
        "bullets": env_bullets,
        "notes": "SPR/顧客マスタに登録されているIT環境や規模に基づく現状認識。",
    }

    # Slide 5 — 課題（framing 済み、but grounded in the real pain points）
    challenge_slide = {
        "layout": "content",
        "title": "課題 — 現状のお困りごと",
        "icon": "challenge",
        "bullets": prose["challenges"],
        "notes": "SPRの日報・customer_challengeから抽出した実際の課題を framing。",
    }

    # Slide 6 — ソリューション（framing + the real catalog products/prices）
    solution_headers = ["製品名", "製品コード", "価格"]
    solution_rows = [[p['name'], p['code'], _yen(p['price'])] for p in ctx.products[:4]]
    
    # We will include the prose benefits in the slide notes so they aren't lost
    sol_notes = "便益は framing、製品・価格は大塚商会カタログの実データ。\n\n[Framing / Benefits]:\n" + "\n".join(prose["solution"])
    
    solution_slide = {
        "layout": "table",
        "title": f"ソリューション — {ctx.product_category}",
        "icon": "solution",
        "table": {
            "headers": solution_headers,
            "rows": solution_rows,
        },
        "notes": sol_notes,
    }

    # Slide 7 — 投資対効果（real numbers + value framing + real comparables）
    f = ctx.financials
    quoted = f.get("quote_amount")
    standard = f.get("standard_amount") or f.get("investment", 0)
    
    chart_categories = []
    chart_values = []
    if quoted and standard and quoted != standard:
        chart_categories = ["標準構成", "ご提案価格"]
        chart_values = [standard, quoted]
    elif quoted:
        chart_categories = ["ご提案価格"]
        chart_values = [quoted]
    else:
        chart_categories = ["投資額"]
        chart_values = [f.get('investment', 0)]
        
    roi_notes = "金額はすべてSPRの実データ。参考事例は同カテゴリの実案件（創作なし）。\n\n[Value / Comparables]:\n"
    roi_notes += "\n".join(prose["value"]) + "\n"
    for c in ctx.comparables:
        roi_notes += f"参考事例: {c['customer']}（{c['product_category']}）{_yen(c['amount'])}・{c['outcome']}\n"

    roi_slide = {
        "layout": "chart",
        "title": "投資対効果",
        "icon": "roi",
        "chart": {
            "renderer": "mpl",
            "categories": chart_categories,
            "series": [{"name": "Amount", "values": chart_values}]
        },
        "notes": roi_notes.strip(),
    }

    # Slide 7b (quote-only) — 割引率 as a doughnut: a real, quoted discount is a
    # customer-appropriate number to visualize (unlike an internal health score,
    # which has no place in a customer-facing deck).
    discount_slide = None
    disc = f.get("discount_rate")
    if quoted and standard and quoted != standard and disc:
        discount_slide = {
            "layout": "chart",
            "title": "標準価格からの割引率",
            "icon": "roi",
            "chart": {
                "type": "doughnut",
                "categories": ["割引額", "ご提案価格"],
                "series": [{"name": "構成比", "values": [disc, max(0, 100 - disc)]}],
            },
            "notes": f"標準 {_yen(standard)} → ご提案 {_yen(quoted)}（{disc}%割引）。SPRの見積実データ。",
        }

    # Slide 8 (New) — 導入スケジュール、接続された工程図として可視化
    schedule_slide = {
        "layout": "timeline",
        "title": "導入スケジュール (標準モデル)",
        "icon": "schedule",
        "phases": [
            {"label": "要件定義", "duration": "0.5〜1ヶ月", "detail": "要件の確認、仕様確定"},
            {"label": "機器手配・設定", "duration": "1〜1.5ヶ月", "detail": "手配・キッティング"},
            {"label": "導入・テスト", "duration": "0.5〜1ヶ月", "detail": "現地設置、動作確認"},
            {"label": "運用開始", "duration": "ー", "detail": "引継ぎ、本番稼働"},
        ],
        "notes": "標準的な導入スケジュール。案件の実態に合わせて調整。",
    }

    # Slide 9 — 次のステップ
    next_slide = {
        "layout": "content",
        "title": "次のステップ",
        "icon": "next",
        "bullets": prose["next_steps"],
        "notes": "丁寧な依頼文体で次の一歩を提示。",
    }

    slides += [exec_summary_slide, background_slide, assessment_slide, challenge_slide,
              solution_slide, roi_slide]
    if discount_slide:
        slides.append(discount_slide)
    slides += [schedule_slide, next_slide]
    return {"slides": slides}


def generate(deal_id: str, lang: str = "ja",
            deal_ids: list[str] | None = None) -> tuple[Path, DocumentContext, dict] | None:
    """Build + render a proposal for `deal_id`. Returns (path, context, spec) or None.
    The spec is returned so the caller can show the exact outline that was rendered
    without re-authoring it (which, with the LLM prose pass, would be a second call
    and could differ from the file). `deal_ids`, when given, merges that customer's
    other deals into the same deck (see context.build_document_context)."""
    ctx = build_document_context(deal_id, deal_ids=deal_ids)
    if ctx is None:
        return None
    spec = build_proposal_spec(ctx, lang=lang)
    path = output_path("proposal", deal_id, "pptx")
    render_pptx(spec, path)
    return path, ctx, spec


if __name__ == "__main__":
    import sys

    did = sys.argv[1] if len(sys.argv) > 1 else "D001"
    out = generate(did)
    if out is None:
        print(f"deal {did} not found")
    else:
        p, c, _spec = out
        print(f"wrote {p}  ({p.stat().st_size} bytes) for {c.customer}")
````

## File: senpai/documents/render.py
````python
"""Shared, LLM-free renderer — the only place python-pptx / python-docx are used.

Both the grounded tools (proposal/ringisho) and the general tools (pptx/docx) build
a normalized *spec* and hand it here. Keeping all rendering in one module means the
binary-format code is written and tested once.

Spec shapes
-----------
deck_spec (PPTX):
    {"slides": [
        {"layout": "title", "title": str, "subtitle": str},
        {"layout": "content", "title": str, "bullets": [str], "notes": str},
        ...
    ]}
doc_spec (DOCX):
    {"title": str, "subtitle": str,
     "sections": [{"heading": str, "body": [str]}, ...]}

`python-pptx` / `python-docx` are imported lazily so a missing lib can never break
the import of senpai.tools (mirrors senpai/tools/gcal.py).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from senpai import config


def output_path(kind: str, slug: str, ext: str) -> Path:
    """A unique, safe path under GENERATED_DIR, e.g. proposal_D001_20260616-1430.pptx.
    Creates the dir on first use."""
    config.GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", (slug or "doc")).strip("_") or "doc"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return config.GENERATED_DIR / f"{kind}_{safe}_{stamp}.{ext}"


# Layouts we populate, mapped to the Otsuka template's layout names (and the
# blank default's, as a fallback). The template is hand-built: its "Title Only"
# layout (タイトルのみ) carries NO body placeholder, so the content layout MUST be
# resolved by name — blindly using slide_layouts[1] would silently drop bullets.
_TITLE_LAYOUT_NAMES = ("タイトル スライド", "Title Slide")
_CONTENT_LAYOUT_NAMES = ("タイトルとコンテンツ", "Title and Content")


def _layout(prs, names, fallback_idx):
    """Pick a slide layout by name (Otsuka template / Office default), else by index."""
    by_name = {layout.name: layout for layout in prs.slide_layouts}
    for name in names:
        if name in by_name:
            return by_name[name]
    return prs.slide_layouts[fallback_idx]


# Vector section icons — a single-glyph badge (colored circle + symbol), never an
# embedded image. Keeps every visual generated from code: nothing that could carry
# a stock photo's own context (a specific office, a specific person) into a deck
# about an unrelated customer. Otsuka blue / teal match the ribbon + bullet cards.
_OTSUKA_BLUE = (0x00, 0x55, 0xA4)
_TEAL = (0x14, 0xB8, 0xA6)
_AMBER = (0xE0, 0x7A, 0x2E)
_GRAY = (0x6B, 0x72, 0x80)
# The source deck's own convention (senpai/data/templates/otsuka_source.pptx):
# every number/price/percentage that appears in a body sentence is pulled out in
# bold navy, not left in the flat body color — it's how the real deck makes a
# grounded figure the thing your eye lands on. Reused here as text styling, not a
# new drawn shape.
_STAT_NAVY = (0x00, 0x20, 0x60)
_STAT_RE = re.compile(
    r"(¥[\d,]+(?:\.\d+)?|\d+(?:\.\d+)?\s?%|\d+(?:,\d{3})*(?:\.\d+)?"
    r"(?:万円|円|件|日間?|ヶ月|ケ月|か月|倍|名|社|回|年|時間))")


def _add_styled_runs(paragraph, text, size, base_color):
    """Split `text` on grounded numeric/price/percentage tokens and bold+navy
    them, leaving the rest at `base_color` — matches the source template's own
    pull-the-number-out convention instead of one flat run."""
    from pptx.dml.color import RGBColor

    parts = _STAT_RE.split(text)
    for i, part in enumerate(parts):
        if not part:
            continue
        run = paragraph.add_run()
        run.text = part
        run.font.size = size
        if i % 2 == 1:  # a captured stat token
            run.font.bold = True
            run.font.color.rgb = RGBColor(*_STAT_NAVY)
        else:
            run.font.color.rgb = base_color
_ICONS = {
    "challenge": ("!", _AMBER),
    "solution": ("✓", _TEAL),
    "roi": ("↑", _OTSUKA_BLUE),
    "next": ("→", _OTSUKA_BLUE),
    "schedule": ("▤", _GRAY),
    "background": ("★", _TEAL),
    "assessment": ("⚙", _GRAY),
    "summary": ("§", _OTSUKA_BLUE),
}


def _render_comparison_png(categories: list[str], values: list[float],
                           value_labels: list[str] | None = None) -> "io.BytesIO":
    """A styled horizontal before/after bar comparison, rendered server-side with
    matplotlib and handed back as PNG bytes for `add_picture` — real numbers in,
    a custom-designed image out (no native-chart legend/gridline styling that
    doesn't match the deck's flat, no-shadow look). Deterministic: same numbers
    always draw the same image, nothing invented or sampled."""
    import io

    import matplotlib
    matplotlib.use("Agg")  # headless — no display/GUI backend needed on a server
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    for candidate in ("Yu Gothic", "Meiryo", "MS Gothic"):
        if any(candidate.lower() in f.name.lower() for f in fm.fontManager.ttflist):
            plt.rcParams["font.family"] = candidate
            break

    navy = "#00205A"       # matches _STAT_NAVY
    gray = "#94A3B8"
    accent = "#E13365"     # the source template's own punchline-pink

    fig, ax = plt.subplots(figsize=(7.5, 2.6), dpi=200)
    bar_colors = [gray, navy] if len(values) > 1 else [navy]
    bars = ax.barh(categories, values, color=bar_colors, height=0.5)

    labels = value_labels or [f"¥{v:,.0f}" for v in values]
    for bar, label in zip(bars, labels):
        ax.text(bar.get_width() + max(values) * 0.02, bar.get_y() + bar.get_height() / 2,
               label, va="center", ha="left", fontsize=13, fontweight="bold", color=navy)

    if len(values) == 2 and values[0]:
        pct = round((1 - values[1] / values[0]) * 100)
        if pct > 0:
            ax.text(max(values) * 0.5, -0.75, f"▼ {pct}%",
                   fontsize=15, fontweight="bold", color=accent, ha="center")

    ax.set_xlim(0, max(values) * 1.35)
    ax.invert_yaxis()
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks([])
    ax.tick_params(axis="y", length=0, labelsize=13)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    plt.close(fig)
    buf.seek(0)
    return buf


def _add_icon_badge(slide, icon_key, x, y, size):
    """A small colored-circle glyph badge — decorative theme marker, not data."""
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.dml.color import RGBColor
    from pptx.util import Pt

    glyph, color = _ICONS.get(icon_key, ("•", _OTSUKA_BLUE))
    badge = slide.shapes.add_shape(MSO_SHAPE.OVAL, x, y, size, size)
    badge.fill.solid()
    badge.fill.fore_color.rgb = RGBColor(*color)
    badge.line.fill.background()
    badge.shadow.inherit = False
    tf = badge.text_frame
    tf.word_wrap = False
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = glyph
    run.font.size = Pt(20)
    run.font.bold = True
    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    return badge


def render_pptx(deck_spec: dict, path: Path) -> Path:
    """Render a deck spec to a .pptx file at `path`. Returns the path.

    Opens the committed Otsuka brand template (config.PPTX_TEMPLATE_PATH) as the
    base so the deck inherits its masters/layouts/theme; falls back to python-pptx's
    blank default if the template is missing (e.g. in CI without the asset).
    """
    from pptx import Presentation
    from pptx.util import Pt, Inches
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.chart.data import CategoryChartData
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.dml.color import RGBColor

    tmpl = config.PPTX_TEMPLATE_PATH
    prs = Presentation(str(tmpl)) if tmpl.exists() else Presentation()
    title_layout = _layout(prs, _TITLE_LAYOUT_NAMES, 0)       # Title Slide
    content_layout = _layout(prs, _CONTENT_LAYOUT_NAMES, 1)   # Title and Content

    slides = deck_spec.get("slides") or []
    if not slides:  # never produce an empty deck
        slides = [{"layout": "title", "title": deck_spec.get("title", "Document"),
                   "subtitle": deck_spec.get("subtitle", "")}]

    for spec in slides:
        is_title = spec.get("layout") == "title"
        slide = prs.slides.add_slide(title_layout if is_title else content_layout)



        if slide.shapes.title is not None:
            slide.shapes.title.text = str(spec.get("title", ""))

        icon_key = spec.get("icon")
        if icon_key and not is_title:
            _add_icon_badge(slide, icon_key, prs.slide_width - Inches(1.0),
                            Inches(0.3), Inches(0.55))

        if is_title:
            # subtitle placeholder (idx 1) on the title layout
            for ph in slide.placeholders:
                if ph.placeholder_format.idx == 1:
                    ph.text = str(spec.get("subtitle", ""))
                    break
            continue

        is_table = spec.get("layout") == "table"
        is_chart = spec.get("layout") == "chart"

        if is_table or is_chart:
            # Remove the body placeholder to avoid "Click to add text" prompt
            for shape in list(slide.shapes):
                if shape.is_placeholder and shape.placeholder_format.idx == 1:
                    sp = shape._sp
                    sp.getparent().remove(sp)
            
            # Use typical positioning for content
            x, y, cx, cy = Inches(1), Inches(1.5), Inches(8), Inches(4.5)

            if is_table:
                table_data = spec.get("table", {})
                headers = table_data.get("headers", [])
                rows = table_data.get("rows", [])
                num_rows = len(rows) + (1 if headers else 0)
                num_cols = max(len(headers), max((len(r) for r in rows), default=0)) if headers or rows else 1
                
                if num_rows > 0 and num_cols > 0:
                    table_shape = slide.shapes.add_table(num_rows, num_cols, x, y, cx, cy)
                    table = table_shape.table
                    
                    row_idx = 0
                    if headers:
                        for col_idx, header in enumerate(headers):
                            cell = table.cell(row_idx, col_idx)
                            cell.text = str(header)
                            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                            # Make header bold
                            for paragraph in cell.text_frame.paragraphs:
                                for run in paragraph.runs:
                                    run.font.bold = True
                        row_idx += 1
                    
                    for row in rows:
                        for col_idx, item in enumerate(row):
                            if col_idx < num_cols:
                                cell = table.cell(row_idx, col_idx)
                                cell.text = str(item)
                                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                        row_idx += 1

            elif is_chart and spec.get("chart", {}).get("renderer") == "mpl":
                # A custom-designed comparison, rendered server-side (matplotlib)
                # and embedded as a picture — real numbers in, brand-matched
                # styling out, no native-chart legend/gridlines to fight with.
                cs = spec["chart"]
                categories = cs.get("categories", [])
                values = (cs.get("series") or [{}])[0].get("values", [])
                labels = cs.get("value_labels") or [f"¥{v:,.0f}" for v in values]
                png = _render_comparison_png(categories, values, labels)
                slide.shapes.add_picture(png, Inches(1), Inches(2.0), width=Inches(8))

                # The image is illustrative — the actual figures also need to
                # exist as real text (accessibility, search, copy-paste), not
                # only as pixels. A compact caption line restates them, with the
                # same number-highlighting every other slide uses.
                caption = slide.shapes.add_textbox(Inches(1), Inches(5.1), Inches(8), Inches(0.5))
                cap_tf = caption.text_frame
                cap_tf.word_wrap = True
                cap_p = cap_tf.paragraphs[0]
                cap_p.alignment = PP_ALIGN.CENTER
                _add_styled_runs(cap_p, "　|　".join(f"{c}: {v}" for c, v in zip(categories, labels)),
                                 Pt(12), RGBColor(*_GRAY))

            elif is_chart:
                chart_data_spec = spec.get("chart", {})
                chart_data = CategoryChartData()
                chart_data.categories = chart_data_spec.get("categories", [])
                for series in chart_data_spec.get("series", []):
                    chart_data.add_series(series.get("name", ""), series.get("values", []))

                # "type": "doughnut" for a single-metric proportion (e.g. discount
                # rate) instead of the default column-bar comparison.
                chart_type = (XL_CHART_TYPE.DOUGHNUT if chart_data_spec.get("type") == "doughnut"
                             else XL_CHART_TYPE.COLUMN_CLUSTERED)
                if chart_type == XL_CHART_TYPE.DOUGHNUT:
                    cx = cy = Inches(3.5)  # a doughnut reads best square, not stretched
                chart = slide.shapes.add_chart(
                    chart_type, x, y, cx, cy, chart_data
                ).chart

                # Add data labels
                plot = chart.plots[0]
                plot.has_data_labels = True
                for series in plot.series:
                    for point in series.points:
                        point.data_label.has_text_frame = True

            # If notes exist, add them
            notes = str(spec.get("notes", "") or "").strip()
            if notes:
                slide.notes_slide.notes_text_frame.text = notes
            continue

        is_timeline = spec.get("layout") == "timeline"
        if is_timeline:
            # A visual process flow (connected boxes + arrows) instead of a plain
            # table — same deterministic phase data, more legible for a rep to
            # walk a customer through in a meeting.
            for shape in list(slide.shapes):
                if shape.is_placeholder and shape.placeholder_format.idx == 1:
                    sp = shape._sp
                    sp.getparent().remove(sp)

            phases = spec.get("phases") or []
            n = len(phases)
            if n:
                margin = Inches(0.6)
                arrow_w = Inches(0.35)
                box_w = int((prs.slide_width - 2 * margin - (n - 1) * arrow_w) / n)
                box_h = Inches(1.6)
                y = Inches(2.8)
                x = margin
                for i, ph in enumerate(phases):
                    box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, box_w, box_h)
                    box.fill.solid()
                    box.fill.fore_color.rgb = (RGBColor(0xF0, 0xF4, 0xF8) if i % 2 == 0
                                               else RGBColor(0xE2, 0xEC, 0xF5))
                    box.line.color.rgb = RGBColor(*_OTSUKA_BLUE)
                    box.shadow.inherit = False
                    tf = box.text_frame
                    tf.word_wrap = True
                    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
                    p0 = tf.paragraphs[0]
                    p0.alignment = PP_ALIGN.CENTER
                    r0 = p0.add_run()
                    r0.text = str(ph.get("label", ""))
                    r0.font.bold = True
                    r0.font.size = Pt(13)
                    r0.font.color.rgb = RGBColor(0, 0, 0)
                    p1 = tf.add_paragraph()
                    p1.alignment = PP_ALIGN.CENTER
                    _add_styled_runs(p1, str(ph.get("duration", "")), Pt(11), RGBColor(*_GRAY))
                    detail = str(ph.get("detail", "")).strip()
                    if detail:
                        p2 = tf.add_paragraph()
                        p2.alignment = PP_ALIGN.CENTER
                        r2 = p2.add_run()
                        r2.text = detail
                        r2.font.size = Pt(9)
                        r2.font.color.rgb = RGBColor(*_GRAY)
                    x += box_w
                    if i < n - 1:
                        arrow = slide.shapes.add_shape(
                            MSO_SHAPE.RIGHT_ARROW, x, y + box_h // 2 - Inches(0.15),
                            arrow_w, Inches(0.3))
                        arrow.fill.solid()
                        arrow.fill.fore_color.rgb = RGBColor(*_OTSUKA_BLUE)
                        arrow.line.fill.background()
                        arrow.shadow.inherit = False
                        x += arrow_w

            notes = str(spec.get("notes", "") or "").strip()
            if notes:
                slide.notes_slide.notes_text_frame.text = notes
            continue

        bullets = [str(b) for b in (spec.get("bullets") or []) if str(b).strip()]

        if bullets and not (is_table or is_chart):
            # Remove the default body placeholder so we can draw custom shapes
            for shape in list(slide.shapes):
                if shape.is_placeholder and shape.placeholder_format.idx == 1:
                    sp = shape._sp
                    sp.getparent().remove(sp)

            # Left-aligned accent-stripe cards — no border, no drop shadow (the
            # centered, shadowed "pill button" look read as a default-autoshape
            # placeholder, not a designed slide). A thin color bar + a small vector
            # dot substitute for the border, and the block is vertically centered
            # in the available area instead of always starting at a fixed y and
            # leaving the rest of the slide empty for short bullet lists.
            margin = Inches(0.8)
            width = prs.slide_width - 2 * margin
            # Roughly two lines' worth of height once text wraps past ~44 chars
            # (word_wrap is on regardless — this only sizes the card, not the text).
            heights = [Inches(1.0) if len(b) > 44 else Inches(0.62) for b in bullets]
            gap = Inches(0.22)
            content_top, content_bottom = Inches(1.95), Inches(6.9)
            total_h = sum(heights, start=0) + gap * (len(bullets) - 1)
            y = content_top + max(0, (content_bottom - content_top - total_h)) // 2
            x = margin

            for b, h in zip(bullets, heights):
                card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, width, h)
                card.fill.solid()
                card.fill.fore_color.rgb = RGBColor(0xF8, 0xFA, 0xFC)
                card.line.fill.background()
                card.shadow.inherit = False
                card.adjustments[0] = 0.06  # subtler corner radius than the default

                accent = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, Inches(0.07), h)
                accent.fill.solid()
                accent.fill.fore_color.rgb = RGBColor(*_OTSUKA_BLUE)
                accent.line.fill.background()
                accent.shadow.inherit = False

                dot_size = Inches(0.14)
                dot = slide.shapes.add_shape(
                    MSO_SHAPE.OVAL, x + Inches(0.3), y + h // 2 - dot_size // 2, dot_size, dot_size)
                dot.fill.solid()
                dot.fill.fore_color.rgb = RGBColor(*_TEAL)
                dot.line.fill.background()
                dot.shadow.inherit = False

                tf = card.text_frame
                tf.word_wrap = True
                tf.vertical_anchor = MSO_ANCHOR.MIDDLE
                tf.margin_left = Inches(0.6)
                tf.margin_right = Inches(0.3)
                p = tf.paragraphs[0]
                p.alignment = PP_ALIGN.LEFT
                _add_styled_runs(p, b, Pt(16), RGBColor(0x1F, 0x29, 0x37))

                y += h + gap

        notes = str(spec.get("notes", "") or "").strip()
        if notes:
            slide.notes_slide.notes_text_frame.text = notes

    prs.save(str(path))
    return path


def render_docx(doc_spec: dict, path: Path) -> Path:
    """Render a doc spec to a .docx file at `path`. Returns the path."""
    from docx import Document

    doc = Document()
    title = str(doc_spec.get("title", "") or "")
    if title:
        doc.add_heading(title, level=0)
    subtitle = str(doc_spec.get("subtitle", "") or "").strip()
    if subtitle:
        doc.add_paragraph(subtitle).italic = True

    for section in doc_spec.get("sections") or []:
        heading = str(section.get("heading", "") or "").strip()
        if heading:
            doc.add_heading(heading, level=1)
        for para in section.get("body") or []:
            text = str(para).strip()
            if not text:
                continue
            # A leading "- " or "・" renders as a bullet list item.
            if text[:2] in ("- ", "・") or text.startswith("• "):
                doc.add_paragraph(text.lstrip("-・• ").strip(), style="List Bullet")
            else:
                doc.add_paragraph(text)

    doc.save(str(path))
    return path
````

## File: senpai/orchestration/metadata.py
````python
from enum import Enum
from dataclasses import dataclass

class OperationKind(Enum):
    READ = "read"         # Safe, deterministic data fetching
    SEARCH = "search"     # Safe, non-deterministic queries (e.g., web_search)
    COMPUTE = "compute"   # CPU-bound data transformation
    WRITE = "write"       # State-mutating internal actions
    EXTERNAL = "external" # State-mutating external actions (e.g., send_email)

@dataclass
class CapabilityMetadata:
    kind: OperationKind
    parallel_safe: bool = True
    idempotent: bool = True
    cacheable: bool = False
    requires_confirmation: bool = False
    max_concurrency: int = 8
    timeout: int = 30
    retries: int = 2

# Global registry of metadata for all tools exposed to the LLM.
# Read/Search tools are generally parallel_safe.
# Write/External tools are strictly serialized and may require confirmation.
TOOL_METADATA: dict[str, CapabilityMetadata] = {
    "query_spr": CapabilityMetadata(OperationKind.READ, cacheable=True),
    "find_deals": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "find_similar_deals": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "retrieve_playbook": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "search_notes": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "lookup_customer_environment": CapabilityMetadata(OperationKind.READ, cacheable=True),
    "get_product_info": CapabilityMetadata(OperationKind.READ, cacheable=True),
    "score_deal_health": CapabilityMetadata(OperationKind.COMPUTE),
    "review_sales_note": CapabilityMetadata(OperationKind.COMPUTE),
    "draft_daily_report": CapabilityMetadata(OperationKind.COMPUTE),
    "route_to_expert": CapabilityMetadata(OperationKind.COMPUTE),
    "summarize_reports": CapabilityMetadata(OperationKind.COMPUTE),
    "get_seasonal_context": CapabilityMetadata(OperationKind.READ, cacheable=True),
    "morning_briefing": CapabilityMetadata(OperationKind.COMPUTE),
    "list_at_risk_deals": CapabilityMetadata(OperationKind.READ),
    "team_pipeline_overview": CapabilityMetadata(OperationKind.COMPUTE),
    "team_report_digest": CapabilityMetadata(OperationKind.COMPUTE),
    "rep_coaching_focus": CapabilityMetadata(OperationKind.COMPUTE),
    "draft_message": CapabilityMetadata(OperationKind.COMPUTE),
    "web_search": CapabilityMetadata(OperationKind.SEARCH, max_concurrency=4, retries=3),
    "search_knowledge": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "search_products": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "create_quote": CapabilityMetadata(OperationKind.COMPUTE),
    "schedule_meeting": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=True),
    "send_email": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=True),
    "get_calendar": CapabilityMetadata(OperationKind.READ, cacheable=True),
    "query_graph": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "segment_intelligence": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "search_workspace_documents": CapabilityMetadata(OperationKind.SEARCH, max_concurrency=4),
    "edit_workspace_document": CapabilityMetadata(OperationKind.WRITE, parallel_safe=False, idempotent=False, requires_confirmation=True),
    "generate_proposal": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=False),
    "generate_ringisho": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=True),
    "generate_pptx": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=False),
    "generate_docx": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=True),
}
````

## File: senpai/planner/plan.py
````python
"""`document_plan(selection)` — turn a capability Selection into an ExecutionPlan.

The graph is deliberately shallow (two levels), which is all document generation
needs and keeps the first planner minimal:

    Level 0 (parallel gather):  conversation / workspace / crm / knowledge / web
    Level 1 (terminal):         documents  ── depends on every gather task

Every gather task runs in parallel (they're independent READ/SEARCH); the single
`documents` task depends on all of them, so the engine runs it only after the
grounding is in the bundle. The edges ARE the dependency: no ordering logic lives
in the engine or the capabilities — it's entirely expressed by `depends_on`.
"""
from __future__ import annotations

from senpai.orchestration import ExecutionPlan, Task, TaskPolicy
from senpai.planner.selection import Selection

_GATHER = "gather"
_DOCS = "documents"


def document_plan(sel: Selection) -> ExecutionPlan:
    query = sel.goal

    # Organize is a self-contained WRITE over the workspace — no gather graph.
    if sel.doc_kind == "organize":
        return ExecutionPlan(tasks=(Task(
            id="workspace_organize", capability="workspace_organize",
            op="apply" if sel.confirm else "plan", inputs={"confirm": sel.confirm},
            policy=TaskPolicy(retries=0, on_failure="skip"),
            group=_DOCS, summary="ワークスペースを整理"),))

    gather: list[Task] = []

    if "conversation" in sel.capabilities:
        gather.append(Task(id="conversation", capability="conversation",
                           inputs={"query": query}, group=_GATHER,
                           summary="会話の文脈を収集"))
    if "workspace" in sel.capabilities:
        gather.append(Task(id="workspace", capability="workspace",
                           inputs={"query": query}, group=_GATHER,
                           summary="ローカル文書を検索・抽出"))
    if "crm" in sel.capabilities:
        gather.append(Task(id="crm", capability="crm",
                           inputs={"deal_id": sel.deal_id or "",
                                   "customer_id": sel.customer_id or ""},
                           group=_GATHER, summary="社内記録を取得"))
    if "knowledge" in sel.capabilities:
        gather.append(Task(id="knowledge", capability="knowledge",
                           inputs={"query": query}, group=_GATHER,
                           summary="社内ナレッジを照合"))
    if "web" in sel.capabilities:
        gather.append(Task(id="web", capability="web",
                           inputs={"query": query}, group=_GATHER,
                           summary="Web検索でカバー"))

    deps = frozenset(t.id for t in gather)
    # A note WRITEs into the workspace; proposal/pptx/docx GENERATE a downloadable file.
    if sel.doc_kind == "note":
        terminal = Task(
            id="workspace_write", capability="workspace_write", op="note",
            inputs={"goal": query, "prompt": query, "path": sel.path, "lang": sel.lang},
            depends_on=deps, policy=TaskPolicy(retries=0, on_failure="skip"),
            group=_DOCS, summary="ノートを保存")
    else:
        # "cover all of this customer's deals" (proposal only) — the deterministic
        # generator merges every deal on file instead of silently grounding on
        # just the biggest one.
        deal_ids: list[str] = []
        if sel.doc_kind == "proposal" and sel.all_deals and sel.customer_id:
            from senpai.data import store as _store
            deal_ids = [d["deal_id"] for d in _store.deals_for_customer(sel.customer_id)]

        terminal = Task(
            id="documents", capability="documents", op=sel.doc_kind,
            inputs={"goal": query, "prompt": query, "deal_id": sel.deal_id or "",
                    "customer_id": sel.customer_id or "", "deal_ids": deal_ids,
                    "target": sel.target, "lang": sel.lang, "title": sel.title},
            depends_on=deps,
            # A WRITE deliverable: never auto-repeat, run after the grounding is in.
            policy=TaskPolicy(retries=0, on_failure="skip"),
            group=_DOCS, summary=f"{sel.doc_kind} を生成")

    return ExecutionPlan(tasks=(*gather, terminal))
````

## File: senpai/planner/run.py
````python
"""Run a document goal end-to-end through the planner spine:

    goal ──► LLMPlanner ──► ExecutionPlan ──► ExecutionEngine ──► EvidenceBundle ──► artifact

`run_document_goal` is the one entry point. It plans, publishes the conversation so
the Conversation/Documents capabilities can see it, executes the plan on the shared
ExecutionEngine, and reads the terminal `documents` fragment out of the bundle as
the artifact. Gather failures degrade to empty (the engine never crashes a run), so
a down web search or an empty workspace just means less grounding — never no deck.

For document generation the "Reasoner" step is trivial — the artifact IS the file,
and the Documents capability already produced the one-line confirmation. The Reasoner
seam (senpai/orchestration/reason.py) is where meeting-prep / account-intelligence
will synthesize prose over the bundle in the next milestone.

`python -m senpai.planner.run "D001 の提案書を作って"` runs it (proposal path is GPU-free).
"""
from __future__ import annotations

from typing import Callable

from senpai.orchestration import EvidenceBundle, ExecutionEngine
from senpai.planner.capabilities import build_registry
from senpai.planner.llm_planner import LLMPlanner

Emit = Callable[[dict], None]
_NOOP: Emit = lambda _ev: None


def run_document_goal(goal: str, *, conversation: list[dict] | None = None,
                      role: str = "junior", deal_id: str | None = None,
                      registry=None, emit: Emit | None = None) -> dict:
    """Plan → execute → artifact for a document-generation goal. Returns:
      {goal, plan: [{id, capability, op, depends_on}], selection, document, text,
       grounded_on, citations, capabilities}
    `document` is None if authoring needed a model that was unavailable (then `text`
    carries the reason). Publishes `conversation` for the grounding capabilities.
    `deal_id` (e.g. the deal picked in the selector) is authoritative when given."""
    if conversation is not None:
        from senpai.tools import conversation as _conv
        _conv.set_conversation(conversation)

    planner = LLMPlanner()
    selection = planner.select(goal, conversation=conversation, deal_id=deal_id)
    plan = __import__("senpai.planner.plan", fromlist=["document_plan"]).document_plan(selection)

    _emit = emit or _NOOP
    # The capability graph is known before the engine runs a single task — surface
    # it immediately (not only in the dict this function returns once everything is
    # done), so a live SSE consumer can show the plan/focus chip right away instead
    # of the whole turn appearing to complete in one silent burst at the end.
    _emit({"type": "selection.ready",
          "selection": {"doc_kind": selection.doc_kind, "deal_id": selection.deal_id,
                        "customer_id": selection.customer_id, "target": selection.target,
                        "capabilities": list(selection.capabilities),
                        "reason": selection.reason},
          "plan": [{"id": t.id, "capability": t.capability, "op": t.op,
                    "depends_on": sorted(t.depends_on)} for t in plan.tasks]})

    bundle: EvidenceBundle = ExecutionEngine(registry or build_registry()).run(
        plan, _emit)

    # The terminal task is the one nothing else depends on (documents / workspace_write
    # / workspace_organize) — read its fragment as the artifact, whatever the kind.
    depended = {d for t in plan.tasks for d in t.depends_on}
    terminal = next((t for t in reversed(plan.tasks) if t.id not in depended), None)
    doc = bundle.get(terminal.id) if terminal else None
    document = None
    text = ""
    grounded_on: list[str] = []
    outline: list = []
    if doc is not None and doc.status in ("ok", "partial"):
        document = doc.data.get("document")
        text = doc.data.get("text", "")
        grounded_on = list(doc.data.get("grounded_on", []))
        outline = list(doc.data.get("outline", []))
    elif doc is not None:  # error fragment
        text = str(doc.provenance.get("error", "document generation failed"))

    return {
        "goal": goal,
        "selection": {"doc_kind": selection.doc_kind, "deal_id": selection.deal_id,
                      "customer_id": selection.customer_id, "target": selection.target,
                      "capabilities": list(selection.capabilities),
                      "reason": selection.reason},
        "plan": [{"id": t.id, "capability": t.capability, "op": t.op,
                  "depends_on": sorted(t.depends_on)} for t in plan.tasks],
        "capabilities": list(selection.capabilities),
        "document": document,
        "text": text,
        "grounded_on": grounded_on,
        "outline": outline,
        "citations": list(doc.citations) if doc else [],
    }


if __name__ == "__main__":
    import json
    import sys

    goal = " ".join(sys.argv[1:]) or "D001 の提案書を作成して"
    result = run_document_goal(goal, emit=lambda ev: None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
````

## File: web/app/manager/workspace/page.tsx
````typescript
import { api } from "@/lib/api";
import { currentEmployeeId } from "@/lib/server-session";
import { CommandCenter } from "@/components/workspace/command-center";
import { ContextPane } from "@/components/workspace/context-pane";

export const dynamic = "force-dynamic";

// The Copilot tab — the same unified Command Center the Junior home uses: live
// deal/account context on the left, the Copilot (Workspace) on the right. Here
// the context pane is scoped to the manager's coachees. Reached from the nav,
// or from a deal's "Ask the Copilot" action which grounds it on that deal first.
export default async function ManagerCopilotPage() {
  const eid = await currentEmployeeId();
  const [{ data: ex }, { data: db }, { data: pr }] = await Promise.all([
    api.coachExamples(),
    api.dashboard(undefined, eid),
    api.principles(),
  ]);

  return (
    <CommandCenter
      examples={ex.examples}
      deals={db.deals}
      principles={pr.principles}
      role="manager"
      contextSlot={<ContextPane key="manager-context" deals={db.deals} role="manager" />}
    />
  );
}
````

## File: web/components/workspace/command-center.tsx
````typescript
"use client";

import type { ReactNode } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { useCachedState } from "@/lib/chat-store";
import type { Role } from "@/lib/session";
import type { CoachExample, DealRow, Principle } from "@/lib/types";
import { Workspace } from "./workspace";

/**
 * The Command Center shell: a live context pane (left) beside the Copilot
 * thread (right). The left pane is role-supplied via `contextSlot` — Junior
 * passes its deal/account context, Manager passes team triage — while the
 * collapsible chrome and the Workspace stay shared. Clicking an item in the
 * context pane grounds the Copilot via the shared workspace focus.
 *
 * Collapsing the context column hands its width to the chat, so the user can
 * run a focused conversation full-bleed and pop the context back open when they
 * need to switch. The open/closed state is cached so it survives navigation.
 */
export function CommandCenter({
  examples,
  deals,
  principles,
  contextSlot,
  role = "junior",
}: {
  examples: CoachExample[];
  deals: DealRow[];
  principles: Principle[];
  contextSlot: ReactNode;
  role?: Role;
}) {
  const { t } = useT();
  const [open, setOpen] = useCachedState<boolean>(`workspace:${role}:ctxOpen`, true);

  return (
    <div
      className={cn(
        "relative grid gap-4 lg:gap-8 h-full w-full min-h-0",
        open ? "lg:grid-cols-[280px_minmax(0,1fr)]" : "lg:grid-cols-1",
      )}
    >
      {!open && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          title={t("cc.todayWork")}
          className="absolute left-0 lg:-left-8 top-3 z-30 flex h-8 items-center gap-1.5 rounded-lg lg:rounded-l-none lg:rounded-r-lg lg:border-l-0 border border-border bg-card px-2.5 text-[12px] text-muted-foreground shadow-sm transition-colors hover:bg-muted hover:text-foreground shrink-0"
        >
          <PanelLeftOpen className="h-4 w-4" />
          <span className="lg:hidden xl:inline">{t("cc.todayWork")}</span>
        </button>
      )}

      {open && (
        <aside className="overflow-y-auto rounded-xl border border-border bg-card/40 p-3 h-full flex flex-col min-h-0 max-lg:max-h-[42vh]">
          <div className="mb-2 flex items-center justify-between shrink-0">
            <span className="eyebrow">{t("cc.context")}</span>
            <button
              type="button"
              onClick={() => setOpen(false)}
              title={t("cc.hidePanel")}
              className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <PanelLeftClose className="h-4 w-4" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto min-h-0">
            {contextSlot}
          </div>
        </aside>
      )}

      <div className={cn("min-w-0 h-full flex flex-col min-h-0", !open && "pl-12 lg:pl-16")}>
        <Workspace examples={examples} deals={deals} principles={principles} role={role} wide />
      </div>
    </div>
  );
}
````

## File: web/components/workspace/crew-turn.tsx
````typescript
"use client";

import { useEffect, useRef } from "react";
import { Building2, UserSearch, GraduationCap, Briefcase } from "lucide-react";
import { crewStream, teamStream, type CrewEvent, type ResolveCandidate } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useCachedState } from "@/lib/chat-store";
import { AnswerMd } from "@/components/assistant/message";
import { ExecutionTimeline, type ExecutionPhase } from "@/components/agent/agent-lane";

// Inline multi-agent execution — triggered by /crew or /team.
//
// UX model: one intelligent system investigating a customer.
// The timeline tells the story of what's happening; once the artifact arrives
// the timeline auto-collapses so the brief becomes the dominant element.
// State is cached per turn so switching tabs and back restores everything.
export function CrewTurn({
  turnId,
  conversationId,
  mode,
  query,
}: {
  turnId: number;
  conversationId: string;
  mode: "deal" | "team";
  query?: string;
  label?: string;
}) {
  const { t, lang } = useT();
  const key = `ws:crew:${conversationId}:${turnId}`;

  const [started,      setStarted]      = useCachedState<boolean>(`${key}:started`, false);
  const [phases,       setPhases]        = useCachedState<ExecutionPhase[]>(`${key}:phases`, []);
  const [brief,        setBrief]         = useCachedState<string>(`${key}:brief`, "");
  const [candidates,   setCandidates]    = useCachedState<ResolveCandidate[]>(`${key}:cands`, []);
  const [pickQuery,    setPickQuery]     = useCachedState<string>(`${key}:pq`, "");
  const [status,       setStatus]        = useCachedState<"running" | "done" | "error">(`${key}:status`, "running");
  const [showArtifact, setShowArtifact]  = useCachedState<boolean>(`${key}:show`, false);
  const [collapsed,    setCollapsed]     = useCachedState<boolean>(`${key}:collapsed`, false);

  const startedRef   = useRef(false);
  const ctrlRef      = useRef<AbortController | null>(null);
  const collapseRef  = useRef<ReturnType<typeof setTimeout> | null>(null);

  // First short, clean line of an agent's contribution → the collapsed summary.
  const hintFrom = (contribution?: string) =>
    contribution
      ?.split("\n")
      .map((l) => l.replace(/^#+\s*/, "").replace(/\*\*/g, "").trim())
      .find((l) => l.length > 2 && l.length < 80 && !/^[-–•]/.test(l));

  const start = (
    run: (onEvent: (e: CrewEvent) => void, opts: { signal: AbortSignal }) => Promise<void>,
  ) => {
    setStarted(true);
    setStatus("running");
    setCandidates([]);
    setPhases([]);
    setBrief("");
    setShowArtifact(false);
    setCollapsed(false);
    if (collapseRef.current) clearTimeout(collapseRef.current);

    const ctrl = new AbortController();
    ctrlRef.current = ctrl;

    const onEvent = (e: CrewEvent) => {
      switch (e.type) {
        case "crew": {
          // Seed ALL phases upfront — pending ones show as future work.
          setPhases(
            e.agents.map((a) => ({
              id: a.id,
              label: a.label,
              emoji: a.emoji,
              status: "pending" as const,
              tools: [],
            })),
          );
          break;
        }

        case "agent_tool":
          // A tool call → an indented subtask under its phase.
          setPhases((prev) =>
            prev.map((p) =>
              p.id === e.agent_id
                ? { ...p, tools: [...p.tools, { name: e.name, summary: e.summary || e.name }] }
                : p,
            ),
          );
          break;

        case "agent":
          setPhases((prev) =>
            prev.map((p) => {
              if (p.id !== e.id) return p;
              if (e.status === "running") return { ...p, status: "running" };
              if (e.status === "done")    return { ...p, status: "done", resultHint: hintFrom(e.contribution) };
              if (e.status === "error")   return { ...p, status: "done" };
              return p;
            }),
          );
          break;

        case "resolve":
          setCandidates(e.candidates);
          setPickQuery(e.query || "");
          break;

        case "final":
          setBrief(e.markdown);
          break;

        case "error":
          setStatus("error");
          break;
      }
    };

    run(onEvent, { signal: ctrl.signal }).then(() => {
      setStatus((s) => (s === "error" ? s : "done"));
      if (ctrlRef.current && !ctrlRef.current.signal.aborted) {
        // Artifact fades in after 300ms…
        setTimeout(() => setShowArtifact(true), 300);
        // …then timeline collapses 800ms later so artifact dominates.
        collapseRef.current = setTimeout(() => setCollapsed(true), 1100);
      }
    });
  };

  useEffect(() => {
    if (startedRef.current || started) return;
    startedRef.current = true;
    if (mode === "team") start((on, o) => teamStream(on, o));
    else start((on, o) => crewStream({ message: query }, on, o));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Cleanup collapse timer on unmount
  useEffect(() => () => { if (collapseRef.current) clearTimeout(collapseRef.current); }, []);

  const pick = (c: ResolveCandidate) => {
    if (c.deal_id) start((on, o) => crewStream({ dealId: c.deal_id! }, on, o));
    else           start((on, o) => crewStream({ message: c.name }, on, o));
  };

  const picking = candidates.length > 0 && phases.length === 0;

  const activePhase = phases.find((p) => p.status === "running") || phases.find((p) => p.status === "pending") || phases[phases.length - 1];
  
  const AGENT_NAMES_EN: Record<string, string> = {
    researcher: "RESEARCHER",
    coach: "COACH",
    strategist: "STRATEGIST",
    team_lead: "TEAM LEAD",
    analyst: "ANALYST",
  };

  let activeAgentName = mode === "team" ? "SENPAI MANAGER" : "SENPAI COACH";
  if (activePhase) {
    if (lang === "en" && AGENT_NAMES_EN[activePhase.id]) {
      activeAgentName = AGENT_NAMES_EN[activePhase.id];
    } else {
      activeAgentName = activePhase.label;
    }
  }

  return (
    <div className="flex gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-navy text-white">
        {mode === "team" ? (
          <Briefcase className="h-[18px] w-[18px]" />
        ) : (
          <GraduationCap className="h-[18px] w-[18px]" />
        )}
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
          {activeAgentName}
        </div>
        
        <div className="flex w-full flex-col gap-3 py-0.5">
          {/* Ambiguous customer picker (compact, list-based) */}
          {picking && (
        <div className="overflow-hidden rounded-xl border border-border bg-card shadow-[0_4px_20px_-10px_rgba(16,24,40,0.2)]">
          <div className="flex items-center gap-1.5 border-b border-border px-3 py-2 text-[12px] font-medium text-muted-foreground">
            <UserSearch className="h-3.5 w-3.5" />
            {lang === "ja"
              ? `「${pickQuery || query || ""}」は複数の顧客に一致します`
              : `"${pickQuery || query || ""}" matches several customers`}
          </div>
          <div className="flex flex-col">
            {candidates.map((c) => (
              <button
                key={c.customer_id}
                onClick={() => pick(c)}
                className="flex items-center gap-2.5 px-3 py-2 text-left text-[13px] transition-colors hover:bg-muted/60"
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                  <Building2 className="h-3 w-3 text-primary" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-medium text-foreground">{c.name}</span>
                  {c.deal_id && <span className="block font-mono text-[10.5px] text-muted-foreground">{c.deal_id}</span>}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Error with no phases — crew could not find target */}
      {status === "error" && phases.length === 0 && !picking && (
        <p className="text-[12.5px] text-conf-low">
          {mode === "deal" && query ? t("crew.notFound") : t("crew.failed")}
        </p>
      )}

          {/* Hierarchical execution timeline */}
          {phases.length > 0 && (
            <ExecutionTimeline
              phases={phases}
              collapsed={collapsed}
              onToggle={() => setCollapsed((v) => !v)}
              lang={lang}
            />
          )}

          {/* Final artifact — the hero; appears once all work finishes */}
          {brief && status === "done" && showArtifact && (
            <div className="mt-5 animate-in fade-in duration-500 fill-mode-both slide-in-from-bottom-2">
              <div className="mb-5 h-px w-8 bg-border" />
              <p className="eyebrow mb-4">{mode === "team" ? t("crew.team.brief") : t("crew.deal.brief")}</p>
              <AnswerMd text={brief} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
````

## File: docs/orchestration-architecture.md
````markdown
# Orchestration architecture

The reusable spine that turns Senpai's per-route gather/synthesis logic into one
layer: a **planner** produces a DAG of deterministic **capabilities**, an
**execution engine** runs them in parallel and collects their structured output
into an immutable **evidence bundle**, and a single **reasoner** synthesizes the
artifact. New capabilities (Filesystem, Email, Calendar, Browser, Office) become
*additive* — write one class, register it — instead of another rewrite.

> Status: **M0–M6 shipped.** M0 = the engine (`senpai/orchestration/`). M1 = Research.
> M2 = crew + team gather. M3 = account gather (`senpai/account/`) + a consolidation
> pass. M4 = the `/api/chat` tool loop on the engine via the **AdaptiveScheduler**. M5
> = the **Workspace capability** (`senpai/workspace/`) — sandboxed local documents, and
> the first production user of **runtime DAG expansion** (`ctx.expand`). M6 = the
> **`LLMPlanner`** (`senpai/planner/`) — goal → capability graph → engine → artifact,
> proven first on document generation (see "M6" and the Roadmap at the end).

---

## The pipeline

```
plan ──► ExecutionEngine ──► EvidenceBundle ──► [Reducer] ──► [Reasoner] ──► [Approval Gate] ──► artifact
          (capabilities)                          stub          seam            future
```

Two stages beyond the naive line exist because of the long-horizon target query
(*"prepare me for tomorrow's Endo Kogyo meeting — gather every proposal, quote,
note, PPTX, PDF, calendar event, email, playbook, then summarize and draft a
follow-up"*):

- **Reducer** — gathering "every document" overflows any single reasoner context.
  A map-reduce compaction step sits between bundle and reasoner. M0 ships a
  pass-through; a real `MapReduceReducer` lands when a capability can produce
  bundle-overflowing volume.
- **Approval Gate** — "draft a follow-up" is *effectful*. WRITE tasks pause the DAG
  for human approval. Today's two-step `confirm=` in `generate_*` is a hand-rolled
  instance; the gate generalizes it. Deferred until the first WRITE capability.

---

## Why this shape

Three of Senpai's five orchestration surfaces are *already* plan→gather→bundle→reason,
just hardcoded and inconsistent:

| Target concept | Already exists as | Location |
|---|---|---|
| EvidenceBundle | `ResearchBundle` (has provenance) | `api/server.py` |
| Capability executors | tool fns + `store` + `score_deal` | `tools/impl.py`, `data/store.py` |
| Parallel engine | `_worker` + `queue.Queue` + threads | `agent/crew.py` |
| Single reasoner | 4 copies of "one LLM over context" | research / crew / account / team |
| Target resolution | `resolve_crew_target`, `resolve_customer_detailed` | `crew.py`, `store.py` |

The one genuinely LLM-*planned* surface is `/api/chat`'s `stream_chat_turn` (the
model picks tools dynamically). The original scope was "unify the four deterministic
surfaces; leave the chat tool-loop alone." **M4 revised that:** the chat loop now runs
its tool calls *through the engine* via the AdaptiveScheduler (below), so it shares the
engine and parallelism — but its *planning* is still the LLM emitting tool calls, not a
`Planner`. The DAG-planning of open-ended goals is the `LLMPlanner`, still ahead.

---

## Design decisions

### Planner — a dynamic DAG
Not a flat list (can't express "web only if CRM misses" or "reason after all"),
not fixed execution levels (a barrier between levels stalls independent work). A
**DAG**: tasks declare `depends_on`; the engine computes readiness continuously.
Crucially the DAG **expands at runtime** — `Filesystem.find_documents` returns N
refs → the engine appends N `Office.extract` tasks. The breadth of a real prep
query is unknowable at plan time.

The planner stays *non-reasoning*: seed plans are deterministic; runtime expansion
is data-driven (not an LLM). A `Planner` Protocol seam lets a future `LLMPlanner`
choose capabilities for open-ended requests without touching the engine. **M0/M1
build plans as plain functions** — no Planner object yet.

### Task — 4 core fields, policy defaulted
```python
Task(id, capability, op="", inputs={}, depends_on=frozenset(),
     policy=DEFAULT_POLICY, group="default", summary="")
```
- `inputs` are literals; a task reads upstream outputs from `ctx.deps` — **no Ref
  DSL** (added later only if ergonomics demand).
- `TaskPolicy(timeout_s, retries, on_failure)` — one small struct, capability-level
  defaults. WRITE safety = the plan sets `retries=0`; no `OperationKind` enum yet.
- A Task carries **no result** — outcomes live in the bundle, keyed by `task.id`.
  Plan and result stay separate, which is what keeps both immutable.

### Capability — one domain, stable interface
```python
class Capability(Protocol):
    name: str
    def run(self, op, inputs, ctx) -> Evidence: ...
```
A capability owns a domain (CRM has `lookup_deal`/`list_proposals`; `run` dispatches
on `op`). It does deterministic work, returns structured `Evidence`, and **never
reasons, orchestrates, or calls another capability**. Its only window outward is
`ExecContext`:

```python
ExecContext(task_id, inputs, deps, emit, expand, cancel, deadline)
#   deps     upstream evidence by task id
#   emit     report a sub-step  -> task.progress event
#   expand   request new tasks  (runtime fan-out)
#   cancel   cooperative cancellation token
```
New cross-cutting concerns (auth/connections, tracing) are added as `ExecContext`
fields later — no capability signature changes.

### EvidenceBundle — immutable, append-only, no reconciliation
Each task writes exactly one `Evidence` fragment keyed by its id; fragments never
overwrite each other → no locks, order-independent. Two sources disagreeing is
**signal for the reasoner**, not something the engine resolves — provenance is
always preserved.

```python
Evidence(status, data, citations, confidence, provenance,
         task_id, capability, op, group, timing)   # last 5 stamped by the engine
```
- `data` is structured JSON, never markdown. `citations` are human handles
  ("SPR D003", "Playbook PB12", "file://…#slide3") the artifact can quote.
- `provenance` (machine locus, for audit/Retrieval-Explorer) is kept distinct from
  `citations` (renderable). `to_reasoner_view()` is the canonical, error-dropped,
  deterministically-ordered view the Reducer/Reasoner consume.

### Execution engine — one threaded scheduler loop
`ExecutionEngine.run(plan, emit) -> EvidenceBundle`. ThreadPoolExecutor, not
asyncio (the OpenAI client and store are blocking; threads parallelize them with no
stack rewrite; `crew.py` already proves the model). The loop:

1. absorb any tasks a running capability asked to add (`ctx.expand`)
2. submit every PENDING task whose dependencies are all terminal
3. wait for the next task; record evidence, emit events
4. if a `fail_run` task failed → cancel and drain
   until nothing is pending and nothing is running.

Supports: dependency-aware scheduling, parallelism, retries (READ-safe ops),
cooperative cancellation, **partial failure** (default `on_failure="skip"` — one
bad capability degrades, never crashes the run), runtime expansion. A capability
raising is caught and turned into an error fragment.

---

## Event model — one vocabulary

The engine is the single source. Events describe the **DAG lifecycle**, never a
domain — adding Browser/Email needs zero new event types. Every event carries
`type, run_id, seq` (monotonic), `ts`.

```
run.started {groups, planned_count}      plan.expanded {added_count, total_count}
task.started {task_id, capability, op, group, summary}
task.progress {task_id, message}         task.evidence {task_id, status, confidence, citations}
task.completed {task_id, duration, status}
task.retrying / task.failed              group.completed {group}
run.completed {completed, failed} / run.cancelled
# reserved (route/Reducer/Reasoner, not engine): reduce.* reason.* artifact.created
#                                                 approval.required auth.required
```

`group` + `summary` are the only layout drivers: a multi-lane `/crew` and a
single-stream `/research` are the **same event stream**, different grouping → the
front-end collapses to one `<ExecutionTimeline>` (Cursor / Deep-Research style).
During migration, thin per-route adapters translate these to the legacy SSE names
so the existing UI keeps working byte-for-byte.

---

## The Endo Kogyo walkthrough

1. **Resolve** "Endo Kogyo" → `customer_id` (existing resolver; ambiguity → picker).
2. **Seed plan** (deterministic `meeting_prep` template): parallel READ tasks —
   `CRM.list_deals/list_proposals/list_quotes`, `Activities.meeting_notes`,
   `Filesystem.find_documents`, `Calendar.find_events`, `Email.recent`,
   `Knowledge.relevant_playbooks`.
3. **Runtime expansion**: `find_documents` → N refs → `ctx.expand(Office.extract×N)`;
   `Email.recent` → threads → `Email.fetch_thread×M`. `plan.expanded` fires.
4. **Parallel gather** under per-capability concurrency caps + auth. `Email` token
   expired → `auth.required`; that branch degrades, the rest proceeds.
5. **EvidenceBundle** accumulates ~30 fragments with citations + confidence.
6. **Reducer** (30 docs overflow the reasoner) → per-document/group map summaries.
7. **Reasoner** (single) → prep summary + follow-up plan, citing sources.
8. **Approval Gate**: "draft follow-up" is WRITE → `approval.required` + preview →
   on approve, `Email.draft` / `Office.export_pptx` → `artifact.created`.

### Weaknesses this surfaces (and the answers)

| Weakness | Mitigation |
|---|---|
| Context overflow on "every document" | **Reducer** map-reduce before synthesis |
| Per-user auth/secrets for external caps | `ConnectionProvider` field on `ExecContext`; `auth.required` event |
| Cost / rate limits (Browser, APIs) | per-capability concurrency caps + `priority` + timeouts + cancellation |
| Effectful safety/ordering (send, book) | `OperationKind=WRITE` + **Approval Gate**; no auto-retry/cache |
| Repeated work across sessions | content-addressed `cache` key in `TaskPolicy` |
| Open-ended intent phrasing | `Planner` seam → future `LLMPlanner`, same `ExecutionPlan` |
| Non-reproducibility of web/email/browser | provenance + timestamps make it *auditable*, not reproducible |

The first four mitigations are *seams reserved in M0* (event constants,
`ExecContext`/`TaskPolicy` shape), not yet implemented — so adding them is not a
rewrite.

---

## M0 — what shipped

`senpai/orchestration/`, GPU-free, no network, not wired to routes:

| File | Role |
|---|---|
| `capability.py` | `Task`, `TaskPolicy`, `ExecutionPlan` (+cycle check), `Capability`, `ExecContext`, `CapabilityRegistry` |
| `evidence.py` | `Evidence` (`ok/empty/error`), `EvidenceBundle` (views, `to_reasoner_view`), `Timing` |
| `engine.py` | `ExecutionEngine` — the one scheduler loop |
| `events.py` | the unified event vocabulary (constants + shapes) |
| `reason.py` | `Reasoner` Protocol + `EchoReasoner` (no-LLM) + `LLMReasoner` (lazy) |
| `reducer.py` | `Reducer` Protocol + `PassthroughReducer` |
| `planner.py` | `Planner` Protocol seam |
| `__main__.py` | self-test |

**Self-test** (`python -m senpai.orchestration` → `RESULT: PASS`) proves: parallelism
(7 tasks 0.5s wall vs ~1.4s serial), dependency ordering, runtime fan-out, retries,
partial-failure degradation, ordered timeline, citations, error-dropping view.

### Simplifications taken (deferred, with a seam)
Planner classes, `Ref` input-binding DSL, `OperationKind` enum + Approval Gate, full
Reducer/Reasoner impls, plan-level reasoner/reducer specs, `priority`/`cache`/per-op
`defaults`, `ConnectionProvider`/`auth.required` — all dropped from M0, each kept as
a Protocol stub or a reserved field/constant so it is additive.

---

## Migration (zero-regression first)

- **M0** ✅ scaffolding, isolated, unit-tested.
- **M1** ✅ Research over the engine — parity-proven, live (details below).
- **M2** ✅ Crew + team gather over the engine — multi-agent UX preserved (below).
- **M3** ✅ Consolidation + account gather over the engine — parity-proven (below).
- **Simplification phase** (deferred, post-migration) — converge the three reasoners
  onto `reason.py`, unify the SSE dialects onto `events.py`, then (a product
  decision) collapse the multi-agent flow into one Planner → Engine → Reasoner.
  `/api/chat`'s dynamic tool-loop stays until the `LLMPlanner` seam is built.

Capabilities call `store`/`scoring` directly (structured), not the string tools in
`impl.py` — those stay for the chat loop. `llm/client.py` is untouched; the Reasoner
wraps `stream_complete`.

---

## M1 — Research migrated (parity-proven)

The Research gather now runs on the engine; resolution, source emission, ambiguity,
web-fallback, and the reasoner are unchanged. **The frontend cannot tell.**

`senpai/research/`:

| File | Role |
|---|---|
| `shaping.py` | byte-for-byte replicas of the server's `_deal_summary` (split into `deal_facts` + `health_read`), `_activity_summary`, `_public_customer`, `_products_for_deals` |
| `capabilities.py` | `CRM`, `Activities`, `SimilarDeals`, `Health`, `Environment`, `Web` — thin wrappers over `store` / `score_deal` / `find_similar_deals` / `web_search_typed` |
| `plan.py` | `research_plan(mode=customer\|deal)` + `web_plan()` |
| `gather.py` | runs the engine, re-merges facts+health, rebuilds provenance per mode → the exact legacy field set |

**The DAG (proves dependency handling):** `crm`, `activities`, `similar_deals`,
`environment` run in parallel; **`health` depends on `crm` + `similar_deals`** (it
scores every deal id they surfaced). The gather re-merges
`{**deal_facts, "health": …}` into the identical legacy `_deal_summary` shape.

**Wiring:** `_build_research_bundle` / `_build_deal_context_bundle` get `*_orch`
twins that the live `/research` (and the chat research route) call; the legacy
builders are kept as the **parity oracle**, not deleted (per "remove only after
parity is confirmed").

**Parity strategy:** the LLM answer is non-deterministic, so we don't diff text — we
prove the *evidence bundle fed to the reasoner is identical*
(`orch.to_dict() == legacy.to_dict()`), which makes artifact quality identical by
construction. `tests/test_research_parity.py` (84 cases): 40 customers × valid-
customer bundle, 40 deal-context bundles, citations present, not-found shell,
web-fallback pass-through, and **partial-failure degradation** (a capability raising
→ that source becomes empty/`not_found`, the run still completes — where the legacy
inline code would have crashed). Full suite: **219 passed, 0 regressions** (the one
remaining `test_research.py` failure is pre-existing and unrelated — verified
identical with M1 changes stashed).

**One deviation:** the not-found **web fallback stays on the direct `web_search_typed`
seam**, not routed through the engine. It is a single external call (not gather
orchestration) and existing tests patch that symbol; routing it through a 1-task plan
added no value and moved a test seam. `WebCapability` is still built and exercised by
the golden test via `web_search_via_engine`.

---

## M2 — Crew gather migrated (multi-agent UX preserved)

`/crew` (and the `/team` fan-out) keep their exact UX — Researcher + Coach run in
parallel, then the Strategist synthesizes a Strategy Brief — but each agent's data
gathering now runs on the engine. Prompts, artifacts, streaming events, and
provenance are unchanged.

**Why not the M1 capabilities directly?** The crew prompts were written against the
*string* outputs of the deterministic tools (`query_spr`, `find_similar_deals`,
`search_notes`, …); M1's capabilities emit *structured* evidence for the research
summarizer. Feeding the crew M1's structured bundle would change its grounding and
therefore its artifact. So M2 shares the **engine and the same underlying tool
layer**, via one tiny capability rather than the M1 capability classes:

`senpai/agent/`:

| File | Role |
|---|---|
| `capabilities.py` | `ToolCapability` — runs any existing tool through `impl.dispatch(op, inputs)`. One wrapper over the shared tool layer; **zero retrieval logic duplicated** (no CRM/Activities/Health/Environment/SimilarDeals/Web reimplemented). |
| `plan.py` | `researcher_plan` (4 tools) / `coach_plan` (1) / `rep_analyst_plan` (2) — same tools, args, order, and human summaries as before. |
| `gather.py` | `run_agent_gather(plan, agent_id, emit)` — runs the plan, translates each `task.started` into the legacy `agent_tool` event (same name/summary/order), returns the tool strings for the agent to assemble its grounding. |

`crew.py`'s `_run_researcher` / `_run_coach` / `_run_rep_analyst` lost their inline
tool calls and now call `run_agent_gather`; everything else (the parallel `_worker`
threads, the prompts, `_run_strategist`, the `crew`/`agent`/`final`/`done` events) is
untouched. Net effect: each agent's tools now run **in parallel** instead of
sequentially (a latency win), with the grounding reassembled in the prompt's fixed
order so the artifact is identical.

**Parity** (`tests/test_crew_parity.py`, 63 cases): per-deal researcher grounding ==
legacy tool strings (30 deals), coach grounding == legacy (30), rep-analyst gather ==
legacy, partial-failure degradation (a tool raising → empty slot, gather completes),
and an **end-to-end `run_crew` event-sequence test** (LLM stubbed) asserting the full
`crew → agents+agent_tool → strategist → final → done` timeline is preserved. Full
suite: **282 passed, 0 new regressions** (same single pre-existing `test_research.py`
failure, unrelated).

After M2, every retrieval-heavy workflow (research, crew, team) shares the engine.
The remaining per-agent reasoning (Researcher/Coach/Strategist prose) is intentionally
kept — collapsing it into a single Reasoner is the post-migration simplification, not
part of M2.

---

## M3 — Consolidation + account migrated

Three steps, recommended order, parity-first:

**1. Dead code removed.** `_legacy_research_stream` (server.py) — an unused duplicate
of the live `research_stream` and the only remaining caller of the legacy
`_build_research_bundle` — deleted. The legacy bundle builders stay (now used only by
the M1 parity oracle).

**2. Shaping de-duplicated.** `_deal_summary` / `_public_customer` / `_activity_summary`
/ `_products_for_deals` existed byte-identically in both `server.py` and
`research/shaping.py`. `research/shaping.py` is now canonical; the server functions
are thin aliases that delegate to it (preserving every call site and the implicit
`_today()` default). The M1/M2 parity suites (147 cases) confirm no behavioral change.

**3. Account gather on the engine** (`senpai/account/`):

| File | Role |
|---|---|
| `capabilities.py` | `AccountContextCapability` — wraps `build_account_context` as structured evidence (same call, same `(context_text, meta)`) |
| `plan.py` | `account_plan()` — a single gather task |
| `gather.py` | `gather_account_context()` — runs the plan on the engine; degrades to the package's own not-found shape on failure |

`account_commentary` now calls `gather_account_context` instead of
`build_account_context`. The commentary artifact is driven entirely by
`account_commentary_prompt(context_text)`, so identical `(context_text, meta)` ⇒
identical prompt ⇒ identical artifact. The route's events (`start` / `artifact_meta`
/ `context` / `strategy` / `delta` / `done`), the prompt, and the inline reasoner
stream are untouched.

The account context is one composite text+meta unit, so it is wrapped as a **single**
capability (like M1's web fallback). Decomposing it into the shared
CRM/Health/Environment capabilities — and converging the account prompt onto
structured evidence — belongs to the simplification phase, not M3.

**Parity** (`tests/test_account_parity.py`, 123 cases): 60 accounts × {ja, en} assert
`gather_account_context == build_account_context`, plus not-found parity and
degraded-failure resilience. Full suite: **405 passed, 0 new regressions** (same lone
pre-existing `test_research.py` failure).

---

## Migration complete — state of the spine

Every retrieval-heavy workflow now gathers through the engine:

| Workflow | Gather | Reasoner (still bespoke) | Events |
|---|---|---|---|
| research | engine (6 caps, DAG) | `_summarize_research_bundle` | source/answer |
| crew | engine (`ToolCapability`) | per-agent `simple_complete` + strategist | agent/agent_tool |
| team | engine (`ToolCapability`) | team-lead `simple_complete` | agent/agent_tool |
| account | engine (1 cap) | inline `stream_complete` | context/delta |
| `/api/chat` | LLM-planned tool loop (intentionally not migrated) | routed synthesis | tool/delta |

This table captured the state after M3. **M4 then put `/api/chat` on the engine**
(AdaptiveScheduler) and **M5 added the Workspace capability + runtime expansion** — see
those sections and the Roadmap for the current picture. The remaining work is the
`LLMPlanner` (next) plus the deferred simplification (converge the reasoners onto
`reason.py`, unify the SSE dialects, the multi-agent-collapse product decision).

---

## M4: Adaptive Execution (The Chat Loop Integration)

The `/api/chat` tool loop has now been integrated with the orchestration engine using a new **AdaptiveScheduler**. 

Instead of requiring the LLM to explicitly reason about parallelism (e.g. through a `parallel_map` tool), the runtime transparently identifies opportunities for parallel execution. The LLM simply emits consecutive tool calls in a single turn, and the scheduler determines execution strategy.

### 1. Capability Metadata and Policies
Every tool declares an execution `policy` (`READ` or `WRITE`) and a `namespace`:
- `READ` tools are side-effect free (e.g., `web_search`, `search_products`) and can be run concurrently.
- `WRITE` tools mutate state (e.g., `schedule_meeting`, `generate_pptx`) and must run sequentially.

### 2. The AdaptiveScheduler
When the LLM emits a set of independent tool calls:
1. The scheduler partitions the calls into batches (stages).
2. Consecutive `READ` operations are grouped into a single parallel stage.
3. `WRITE` operations act as barriers, forcing preceding stages to resolve and running sequentially themselves.
4. An `ExecutionPlan` is generated and passed to the existing `ExecutionEngine`.

This allows a prompt like *"Find the best laptops from MSI, ASUS, Lenovo, and Acer"* to execute 4 web searches simultaneously in the backend, radically reducing latency, while the LLM remains completely unaware of the orchestration mechanics.

### 3. Stability and UI
- **Context Length Safety**: When many parallel tools run, their concatenated output could overflow the context window (particularly for the fallback model). To guarantee stability, the engine actively truncates massive parallel payloads (e.g. to 1500 chars) before handing the evidence bundle back to the Reasoner.
- **Visualizing Parallelism**: In the frontend, tool events are tagged with a `batchId`. The `workspace` chat UI dynamically groups tools from the same batch and renders them using a hierarchical "ticks and squares" timeline, clearly exposing the parallel execution behavior to the user.

---

## M5 — Workspace capability (local files; runtime expansion in production)

The first capability that reaches **outside the seed database** — it finds and reads
real local documents and returns their text as structured Evidence into the same
EvidenceBundle every other capability feeds. It is also the **first production use of
the engine's runtime DAG expansion** (`ctx.expand`), which until now only the M0
self-test exercised. This is the proof that the spine scales past the seed DB.

`senpai/workspace/` (GPU-free, read-only, sandboxed):

| File | Role |
|---|---|
| `sandbox.py` | The single choke point. `safe_path` resolves a path (symlinks included) and rejects anything outside `config.WORKSPACE_ROOT`; `list_documents()` recursively lists allowed files; a missing root degrades to `[]`, never raises. |
| `extract.py` | Text extraction per type — PDF (`pypdf`), DOCX (`python-docx`), PPTX (`python-pptx`), XLSX (`openpyxl`), TXT/MD (plain). Char-capped, never raises: a corrupt file yields empty text + a note. |
| `capabilities.py` | `WorkspaceCapability` — `op="find"` relevance-ranks documents and **`ctx.expand`s one `extract` task per hit** (parallel); `op="extract"` reads one file to structured Evidence with a `file://<rel>` citation. |
| `plan.py` | `workspace_plan(query)` — a single `find` seed task; the DAG grows at runtime to fit what's on disk. |
| `gather.py` | Runs the plan on the engine; `workspace_evidence()` returns structured `{found, documents, citations}`; `gather_workspace_documents()` reduces to a grounded string. |

**The runtime fan-out (the whole point):**

```
workspace:find ──► ctx.expand ──► workspace:extract × N   (parallel)
```

`find` can't know how many documents exist, so the plan seeds one task and the
capability appends N `extract` tasks once it has looked at the disk — bounded by
`WORKSPACE_MAX_FILES`. `plan.expanded` fires; the extracts run in parallel; each lands
as its own fragment keyed `find:extract:<i>`.

**Surface + safety.** Exposed as the `search_workspace_documents` chat tool (junior /
research / manager subsets), `SEARCH` policy in `metadata.py`, and a `trace.record`
for the Retrieval Explorer. **Strictly read-only** — there is no write/edit/delete op
by design; sandbox escape is unit-tested. Config: `SENPAI_WORKSPACE_ROOT`,
`WORKSPACE_EXTS`, `WORKSPACE_MAX_FILES`, `WORKSPACE_MAX_CHARS`, `WORKSPACE_MAX_BYTES`.

**Tests** (`tests/test_workspace.py`, 7): sandbox rejects `../` / absolute / symlink
escapes; every declared type extracts; `find` fans out into one `extract` per document
(the DAG *grew*); citations are `file://…`; fan-out is capped; a missing workspace
degrades. Full suite: **7 new tests pass, 0 new regressions** (the two remaining
failures — `test_semantic` lexical, `test_research` ambiguity — are pre-existing and
fail in isolation, unrelated to this work).

### Reuse of the Segment-Intelligence pattern
Workspace deliberately mirrors `docs/segment-intelligence.md`'s proven shape: **the
tool returns grounded retrieval; the chat loop's existing synthesis round does the
"reduce"** (no nested LLM call in the tool). Same `trace.record` → Retrieval Explorer,
same "citations are provenance" discipline (`file://<rel>` here, `deal_id`s there).
So the two are already composable: a manager question can draw on **segment reports**
(why we lose these deals, from the seed DB) *and* **local files** (the actual proposal
we sent) in one EvidenceBundle. Fusing them into one grounded answer is exactly the
job of the `LLMPlanner` — now shipped for document generation (M6).

---

## M6 — LLMPlanner (goal → capability graph → artifact)

The planner that had been a `Planner` Protocol seam since M0 is now real, and
**deliberately minimal**: it is *not* an autonomous or recursive agent. It makes
exactly one decision — *which capabilities are needed to ground this document* — and
emits a static `ExecutionPlan`. The existing engine runs it; the capabilities do the
work; the terminal capability turns the bundle into the artifact.

```
goal ──► LLMPlanner ──► ExecutionPlan ──► ExecutionEngine ──► EvidenceBundle ──► artifact
         (selects caps)   (fixed 2-level DAG)   (reused)          (reused)         (a file)
```

`senpai/planner/` (the whole surface is small on purpose):

| File | Role |
|---|---|
| `selection.py` | `Selection` (the plan the planner emits) + `heuristic_selection` — the deterministic default and the always-available fallback. **IDs are resolved here from the store, never by the model** (the "never invent an ID" rule): an explicit `D###`, else a customer name → its primary open deal. A `proposal` with no resolvable deal degrades to a free `pptx`. |
| `capabilities.py` | Gather + terminal capabilities, each a **thin adapter over logic that already exists**. Gather: `conversation` / `workspace` / `crm` / `knowledge` / `web` emit uniform `{"text", "label"}` grounding. Three terminals **consume the bundle (via `ctx.deps`)**, never re-gather: `documents` authors+renders+registers a downloadable file (`author`/`proposal`/`render`/`registry`); `workspace_write` writes a markdown **note into the workspace** (sandbox-checked, confirm-gated `edit_workspace_document`); `workspace_organize` **tidies the workspace** — buckets loose files into topic folders via the sandbox's no-overwrite `move_within`, **preview-first**, moves only on an explicit apply cue. |
| `plan.py` | `document_plan(selection)` — the fixed two-level DAG: gather capabilities at level 0 (parallel, independent), one `documents` task depending on all of them. The edges *are* the ordering; the engine and capabilities stay ignorant of it. |
| `llm_planner.py` | `LLMPlanner.plan(goal)` — one `simple_complete` call picks the capability set + doc kind (strict JSON, validated); any failure falls straight back to `heuristic_selection`. The model chooses *what to gather*, never IDs, ordering, or execution. |
| `run.py` | `run_document_goal(goal, conversation=…)` — plan → execute on the shared `ExecutionEngine` → read the terminal `documents` fragment as the artifact. `python -m senpai.planner.run "D001 の提案書"` runs it (proposal path is GPU-free). |

**Capability-driven, not tool-driven.** The plan is expressed in capabilities
(Workspace, CRM, Knowledge, Web, Conversation, Documents), so the planner selects
*which sources ground the artifact* rather than scripting tool calls. The grounding
that `generate_pptx` used to gather *inside* the tool (conversation + workspace + CRM +
web) is now the **explicit gather half of the graph**, and the `documents` capability
consumes it from the bundle — the same grounding, promoted from a hidden side-effect to
first-class plan nodes.

**Why the artifact step has no Reasoner yet.** For document generation the artifact
*is* the file and the `documents` capability already emits the one-line confirmation, so
`run.py` returns the fragment directly. The `reason.py` seam is where meeting-prep /
account-intelligence will synthesize prose over the bundle — the next expansion, not
this milestone.

**Surface — integrated into normal chat.** `/api/chat` routes by intent: a
**document-generation goal** (`_is_document_goal` — a *create* verb + a *document* noun,
tight enough that "draft an email" / "make a quote" / "tell me about X" stay put; 稟議
excluded) is auto-routed through the planner via the shared `_plan_stream`, which emits
the same `plan | context | tool | document | answer` events the chat UI already renders —
so a plain *"make a proposal for Murata Printing"* prompt just works, **no `/plan`
prefix**. An attached file rides along as conversation context; a selector-picked deal is
authoritative. `POST /api/plan` remains as an explicit/programmatic surface. The ReAct
tool-loop and its `generate_*` tools are untouched — the planner is an additive front
door, not a replacement. Full walkthrough: **`docs/llm-planner.md`**.

**Tests** (`tests/test_planner.py`, 8, GPU-free): selection resolves a real deal id /
web-gates a general deck / resolves a customer name to its open deal; the plan's
`documents` task depends on every gather task and is acyclic; **end-to-end** a proposal
goal plans → runs on the engine → produces a *registered, downloadable* PPTX grounded on
conversation + CRM + workspace (the capability graph feeding the artifact, not a
re-gather); the `documents` grounding assembles deps most-specific-first; the authored
pptx path degrades cleanly with no model. Full suite: **8 new tests pass, 0 new
regressions** (the same two pre-existing isolation failures remain).

---

## Roadmap — what's live vs. what's ahead

| Capability / seam | State |
|---|---|
| ExecutionEngine, EvidenceBundle, events | ✅ live (M0) |
| Research / crew / team / account gather | ✅ live (M1–M3) |
| Chat loop on engine (AdaptiveScheduler) | ✅ live (M4) |
| Runtime DAG expansion (`ctx.expand`) | ✅ **live in production** (M5 Workspace) |
| Workspace: local file find + extract | ✅ live (M5), read-only |
| `LLMPlanner` — goal → capability graph → artifact | ✅ **live (M6)** — document generation; `senpai/planner/`, `POST /api/plan` |
| `LLMPlanner` — meeting-prep / account-intelligence / open-ended | ▶ **next** — same spine, add a Reasoner pass over the bundle |
| Approval Gate (`OperationKind=WRITE`) | ⏳ stub — generalizes today's `confirm=` |
| Reducer (map-reduce before synthesis) | ⏳ `PassthroughReducer` stub |
| `ConnectionProvider` / `auth.required` (Email/Calendar) | ⏳ reserved field/event |
| Converge the 4 bespoke reasoners onto `reason.py` | ⏳ deferred simplification |

**The `LLMPlanner` is now live for document generation (M6).** The next milestone
extends the *same spine* to open-ended flows like *"prepare me for tomorrow's Endo Kogyo
meeting"*: the planner already selects a capability graph and runs it on the engine — the
additions are (a) a broader plan shape (more gather capabilities, e.g. Segment
Intelligence + Activities) and (b) a real **Reasoner** pass (`reason.py`) that synthesizes
prose over the bundle instead of the trivial artifact-is-the-file step, with the
**Reducer** compacting when local files overflow the context. Citing both `deal_id`s and
`file://` sources already falls out of the EvidenceBundle. M6 is the proof that the
full hop — goal → capability selection → engine → bundle → artifact — works end to end.
````

## File: senpai/data/store.py
````python
"""In-memory data store — the single source of truth for tools and front ends.

Loads the committed seed JSON once (module-level cache) and exposes small,
pure-Python query helpers. The four production tables (deals, sales_activities,
quotes, orders) mirror the real SPR schema (see Schema.md); reps/customers/
products/environments/playbook are supplementary reference data the SPR tables
reference. Everything downstream (scoring, tools, dashboard, chat) reads through
here, so the data model lives in exactly one place.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Literal

from senpai import config

_FILES = ["reps", "customers", "products", "environments", "playbook",
          "deals", "sales_activities", "quotes", "orders", "coaching_threads"]


@lru_cache(maxsize=1)
def _load() -> dict[str, list[dict]]:
    data: dict[str, list[dict]] = {}
    for name in _FILES:
        path = config.SEED_DIR / f"{name}.json"
        rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        # Overlay any runtime-ingested rows (daily reports, etc.) ON TOP of the
        # committed seed. The seed stays canonical/byte-stable; ingested rows live
        # in a separate gitignored dir and are demo-only (see config.INGESTED_DIR).
        over = config.INGESTED_DIR / f"{name}.json"
        if over.exists():
            extra = json.loads(over.read_text(encoding="utf-8"))
            if isinstance(extra, list):
                # reps overlay UPSERTS by employee_id: an overlay row replaces the
                # seed row of the same id (so an admin can edit reports_to on an
                # existing seed rep), and new ids (signups) append. Every other
                # table stays purely additive. Seed on disk is never mutated.
                if name == "reps":
                    by_id = {r.get("employee_id"): r for r in extra}
                    rows = [by_id.pop(r.get("employee_id"), r) for r in rows]
                    rows = rows + [r for r in extra if r.get("employee_id") in by_id]
                else:
                    rows = rows + extra
        data[name] = rows
    return data


def append_activity(record: dict) -> None:
    """Persist one ingested sales_activity to the gitignored overlay file, then
    drop the cache so the next read includes it. Never touches the committed seed.
    Build records with senpai.ingestion.persist.build_activity_record so the shape
    matches the seed exactly."""
    config.INGESTED_DIR.mkdir(parents=True, exist_ok=True)
    path = config.INGESTED_DIR / "sales_activities.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    rows.append(record)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    reload()


def next_employee_id() -> str:
    """The next free employee id (R01, R02, … → R25). Ids are 'R' + a number."""
    nums = [int(re.sub(r"\D", "", r["employee_id"]) or 0) for r in all_reps()]
    return f"R{(max(nums) + 1) if nums else 1:02d}"


def append_rep(record: dict) -> None:
    """Persist one new rep (a signup) to the gitignored overlay, then drop the
    cache so the next read includes it. Never touches the committed seed — same
    additive-overlay pattern as append_activity. `record` must match the seed rep
    shape (employee_id, name, role, department, division, specialty_tags,
    is_top_performer) plus the optional reports_to link."""
    config.INGESTED_DIR.mkdir(parents=True, exist_ok=True)
    path = config.INGESTED_DIR / "reps.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    rows.append(record)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    reload()


def set_reports_to(employee_id: str, manager_id: str) -> dict:
    """Reassign a rep to a manager by writing reports_to into the gitignored reps
    overlay, then dropping the cache. Works for seed reps too: the overlay upserts
    by employee_id (see _load), so writing a row for R05 replaces the seed R05 on
    read without duplicating it or touching committed seed. Returns the updated
    rep. Raises ValueError if the rep is unknown or the target is not a
    senior/expert (only they can be managers — mirrors signup's _manager_pool)."""
    rep = get_rep(employee_id)
    if rep is None:
        raise ValueError(f"unknown rep {employee_id}")
    manager = get_rep(manager_id)
    if manager is None or manager.get("role") not in ("senior", "expert"):
        raise ValueError(f"{manager_id} is not an assignable manager")
    if manager_id == employee_id:
        raise ValueError("a rep cannot report to themselves")

    config.INGESTED_DIR.mkdir(parents=True, exist_ok=True)
    path = config.INGESTED_DIR / "reps.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    updated = {**rep, "reports_to": manager_id}
    for i, r in enumerate(rows):
        if r.get("employee_id") == employee_id:
            rows[i] = updated
            break
    else:
        rows.append(updated)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    reload()
    return updated


@lru_cache(maxsize=1)
def customer_aliases() -> dict[str, list[str]]:
    """English / romaji / known-alias forms per customer_id (customer_aliases.json).
    Keys starting with '_' (e.g. '_comment') are metadata and skipped."""
    path = config.SEED_DIR / "customer_aliases.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, list)}


def reload() -> None:
    """Drop the cache (used by tests / after regenerating seed)."""
    _load.cache_clear()
    _index.cache_clear()
    customer_aliases.cache_clear()
    _alias_index.cache_clear()


# --- indexes ---------------------------------------------------------------
# The relational accessors below (activities_for_deal, quote_for_deal, …) used to
# linear-scan the full table on every call. Hot paths like coach.cases call them
# tens of thousands of times → O(rows × calls). Build the lookups ONCE here,
# memoized against the loaded store and dropped on reload(), so each accessor is
# an O(1) dict hit. Pure performance — identical results.
@lru_cache(maxsize=1)
def _index() -> dict:
    acts_by_deal: dict[str, list[dict]] = {}
    for a in all_activities():
        did = a.get("deal_id")
        if did is not None:
            acts_by_deal.setdefault(did, []).append(a)
    for rows in acts_by_deal.values():
        rows.sort(key=lambda a: a.get("activity_date", ""), reverse=True)

    orders_by_cust: dict[str, list[dict]] = {}
    for o in all_orders():
        orders_by_cust.setdefault(o.get("customer_id"), []).append(o)
    for rows in orders_by_cust.values():
        rows.sort(key=lambda o: o.get("ordered_at", ""), reverse=True)

    quotes_by_cust: dict[str, list[dict]] = {}
    for q in all_quotes():
        quotes_by_cust.setdefault(q.get("customer_id"), []).append(q)
    for rows in quotes_by_cust.values():
        rows.sort(key=lambda q: q.get("quoted_at", ""), reverse=True)

    deals_by_cust: dict[str, list[dict]] = {}
    deals_by_rep: dict[str, list[dict]] = {}
    for d in all_deals():
        deals_by_cust.setdefault(d.get("customer_id"), []).append(d)
        deals_by_rep.setdefault(deal_rep_id(d), []).append(d)

    return {
        "acts_by_deal": acts_by_deal,
        "orders_by_cust": orders_by_cust,
        "quotes_by_cust": quotes_by_cust,
        "deals_by_cust": deals_by_cust,
        "deals_by_rep": deals_by_rep,
        "deal_by_id": {d["deal_id"]: d for d in all_deals()},
        "customer_by_id": {c["customer_id"]: c for c in all_customers()},
        "rep_by_id": {r["employee_id"]: r for r in all_reps()},
        "product_by_id": {p["product_code"]: p for p in all_products()},
        "quote_by_id": {q["quote_id"]: q for q in all_quotes()},
        "order_by_id": {o["order_id"]: o for o in all_orders()},
    }


# --- collections -----------------------------------------------------------
def all_deals() -> list[dict]:
    return _load()["deals"]


def all_reps() -> list[dict]:
    return _load()["reps"]


def all_customers() -> list[dict]:
    return _load()["customers"]


def all_products() -> list[dict]:
    return _load()["products"]


def all_activities() -> list[dict]:
    return _load()["sales_activities"]


def all_quotes() -> list[dict]:
    return _load()["quotes"]


def all_orders() -> list[dict]:
    return _load()["orders"]


def all_playbook() -> list[dict]:
    return _load()["playbook"]


def open_deals() -> list[dict]:
    """Live pipeline = deals whose order_rank is in the open band (2_A+ … 6_P)."""
    return [d for d in all_deals() if config.is_open_rank(d.get("order_rank"))]


# --- field accessors -------------------------------------------------------
def deal_rep_id(deal: dict) -> str:
    """Employee ID owning a deal (from sales_info)."""
    return (deal.get("sales_info") or {}).get("employee_id", "")


# --- lookups ---------------------------------------------------------------
def get_deal(deal_id: str) -> dict | None:
    # IDs are uppercase by schema; exact-match first (fast internal path), then an
    # uppercase fallback so user input like "d128" resolves the same as "D128".
    idx = _index()["deal_by_id"]
    return idx.get(deal_id) or (idx.get(deal_id.upper()) if isinstance(deal_id, str) else None)


def get_customer(customer_id: str) -> dict | None:
    idx = _index()["customer_by_id"]
    return idx.get(customer_id) or (idx.get(customer_id.upper()) if isinstance(customer_id, str) else None)


def get_rep(employee_id: str) -> dict | None:
    return _index()["rep_by_id"].get(employee_id)


def get_product(product_code: str) -> dict | None:
    return _index()["product_by_id"].get(product_code)


def get_environment(customer_id: str) -> dict | None:
    return next((e for e in _load()["environments"]
                 if e["customer_id"] == customer_id), None)


# --- relations -------------------------------------------------------------
def deals_for_rep(employee_id: str) -> list[dict]:
    return _index()["deals_by_rep"].get(employee_id, [])


def deals_for_customer(customer_id: str) -> list[dict]:
    return _index()["deals_by_cust"].get(customer_id, [])


def activities_for_deal(deal_id: str) -> list[dict]:
    """All sales activities for a deal, newest first (the deal's interaction log)."""
    return _index()["acts_by_deal"].get(deal_id, [])


def activities_for_customer(customer_id: str) -> list[dict]:
    """All activities across a customer's deals, newest first."""
    rows: list[dict] = []
    for d in deals_for_customer(customer_id):
        rows.extend(activities_for_deal(d["deal_id"]))
    return sorted(rows, key=lambda a: a.get("activity_date", ""), reverse=True)


def daily_reports_for_rep(employee_id: str) -> list[dict]:
    """002_Daily Report activities authored by a rep."""
    return [a for a in all_activities()
            if (a.get("sales_info") or {}).get("employee_id") == employee_id
            and a.get("activity_type") == "002_Daily Report"]


def all_coaching_threads() -> list[dict]:
    """Manager↔rep coaching threads (coaching_threads.json; [] if absent)."""
    return _load().get("coaching_threads", [])


def coaching_threads_for_rep(employee_id: str) -> list[dict]:
    """Coaching threads owned by a rep, newest first."""
    rows = [t for t in all_coaching_threads() if t.get("employee_id") == employee_id]
    return sorted(rows, key=lambda t: t.get("created_at", ""), reverse=True)


def coaching_threads_for_deal(deal_id: str) -> list[dict]:
    """Coaching threads raised on a specific deal, newest first."""
    rows = [t for t in all_coaching_threads() if t.get("deal_id") == deal_id]
    return sorted(rows, key=lambda t: t.get("created_at", ""), reverse=True)


def coachees_of(manager_id: str) -> set[str]:
    """Employee ids this manager coaches — the reps in any thread where they are
    the manager_id. This is the only explicit 'who I coach' relationship in the
    data (there's no org/reporting chart), so it defines a manager's team."""
    return {t["employee_id"] for t in all_coaching_threads()
            if t.get("manager_id") == manager_id and t.get("employee_id")}


def team_of(manager_id: str) -> set[str]:
    """A manager's full team: reps they coach in threads (coachees_of) plus reps
    assigned to them at signup (reports_to). Existing managers get their
    thread-based team; freshly-created juniors join via reports_to even before
    they have any deals or threads."""
    assigned = {r["employee_id"] for r in all_reps() if r.get("reports_to") == manager_id}
    return coachees_of(manager_id) | assigned


def quote_for_deal(deal_id: str) -> dict | None:
    """A deal's quote, resolved via the quote_id linked on its activities."""
    qid = next((a.get("quote_id") for a in activities_for_deal(deal_id)
                if a.get("quote_id")), None)
    return _index()["quote_by_id"].get(qid) if qid else None


def orders_for_deal(deal_id: str) -> list[dict]:
    """Order lines for a deal, resolved via the order_id linked on its activities."""
    order_by_id = _index()["order_by_id"]
    seen: set[str] = set()
    out: list[dict] = []
    for a in activities_for_deal(deal_id):
        oid = a.get("order_id")
        if oid and oid not in seen and oid in order_by_id:
            seen.add(oid)
            out.append(order_by_id[oid])
    return out


def orders_for_customer(customer_id: str) -> list[dict]:
    """All orders for a customer, newest first (the account's purchase history)."""
    return _index()["orders_by_cust"].get(customer_id, [])


def quotes_for_customer(customer_id: str) -> list[dict]:
    """All quotes for a customer, newest first (the account's quoting history)."""
    return _index()["quotes_by_cust"].get(customer_id, [])


# --- display helpers -------------------------------------------------------
def customer_name(customer_id: str) -> str:
    c = get_customer(customer_id)
    return c["name"] if c else customer_id


def rep_name(employee_id: str) -> str:
    r = get_rep(employee_id)
    return r["name"] if r else employee_id


# --- backward-compat shims (for the friend-owned web-app / coach experiment) ---
# Our pipeline reads sales_activities directly; the experiment still calls the old
# notes/report API. These derive old-shaped data from sales_activities so that code
# keeps working unchanged. They are NOT used by our pipeline.
def notes_for_deal(deal_id: str) -> list[dict]:
    """Old 'notes' shape, derived from sales_activities (newest first). Each row
    carries both the new keys and the legacy aliases (date/text/channel/rep_id)."""
    out = []
    for a in activities_for_deal(deal_id):
        out.append({**a,
                    "date": a.get("activity_date"),
                    "text": a.get("daily_report"),
                    "channel": a.get("activity_type"),
                    "rep_id": (a.get("sales_info") or {}).get("employee_id")})
    return out


def report_for_deal(deal_id: str) -> dict | None:
    """No standalone report object exists in the SPR schema (daily_report lives on
    activities). Returned as None for compat; callers tolerate it."""
    return None


def reports_for_rep(employee_id: str) -> list[dict]:
    """Compat alias — daily-report activities for a rep."""
    return daily_reports_for_rep(employee_id)


def find_customer_by_name(name: str) -> dict | None:
    """Loose JA match: exact, then substring (handles 'アクメ商事' vs '株式会社アクメ商事').
    For cross-language resolution (English/romaji/alias) use resolve_customer."""
    if not name:
        return None
    n = name.strip()
    for c in all_customers():
        if c["name"] == n:
            return c
    for c in all_customers():
        if n in c["name"] or c["name"] in n:
            return c
    return None


# --- alias-aware customer resolution ---------------------------------------
# Resolves Japanese, English, romaji and known-alias forms to the canonical
# customer record — BEFORE any retrieval. Built so a name that maps to more than
# one customer is treated as ambiguous and never guessed (we'd rather miss than
# fabricate the wrong customer's facts).
_CORP_TOKENS = ["株式会社", "有限会社", "合同会社", "(株)", "（株）", "(有)", "（有）"]


def _norm(s: str) -> str:
    """Case/space-insensitive key. JA text is unaffected by lower()."""
    return " ".join((s or "").split()).lower()


def name_forms(name: str) -> list[str]:
    """A customer name plus its bare form (corporate prefix/suffix removed), so
    '有限会社村田印刷' is found from text that just says '村田印刷'."""
    forms = {name}
    bare = name
    for tok in _CORP_TOKENS:
        bare = bare.replace(tok, "")
    bare = bare.strip()
    if len(bare) >= 2:
        forms.add(bare)
    return [f for f in forms if f]


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, set[str]]:
    """Map a normalized name/alias key -> set of customer_ids that answer to it.
    A key owned by >1 customer is ambiguous (callers must not guess)."""
    aliases = customer_aliases()
    idx: dict[str, set[str]] = {}
    for c in all_customers():
        cid = c["customer_id"]
        keys = set(name_forms(c.get("name", ""))) | set(aliases.get(cid, []))
        for k in keys:
            kk = _norm(k)
            if len(kk) >= 2:
                idx.setdefault(kk, set()).add(cid)
    return idx


@dataclass
class CustomerCandidate:
    customer_id: str
    name: str
    matched_aliases: list[str] = field(default_factory=list)


@dataclass
class CustomerResolution:
    status: Literal["resolved", "ambiguous", "not_found"]
    query: str
    customer: dict | None = None
    candidates: list[CustomerCandidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "query": self.query,
            "customer": self.customer,
            "candidates": [asdict(c) for c in self.candidates],
        }


def _candidate(customer_id: str, match_key: str = "") -> CustomerCandidate:
    c = get_customer(customer_id) or {"customer_id": customer_id, "name": customer_id}
    aliases = []
    for form in name_forms(c.get("name", "")) + customer_aliases().get(customer_id, []):
        if not match_key or _norm(form) == match_key:
            aliases.append(form)
    return CustomerCandidate(
        customer_id=customer_id,
        name=c.get("name", customer_id),
        matched_aliases=sorted(set(aliases)),
    )


def resolve_customer_detailed(query: str) -> CustomerResolution:
    """Resolve one customer, preserving ambiguity as a first-class state."""
    q = (query or "").strip()
    if not q:
        return CustomerResolution(status="not_found", query=query or "")

    by_id = get_customer(q)
    if by_id:
        return CustomerResolution(status="resolved", query=q, customer=by_id)

    key = _norm(q)
    ids = _alias_index().get(key)
    if ids:
        if len(ids) == 1:
            return CustomerResolution(
                status="resolved", query=q, customer=get_customer(next(iter(ids))))
        return CustomerResolution(
            status="ambiguous",
            query=q,
            candidates=[_candidate(cid, key) for cid in sorted(ids)],
        )

    loose = find_customer_by_name(q)
    if loose:
        return CustomerResolution(status="resolved", query=q, customer=loose)

    return CustomerResolution(status="not_found", query=q)


def resolve_customer(query: str) -> dict | None:
    """Resolve a customer from an id, JA name, English/romaji name or known alias.
    Returns None when the query is empty, unknown, or ambiguous (maps to >1
    customer) — never a guess. This is the single entry point tools and the coach
    use before retrieval."""
    return resolve_customer_detailed(query).customer


def _key_in_text(key: str, low_text: str) -> bool:
    """Whether an alias `key` occurs in `low_text`. ASCII/romaji keys require WORD
    boundaries so 'new' does not match inside 'news' and 'canon' would not match
    'canonical' — latin words run together with spaces, so bare substring matching
    produces false customers. Japanese keys keep substring matching (JA has no word
    boundaries, and names are contiguous), e.g. '村田印刷' inside '村田印刷さん'."""
    if key.isascii():
        return re.search(r"\b" + re.escape(key) + r"\b", low_text) is not None
    return key in low_text


_CUSTOMER_ID_RE = re.compile(r"\bC\d{1,4}\b", re.IGNORECASE)


def _customer_id_in_text(text: str) -> str | None:
    """A single, unambiguous customer id (e.g. 'C14') named anywhere in the text.
    Returns the canonical id when exactly one VALID id appears, else None (0 ids,
    or several different ids → defer to name matching / ambiguity). Mirrors how the
    research bridge already extracts deal ids ('D027') from a phrased request."""
    seen = list(dict.fromkeys(m.group(0).upper()
                              for m in _CUSTOMER_ID_RE.finditer(text or "")))
    valid = [cid for cid in seen if get_customer(cid)]
    return valid[0] if len(valid) == 1 else None


def _best_alias_matches(text: str) -> tuple[tuple[int, set[str]] | None,
                                            tuple[int, set[str]] | None]:
    """Scan the alias index for the most specific name/alias present in `text`,
    tracked separately for UNIQUELY-resolving keys and AMBIGUOUS (multi-customer)
    keys. Returns (best_unique, best_ambiguous) as (key_len, ids) or None.

    A unique full name must beat a shared stem even when the stem is "longer" by
    raw character count — character length is not comparable across scripts, so a
    4-char exact kanji name ('松田運輸' → one customer) would otherwise lose to a
    7-char romaji stem ('matsuda' → four 松田 companies) and re-trigger ambiguity
    forever. Callers prefer `best_unique` when present; ambiguity is only real
    when NO unique alias is in the text."""
    low = (text or "").lower()
    best_uniq: tuple[int, set[str]] | None = None
    best_amb: tuple[int, set[str]] | None = None
    for key, ids in _alias_index().items():
        if not _key_in_text(key, low):
            continue
        if len(ids) == 1:
            if best_uniq is None or len(key) > best_uniq[0]:
                best_uniq = (len(key), ids)
        elif best_amb is None or len(key) > best_amb[0]:
            best_amb = (len(key), ids)
    return best_uniq, best_amb


def match_customer_in_text(text: str) -> dict | None:
    """Find the customer named anywhere in free text — across JA, English, romaji
    and alias forms. A uniquely-resolving name wins (so 'Aozora Services' beats
    'Aozora', and an exact '松田運輸' beats the shared 'matsuda' stem); an ambiguous
    stem with no unique name present resolves to None so we never attribute the
    wrong customer's history. An explicit customer id ('C14') is the most precise,
    unambiguous signal and wins over any name match."""
    cid = _customer_id_in_text(text)
    if cid:
        return get_customer(cid)
    best_uniq, _ = _best_alias_matches(text)
    if best_uniq:
        return get_customer(next(iter(best_uniq[1])))
    return None


def ambiguous_match_in_text(text: str) -> list[dict]:
    """When the customer name/alias found in `text` maps to MORE THAN ONE customer
    (e.g. 'marusan' → 丸三クリニック / 丸三食品 / 丸三商事 / 丸三システム) AND no
    unique full name is also present, return those candidate records so callers can
    disambiguate instead of silently failing. Empty when a unique name is present
    (use match_customer_in_text) or no name matches. This is the surface-the-
    ambiguity counterpart to the never-guess resolvers."""
    best_uniq, best_amb = _best_alias_matches(text)
    if best_uniq:  # an exact full name pins it down → not ambiguous
        return []
    if best_amb:
        return [c for cid in sorted(best_amb[1]) if (c := get_customer(cid))]
    return []


def resolve_customer_in_text(text: str) -> CustomerResolution:
    """Resolve the customer NAMED ANYWHERE in free text — preserving ambiguity as
    a first-class state. Unlike resolve_customer_detailed (which treats the whole
    query as the name), this locates the customer token inside an action/verb-
    wrapped message: 'create a quotation for akebono' → ambiguous (3 あけぼの
    companies), not not_found. So callers (e.g. research) reach internal records
    instead of falling through to web search on a phrased request. An explicit
    customer id ('research about C14') resolves directly via match_customer_in_text."""
    uniq = match_customer_in_text(text)
    if uniq:
        return CustomerResolution(status="resolved", query=text, customer=uniq)
    amb = ambiguous_match_in_text(text)
    if amb:
        low = (text or "").lower()
        best_key = ""
        for key, ids in _alias_index().items():
            if _key_in_text(key, low) and len(ids) > 1 and len(key) > len(best_key):
                best_key = key
        return CustomerResolution(
            status="ambiguous", query=text,
            candidates=[_candidate(c["customer_id"], best_key) for c in amb])
    return CustomerResolution(status="not_found", query=text)


# --- fallback resolution: fuzzy matching + company-name extraction ----------

_COMPANY_SUFFIXES = (
    "商事", "商会", "製作所", "印刷", "サービス", "システム",
    "電機", "工業", "建設", "産業", "電子", "情報", "物産", "興業",
)
_COMPANY_PREFIXES_RE = (
    r"株式会社\s*([^\s、。\n]{2,10})",
    r"有限会社\s*([^\s、。\n]{2,10})",
    r"合同会社\s*([^\s、。\n]{2,10})",
    r"([^\s、。\n]{2,10})\s*(?:株式会社|有限会社|合同会社|（株）|\(株\))",
)


def extract_company_names_from_text(text: str) -> list[str]:
    """Pull likely company name tokens from free text using suffix/prefix patterns.
    Returns unique candidates, longest first — callers try each through the
    resolver (exact/alias) to find a match."""
    import re
    found: list[str] = []
    # Explicit legal-form patterns
    for pat in _COMPANY_PREFIXES_RE:
        for m in re.finditer(pat, text):
            cand = m.group(0).strip()
            if len(cand) >= 2:
                found.append(cand)
    # Suffix patterns: e.g. 'アクメ商事', '大和システム'
    for suf in _COMPANY_SUFFIXES:
        for m in re.finditer(rf"([^\s、。\n]{{1,8}}{re.escape(suf)})", text):
            found.append(m.group(0))
    # De-dup, longest first
    seen: set[str] = set()
    out: list[str] = []
    for c in sorted(found, key=len, reverse=True):
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def fuzzy_match_customer_in_text(
    text: str,
    threshold: float = 0.72,
) -> tuple[dict | None, float]:
    """Approximate customer match when exact/alias lookup finds nothing.

    Slides a window the length of each alias key over the normalised note text
    and scores character-level similarity (difflib SequenceMatcher). Only
    unambiguous alias keys (mapping to exactly one customer) are considered.
    Keys shorter than 4 normalised chars are skipped to avoid false positives.

    Returns (customer, best_score). customer is None when best_score < threshold.
    """
    import difflib

    low = (text or "").lower()
    if not low:
        return None, 0.0

    best_c: dict | None = None
    best_score = 0.0

    for key, ids in _alias_index().items():
        if len(key) < 4 or len(ids) != 1:
            continue
        klen = len(key)
        if klen > len(low):
            # Try full note as single window
            r = difflib.SequenceMatcher(None, key, low, autojunk=False).ratio()
            if r > best_score:
                best_score = r
                if r >= threshold:
                    best_c = get_customer(next(iter(ids)))
            continue
        for start in range(len(low) - klen + 1):
            window = low[start: start + klen]
            r = difflib.SequenceMatcher(None, key, window, autojunk=False).ratio()
            if r > best_score:
                best_score = r
                if r >= threshold:
                    best_c = get_customer(next(iter(ids)))

    return (best_c if best_score >= threshold else None), best_score
````

## File: senpai/planner/capabilities.py
````python
"""The planner's capabilities: one per grounding source, plus the terminal document
producer. Every one is a THIN adapter over logic that already exists — no retrieval,
scoring, or rendering is reimplemented here. This is the whole point of the
capability graph: the planner selects *which* of these run; the engine runs them;
their Evidence lands in one bundle; the Documents capability consumes that bundle.

    conversation ─┐
    workspace ────┤
    crm ──────────┼──►  documents   (depends on all gathered; authors the artifact)
    knowledge ────┤
    web ──────────┘

Gather capabilities emit a uniform `{"text": <grounding>, "label": <section>}` so the
Documents capability can concatenate them into one grounding block regardless of
which were selected. All are READ/SEARCH and degrade to empty — never raise.
"""
from __future__ import annotations

from typing import Any, Mapping

from senpai.orchestration import ExecContext
from senpai.orchestration.evidence import Evidence
from senpai.orchestration.metadata import CapabilityMetadata, OperationKind

# Section-header labels mirror the doc tools' inline grounding blocks, so a deck
# authored via the planner reads identically to one authored via generate_pptx.
_LABELS = {
    "conversation": "これまでの会話・確定済みの文脈",
    "workspace": "ローカル文書（あなたのファイル）",
    "crm": "社内データ",
    "knowledge": "社内ナレッジ",
    "web": "Web検索",
}


def _text_evidence(name: str, text: str, citations=()) -> Evidence:
    text = (text or "").strip()
    if not text:
        return Evidence.empty(provenance={"capability": name})
    return Evidence.ok({"text": text, "label": _LABELS.get(name, name)},
                       citations=tuple(citations), status="ok")


class ConversationCapability:
    """Grounding from the live session — a company/quote/deal already discussed.
    Reuses the doc tools' own `_conversation_grounding` over the published convo."""
    name = "conversation"
    metadata = CapabilityMetadata(OperationKind.READ)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.tools.impl import _conversation_grounding
        text = _conversation_grounding(str(inputs.get("query", "")))
        ctx.emit("会話文脈あり" if text else "会話文脈なし")
        return _text_evidence("conversation", text)


class WorkspaceCapability:
    """Relevant LOCAL documents (sandboxed, read-only). Reuses the doc tools'
    relevance-gated `_workspace_grounding`, which runs the real find→extract."""
    name = "workspace"
    metadata = CapabilityMetadata(OperationKind.SEARCH, max_concurrency=4)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.tools.impl import _workspace_grounding
        text = _workspace_grounding(str(inputs.get("query", "")))
        ctx.emit("該当文書あり" if text else "該当文書なし")
        # Citations are the file provenance already embedded in the text ("出典: file://…").
        return _text_evidence("workspace", text)


class CRMCapability:
    """Internal SPR records for the resolved deal/customer. Reuses `impl.query_spr`."""
    name = "crm"
    metadata = CapabilityMetadata(OperationKind.READ, cacheable=True)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.data import store
        from senpai.tools.impl import query_spr
        deal_id = str(inputs.get("deal_id") or "")
        customer_id = str(inputs.get("customer_id") or "")
        if deal_id:
            text, cite = query_spr(deal_id=deal_id), f"SPR {deal_id}"
        elif customer_id:
            text, cite = query_spr(customer=customer_id), f"SPR {customer_id}"
            # query_spr's customer branch is a summary line per deal only — unlike
            # its deal_id branch, it never includes activity/daily-report history.
            # Without an open deal_id (the common case for a closed-won/lost
            # account), that history is the only place a real win/loss reason
            # ("competitor comparison", "budget on hold") lives — pull it directly
            # so authoring doesn't have to guess a cause.
            acts = store.activities_for_customer(customer_id)[:5]
            if acts:
                text += "\n直近の活動:\n" + "\n".join(
                    f"  ・{a['activity_date']} {a['deal_id']} [{a['activity_type']}] {a['daily_report']}"
                    for a in acts)
        else:
            return Evidence.empty(provenance={"capability": "crm"})
        ctx.emit("社内記録を取得")
        return _text_evidence("crm", text, citations=[cite])


class KnowledgeCapability:
    """Validated playbook / approved coaching knowledge for the goal. Reuses
    `impl.search_knowledge` (attributed, cited snippets)."""
    name = "knowledge"
    metadata = CapabilityMetadata(OperationKind.SEARCH, cacheable=True)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.tools.impl import search_knowledge
        text = search_knowledge(query=str(inputs.get("query", "")), limit=3)
        if "見つかりません" in text:
            return Evidence.empty(provenance={"capability": "knowledge"})
        ctx.emit("社内ナレッジを取得")
        return _text_evidence("knowledge", text)


class WebCapability:
    """External web search for factual/current topics. Reuses `impl.web_search`."""
    name = "web"
    metadata = CapabilityMetadata(OperationKind.SEARCH, max_concurrency=4, retries=1)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.tools.impl import web_search
        try:
            text = web_search(query=str(inputs.get("query", "")))
        except Exception as e:  # noqa: BLE001 — web is best-effort grounding
            return Evidence.empty(provenance={"capability": "web", "error": str(e)})
        ctx.emit("Web検索を実施")
        return _text_evidence("web", text)


# Order gathered grounding lands in the document, most-specific first.
_GATHER_ORDER = ("conversation", "workspace", "crm", "knowledge", "web")


class DocumentsCapability:
    """The terminal producer: consume the gathered EvidenceBundle (via ctx.deps),
    assemble one grounding block, and author + render + register the artifact —
    reusing the existing author/proposal/render/registry logic. `op` is the doc kind
    (proposal | pptx | docx). This capability does NOT re-gather: its grounding is
    exactly what the selected capabilities put in the bundle."""
    name = "documents"
    metadata = CapabilityMetadata(OperationKind.WRITE, parallel_safe=False,
                                  idempotent=False, retries=0)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        kind = op or "pptx"
        if kind == "proposal":
            return self._proposal(inputs, ctx)
        return self._authored(kind, inputs, ctx)

    # -- grounding assembled from the bundle (not re-gathered) -------------------
    def _grounding(self, ctx: ExecContext) -> str:
        by_cap = {ev.capability: ev for ev in ctx.deps.values()}
        blocks = []
        for cap in _GATHER_ORDER:
            ev = by_cap.get(cap)
            if ev and ev.status in ("ok", "partial") and ev.data.get("text"):
                blocks.append(f"【{ev.data.get('label', cap)}】\n{ev.data['text']}")
        return "\n\n".join(blocks)

    def _citations(self, ctx: ExecContext) -> list[str]:
        cites: list[str] = []
        for ev in ctx.deps.values():
            cites.extend(ev.citations)
        return cites

    # -- proposal: deal-scoped, deterministic (GPU-free) ------------------------
    def _proposal(self, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.documents import proposal, registry
        deal_id = str(inputs.get("deal_id") or "")
        if not deal_id:
            return Evidence.error("proposal requires a deal_id",
                                  provenance={"capability": "documents"})
        deal_ids = [str(d) for d in (inputs.get("deal_ids") or [])]
        res = proposal.generate(deal_id, lang=str(inputs.get("lang", "ja")),
                                deal_ids=deal_ids or None)
        if res is None:
            return Evidence.error(f"deal {deal_id} not found",
                                  provenance={"capability": "documents"})
        path, doc_ctx, spec = res
        rec = registry.register("proposal", path, deal_id=deal_id)
        ctx.emit(f"提案書を生成: {rec['filename']}")
        outline = [{"title": s.get("title", "")} for s in spec.get("slides", [])]
        n = len(doc_ctx.deals)
        msg = (f"提案書(PPTX)を生成しました: {rec['filename']}（{n}件の案件を統合）"
              if n > 1 else f"提案書(PPTX)を生成しました: {rec['filename']}")
        return self._artifact_evidence(rec, ctx, msg, outline=outline)

    # -- pptx/docx: free-prompt, authored over the gathered grounding -----------
    def _authored(self, kind: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.documents import author, registry
        from senpai.documents.render import output_path, render_docx, render_pptx
        goal = str(inputs.get("goal") or inputs.get("prompt") or "")
        lang = str(inputs.get("lang", "ja"))
        # Whether a CRM customer resolved — independent of deal status, this alone
        # decides the sales-pitch voice (see playbook.deck_style_guide).
        customer_scoped = bool(inputs.get("customer_id"))
        grounding = self._grounding(ctx)
        if not author._use_llm():
            return Evidence.error("model required for pptx/docx authoring",
                                  provenance={"capability": "documents", "kind": kind})
        if kind == "docx":
            spec = author.author_doc(goal, grounding=grounding, lang=lang)
            if spec is None:
                return Evidence.error("author unavailable",
                                      provenance={"capability": "documents"})
            path = output_path("docx", spec.get("_title") or goal[:30], "docx")
            render_docx(spec, path)
            rec = registry.register("docx", path)
            n = len(spec.get("sections", []))
            msg = f"文書(DOCX)を生成しました: {rec['filename']}（{n}セクション）。"
            outline = [{"title": s.get("heading", "")} for s in spec.get("sections", [])]
        else:
            spec = author.author_deck(goal, grounding=grounding, lang=lang,
                                      customer_scoped=customer_scoped)
            if spec is None:
                return Evidence.error("author unavailable",
                                      provenance={"capability": "documents"})
            path = output_path("pptx", spec.get("_title") or goal[:30], "pptx")
            render_pptx(spec, path)
            rec = registry.register("pptx", path)
            n = len(spec.get("slides", []))
            msg = f"プレゼン(PPTX)を生成しました: {rec['filename']}（{n}スライド）。"
            outline = [{"title": s.get("title", "")} for s in spec.get("slides", [])
                      if s.get("layout") != "title"]
        ctx.emit(f"資料を生成: {rec['filename']}")
        return self._artifact_evidence(rec, ctx, msg, outline=outline)

    def _artifact_evidence(self, rec: dict, ctx: ExecContext, msg: str,
                           outline: list | None = None) -> Evidence:
        document = {"doc_id": rec["doc_id"], "kind": rec["kind"],
                    "filename": rec["filename"], "download_url": rec["download_url"]}
        data = {"text": msg, "document": document, "grounded_on": sorted(
                    ev.capability for ev in ctx.deps.values()
                    if ev.status in ("ok", "partial") and ev.data.get("text"))}
        if outline:
            data["outline"] = outline
        return Evidence.ok(
            data, citations=[*self._citations(ctx), f"doc://{rec['doc_id']}"], status="ok")


# --- workspace WRITE terminals: note (create a text file) + organize (tidy) --------
import re as _re


def _slugify(text: str, default: str = "note") -> str:
    base = _re.sub(r"[^\w]+", "-", (text or "").strip().lower()).strip("-")
    base = _re.sub(r"-{2,}", "-", base)
    return (base[:48] or default)


# Deterministic filename → destination folder classifier for organize. Keyword-based,
# GPU-free; a file that matches nothing lands in "other/". Order = priority.
_ORGANIZE_RULES = (
    ("quotes",        ("見積", "quote", "estimate", "quotation", "お見積")),
    ("proposals",     ("提案", "proposal")),
    ("meeting-notes", ("議事", "meeting", "kickoff", "minutes", "打合", "面談", "notes", "memo", "メモ")),
    ("reports",       ("報告", "report", "レポート")),
    ("contracts",     ("契約", "contract", "nda", "agreement", "覚書")),
)


def _organize_bucket(name: str) -> str:
    low = name.lower()
    for folder, keys in _ORGANIZE_RULES:
        if any(k.lower() in low for k in keys):
            return folder
    return "other"


class WorkspaceWriteCapability:
    """Terminal that WRITES a short text note INTO the workspace (a real file the rep
    keeps), authored from the gathered grounding + the goal. Reuses the existing,
    sandbox-checked, confirm-gated `impl.edit_workspace_document` — this capability
    does not open a path itself. Read-gather → write is how the planner produces a
    persisted note instead of a downloadable artifact."""
    name = "workspace_write"
    metadata = CapabilityMetadata(OperationKind.WRITE, parallel_safe=False,
                                  idempotent=False, retries=0)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.tools.impl import edit_workspace_document
        goal = str(inputs.get("goal") or inputs.get("prompt") or "")
        grounding = _grounding_from_deps(ctx)
        content = self._authored(goal, grounding, str(inputs.get("lang", "ja")))
        path = str(inputs.get("path") or "").strip() or self._pick_path(goal)
        result = edit_workspace_document(path, content, confirm=True)
        if result.startswith("エラー") or "エラーが発生" in result:
            return Evidence.error(result, provenance={"capability": "workspace_write"})
        ctx.emit(f"ノートを保存: {path}")
        grounded_on = sorted(ev.capability for ev in ctx.deps.values()
                             if ev.status in ("ok", "partial") and ev.data.get("text"))
        return Evidence.ok({"text": result, "saved_path": path, "kind": "note",
                            "grounded_on": grounded_on},
                           citations=[f"file://{path}"], status="ok")

    def _pick_path(self, goal: str) -> str:
        # A filename named in the goal wins; otherwise a slug under notes/.
        m = _re.search(r"([\w./-]+\.(?:md|txt|json|csv))", goal, _re.IGNORECASE)
        if m:
            return m.group(1)
        return f"notes/{_slugify(goal)}.md"

    def _authored(self, goal: str, grounding: str, lang: str) -> str:
        from senpai.documents import author
        if author._use_llm():
            instr = (
                "You are writing a concise MARKDOWN note to save into the user's files. "
                "Return ONLY the note body (no code fence). "
                f"Write in {'Japanese' if lang == 'ja' else 'English'}.\n"
                f"Use the reference context as the source of facts; do not invent figures.\n"
                f"Request: {goal}\n\n"
                f"{('参考情報:\n' + grounding) if grounding else '(参考情報なし)'}")
            out = author._complete(instr)
            if out:
                return out.strip()
        # Deterministic fallback: the grounding itself, titled.
        title = goal.strip() or "メモ"
        body = grounding or "(参考情報なし)"
        return f"# {title}\n\n{body}\n"


class WorkspaceOrganizeCapability:
    """Terminal that TIDIES the workspace: buckets loose documents into topic folders
    (quotes / proposals / meeting-notes / …) by a deterministic filename classifier.
    `op='plan'` previews the moves (read-only, the default — organizing real files is
    destructive); `op='apply'` performs them via the sandbox's no-overwrite
    `move_within`. Files already inside a subfolder are left alone."""
    name = "workspace_organize"
    metadata = CapabilityMetadata(OperationKind.WRITE, parallel_safe=False,
                                  idempotent=False, retries=0)

    def _llm_organize_bucket(self, names: list[str]) -> dict[str, str]:
        from senpai.documents import author
        import json, re
        
        if not author._use_llm() or not names:
            return {n: _organize_bucket(n) for n in names}
            
        prompt = (
            "You are an assistant organizing a user's files. "
            "Given the list of filenames below, assign a single short folder name to each file based on its likely content. "
            "Use standard categories like 'quotes', 'proposals', 'meeting-notes', 'reports', 'contracts', "
            "or create custom descriptive ones like 'invoices', 'research', 'specs'. "
            "Return strictly a JSON object mapping the exact filename to the folder name. No prose.\n\n"
            "Files:\n" + "\n".join(f"- {n}" for n in names)
        )
        
        try:
            out = author._complete(prompt)
            if out:
                m = re.search(r"\{.*\}", out, re.DOTALL)
                if m:
                    mapping = json.loads(m.group(0))
                    return {n: str(mapping.get(n, _organize_bucket(n))).strip("/") for n in names}
        except Exception:
            pass
            
        return {n: _organize_bucket(n) for n in names}

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.workspace import sandbox
        docs = sandbox.list_documents()
        root = sandbox.workspace_root()
        
        # Only reorganize files sitting at the ROOT (don't churn already-filed docs).
        root_files = [p for p in docs if "/" not in sandbox.rel(p) and "\\" not in sandbox.rel(p)]
        
        if root_files:
            file_to_folder = self._llm_organize_bucket([p.name for p in root_files])
        else:
            file_to_folder = {}

        moves: list[tuple[str, str]] = []
        for p in root_files:
            rel = sandbox.rel(p)
            folder = file_to_folder.get(p.name, _organize_bucket(p.name))
            dest = f"{folder}/{p.name}"
            if dest != rel:
                moves.append((rel, dest))

        if not moves:
            return Evidence.ok({"text": "整理対象のファイルはありません（すべて分類済み）。",
                                "kind": "organize", "moves": []}, status="ok")

        preview = "\n".join(f"  {s} → {d}" for s, d in moves)
        if op != "apply":
            body = (f"【整理プレビュー（未実行・{len(moves)}件）】\n{preview}\n\n"
                    "実行するには「整理して実行」/「apply」と指示してください。")
            ctx.emit(f"{len(moves)}件の移動を提案")
            return Evidence.ok({"text": body, "kind": "organize", "applied": False,
                                "moves": [{"from": s, "to": d} for s, d in moves]},
                               status="ok")

        done, failed = [], []
        for s, d in moves:
            try:
                sandbox.move_within(s, d)
                done.append((s, d))
            except Exception as e:  # noqa: BLE001 — one bad move must not abort the rest
                failed.append((s, str(e)))
        ctx.emit(f"{len(done)}件を整理")
        lines = [f"【整理を実行しました（{len(done)}件）】",
                 *(f"  {s} → {d}" for s, d in done)]
        if failed:
            lines.append(f"スキップ {len(failed)}件: " + "、".join(f"{s}({e})" for s, e in failed))
        return Evidence.ok({"text": "\n".join(lines), "kind": "organize", "applied": True,
                            "moves": [{"from": s, "to": d} for s, d in done]}, status="ok")


def _grounding_from_deps(ctx: ExecContext) -> str:
    """Assemble gathered grounding from ctx.deps, most-specific-first (shared by the
    Documents and WorkspaceWrite terminals)."""
    by_cap = {ev.capability: ev for ev in ctx.deps.values()}
    blocks = []
    for cap in _GATHER_ORDER:
        ev = by_cap.get(cap)
        if ev and ev.status in ("ok", "partial") and ev.data.get("text"):
            blocks.append(f"【{ev.data.get('label', cap)}】\n{ev.data['text']}")
    return "\n\n".join(blocks)


def build_registry():
    """A registry with all planner capabilities, ready for the ExecutionEngine."""
    from senpai.orchestration import CapabilityRegistry
    reg = CapabilityRegistry()
    for cap in (ConversationCapability(), WorkspaceCapability(), CRMCapability(),
                KnowledgeCapability(), WebCapability(), DocumentsCapability(),
                WorkspaceWriteCapability(), WorkspaceOrganizeCapability()):
        reg.register(cap)
    return reg
````

## File: docs/week6_phase2_week2_progress.md
````markdown
# Senpai — Progress Report
### Internship Week 6 · Phase 2, Week 2 · June 2026
**Team:** AI Department (intern team) · **Audience:** Manager / mentors / Givery team
**Project:** Senpai — Sales Knowledge & Onboarding Copilot for Otsuka Shokai

---

## 0. Executive Summary

This week we transformed Senpai from a working prototype into a credible, production-shaped
system. The core engine remained deterministic and grounded — we never moved that principle —
but we expanded it across five major directions simultaneously:

1. **Performance.** A memoized index layer cut coaching API latency from ~7s to ~140ms (~54×
   faster) and the full test suite from 36s to 1.4s.
2. **Expanded intelligence surfaces.** Account Intelligence (8-dimension customer health),
   Morning Briefing (urgency-ranked action list), a full Account Expansion engine (cross-sell /
   upsell / growth opportunities), and a Strategic Tier + Regional Stance engine (deal-size and
   region drive a transparent, deterministic coaching posture).
3. **Deeper coaching.** Rep coaching profiles, fiscal-year progress tracking, coaching threads,
   a coaching explainability layer, and a growth/motivation portal — all deterministic.
4. **Document generation.** Four new tools: `generate_proposal` (4-slide PPTX from SPR data),
   `generate_ringisho` (Japanese 稟議書 DOCX), `generate_pptx` (free-prompt general PPTX),
   `generate_docx` (free-prompt general DOCX) — all grounded, two-step confirm before file creation.
5. **Retrieval evolution.** Hybrid BM25 + dense vector search with Reciprocal Rank Fusion,
   a runtime knowledge graph (744 nodes) with multi-hop queries, and a `search_notes` tool
   surfaced to the model — making the system meaning-aware without GPU at runtime.
6. **Workspace shell.** A unified conversational surface replacing the old split
   Assistant + Coach pages — slash commands, immutable artifacts, streaming senior reads,
   file attachment, and multi-sheet XLSX export.
7. **Ingestion via Paperclip.** A multimodal ingestion pipeline (audio/image/text) that writes
   structured `sales_activities` records through an editable draft UI — closing the capture loop
   so the knowledge base can grow from real field activity.

The total test suite grew to **137 tests (1 skipped)** across 17 test files. All engine APIs
remain GPU-free.

---

## 1. Architecture principles that held this week

Everything new was built against the same design spine established in Week 1:

| Principle | How it was upheld this week |
|---|---|
| **Deterministic first** | Every new subsystem (account health, expansion, morning briefing, coaching profile, progress, explainability, growth) computes its output in pure Python. The LLM only narrates the already-computed package. |
| **LLM as presentation layer** | `generate_proposal` / `generate_ringisho` inject numbers from the deterministic `DocumentContext`; the LLM writes only the value-proposition line and the 稟議書 prose. Numbers never come from the model. |
| **Grounded or silent** | Every new API endpoint includes a strict grounding contract ("never invent", "quote numbers exactly", "refer to signals by `[id]`"). On LLM failure, the deterministic summary is served unchanged. |
| **Single source of truth** | All new engines read through `store.py` — nothing bypasses the central data layer. |
| **Overlay persistence** | Ingested activities append to a gitignored overlay layer; the committed seed is never mutated. |
| **Knowledge / Experience / Motivation loop** | Week 1 established these as the design spine. This week's growth portal (§7), coaching progress (§6.2), and morning briefing (§5) close the loop explicitly. |

---

## 2. Performance — Store Indexing

**Problem.** Hot paths in the coaching engine (e.g. `coach.cases`, which finds similar deals
across thousands of activity comparisons) called relational accessors like
`activities_for_deal()`, `orders_for_customer()`, `quotes_for_customer()` in inner loops.
Each call linearly scanned the full table. At scale this produced O(rows × calls) work.

**Fix.** `senpai/data/store.py` — a new `_index()` function, memoized with `@lru_cache(maxsize=1)`,
builds **per-key dictionaries once** at first access and is dropped automatically on `reload()`.
Every relational accessor is now an O(1) dictionary hit.

```python
@lru_cache(maxsize=1)
def _index() -> dict:
    acts_by_deal: dict[str, list[dict]] = {}
    for a in all_activities():
        acts_by_deal.setdefault(a.get("deal_id"), []).append(a)
    # … orders_by_cust, quotes_by_cust, deals_by_rep, deals_by_cust …
    return { … }

def activities_for_deal(deal_id: str) -> list[dict]:
    return _index()["acts_by_deal"].get(deal_id, [])
```

The index is **result-sorted** (activities: newest-first by `activity_date`; orders:
newest-first by `ordered_at`) so callers never need to sort their own slices.

**Measured impact:**

| Endpoint | Before | After | Speedup |
|---|---|---|---|
| `/api/coach/review` (coaching) | 7.7 s | 181 ms | **~43×** |
| `/api/coach/rep-profiles` | 7.4 s | 137 ms | **~54×** |
| Full `pytest` suite | 36.4 s | 1.4 s | **~26×** |

---

## 3. Retrieval Evolution — Hybrid Semantic Search + Knowledge Graph

### 3.1 Hybrid semantic search (`senpai/retrieval/`)

The original retrieval was keyword/tag matching. This week we built a full two-signal hybrid
stack — GPU-free at runtime.

**Build step (`retrieval/build_index.py`):**
- Embeds each corpus (daily reports, playbook entries) with **fastembed** (ONNX/CPU,
  `paraphrase-multilingual-MiniLM`, 384-d) and **commits** the artifacts to `senpai/data/index/`.
- Runtime never needs a GPU or model download for the corpus side — only the live query
  is embedded (one short CPU call).
- Committed artifacts: `{corpus}.npy` (L2-normalized float32 matrix), `{corpus}.meta.json`
  (per-row metadata + raw text), `{corpus}.tokens.json` (precomputed BM25 tokens),
  `manifest.json` (model, dim, per-corpus count + content hash).

**Runtime search (`retrieval/semantic.py`):**
- **BM25 (lexical)** over Janome-tokenized, POS-filtered text (nouns/verbs/adjectives/
  adverbs only — particles and light verbs removed so function words don't pollute ranking).
- **Dense cosine** against committed vectors.
- **Reciprocal Rank Fusion** (`score = Σ 1/(k+rank)`) with `DENSE_WEIGHT=3` vs `BM25_WEIGHT=1`
  (embedding is the stronger paraphrase signal, BM25 still helps exact-term queries).
- **Text-space deduplication** before fusion: duplicate daily reports don't flood either
  signal's candidate pool.
- **Graceful degrade:** `dense + BM25 → BM25 only → keyword substring` — the richest
  available layer wins. `semantic.mode()` reports which layer is active.

**Surfaced to the model:**
- `search_notes` tool: semantic search over daily reports (日報), clamped to ≤6 results to
  cap synthesis input size.
- `retrieve_playbook` internally upgraded to this layer (same signature, backward-compatible).

**Stress tested** via `scripts/stress_retrieval.py`. Key lessons encoded in the design:
the word-boundary rule for ASCII keys (`\b` for `new` so it doesn't match `news`), and the
content-word tokenizer that stops BM25 from over-matching function words.

### 3.2 Knowledge graph (`senpai/graph/`)

A `networkx.MultiDiGraph` built from the store at runtime (cached; never drifts from the
seed data).

**Nodes:** `rep` · `customer` · `deal` · `product` · `industry:*` · `category:*` · `acttype:*`

**Edges:** `OWNS` · `FOR` · `CONCERNS` · `IN_CATEGORY` · `IN_INDUSTRY` · `HAD`

Deal nodes are **denormalized** with category/industry/outcome/rep/products/acttypes so
filter traversals are a fast scan rather than expensive graph walks.

**Current graph size: 744 nodes.**

**Parameterized query functions (`graph/query.py`):**
- `reps_who_win(category, industry, after_activity_type)` — "which reps win サーバー deals in
  製造業 after a site survey?" (relational question the flat retrieval layer can't answer).
- `account_graph(customer_id)` — full neighborhood of an account: deals, reps, products.
- `connections(a, b)` — shortest relational path between two entities.
- `similar_by_graph(deal_id)` — deals sharing rep/product/industry/category.

**Surfaced to the model:** `query_graph` tool (intent = `reps_who_win | account | connections | similar`).

---

## 4. Account Intelligence (`senpai/account/`)

Deal health answers "is **this opportunity** on track?" Account Intelligence answers "is
**this whole customer relationship** healthy and growing?" — a distinct, higher-level read
that a senior account manager would give.

### 4.1 Account health engine (`account/health.py`)

`account_health(customer_id)` → 0–100 score, band, 8 dimensions, human-readable reasons.

**Higher-is-better** (inverse of deal risk, so the two scores are never confused).

| Dimension | Weight | Signal |
|---|---|---|
| `activity_trend` | 15 | recent-90d vs prior-90d activity ratio |
| `inactivity` | 10 | days since last activity (decays 14→90d) |
| `pipeline_progression` | 15 | open deals advanced vs slipped by `order_rank` |
| `win_rate` | 15 | won / (won+lost) closed deals |
| `quote_engagement` | 10 | recent quotes + quote→order conversion |
| `order_recency` | 15 | recency of last order + repeat-order count |
| `dm_access` | 10 | share of open deals with a decision-maker identified |
| `growth` | 10 | recent-180d vs prior-180d order revenue |

**Bands:** ≥70 green (healthy/strategic), 45–69 yellow (watch), <45 red (at risk).
`AccountHealth.top_reasons(n)` returns the weakest dimensions for the commentary contract.

### 4.2 Relationship trajectory (`account/trajectory.py`)

`relationship_trajectory()` runs deterministic pattern matchers over account aggregates,
each emitting a `Pattern(id, label, evidence, polarity)` with a concrete evidence string.

- **Positive patterns:** `repeat_purchasing`, `activity_increasing`, `expansion_potential`
- **Risk patterns:** `activity_declining`, `spend_declining`, `multiple_stalled` (≥2 red
  open deals), `engaged_no_progress` (high contact, zero advancement/revenue),
  `loyal_dormant` (past wins but ≥60d silent)

### 4.3 Account expansion engine (`account/expansion.py`)

Three families of opportunity, all grounded in store records. The only authored content is
a static category adjacency map and a list of environment trigger phrases.

1. **Cross-sell** — gap categories *complementary* to what the account already owns
   (`_COMPLEMENTS` adjacency over the 7 catalog majors: OA機器, PC周辺機器, サーバー, etc.).
2. **Upsell** — environment upgrade triggers matched against the customer's IT environment
   record (`ADSL|更改検討|老朽` → ネットワーク機器; `Windows 10|EOL` → PC周辺機器;
   `無線LAN|Wi-Fi` → ネットワーク機器).
3. **Growth** — engaged account (≥2 open deals) with thin category coverage (≤2) →
   strategic-account flag.

Each `Opportunity(kind, target, rationale, evidence, confidence)` carries its own grounding.

### 4.4 Account summary and commentary (`account/summary.py`, `account/context.py`)

`build_account_summary(customer_id)` rolls up health, trajectory, and expansion into one
`AccountSummary` — industry/size, pipeline ¥, historical revenue, last activity, recent
quotes/orders, IT environment, a `recommended_focus` line (deterministic, no LLM required).

The commentary endpoint streams a senior account-manager's read under a four-heading
contract (Account Reality / Single Deal vs Whole Account / The Real Risk / Recommended Focus)
with strict grounding rules: ground every statement in the context, quote numbers exactly,
refer to signals by `[id]`, never invent.

### 4.5 API and frontend

| Endpoint | Output |
|---|---|
| `GET /api/account/{id}` | `AccountSummary.to_dict()` — deterministic |
| `POST /api/account/{id}/commentary` | SSE — streamed senior read |
| `GET /api/customers/resolve?q=…` | Deterministic name→id resolution |
| `POST /api/customers/smart-resolve` | Deterministic + fuzzy + LLM-ranked resolution |

**Frontend (`web/components/account/`):**
- `accounts-index.tsx` — discoverability surface: rolls open-deal pipeline up by customer
  (worst band, open count, pipeline ¥), sorted by pipeline value. No extra backend call —
  reuses the existing dashboard payload.
- `account-view.tsx` — the full Account Intelligence page: 8 health dimensions, risk/expansion
  signals, recent quotes/orders, IT environment, open-deal drawer, streamed senior read.

Both views are role-aware (`junior | manager`) and mount identical components.

### 4.6 Industry and customer-size differentiation

The synthetic data and the graph are both **industry- and size-aware** — this is the closest
the current system comes to geographic/market-segment differentiation.

**Customer size tiers (`_SIZE` in `data/gen_seed.py`):**
- Two tiers: `小規模` (small) and `中規模` (medium), weighted 3:1 toward SMB.
- Every customer record carries a `size` field exposed in `AccountSummary.size` and the
  graph node's attribute.
- Otsuka Shokai's real book is SMB-heavy, so the dataset intentionally mirrors that skew.

**Industry segmentation (`_INDUSTRY`):**

```
製造 / 小売 / 医療 / 建設 / 飲食 / 物流 / 教育 / 不動産 / 士業 / IT
```

10 industry tags, one per customer, propagated into:
- **Knowledge graph** — `industry:<name>` grouping nodes connected to each customer via
  `IN_INDUSTRY` edges; deal nodes carry the customer's `industry` attribute.
- **`reps_who_win(category, industry, after_activity_type)`** — parameterized query that
  filters the win-rate leaderboard to a specific industry, answering "which reps close
  サーバー deals in 製造業 after a site survey?"
- **`similar_by_graph(deal_id)`** — multi-signal similarity scorer that adds +1 for an
  industry match (on top of +2 per shared product, +1 for same rep), so industry context
  shapes which past deals surface as comparable.
- **`account_graph(customer_id)`** — returns `industry` and `size` in the customer header
  so the senior commentary can frame risk in market-segment terms.
- **`AccountSummary`** — `industry` and `size` are first-class fields; the account-context
  assembler includes them in the grounded header line fed to the model.

**Design note:** industry is the primary market-segment discriminator; size captures the SMB
vs mid-market split that shapes deal complexity and decision-maker topology. A **`region`**
field (関東 / 関西 / その他) was also added this week to drive the Strategic Stance engine
(§4.7).

### 4.7 Strategic Tier + Regional Stance (`account/strategy.py`)

A deterministic **pre-query stance selector**: before the model writes any account read, a
pure function picks the *coaching posture* from two hard facts — the account's largest open-deal
amount (→ a Strategic Tier) and the customer's region (→ a regional modifier). It returns both
the **directives injected into the prompt** and a transparent **rationale surfaced to the rep**,
so the salesperson always sees *which* threshold and *which* region produced the advice — and
can override it.

**Strategic Tiers** (driven by the largest open deal; the biggest opportunity sets the posture):

| Tier | Band | Stance directives |
|---|---|---|
| Tier 1 メガ案件 | ≥ ¥1.5M (top ~5%) | Advisory, not quick-close; 根回し (nemawashi) across stakeholders; multi-layer 稟議 (ringi) prep; involve own management |
| Tier 2 標準案件 | ¥300K–¥1.5M | Balanced consultative; needs-discovery + cost/benefit; standard approval path |
| Tier 3 ボリューム案件 | < ¥300K | High-velocity close; ROI-led pitch; minimise touch-points; shortest route to the DM |

**Threshold calibration:** the original spec proposed ¥100M / ¥5M, but Otsuka Shokai is an SMB
IT reseller — the dataset's largest deal is ¥3.12M (median ¥216K), so absolute enterprise
thresholds put **100% of accounts in Tier 3** (feature invisible). The thresholds are instead
calibrated to the data's distribution (≈p95 / ≈p60), yielding a real spread:
**6 mega / 37 standard / 107 volume** accounts (≈5% / 34% / 61% of deals). "Mega" means
"large for this book," not absolute scale — `TIER1_MIN_YEN` / `TIER3_MAX_YEN` are the single
tuning surface.

**Regional modifiers** (`region` field, derived per-customer from a local RNG keyed on
`customer_id` so SPR tables stay byte-identical):
- **関東 (Kanto)** — formal; respect process and organisational hierarchy
- **関西 (Kansai)** — direct, merchant-minded (商人気質); frank about value and price
- **その他** — neutral / standard

**Transparency (the key requirement):** the stance is *deterministic and shown*, not hidden in
the prompt. `StrategicContext` carries a bilingual `rationale` ("最大の進行中案件が¥1,800,000
（¥1,500,000以上）のためメガ案件と判定。地域: 関東。") that is surfaced on **every** account
surface, all reading the same deterministic `GET /api/account/{id}` payload (`strategy` field):

1. **Account page** (`account-view.tsx`) — a Strategic Stance card plus header chips: tier +
   region, the rationale ("why this was chosen"), and the directive bullets.
2. **Workspace `/account` brief** (`assembleAccountArtifact`) — a "Strategic stance" section in
   the immutable artifact (tier · region + rationale + directives), so the stance travels with
   the saved brief.
3. **Commentary stream** — a typed `strategy` SSE event on `/api/account/{id}/commentary` for
   any client that consumes the live stream.

The directives are injected into the commentary prompt via `StrategicContext.as_prompt_block()`;
the prompt instructs the model to *adopt the posture and reflect it in Recommended Focus*. The
directives are authored posture heuristics (like `_recommended_focus`), never factual claims —
the only data they rest on is the deal amount and region, both quoted verbatim in the rationale.

**Robustness:** `normalize_region()` keeps `AccountSummary.region` consistent with the strategy's
region for any input, and `as_prompt_block()` falls back to the neutral region directive on a
malformed region rather than raising.

Tests: `tests/test_strategy.py` (7 tests — tier boundaries, region normalization, rationale
grounding, dict round-trip, all-three-tiers-occur in the seed). Verified end-to-end through
`build_account_summary` → `build_account_context` and the stress pipeline (no SPR-data regression
from the `region` field).

---

## 5. Morning Briefing (`senpai/briefing.py`)

A prioritized next-best-action worklist that a rep reads at the start of their day.

**How it works:**
1. Sweeps all of a rep's open deals.
2. Scores each with the deterministic health engine.
3. Ranks by `urgency × value` where urgency is the health risk score and value is the
   deal's expected order amount.
4. Attaches **one concrete next action per deal**, derived from the dominant risk signal:

   | Signal | Action |
   |---|---|
   | `order_date_past` | 受注時期を再確認し、完了予定日を更新する |
   | `missing_dm` | 決裁者を特定する (役職者へのアプローチを設定) |
   | `staleness / low_activity` | 今日フォローの連絡を入れる (N日間接触なし) |
   | `stall_language` | 停滞の要因をヒアリングし、次の一手を決める |
   | `rank_regression` | ランク下降の原因を確認し、挽回策を立てる |

5. Adds a **predictive cadence nudge**: deals that are *about to* breach their rank's
   contact cadence — but haven't gone stale yet — surface before they turn yellow.

**Why it matters:** the briefing is as auditable as the scoring engine because every action
derives from the same `score_deal` signals and `RANK_BENCHMARKS` cadence constants. No model
invents the action. The briefing degrades to the deterministic summary if the model is offline.

**Tool wired:** `morning_briefing(rep_id, limit)` added to both junior and manager tool sets.
Tests: `tests/test_briefing.py`.

---

## 6. Expanded Coaching Platform

### 6.1 Enriched synthetic data (rep skill model)

The synthetic data generator (`data/gen_seed.py`) was upgraded with a **deterministic per-rep
skill model** (`REP_SKILL`). Each rep has characteristic weakness themes (juniors more,
experts fewer) and some juniors are flagged **improving** (their notes get more complete over
fiscal years).

- Only 3 activity fields change via a local RNG keyed on each activity (`daily_report`,
  `business_card_info`, `customer_challenge`) → SPR tables (deals/quotes/orders/amounts/dates)
  stay **byte-identical**.
- Reports now span a realistic quality spread (≈26% thorough → tapering to thin) instead of
  the old uniform 2–5 lens fill.
- **Coaching threads** (`data/seed/coaching_threads.json`): deterministic manager↔rep chat
  raised on flagged deals — `issue_key`, `status ∈ {open, acknowledged, resolved}`, dated
  `messages`. Resolved threads correlate with the improving-rep flag, giving `rep_progress`
  its acted-on signal.

### 6.2 Manager Coaching Workspace (`senpai/coaching.py`)

461-line module that answers a manager's daily question: **"where should I spend my coaching
time today?"** — four grounded views, no LLM, no new scoring.

**Seven deterministic issue rules** (`_issues()`), mapped to priority tiers:

| Issue key | Priority | Fires when |
|---|---|---|
| `confidence_mismatch` | high | `optimism_mismatch` flag is set on the deal |
| `missing_decision_maker` | high | deal is at `DECISION_MAKER_RANKS` but no business card title found |
| `long_inactivity` | high | last activity >30 days ago (or no activities at all) |
| `premature_discount` | medium | discount >10% AND no decision-maker OR deal in a low rank |
| `repeated_unresolved` | medium | current `order_rank` regressed vs `initial_order_rank` |
| `weak_customer_discovery` | medium | ≥3 activities but <34% have `customer_challenge` filled |
| `incomplete_reports` | low | a configurable completeness threshold |

`compute_issues()` is the public entry point — it's reused by `coach/profile.py` so the same
rules power both the workspace queue and the per-rep profile without duplication.

**Four views** (`coaching_workspace()`):

1. **`needs_coaching`** — ranked queue: primary sort by `ISSUE_PRIORITY` tier, secondary by
   deal health score descending; each entry carries one headline issue + a transparent reason.
2. **`trends`** — team-wide issue frequency, with a direction derived from `order_rank`
   movement (rank declined = "worsening", advanced = "improving").
3. **`confidence_vs_reality`** — Confidence vs Reality: the rep's stated rank (their
   expressed confidence) is cross-checked against 3 observed signals
   (quote on file, DM identified, recent activity in last 30d); mismatched deals surface first.
4. **`summary`** — a weekly digest: total open deals, deals with ≥1 issue, most-common issue.

API: `GET /api/coach/workspace`.

### 6.3 Review Coach (`senpai/coach/review.py`)

218-line module that gives a **deal-specific coaching read** by scanning what is *absent* from
a rep's note — not what is present. Absence-based firing is the key design: the lens fires
when cue phrases are **not found**, because gaps are what a senior reads for.

**Five LENSES**, each with: cue list, observation text, missing-info label, bilingual open
question, risk level, and decision factor:

| Lens | What absence signals |
|---|---|
| `decision_maker` | No 決裁・部長・社長・役員・キーマン mention — authority path unknown |
| `timeline` | No 期日・来月・Q末・スケジュール — no close horizon agreed |
| `criteria` | No 選定理由・評価・比較 — what the customer actually wants is unclear |
| `next_step` | No 次回・提案・デモ — no committed forward action |
| `budget` | No 予算・費用・価格帯 — financial qualification absent |

Also includes **presence detectors** for stall language (`検討中・返事待ち・保留`) and
competitor signals — firing even when a lens is silent.

**`CoachReview` dataclass** assembles: `observations`, `missing_info`, `risks`, `questions`,
`next_actions`, `decision_factors`, `used_deal` (the grounded deal record),
`explanations` (one per lens), and **`open_questions`** — bilingual (JA+EN) open-ended
questions that surface the unknown, never factual claims.

**Grounding P0 rule:** absence → open questions only. The coach never says "the customer
wants X" when X isn't in the note. Every question is phrased to *elicit* the missing fact,
not invent it. English equivalents live in `_LENS_QUESTION_EN` so bilingual output is
consistent.

API: `POST /api/coach/review`.

### 6.4 Similar Past Cases (`senpai/coach/cases.py`)

148-line module that teaches through **real organizational experience** rather than invented
advice. Given a rep's note (and optional current deal), it retrieves a small set of closed
deals whose situation rhymes with the current one — mixing wins and losses for contrast.

**Five situational themes**, each mapped to validated principle IDs:

| Theme | Principle IDs | When it fires |
|---|---|---|
| `no_decision_maker` | P003, P006 | lost deal, no DM title in any activity |
| `discounting` | P002 | lost deal, discount >10% |
| `stalled` | P001 | lost deal, few activities or no comments |
| `budget` | P005 | cue phrases about 予算/費用 in the note |
| `discovery` | P008, P010 | note references 初回/ヒアリング/環境 |
| `disciplined_close` | P001, P010 | won deal (the positive contrast case) |

**Scoring (`find_similar_cases()`):** every closed deal starts at 0.5 (baseline so some
experience always surfaces). Product category match adds +3; thematic cue match adds +1.5;
lost deals get +0.3 (failures teach more vividly).

**Teaching mix guarantee:** the function explicitly ensures the returned set contains at least
one `won` and one `lost` deal — so the rep always sees a contrast, not just failures.

Each returned case is language-neutral facts: `deal_id`, customer name, category, amount,
outcome, theme, `principle_ids`, `decision_maker` flag, `discounted` flag, `n_activities`.
The frontend renders the localized summary; no synthetic narrative is generated here.

### 6.5 Context Retrieval Layer (`senpai/coach/context.py`)

497-line grounded context assembler. Before the model produces a commentary, this function
assembles the **full business context package** from store records so the model reasons over
real signals — not the meeting note alone.

**Resolution cascade** (`_resolve_customer_cascade()`):

| Confidence | Method | Policy |
|---|---|---|
| `high` | explicit `deal_id`, exact alias match | Ground fully — inject all customer/deal facts |
| `medium` | fuzzy character-similarity (score ≥ 0.72) | Near-miss — surface as "did you mean…?" candidate, read note-only until rep confirms |
| `low` | company-name-pattern extraction | Likely match, unconfirmed — same near-miss policy |
| `none` | no customer identified | Note-only — model must not fabricate customer facts |

This prevents the most dangerous failure mode: "Okamoto Electronics" in a note must not
silently pull in 岡本電機's deal records.

**Bilingual signal translation (`_SIGNAL_EN`):**
12 regex patterns translate the engine's Japanese flag/signal strings into English at
context-assembly time. Example: `^(\d+)日間接触なし\(目安(\d+)日超\)$` → `"{N} days without
contact (over the {M}-day benchmark)"`. This means the model has no Japanese to
copy-paste into an English commentary.

**`build_commentary_context()` assembles:**
- Customer profile (name, industry, size, IT environment)
- Deal status (rank, amount, expected date, days inactive)
- Health score, band, and signals (translated to the requested language)
- Active flags in human-readable form
- Quote on file (amount, product category, discount %, quoted date)
- Order history digest (count, total ¥, last order date)
- Customer history across other deals (won/lost/open counts)
- **Account health cross-link** — `account_health(customer_id)` included so the model
  can frame a stalled deal against a healthy overall account ("deal stuck at 3_A but
  the account is green overall — not a relationship problem")
- Similar past cases (if `COACH_USE_SIMILAR_CASES` is on)
- Relevant corpus principles (if `COACH_USE_CORPUS` is on)

**DO NOT FABRICATE guards:** the context text includes explicit instructions at each
uncertain resolution tier so the model knows exactly what it can and cannot state.
Ambiguous or low-confidence matches are clearly labelled so the model hedges rather
than presenting unverified facts as certain.

### 6.6 Rep coaching profile (`senpai/coach/profile.py`)

`rep_coaching_profile(employee_id)` aggregates deterministic coaching issues across a rep's
whole book into a 1:1 brief:

- Weaknesses ranked by **severity then frequency** (missing decision-maker outranks report hygiene)
- Each weakness carries: count + **real example deals** + a **validated principle** (`knowledge/`) +
  a **real past case** (`coach.cases`) + one **concrete action**
- **Strengths**, a headline **development focus** (with explainability card), **1:1 talking points**
- **Coaching-thread status** (how many resolved, open, acknowledged)

`team_coaching_profiles()` rolls this up across the whole team for the manager.

API: `GET /api/coach/rep-profile/{id}`, `GET /api/coach/rep-profiles`.

### 6.7 Rep progress (`senpai/coach/progress.py`)

`rep_progress(employee_id, windows=4)` replays the engine **as of each of the last fiscal years**
(scoring each deal at its last in-window activity to avoid false staleness signals) and produces:
- Per-issue **trend** over time (improving/flat/worsening)
- Overall headline: 改善傾向 / 横ばい / 悪化傾向
- **Coaching acted-on rate** from threads (was past coaching resolved?)

This closes the feedback loop: the coaching engine *rediscovers* the weaknesses seeded into
the rep skill model — a seeded decision-maker-weak rep surfaces `missing_decision_maker`, and
an improving discovery-weak rep visibly trends down.

API: `GET /api/coach/rep-progress/{id}`.

### 6.8 Coaching explainability (`senpai/coach/explainability.py`)

For every coaching recommendation (lens, signal, flag, issue), `build_explanation()` assembles
a grounded explanation in four parts:

1. **Trigger Conditions** — which rule fired and what data matched
2. **Supporting Evidence** — the actual field values behind the trigger
3. **Similar Historical Cases** — real closed deals with the same pattern
4. **Outcome Statistics** — win/loss rates computed from `store.all_deals()` only
   (returned as `None` when fewer than `MIN_SAMPLE=5` closed deals match — never interpolated)

Frontend: `web/components/coach/` explainability cards.
Tests: `tests/test_explainability.py`.

---

## 7. Growth / Motivation Portal (`senpai/growth.py`)

Closes the **Motivation** pillar of the Knowledge / Experience / Motivation loop.

A read-only analytics layer that turns a rep's real activity history into visible progress
markers — purpose is encouragement, not grading.

**Five skills, each derived from a transparent ratio over real deals:**

| Skill | Signal |
|---|---|
| `relationship_building` | Repeat-visit activity rate |
| `decision_maker_discovery` | Share of deals with business_card_info filled |
| `customer_discovery` | Share of activities with customer_challenge filled |
| `closing_discipline` | Order-rank advancement rate |
| `proposal_pricing` | Quote-to-order conversion rate |

Each daily report is treated as one completed coaching review (rep reflecting on a call) —
the closest real proxy to "reviews completed" without persisting app usage.

Frontend routes: `web/app/junior/` and `web/app/manager/` growth pages.

---

## 8. Document Generation Tools (`senpai/documents/`)

Four new tools add a **document output layer** to the assistant — one of the highest-value
actions a rep takes when a deal is near closing.

### 8.1 `generate_proposal` — 4-slide PPTX sales proposal

Grounded entirely in the deal's SPR data via `DocumentContext` (built by `documents/context.py`):

| Slide | Content | Source |
|---|---|---|
| 1 — Title | Customer name + value proposition | LLM narration (one line only) |
| 2 — 課題 | Up to 5 pain points | `sales_activities.customer_challenge` + `daily_report` |
| 3 — ソリューション | Matched catalog products with codes + prices | `products.json` |
| 4 — 投資対効果 & 次のステップ | Deal financials (HW/SW/services splits) + comparable deals | SPR `total_order_amount`, `quotes` |

**Design principle:** all ¥ numbers come from the deterministic `DocumentContext`. The LLM
writes only the value-proposition subtitle. A footnote on each slide states its data source.

### 8.2 `generate_ringisho` — 稟議書 (DOCX)

A formal Japanese internal-approval document written from the **customer's IT-manager persona
pitching their own CEO**. Structure:

1. 背景・課題 — grounded in SPR pain points
2. 提案内容 — grounded in catalog products
3. 投資額と効果 — injected from `DocumentContext.financials` (never invented)
4. 結論・承認依頼
5. 承認欄

LLM writes the prose sections; the financial table is a deterministic injection.

### 8.3 `generate_pptx` / `generate_docx` — general-purpose document tools

Free-prompt LLM-authored documents, optionally grounded by internal records (`/api/account`)
or web search. **Two-step confirm** before any file is created (the model surfaces a slide/
section outline; the user confirms before the file is written). Both degrade cleanly when
the model is offline.

### 8.4 Download flow

All four tools save to `config.GENERATED_DIR` and return a download path. The web UI exposes
a download button. Smoke-tested with `python -m senpai.documents.proposal D001` and
`python -m senpai.documents.ringisho D001`.

Tests: `tests/test_documents.py` — the deterministic proposal/ringisho path is fully covered
(no GPU); general PPTX/DOCX tests assert clean degradation when `SENPAI_USE_LLM` is off.

---

## 9. Workspace Shell (`web/components/workspace/`)

The Workspace replaces the old split `Assistant` + `Review Coach` pages with one conversational
surface where deterministic skills, grounded artifacts, and ordinary chat coexist.

### 9.1 Three skills (slash commands)

| Command | Backend | Produces |
|---|---|---|
| `/review <note or deal id>` | `POST /api/coach/review` + SSE narrate | **review** artifact — 6 teaching sections + streamed senior read |
| `/account <name or id>` | `GET /api/account/{id}` + SSE commentary | **account_brief** artifact — health, risk signals, expansion, focus + streamed read |
| `/research <question>` | `POST /api/chat` (research role) → SSE | **research** artifact — source ledger + grounded answer + web citations |
| *(bare turn)* | `POST /api/chat` (junior/manager tool-loop) | normal chat reply with tool ledger |

The *user*, never an intent-classifier, decides which skill runs — the trust boundary stays legible.
Unknown commands are rejected, not silently reinterpreted.

### 9.2 Artifact model

An **Artifact** is the typed, immutable, grounded output of a skill:

- **Immutability:** a skill never edits an artifact in place. Re-running appends a new artifact
  that `supersedes` the previous one.
- **Deterministic provenance:** `evidence` carries source IDs only (deal/SPR/principle/
  playbook/web IDs). The LLM is never the source of an evidence entry.
- Evidence IDs are parsed with a strict regex (`/^(PB\d+|P\d+|I\d+|D\d+)$/`); a stray human
  name can never become evidence.

Three assemblers — `assembleReviewArtifact`, `assembleAccountArtifact`, `assembleResearchArtifact`
— map existing API payloads into artifacts and add no facts.

### 9.3 Unified rendering

The old three duplicated card renderers were collapsed into a single `ArtifactBody` driven
by a `KIND_META` table (per-kind header, alert, commentary placement).
Sub-components: `Markdown`, `SectionBlock`, `CommentaryBlock`, `EvidenceDrawer`.

### 9.4 File attachment to context (Part A)

The chat input now supports **file attachment**: a user can clip a file and its text content
is injected into the next turn's context — grounding the conversation in an uploaded document
without a separate ingestion round-trip. Captured via a "Capture card" that is editable before
submission.

### 9.5 Multi-sheet XLSX export

Every ready artifact carries an **Export** button that downloads a real `.xlsx` via
`write-excel-file/browser` (dynamically imported, no SSR).

**Trust model:** export is a **serializer, not a generator** — only reformats the already-grounded
artifact, adds no facts, LLM touches nothing. Two sheets:
- **Brief** — heading + meta + each section + senior read commentary
- **Sources** — evidence table (deal/SPR/principle/playbook/web IDs + URLs)

Provenance travels into the file so the workbook stays auditable after it leaves Senpai.

---

## 10. Capture via Clip + Ingestion Pipeline

Closes the capture loop: a rep uploads a voice memo or business-card photo → it becomes a
structured, editable SPR draft → confirmed records go live in the engine immediately.

This is **two separate layers** that were built and integrated this week:

### 10.1 Capture via Clip (frontend — `web/components/workspace/workspace.tsx`)

A **paperclip button** in the Workspace input bar (commit `bfdb542`). The user selects an
`audio/*` or `image/*` file; the workspace immediately posts it to `POST /api/ingest` and
renders a **`CaptureTurn`** in the thread — a card with five editable fields:

| Field | SPR column |
|---|---|
| Activity type (dropdown) | `activity_type` |
| Daily report | `daily_report` |
| Contact / business-card info | `business_card_info` |
| Customer challenge | `customer_challenge` |
| Product category | `product_major_category` |

Design decisions:
- **Deliberately mutable** — unlike the immutable skill artifacts (`/review`, `/account`),
  a capture draft is *meant* to be edited (it will become an SPR record). So it carries the
  raw `IngestResult`, not an `Artifact`.
- **Human-in-the-loop** — the draft must be reviewed before saving. Hallucinations from the
  extraction model are caught here before they touch the store.
- **Mock badge** — when the multimodal API is offline, extraction returns a mock result; a
  yellow "モック抽出" badge flags this so the rep knows it needs manual filling.
- **Copy button** — copies the whole draft as plain text so it can be pasted into an external
  SPR system if needed.
- i18n: all labels and toasts are bilingual (`capture.*` keys in `web/lib/i18n.tsx`).

### 10.2 Multimodal ingestion backend (`senpai/ingestion/pipeline.py`, `ingestion/multimodal.py`)

`MultimodalIngestor` handles three modalities:
- **Audio** (voice memos) → Whisper transcription
- **Images** (business cards, whiteboards) → Vision/OCR text extraction
- **Text** — direct pass-through

All modalities feed a structured extraction step (LLM → `ActivityExtraction` Pydantic schema)
that outputs the five SPR fields listed above. Extraction uses the local model endpoint with
an OpenAI-compatible fallback (`INGEST_BASE_URL`/`INGEST_API_KEY`); offline it returns a
deterministic skeleton so the frontend always receives a parseable draft.

### 10.3 Persistence (`ingestion/persist.py`)

`build_activity_record()` produces a record in the **exact seed shape** — correcting three
gaps in the earlier prototype:
- Fiscal year/quarter from the Japanese fiscal calendar (`config.fiscal_year_quarter`), not mocked.
- Department/division from the actual rep record, not hardcoded.
- `days_since_last_order` / `total_order_count` derived from the customer's real order history.

`store.append_activity()` writes to the gitignored overlay (`config.INGESTED_DIR`) and drops
the `_index` / `_load` caches — the next request reads the ingested activity like any
committed row. The committed seed is never mutated.

Tests: `tests/test_ingestion_persist.py`.

---

## 11. Knowledge Pipeline (`senpai/knowledge/`)

A full four-layer pipeline for turning senior interview quotes into coaching items that
juniors can trust — with computed (not authored) confidence and a mandatory human approval gate.

### 11.1 Data model (`knowledge/schema.py`)

Four layers, each a plain dataclass serialised to committed JSON (auditable in a diff, no DB):

| Layer | Object | What it is |
|---|---|---|
| 0 | `Source` | A raw interview or survey (`source_id`: I01, I02…) |
| 1 | `Principle` | A **validated claim** backed by ≥1 cited interview quote — the ground truth GenAI may never exceed |
| 2 | `GeneratedItem` | A **draft coaching item** (scenario + signals + questions + risks + alternatives) generated from ONE principle |
| — | `Provenance` | Model, prompt version, generated_at, `grounding_passed` flag |
| — | `Review` | Status, reviewer, reviewed_at, notes |

**Confidence is computed, never authored:**
- `CONF_HIGH` — approved + principle backed by ≥2 independent interviews
- `CONF_MEDIUM` — approved + 1 interview, or corroborated by survey
- `CONF_LOW` — approved but thinly sourced
- `CONF_UNVERIFIED` — not approved or failed grounding → **never shown to juniors**

### 11.2 Generation (`knowledge/generate.py`)

`generate_item(principle_id)` → `GeneratedItem` (status: `draft`).

The model receives **only** the validated principle + its source quotes. Hard rules enforced in
the prompt and verified by `ground_check`:
1. No new advice/numbers/proper nouns not in the principle.
2. Scenario may be fictional; signals/questions/risks must be entailed by the principle.
3. `alternatives` must include 1–2 "it depends" counter-views (no single correct answer).

`ground_check` catches cheap hallucinations before human review: rejects items that contain
invented numbers (`\d+\s*[%％]|\d[\d,]*\s*円`). Offline fallback: a deterministic skeleton
item (restates the principle) so the pipeline runs without the model server.

### 11.3 Human review gate (`knowledge/review.py`)

`approve` / `request_edit` / `reject` — the only path an item takes to becoming visible.
Every transition records who, when, and notes. `approve` forces `grounding_passed=True` if
a reviewer explicitly overrides a failed ground check (the override is logged in notes).
`pending()` surfaces draft/needs_edit items with grounding-passed items first, so reviewers
triage the clean ones fast.

### 11.4 Persistence (`knowledge/store.py`)

Two committed JSON files (`sources.json`, `principles.json`, `generated_items.json`) plus
sidecar overlay files (`*.ingested.json`) for manager-contributed knowledge — same pattern
as `senpai/data/store.py` (overlay appended, seed canonical).

Currently: **11 validated principles**, **7 approved coaching items** in the committed seed.

### 11.5 Knowledge Explorer frontend

`web/components/knowledge/knowledge-explorer.tsx` (significantly expanded this week) shows
principles with verbatim interview provenance, computed-confidence badges, and their derived
coaching items — each traceable to the exact senior quote it came from.

---

## 12. Additional Tools Added

The tool set grew from 18 to **38 functions** in `senpai/tools/impl.py`.

New tools added this week:

| Tool | What it does |
|---|---|
| `find_deals` | Schema-driven faceted deal search — `product_category, industry, size, outcome, order_rank, profile_tags, min_amount, max_amount, product_code, limit` — all SPR fields, no invented filters |
| `search_notes` | Semantic search over daily reports (日報) — meaning-aware, BM25+dense |
| `query_graph` | Multi-hop knowledge graph queries (`reps_who_win`, `account`, `connections`, `similar`) |
| `search_knowledge` | Semantic search over validated knowledge principles + playbook |
| `search_products` | Faceted product catalog search (`category, max_price, product_code`) |
| `create_quote` | Draft a quote from catalog items with discount, grounded in real prices |
| `get_calendar` | Calendar lookup for scheduling context |
| `morning_briefing` | Urgency-ranked daily action list (§5) |
| `generate_proposal` | 4-slide PPTX from SPR deal data (§8.1) |
| `generate_ringisho` | 稟議書 DOCX (§8.2) |
| `generate_pptx` | Free-prompt general PPTX (§8.3) |
| `generate_docx` | Free-prompt general DOCX (§8.3) |
| `schedule_meeting` | Two-step Google Calendar booking (draft → confirm → real event) |

`schedule_meeting` received a **two-step confirm** upgrade: `confirm=False` returns a draft
for human review; `confirm=True` lazily imports `gcal` and books, with `（シミュレーション）`
fallback if the Calendar call fails.

---

## 13. Latency Investigation and Router/Model Evals

Full details in `docs/phase25_session_log.md`. Summary of decisions:

### 13.1 Latency investigation (prompt + routing, no model change)

Baseline: ~395s end-to-end on a multi-tool research turn.
- **Tool-selection round (~23s):** capping `<think>` buys ~nothing — left intact.
- **Final synthesis (~230s):** dominates. Lever is input/output *size*, not think budget.

Three changes landed:
1. Parallel tool calls: system prompts now instruct the model to emit independent lookups in
   one turn (fewer sequential selection rounds).
2. Router rule: all-retrieval multi-tool turns → FAST mode (no reasoning needed for pure
   data retrieval).
3. `search_notes` clamp: `limit` clamped to ≤6 (caps dominant synthesis input).

**Result: ~395s → ~256s.**

### 13.2 Atlas intent-router evaluation (offline, NOT shipped)

63 hand-labeled bilingual queries, `LogisticRegression` on MiniLM embeddings, 5-fold CV.

- Destination head (research/tool/chat): ~0.82 — usable but not a clear win over rules.
- Mode head (fast/think): ~tie with `DeterministicReasoningRouter` — rules already as good.
- Tool-hint head (which tool): ~0.49 — not separable in MiniLM space.

**Decision: do not build Atlas.** Rules win on simplicity and on the mode head.

### 13.3 Model decomposition (in progress)

Question: can the final synthesis step use a smaller model (Qwen3-8B) for a latency win
while the 27B keeps doing tool selection?

Round 1 (bf16-8B vs Q4_K_M-27B, 4 FAST queries):

| Arm | Avg latency | Grounding fidelity |
|---|---|---|
| 27B Q4_K_M | 64.9s | 0.957 |
| 8B bf16 | 58.5s | 0.961 |

Speedup only ~1.11× because both move similar bytes/token (bf16-8B ~16GB ≈ Q4-27B ~14GB).
**Key finding: an 8B achieves parity grounding quality.** Round 2 (Q4_K_M 8B, ~5GB → ~3×
fewer bytes/token) is pending; expected ~3× synthesis speedup.

---

## 14. SSE Event Protocol and Resolution Improvements

### 14.1 Customer resolution — word-boundary rule

Fixed a live `news → new` false match. ASCII/romaji alias keys now require regex word
boundaries (`\b`); Japanese keys keep substring matching (no word boundaries in JA text).

```python
def _key_in_text(key, low_text):
    if key.isascii():
        return re.search(r"\b" + re.escape(key) + r"\b", low_text) is not None
    return key in low_text
```

Added `C##` customer-id recognition alongside `D###` deal-ids in free-text extraction.

### 14.2 Tool-calling fix (no-think suppression bug)

**Symptom:** "setup a meeting" narrated a fake `[ツール呼び出し]` instead of calling the tool.
**Root cause:** `TOOLLOOP_NO_THINK` empty-`<think>` prefill in the **selection** round suppressed
tool emission.
**Fix:** selection rounds now use `_prep(convo, False)` (keep think) + a prompt directive
"call tools directly, don't narrate". A/B test confirmed: `NOTHINK_ON` → 0 tool calls,
`NOTHINK_OFF` → `schedule_meeting` called correctly.

### 14.3 Reasoning leak fix

`_strip_reasoning` generalized to handle `<think>`, `<thinking>`, `<analysis>`, `<reasoning>`
tag variants. Research summarizers routed through `_strip_reasoning`.

### 14.4 Health engine double-count bug fix (`9194756`)

`staleness` and `low_activity` signals were **both firing on the same silence** condition,
double-penalizing deals that had no recent activity. Fixed in `senpai/health/scoring.py` +
`flags.py` so the two signals are mutually exclusive (staleness subsumes low_activity).
`tests/test_scoring.py` gained 15 new assertions covering this exact edge case.

---

## 15. Quality Assurance Infrastructure

Beyond the pytest suite, this week added three categories of test/audit tooling:

### 15.1 Stress pipeline (`scripts/stress_pipeline.py`)

A hermetic robustness harness (no GPU, no network) that probes 7 aspects of the
deterministic core in one run:

1. **Tool dispatch** — every tool survives empty / garbage / hostile args and never raises
   (the chat loop must never crash); valid calls produce non-empty output.
2. **Scoring engine** — edge cases (empty fields, missing dates, junk values, every
   `order_rank` value); score always in 0–100 with a valid band.
3. **Flags engine** — same edge cases; never crashes.
4. **Morning briefing** — every rep + team + unknown rep; sorted, grounded, deterministic.
5. **`find_deals`** — facet filters honoured, outcome matches the rank model, hostile
   inputs never crash, deterministic.
6. **Store referential integrity** — all deals resolve to real customers/reps; unknown IDs
   degrade to `None`/`[]`.
7. **Whole-pipeline determinism** — score every open deal twice → identical results.

### 15.2 Health score backtest (`scripts/backtest_health.py`)

A calibration harness that validates the health score against actual deal outcomes:

- Scores every **closed** deal (won = `WON_RANKS`, lost = `DEAD_RANKS`).
- Computes **AUC** — P(a lost deal scores riskier than a won deal); 0.5 = no signal, 1.0 = perfect.
- Produces a **calibration table**: for each band (and raw-score bucket), the actual loss rate.

On the synthetic seed this validates internal consistency (does the score separate the
outcome labels the generator baked in?). The same script is ready for real historical data —
the report layout is identical, making it the calibration tool for when SPR access arrives.

### 15.3 Grounding audit scripts

Three grounding audit scripts (`scripts/grounding_audit.py`, `grounding_audit4.py`,
`grounding_reaudit.py`) that run on the deterministic engine (no LLM) and check:

- **Cross-customer leakage** — does retrieval ever surface records from a different customer
  than the one in focus?
- **Prompt composition by source** — classifies every line of the commentary context into
  `customer_core / crm / deterministic_health / activity / quote_order / environment /
  similar_case_CROSS_CUSTOMER / corpus_playbook`, then reports the fraction of each type
  so we can audit how grounded each prompt is.
- **Structural origin classification** — distinguishes customer evidence (safe) from
  cross-customer analogies (labelled) from corpus/playbook content.

### 15.4 Contract checker (`scripts/check_contract.py`)

Hits every GET endpoint the web client calls via FastAPI's in-process `TestClient` and asserts
that the top-level keys the TypeScript types expect still exist. Runs in <1s with no GPU.

**Discipline enforced:** `docs/web-integration.md` documents the one-boundary rule:
"endpoint first, then `types.ts` → `api.ts` → `fixtures.ts` → component" — so the Python
engine and the Next.js app can never silently drift. `scripts/check_contract.py` is the
automated enforcement gate.

### 15.5 Live cache test (`scripts/live_cache_test.py`)

End-to-end test that drives the real bridge in-process via `TestClient`, parses the actual
SSE stream, and verifies that `context`/`cached` flags are set correctly and real tokens
stream from the LLM. Requires the model server on `:8765` (`SENPAI_USE_LLM=1`).

---

## 16. Test Suite

17 test files (plus `conftest.py`), **137 tests (1 skipped)**, all GPU-free.

| File | What it covers |
|---|---|
| `test_scoring.py` | Deal health scoring engine |
| `test_flags.py` | Reliability flags |
| `test_manager_tools.py` | Manager tool set |
| `test_coach.py` | Review coach (lenses, absence reasoning) |
| `test_coaching_data.py` | Rep skill model + byte-stability + SPR anchors |
| `test_rep_profile.py` | Rep coaching profile generation |
| `test_progress.py` | Fiscal-year progress tracking |
| `test_briefing.py` | Morning briefing ranking + actions |
| `test_documents.py` | Proposal/ringisho PPTX/DOCX generation |
| `test_deals_search.py` | `find_deals` faceted search |
| `test_graph.py` | Knowledge graph construction + multi-hop queries |
| `test_semantic.py` | Hybrid retrieval (BM25, dense, RRF) |
| `test_knowledge.py` | Knowledge pipeline + confidence computation |
| `test_explainability.py` | Explainability module |
| `test_ingestion_persist.py` | Ingestion persist + overlay + cache invalidation |
| `test_research.py` | Research tool and grounding audit |
| `test_strategy.py` | Strategic Tier + regional stance (boundaries, normalization, grounding) |
| `conftest.py` | Shared fixtures (`SENPAI_USE_LLM=0`, tmp overlay dirs) |

**New tests this week:** +18 coaching tests, +10 document tests, +8 graph/semantic tests, +6
briefing tests, +7 strategy tests = **+49 new tests** since the start of Week 2.

---

## 17. Retrieval Observability — Retrieval Explorer

**`senpai/retrieval/trace.py`** is a per-turn observability buffer using Python's `ContextVar`
so concurrent requests never share state. Every retrieval surface (`notes_semantic`,
`knowledge_keyword`, `graph`) records into this buffer: source type, source ID, customer,
score, scope (`account:<id>` or `all`).

The API drains the buffer after each tool call and ships it to the UI as `tool` events in the
SSE stream.

**`web/components/assistant/retrieval-explorer.tsx`** is the UI surface — a collapsible
panel in the chat thread that shows for every turn:
- Which retrievers fired (`日報（意味検索）`, `社内ナレッジ（キーワード）`, `関係グラフ`)
- Scope: **account-scoped** (green badge, the trustworthy default) vs **all customers**
- Per-chunk detail: ID, customer name, score

This makes grounding **debuggable** — you can see exactly which chunks reached the model
and immediately spot cross-customer leakage.

---

## 18. Synthetic Dataset Expansion

The seed dataset was massively expanded to **FY2023–FY2026 historical data** (3 cohorts):
- **Live pipeline** (~140 deals): `order_rank` 2_A+…6_P, dated within 0–90 days of anchor
- **Historical won** (~280 deals): `1_Confirmed`, spread across prior fiscal years
- **Historical dead** (~100 deals): `7_Lost`/`8_Cancelled`

`store.open_deals()` filters to open ranks so the live dashboard stays bounded at ~140
even though the corpus is 520.

| File | Rows | What it is |
|---|---:|---|
| `deals.json` | **520** | Opportunity-level records |
| `sales_activities.json` | **2,337** | Activity log / daily reports |
| `quotes.json` | **480** | Quotes for progressed deals |
| `orders.json` | **280** | Order lines (confirmed/won deals) |
| `customers.json` | **150** | SMB customer master (industry, size, and new `region` field) |
| `reps.json` | **24** | Sales reps (junior + senior, skill profiles) |
| `products.json` | 29 | Product master (major/mid/minor, pricing) |
| `environments.json` | 150 | Customer IT environment records |
| `playbook.json` | 31 | Coaching entries |
| `rank_history.json` | **1,612** | Order-rank change log (slip/regression detection) |
| `customer_aliases.json` | 150 | English/romaji alias forms |
| `coaching_threads.json` | 43 threads | Manager↔rep chat on flagged deals |

Documented in `docs/synthetic_dataset.md` (new file this week).

---

## 19. Week-over-Week Summary

| Dimension | Week 1 (end) | Week 2 (end) |
|---|---|---|
| Tests | 30 passing | **137 passing (1 skipped)** |
| Tools | 18 | **38** |
| API endpoints | ~10 | **~20** |
| API latency (coaching) | ~7.5s | **~140ms (~54×)** |
| Synthetic dataset (deals) | 60 | **520 (3-year history)** |
| Synthetic dataset (activities) | 186 | **2,337** |
| Knowledge pipeline | Principles only | **Generate → ground-check → review gate → approved items** |
| Retrieval | Keyword/tag only | **BM25 + dense + RRF + knowledge graph (744 nodes)** |
| Document output | None | **PPTX + DOCX (4 tool variants)** |
| Coaching depth | Review Coach only | **Profile + progress + threads + explainability** |
| Account view | Deal-level only | **8-dimension account health + trajectory + expansion + strategic tier/region stance** |
| Workspace | Two separate pages | **Unified slash-command shell + artifacts + XLSX export** |
| Ingestion | None | **Capture via Clip (paperclip button → editable CaptureTurn) + backend pipeline** |
| Observability | None | **Retrieval Explorer (per-chunk source + scope + score)** |
| QA scripts | 0 | **5 (stress pipeline, health backtest, grounding audit ×3, contract checker, live cache test)** |

---

## Appendix A — New Files This Week

| Path | What it is |
|---|---|
| `senpai/account/` | Account Intelligence engine (health, trajectory, expansion, summary, context, **strategy**) |
| `senpai/account/strategy.py` | Strategic Tier + regional stance selector (deterministic, transparent rationale) |
| `senpai/briefing.py` | Morning briefing — urgency-ranked action worklist |
| `senpai/coach/profile.py` | Rep coaching profile (1:1 brief, weaknesses, strengths) |
| `senpai/coach/progress.py` | Fiscal-year progress + coaching acted-on rate |
| `senpai/coach/explainability.py` | Coaching explainability (triggers, evidence, outcome stats) |
| `senpai/growth.py` | Growth / Motivation portal (5 transparent skill scores) |
| `senpai/documents/` | Document generation (proposal, ringisho, author, context, render, registry, narrative) |
| `senpai/retrieval/` | Hybrid semantic search (build_index, semantic, deals, knowledge, playbook, **trace**) |
| `senpai/retrieval/trace.py` | Per-turn retrieval observability buffer (ContextVar) |
| `senpai/graph/` | Knowledge graph (build, query) |
| `senpai/ingestion/` | Multimodal ingestion (pipeline, multimodal, persist) |
| `senpai/tools/gcal.py` | Google Calendar integration (two-step confirm) |
| `senpai/knowledge/schema.py` | 4-layer knowledge data model (Source→Principle→GeneratedItem) |
| `senpai/knowledge/generate.py` | LLM coaching-item generation from validated principles |
| `senpai/knowledge/review.py` | Human review gate (approve / request_edit / reject) |
| `senpai/knowledge/store.py` | Knowledge persistence + overlay (mirrors data store pattern) |
| `web/components/workspace/` | Workspace shell + Capture via Clip (paperclip button, CaptureTurn, editable draft) |
| `web/components/account/` | Account Intelligence frontend (accounts-index, account-view) |
| `web/components/assistant/retrieval-explorer.tsx` | Retrieval Explorer — per-chunk grounding debugger |
| `web/components/coaching/rep-profiles.tsx` | Rep coaching profiles frontend (372 lines) |
| `web/lib/artifact-export.ts` | Client-side XLSX export (two-sheet: brief + sources) |
| `web/lib/artifacts.ts` | Artifact type definitions and pure assemblers |
| `web/public/logo.png` | Senpai brand logo |
| `web/components/site/brand.tsx` | Brand component |
| `scripts/stress_pipeline.py` | 7-probe robustness harness (§15.1) |
| `scripts/backtest_health.py` | Health score calibration / AUC backtest (§15.2) |
| `scripts/grounding_audit.py` | Cross-customer leakage + prompt composition audit (§15.3) |
| `scripts/grounding_audit4.py` | Structural grounding classification (§15.3) |
| `scripts/grounding_reaudit.py` | Grounding re-audit (updated version) |
| `scripts/live_cache_test.py` | Live SSE cache correctness test (§15.5) |
| `scripts/check_contract.py` | Web ↔ engine contract checker (§15.4) |
| `scripts/eval_intent_router.py` | Atlas feasibility eval (§13.2) |
| `scripts/bench_synthesis.py` | Model decomposition A/B with frozen tool context (§13.3) |
| `scripts/bench_synthesis_results.json` | Round 1 benchmark results (27B vs 8B-bf16) |
| `docs/synthetic_dataset.md` | Synthetic dataset reference (3-year time model, row counts) |
| `docs/web-integration.md` | Web ↔ engine integration pattern + contract discipline |
| `docs/phase25_session_log.md` | Phase 2.5 session log (latency, evals, bugs, features) |
| `docs/accounts.md` | Account Intelligence reference |
| `docs/coaching.md` | Coaching platform reference |
| `docs/retrieval.md` | Retrieval reference |
| `docs/resolution_and_routing.md` | Customer resolution + reasoning router reference |
| `docs/workspace.md` | Workspace shell reference |
| `docs/llm_bridge.md` | LLM bridge + SSE protocol reference |
| `docs/README.md` | Documentation index |

## Appendix B — Run Commands

```bash
export SENPAI_TODAY=2026-06-16

# Python app (no GPU)
.venv/bin/streamlit run senpai/apps/manager_dashboard.py   # dashboard :8501
.venv/bin/streamlit run senpai/apps/matsuda_demo.py        # Matsuda demo

# Web app (combined launcher)
SENPAI_TODAY=2026-06-16 bash scripts/run_web.sh            # bridge :8000 + frontend :3000
# Or separately:
SENPAI_TODAY=2026-06-16 uvicorn senpai.api.server:app --port 8000
cd web && npm install && npm run dev

# Document generation (no GPU)
python -m senpai.documents.proposal D001
python -m senpai.documents.ringisho D001

# Build retrieval index
SENPAI_TODAY=2026-06-16 python -m senpai.retrieval.build_index

# Verify (no GPU)
.venv/bin/pytest tests/

# QA scripts (no GPU, no network)
SENPAI_TODAY=2026-06-16 python scripts/stress_pipeline.py
SENPAI_TODAY=2026-06-16 python scripts/backtest_health.py
SENPAI_TODAY=2026-06-16 python scripts/check_contract.py
SENPAI_TODAY=2026-06-16 python scripts/grounding_audit.py

# Offline evals
python scripts/eval_intent_router.py
python scripts/bench_synthesis.py --candidate-base http://127.0.0.1:8766/v1 \
       --candidate-model qwen3-8b --queries 4
```
````

## File: senpai/planner/selection.py
````python
"""What the planner decides: a `Selection` — which capabilities to gather from and
what document to produce — plus the deterministic resolver that grounds it.

The LLM's job (in llm_planner.py) is to pick *which capabilities* are worth
gathering. IDs are never trusted to the model: the customer/deal a document is
grounded in is resolved here, deterministically, from the store (the project's
"never invent an ID" rule). So even a hallucinated capability list can only widen
or narrow the gather — it can never point the document at the wrong deal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from senpai import config
from senpai.data import store

# The gather capabilities the planner may select from (documents is always the
# terminal, so it is not part of the selectable gather set).
GATHER_CAPABILITIES = ("conversation", "workspace", "crm", "knowledge", "web")
# What the terminal produces. proposal/pptx/docx = generate an artifact file; note =
# write a text file into the workspace; organize = tidy the workspace on disk.
DOC_KINDS = ("proposal", "pptx", "docx", "note", "organize")

_DEAL_ID_RE = re.compile(r"\bD\d{3}\b", re.IGNORECASE)
_PROPOSAL_CUES = ("提案", "proposal", "提案書")
# "cover every deal for this customer" — a proposal grounded in ALL of a resolved
# customer's deals (merged financials/products/comparables), not just the biggest
# one. Independent of doc_kind/deal-status routing; see _wants_all_deals.
_ALL_DEALS_RE = re.compile(
    r"\ball\s+(?:the\s+)?deals\b|\bevery\s+deal\b|\beach\s+deal\b|"
    r"全て?の案件|全案件|各案件", re.IGNORECASE)
# 稟議 (ringisho) is intentionally NOT here: it has its own dedicated template/tool
# (generate_ringisho) and is routed to the ReAct loop, not the planner.
_DOCX_CUES = ("文書", "報告書", "レポート", "docx", "document", "report")
# External/factual cue (stale-in-weights topics) — reuse the doc tools' own heuristic.
from senpai.tools.impl import _auto_web  # noqa: E402


# --- planner intent detection (the router's source of truth) ----------------
# Document GENERATION: a create verb + a document noun. 稟議 excluded (own tool).
_DOC_VERB = (r"(?:make|create|generate|build|draft|write|produce|prepare|"
             r"put\s+together|作って|作成|作る|生成|書いて|まとめて|用意|つくって)")
_DOC_NOUN = (r"(?:proposal|deck|slides?|slide\s?deck|presentation|power\s?point|"
             r"pptx?|ppt|docx?|word\s+doc(?:ument)?|document|report|"
             r"提案書|提案|スライド|資料|プレゼン(?:テーション)?|文書|報告書|レポート)")
_DOC_GOAL_RE = re.compile(
    _DOC_VERB + r"\b.{0,40}?" + _DOC_NOUN + r"|" + _DOC_NOUN + r".{0,20}?(?:を|の)?\s*" + _DOC_VERB,
    re.IGNORECASE)
_RINGISHO_RE = re.compile(r"稟議|ringisho", re.IGNORECASE)

# ORGANIZE: tidy/sort/reorganize the workspace on disk (a WRITE that moves files).
_ORGANIZE_RE = re.compile(
    r"\b(?:organi[sz]e|reorgani[sz]e|rearrange|tidy(?:\s?up)?|clean\s?up|sort|file\s+away|declutter)\b"
    r".{0,30}?(?:files?|documents?|docs?|folder|workspace)|"
    r"\b(?:put|move|place)\b.{1,40}?\b(?:in|into|under|to|inside)\b.{1,30}?(?:folder|directory)?|"
    r"(?:ファイル|資料|ドキュメント|文書|フォルダ|ワークスペース).{0,10}?"
    r"(?:整理|片付け|仕分け|フォルダ分け|分類|移動)|"
    r"(?:整理|片付け|仕分け|フォルダ分け|分類|移動)(?:して|する)?", re.IGNORECASE)

# NOTE: save/write a short text file INTO the workspace (not a generated artifact).
_NOTE_RE = re.compile(
    r"\b(?:save|jot(?:\s+down)?|record|note\s+down|write\s+(?:a\s+|this\s+)?(?:note|down))\b"
    r".{0,40}?(?:my\s+)?(?:files?|documents?|docs?|workspace|note|\.md|\.txt)|"
    r"(?:save|write|append).{0,20}?(?:to|into)\s+[\w./-]+\.(?:md|txt|json|csv)|"
    r"(?:メモ|ノート|記録)(?:を|に)?.{0,10}?(?:保存|作成|残|書|追記)|"
    r"(?:ファイル|資料|文書)(?:に|へ).{0,10}?(?:保存|書き込|追記|記録)", re.IGNORECASE)

# Explicit "actually do it" for the destructive organize (otherwise preview only).
_APPLY_RE = re.compile(r"\b(?:apply|do\s+it|go\s+ahead|confirm|execute)\b|実行|適用|やって",
                       re.IGNORECASE)
# A broader affirmation, only ever consulted right after an organize PREVIEW (so a
# bare "yes"/"go ahead"/"はい" continues and applies the pending reorganize).
_AFFIRM_RE = re.compile(
    r"\b(?:yes|yeah|yep|ok|okay|sure|go\s+ahead|do\s+it|apply|proceed|confirm|"
    r"execute|please\s+do|go\s+for\s+it)\b|はい|お願い|やって|実行|適用|進めて|それで",
    re.IGNORECASE)
# The marker the organize PREVIEW writes into its assistant reply (see
# WorkspaceOrganizeCapability); its presence in the last assistant turn is what makes
# a following affirmation mean "apply the reorganize".
_ORGANIZE_PREVIEW_MARK = "【整理プレビュー"


def _recent_assistant_texts(history: list | None, limit: int = 3) -> list[str]:
    """The most recent assistant messages' texts, so continuation detection works
    even if the model hallucinated a turn in between."""
    if not history:
        return []
    texts = []
    for item in reversed(history):
        role = getattr(item, "role", None)
        content = getattr(item, "content", None)
        if role is None and isinstance(item, dict):
            role, content = item.get("role"), item.get("content")
        if role == "assistant":
            texts.append(content or "")
            if len(texts) >= limit:
                break
    return texts


def _organize_apply_continuation(message: str, history: list | None) -> bool:
    """True when the user is confirming a pending organize preview (an affirmation
    immediately after the preview was shown, checking up to 3 turns back)."""
    if not bool(_AFFIRM_RE.search(message or "")):
        return False
    recent = _recent_assistant_texts(history, limit=3)
    return any(_ORGANIZE_PREVIEW_MARK in text for text in recent)


def is_organize_goal(message: str, history: list | None = None) -> bool:
    return (bool(_ORGANIZE_RE.search(message or ""))
            or _organize_apply_continuation(message, history))


def is_note_goal(message: str) -> bool:
    return bool(_NOTE_RE.search(message or ""))


def is_document_goal(message: str) -> bool:
    m = message or ""
    if _RINGISHO_RE.search(m):
        return False
    return bool(_DOC_GOAL_RE.search(m))


def is_planner_goal(message: str, history: list | None = None) -> bool:
    """Any goal the LLMPlanner owns: organize / note-write / document generation.
    Order matters — organize and note are checked first because their phrasings can
    also contain a document noun ('organize my documents')."""
    return (is_organize_goal(message, history) or is_note_goal(message)
            or is_document_goal(message))


@dataclass(frozen=True)
class Selection:
    """The plan the LLMPlanner emits: the capability set to gather from + the
    document to build (kind + the deterministically-resolved entity it grounds in)."""
    goal: str
    capabilities: tuple[str, ...]          # subset of GATHER_CAPABILITIES
    doc_kind: str                          # one of DOC_KINDS
    deal_id: str | None = None
    customer_id: str | None = None
    target: str = ""                       # display name of the entity in focus
    lang: str = "ja"
    title: str = ""
    reason: str = ""                       # why these capabilities (observability)
    confirm: bool = False                  # apply a destructive op (organize); else preview
    path: str = ""                         # target file for a note write (optional)
    all_deals: bool = False                # proposal: merge ALL of the customer's deals

    def with_capabilities(self, caps) -> "Selection":
        ordered = tuple(c for c in GATHER_CAPABILITIES if c in set(caps))
        return replace(self, capabilities=ordered)


def _wants_all_deals(goal: str) -> bool:
    return bool(_ALL_DEALS_RE.search(goal or ""))


def _resolve_entity(goal: str, deal_hint: str | None = None) -> tuple[str | None, str | None, str]:
    """(deal_id, customer_id, display_target) for the document, from the store.
    A `deal_hint` (e.g. the deal the rep picked in the selector) is authoritative;
    then an explicit D### in the goal; otherwise a customer name resolves to its
    primary open deal (largest amount) so a proposal can be grounded. None/None when
    the entity isn't in the CRM (e.g. a workspace-only company) — then a free deck
    grounds on the workspace/conversation instead."""
    if deal_hint:
        d = store.get_deal(deal_hint.strip().upper())
        if d:
            did = d["deal_id"]
            return did, d["customer_id"], store.customer_name(d["customer_id"])
    m = _DEAL_ID_RE.search(goal or "")
    if m:
        did = m.group(0).upper()
        d = store.get_deal(did)
        if d:
            return did, d["customer_id"], store.customer_name(d["customer_id"])
    cust = store.match_customer_in_text(goal or "")
    if not cust:
        return None, None, ""
    cid = cust["customer_id"]
    deals = store.deals_for_customer(cid)
    open_deals = [d for d in deals if config.is_open_rank(d.get("order_rank"))]
    # Prefer an open deal (the live pipeline); but a customer whose deals are all
    # Confirmed/Lost is still a real account with real history to ground a proposal
    # on — falling all the way to None here is what silently degraded these to
    # ungrounded free decks. Ground on the best deal on file either way.
    pool = open_deals or deals
    pool = sorted(pool, key=lambda d: d.get("total_order_amount", 0), reverse=True)
    deal_id = pool[0]["deal_id"] if pool else None
    return deal_id, cid, cust.get("name", "")


def _pick_doc_kind(goal: str, deal_id: str | None, history: list | None = None) -> str:
    g = (goal or "")
    # Workspace ops win over document generation (their phrasing overlaps).
    if is_organize_goal(g, history):
        return "organize"
    if is_note_goal(g):
        return "note"
    if deal_id or any(c in g.lower() or c in g for c in _PROPOSAL_CUES):
        # A grounded proposal needs a deal; without one it degrades to a free deck.
        return "proposal" if deal_id else "pptx"
    if any(c in g.lower() or c in g for c in _DOCX_CUES):
        return "docx"
    return "pptx"


def _lang_of(goal: str) -> str:
    """JA unless the goal has no CJK at all (then EN)."""
    return "ja" if re.search(r"[぀-ヿ一-鿿]", goal or "") else "ja"


def heuristic_selection(goal: str, deal_hint: str | None = None, history: list | None = None) -> Selection:
    """Deterministic capability selection — the default, and the fallback whenever
    the LLM is off or returns junk. Always gathers conversation (session context);
    adds workspace (self-gated on a real file match), CRM when an entity resolved,
    knowledge for proposals (playbook grounding), and web for external/factual
    topics with no internal entity."""
    deal_id, customer_id, target = _resolve_entity(goal, deal_hint)
    doc_kind = _pick_doc_kind(goal, deal_id, history)

    # Organize is self-contained (it inspects the workspace itself) — no gather.
    # Apply when the goal itself says so ("...and apply") OR when it's an affirmation
    # confirming a pending preview ("go ahead"); otherwise preview (never move silently).
    if doc_kind == "organize":
        confirm = (bool(_APPLY_RE.search(goal or ""))
                   or _organize_apply_continuation(goal, history))
        return Selection(goal=goal, capabilities=(), doc_kind="organize",
                         lang=_lang_of(goal), confirm=confirm,
                         reason="heuristic: organize workspace ("
                                + ("apply" if confirm else "preview") + ")")

    caps = ["conversation", "workspace"]
    if customer_id or deal_id:
        caps.append("crm")
    if doc_kind == "proposal":
        caps.append("knowledge")
    if _auto_web(goal) and not (customer_id or deal_id):
        caps.append("web")

    return Selection(
        goal=goal, capabilities=tuple(caps), doc_kind=doc_kind,
        deal_id=deal_id, customer_id=customer_id, target=target,
        lang=_lang_of(goal), all_deals=_wants_all_deals(goal),
        reason="heuristic: " + ("entity in CRM" if (customer_id or deal_id)
                                else "no CRM entity — workspace/conversation grounded"))


def ground_selection(goal: str, caps, doc_kind: str, reason: str = "",
                     deal_hint: str | None = None, history: list | None = None) -> Selection:
    """Build a Selection from an LLM-chosen capability set + doc_kind, but re-ground
    the entity/IDs deterministically and enforce invariants: conversation is always
    gathered; a `proposal` with no resolvable deal degrades to a free `pptx`; CRM is
    only kept when an entity actually resolved."""
    deal_id, customer_id, target = _resolve_entity(goal, deal_hint)
    if doc_kind not in DOC_KINDS:
        doc_kind = _pick_doc_kind(goal, deal_id, history)
    # IDs/routing are never trusted to the model (see module docstring) — a
    # deterministically resolved deal always grounds a proposal, regardless of
    # what the LLM guessed for doc_kind. Only an explicit docx/note ask is left as
    # the model chose it (those aren't deal-shaped documents).
    if deal_id and doc_kind not in ("docx", "note"):
        doc_kind = "proposal"
    if doc_kind == "proposal" and not deal_id:
        doc_kind = "pptx"  # can't ground a proposal without a deal

    chosen = {c for c in caps if c in set(GATHER_CAPABILITIES)}
    chosen.add("conversation")             # session context is always worth gathering
    if "crm" in chosen and not (customer_id or deal_id):
        chosen.discard("crm")              # nothing for CRM to ground on
    if doc_kind == "proposal":
        chosen.add("knowledge")

    return Selection(
        goal=goal, capabilities=tuple(c for c in GATHER_CAPABILITIES if c in chosen),
        doc_kind=doc_kind, deal_id=deal_id, customer_id=customer_id, target=target,
        lang=_lang_of(goal), all_deals=_wants_all_deals(goal),
        reason=reason or "llm-selected")
````

## File: web/components/site/app-shell.tsx
````typescript
"use client";

import { Fragment, useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Building2,
  FileText,
  Home,
  Library,
  Lightbulb,
  LogOut,
  type LucideIcon,
  Sparkles,
  Upload,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { useSession, type Role } from "@/lib/session";
import { Brand } from "./brand";
import { LangToggle } from "./lang-toggle";

type NavItem = { href: string; key: string; icon: LucideIcon; group?: string };

const NAV: Record<Role, NavItem[]> = {
  // Junior: the Command Center (Home) is the whole daily job — the old
  // Workspace lives inside it (chat + context panes), so it's gone from the
  // rail. Accounts / Knowledge / Reports / Ingestion are a visually separated
  // secondary group: Accounts is the browse-everything directory that
  // complements the Home pane's focused daily work; the rest are occasional,
  // deliberate tasks.
  junior: [
    { href: "/junior", key: "nav.home", icon: Home, group: "main" },
    { href: "/junior/accounts", key: "nav.accounts", icon: Building2, group: "more" },
    { href: "/junior/knowledge", key: "nav.knowledge", icon: Library, group: "more" },
    { href: "/junior/reports", key: "nav.reports", icon: FileText, group: "more" },
    { href: "/junior/ingestion", key: "nav.ingestion", icon: Upload, group: "more" },
  ],
  // Manager: Home is the overview-first team dashboard (Overview / All deals /
  // Flags tabs — the former Dashboard + Pipeline + Reliability routes). The
  // Copilot is its own tab. Knowledge absorbs the old principle-authoring
  // "Ingestion" page. Accounts / Coaching round out the secondary group.
  manager: [
    { href: "/manager", key: "nav.home", icon: Home, group: "main" },
    { href: "/manager/workspace", key: "nav.copilot", icon: Sparkles, group: "more" },
    { href: "/manager/coaching", key: "nav.coaching", icon: Lightbulb, group: "more" },
    { href: "/manager/accounts", key: "nav.accounts", icon: Building2, group: "more" },
    { href: "/manager/knowledge", key: "nav.mknowledge", icon: Library, group: "more" },
  ],
};

export function AppShell({ role, children }: { role: Role; children: React.ReactNode }) {
  const { t } = useT();
  const { role: active, ready, logout } = useSession();
  const pathname = usePathname();
  const router = useRouter();

  // Demo guard: if not signed in as this role, bounce to the landing page.
  useEffect(() => {
    if (ready && active !== role) router.replace("/");
  }, [ready, active, role, router]);

  if (ready && active !== role) return null;

  const nav = NAV[role];
  const roleLabel = t(role === "junior" ? "role.junior" : "role.manager");

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Sidebar */}
      <aside className="sticky top-0 hidden h-screen w-[252px] shrink-0 flex-col border-r border-border bg-card px-3.5 py-5 lg:flex">
        <div className="px-2">
          <Brand tagline={t("app.tagline")} />
        </div>

        <div className="mt-6 px-2">
          <span className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[11px] font-medium",
            role === "manager" ? "bg-navy/[0.06] text-navy" : "bg-primary/[0.08] text-primary",
          )}>
            <span className={cn("h-1.5 w-1.5 rounded-full", role === "manager" ? "bg-navy" : "bg-primary")} />
            {roleLabel}
          </span>
        </div>

        <nav className="mt-4 flex flex-col gap-0.5">
          {nav.map((item, i) => {
            const active = item.href === `/${role}` ? pathname === item.href : pathname.startsWith(item.href);
            const Icon = item.icon;
            // Separate nav groups (e.g. Junior's primary vs. secondary items).
            const showDivider = i > 0 && item.group !== nav[i - 1].group;
            return (
              <Fragment key={item.href}>
                {showDivider && <div className="mx-2.5 my-2 border-t border-border/60" />}
                <Link
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] font-medium transition-colors",
                    active ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                  )}
                >
                  <Icon className={cn("h-[18px] w-[18px]", active ? "text-primary" : "")} />
                  {t(item.key)}
                </Link>
              </Fragment>
            );
          })}
        </nav>

        <div className="mt-auto space-y-3 px-1">
          <div className="rounded-lg border border-border bg-muted/40 p-3">
            <div className="eyebrow mb-1.5">{t("diff.promiseTitle")}</div>
            <p className="text-[11.5px] leading-relaxed text-muted-foreground">{t("diff.promise")}</p>
          </div>
          <button
            onClick={() => { logout(); router.replace("/"); }}
            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <LogOut className="h-[18px] w-[18px]" /> {t("common.signOut")}
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col h-full overflow-hidden">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-border bg-background/85 px-5 py-3 backdrop-blur md:px-8">
          <div className="flex items-center gap-2 lg:hidden">
            <Brand compact />
          </div>
          <div className="hidden text-[13px] font-medium text-muted-foreground lg:block">{roleLabel}</div>
          <div className="flex items-center gap-2">
            <LangToggle />
            <button
              onClick={() => { logout(); router.replace("/"); }}
              className="hidden items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1.5 text-[12px] font-medium text-muted-foreground transition-colors hover:text-foreground sm:flex lg:hidden"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        </header>

        <main className="w-full flex-1 overflow-y-auto px-5 py-4 md:px-8 md:py-5 max-w-none flex flex-col min-h-0">
          {children}
        </main>
      </div>
    </div>
  );
}
````

## File: tests/test_documents.py
````python
"""Tests for the document-generation tools (generate_proposal/ringisho/pptx/docx).

The deterministic path (proposal/ringisho) is exercised fully — no GPU/LLM, since
conftest leaves SENPAI_USE_LLM off. The general tools (pptx/docx) require a model, so
here we only assert they degrade gracefully (a clear message, no file) when it's off.
All output is redirected to a tmp dir so the committed seed is never touched.
"""
from __future__ import annotations

import pytest
from docx import Document
from pptx import Presentation

from senpai import config
from senpai.data import store
from senpai.documents import proposal, registry, ringisho
from senpai.documents.context import build_document_context
from senpai.documents.render import render_docx, render_pptx
from senpai.tools.impl import dispatch

DEAL = "D001"  # seeded dead-but-optimistic deal with real pain points + financials


@pytest.fixture(autouse=True)
def _tmp_generated(tmp_path, monkeypatch):
    """Redirect generated files to a tmp dir for every test."""
    monkeypatch.setattr(config, "GENERATED_DIR", tmp_path / "generated")
    return tmp_path / "generated"


def _pptx_text(path) -> str:
    out = []
    for slide in Presentation(str(path)).slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                out.append(shape.text_frame.text)
            if shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        if cell.text_frame:
                            out.append(cell.text_frame.text)
            if shape.has_chart:
                try:
                    chart = shape.chart
                    for plot in chart.plots:
                        for series in plot.series:
                            if series.name:
                                out.append(series.name)
                            for val in series.values:
                                out.append(str(val))
                except Exception:
                    pass
    return "\n".join(out)


def _docx_text(path) -> str:
    return "\n".join(p.text for p in Document(str(path)).paragraphs)


# --- render.py (pure, LLM-free) ------------------------------------------------
def test_render_pptx_slide_count(tmp_path):
    spec = {"slides": [
        {"layout": "title", "title": "T", "subtitle": "sub"},
        {"layout": "content", "title": "A", "bullets": ["x", "y"]},
        {"layout": "content", "title": "B", "bullets": ["z"]},
    ]}
    p = render_pptx(spec, tmp_path / "d.pptx")
    prs = Presentation(str(p))
    assert len(prs.slides) == 3


def test_render_docx_headings(tmp_path):
    spec = {"title": "Doc", "sections": [
        {"heading": "One", "body": ["para a", "- bullet"]},
        {"heading": "Two", "body": ["para b"]},
    ]}
    p = render_docx(spec, tmp_path / "d.docx")
    text = _docx_text(p)
    assert "One" in text and "Two" in text and "bullet" in text


# --- context grounding ---------------------------------------------------------
def test_context_numbers_match_store():
    ctx = build_document_context(DEAL)
    d = store.get_deal(DEAL)
    assert ctx is not None
    assert ctx.financials["investment"] == d["total_order_amount"]
    assert ctx.customer == store.customer_name(d["customer_id"])
    assert ctx.pain_points  # real customer_challenge values exist for this deal


def test_context_unknown_deal_is_none():
    assert build_document_context("ZZZ") is None


# --- proposal (PPTX) -----------------------------------------------------------
def test_proposal_arc_and_grounded():
    res = proposal.generate(DEAL)
    assert res is not None
    path, ctx, spec = res
    prs = Presentation(str(path))
    # Full proposal arc: 表紙 → 背景 → 課題 → ソリューション → 投資対効果 → 次のステップ.
    assert len(prs.slides) == 9
    assert len(spec["slides"]) == 9
    text = _pptx_text(path)
    assert ctx.customer in text                       # title slide names the customer
    assert (f"{ctx.financials['investment']:,}" in text or str(float(ctx.financials['investment'])) in text)  # ROI slide carries the real ¥ (D001 has no quote)


# --- ringisho (DOCX) -----------------------------------------------------------
def test_ringisho_headings_and_amount():
    res = ringisho.generate(DEAL)
    assert res is not None
    path, ctx = res
    text = _docx_text(path)
    for heading in ("稟議書", "背景・課題", "提案内容", "投資額と効果", "結論・承認依頼"):
        assert heading in text
    assert f"{ctx.financials['investment']:,}" in text


# --- pptx generates directly (no confirm gate) ---------------------------------
def test_proposal_tool_generates_directly(_tmp_generated):
    gen = _tmp_generated
    # PPTX proposals build in one round — no preview/confirm step.
    out = dispatch("generate_proposal", {"deal_id": DEAL})
    assert "生成しました" in out
    assert "プレビュー" not in out
    assert len(list(gen.glob("*.pptx"))) == 1                 # file written on the first call


def test_ringisho_tool_writes_docx(_tmp_generated):
    dispatch("generate_ringisho", {"deal_id": DEAL, "confirm": True})
    assert len(list(_tmp_generated.glob("*.docx"))) == 1


# --- general tools need the model ----------------------------------------------
def test_general_tools_need_model(_tmp_generated):
    msg = dispatch("generate_pptx", {"prompt": "GTA 6", "confirm": True})
    assert "モデル" in msg                                     # "needs the model"
    msg2 = dispatch("generate_docx", {"prompt": "security training"})
    assert "モデル" in msg2
    assert not _tmp_generated.exists() or not list(_tmp_generated.iterdir())  # no file


# --- grounding: general tools ground on conversation + workspace, not just CRM --
def test_gather_grounding_uses_conversation_and_workspace(tmp_path, monkeypatch):
    """A 'proposal for <company>' where the company lives in the rep's local files
    (and was discussed earlier) must ground on that file/conversation — and must NOT
    inject an unrelated fuzzy CRM customer (the wrong-company-name hallucination).
    Uses a hermetic workspace so it never depends on the configured WORKSPACE_ROOT."""
    from senpai import config
    from senpai.tools import conversation as conv
    from senpai.tools import impl

    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "murata_printing_display_quote.txt").write_text(
        "有限会社村田印刷 様\n27インチモニター × 4台: ¥204,000\n", encoding="utf-8")
    monkeypatch.setattr(config, "WORKSPACE_ROOT", ws)

    conv.set_conversation([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "村田印刷にいくら見積もった？"},
        {"role": "tool", "content": "ワークスペース文書: 有限会社村田印刷 ¥204,000"},
        {"role": "assistant", "content": "村田印刷への見積もりは¥204,000です。"},
        {"role": "user", "content": "make a proposal ppt for Murata Printing"},
    ])
    try:
        g = impl._gather_grounding("make a proposal ppt for Murata Printing 村田印刷",
                                   customer="", use_web=False)
    finally:
        conv.set_conversation(None)
    assert "村田印刷" in g                       # the referenced entity is grounded
    assert "204,000" in g                        # its real figure, from file/conversation
    assert "松田" not in g                        # no unrelated fuzzy CRM customer
    assert "【社内データ】" not in g              # CRM suppressed when workspace matched


def test_gather_grounding_junk_gated_and_crm_fallback(tmp_path, monkeypatch):
    """An unrelated topic pulls no workspace junk; a real CRM customer still grounds.
    The workspace root is pointed at an empty dir so the assertion is deterministic
    regardless of what real files exist under the configured WORKSPACE_ROOT."""
    from senpai import config
    from senpai.tools import conversation as conv
    from senpai.tools import impl

    empty = tmp_path / "empty_workspace"
    empty.mkdir()
    monkeypatch.setattr(config, "WORKSPACE_ROOT", empty)  # sandbox re-reads config each call

    conv.set_conversation(None)
    assert impl._workspace_grounding("best gaming laptops under 1000000 yen") == ""
    # A named CRM customer with no local file still injects internal records.
    g = impl._gather_grounding("藤本食品の提案書", customer="", use_web=False)
    assert "【社内データ】" in g


def test_gather_grounding_uses_session_focus(tmp_path, monkeypatch):
    """'make a proposal' with no customer named, but a deal was looked up earlier this
    session → grounding pulls that deal's CRM record via SessionFocus (a lookup off the
    resolved id), not a fuzzy re-match. Hermetic empty workspace so ws never interferes."""
    from senpai import config
    from senpai.data import store
    from senpai.tools import conversation as conv
    from senpai.tools import impl

    empty = tmp_path / "empty_ws"
    empty.mkdir()
    monkeypatch.setattr(config, "WORKSPACE_ROOT", empty)

    deal = "D001"
    cid = store.get_deal(deal)["customer_id"]
    conv.set_conversation([
        {"role": "user", "content": "この案件の状況は？"},
        {"role": "tool", "content": f"{deal} 案件 / 受注ランクA / ¥204,000"},
        {"role": "assistant", "content": "進行中です。"},
        {"role": "user", "content": "提案書を作って"},
    ])
    try:
        g = impl._gather_grounding("提案書を作って", customer="", use_web=False)
    finally:
        conv.set_conversation(None)
    assert "【社内データ】" in g                     # CRM grounded off the deal in focus
    assert store.customer_name(cid) in g            # the RIGHT customer, from the id


def test_conversation_grounding_relevance_beats_recency():
    """The entity in focus must survive even after several unrelated turns push it out
    of the plain last-N window: relevance ranking pulls the older Murata fact back in,
    while the recent off-topic chatter that a tail-only slice would have kept is
    dropped as irrelevant to the current request."""
    from senpai.tools import conversation as conv
    from senpai.tools import impl

    convo = [
        {"role": "user", "content": "村田印刷にいくら見積もった？"},
        {"role": "tool", "content": "ワークスペース文書: 有限会社村田印刷 27インチ×4 ¥204,000"},
        {"role": "assistant", "content": "村田印刷への見積もりは¥204,000です。"},
    ]
    # Several intervening, unrelated turns — enough to push Murata past RECENT_FLOOR.
    for q, a in [("今日の天気は？", "晴れです。"),
                 ("会議は何時？", "15時からです。"),
                 ("昼食のおすすめは？", "近くの蕎麦屋です。"),
                 ("電車は動いてる？", "平常運転です。")]:
        convo += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    convo.append({"role": "user", "content": "村田印刷の提案書を作って"})

    conv.set_conversation(convo)
    try:
        g = impl._conversation_grounding("村田印刷の提案書を作って 村田印刷")
    finally:
        conv.set_conversation(None)
    assert "204,000" in g          # the older on-topic fact was rescued by relevance
    assert "蕎麦屋" not in g        # recent-but-irrelevant chatter was NOT padded in


def test_truncate_on_boundary_does_not_sever_facts():
    from senpai.tools import impl

    text = "村田印刷への見積もり金額は¥204,000です。" + "あ" * 5000 + "末尾の重要な数値¥999"
    out = impl._truncate_on_boundary(text, 1500)
    assert len(out) <= 1500 + 2          # budget respected (+ elision marker)
    assert out.endswith("…")             # marked as elided
    assert "¥204,000" in out             # the leading fact is intact, not half-cut
    # A string already within budget is returned unchanged (no marker).
    assert impl._truncate_on_boundary("短い文。", 1500) == "短い文。"


# --- registry + isolation ------------------------------------------------------
def test_registry_records_for_download(_tmp_generated):
    dispatch("generate_proposal", {"deal_id": DEAL, "confirm": True})
    # _DOCS is a process-global registry; take the most recent proposal record.
    rec = next(r for r in reversed(list(registry._DOCS.values())) if r["kind"] == "proposal")
    assert registry.get(rec["doc_id"]) is rec
    assert str(_tmp_generated) in rec["path"]                  # under tmp, not the seed


def test_seed_dir_not_written():
    proposal.generate(DEAL)
    ringisho.generate(DEAL)
    # generated files land under the (tmp) GENERATED_DIR, never the committed seed
    assert not list(config.SEED_DIR.glob("*.pptx"))
    assert not list(config.SEED_DIR.glob("*.docx"))
````

## File: web/app/junior/page.tsx
````typescript
import { api } from "@/lib/api";
import { currentEmployeeId } from "@/lib/server-session";
import { CommandCenter } from "@/components/workspace/command-center";
import { ContextPane } from "@/components/workspace/context-pane";

export const dynamic = "force-dynamic";

// The Junior home is the unified Command Center: live deal/account context on
// the left, the Copilot (Workspace) on the right. Same server-side fetch the
// standalone Workspace page used.
export default async function JuniorHome() {
  const eid = await currentEmployeeId();
  const [{ data: ex }, { data: db }, { data: pr }, { data: gr }] = await Promise.all([
    api.coachExamples(),
    api.dashboard(),
    api.principles(),
    api.growth(eid),
  ]);

  return (
    <CommandCenter
      examples={ex.examples}
      deals={db.deals}
      principles={pr.principles}
      role="junior"
      contextSlot={<ContextPane key="junior-context" deals={db.deals} role="junior" profile={gr.growth} />}
    />
  );
}
````

## File: web/components/workspace/context-pane.tsx
````typescript
"use client";

import { useMemo, useState } from "react";
import { Building2, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { useWorkspaceFocus } from "@/lib/chat-store";
import { customerText } from "@/lib/content-i18n";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { BandPill } from "@/components/band";
import { AccountView } from "@/components/account/account-view";
import type { Role } from "@/lib/session";
import type { Band, DealRow, GrowthData } from "@/lib/types";

// Surface the most urgent work first: at-risk deals before watch before healthy.
const BAND_ORDER: Record<Band, number> = { red: 0, yellow: 1, green: 2 };

/**
 * The left pane of the Command Center: the rep's live deal/account context.
 * Clicking a deal sets the shared workspace focus, which the Copilot (right
 * pane) reads to ground its next answer — no slash commands, no retyping a
 * customer name. "Open account" reuses the existing AccountView in a drawer, so
 * the full account read sits beside the conversation instead of on its own page.
 */
export function ContextPane({
  deals,
  role,
  profile,
}: {
  deals: DealRow[];
  role: Role;
  // Junior passes its growth profile; the manager surface has no single-rep
  // profile, so this is optional. Currently informational only.
  profile?: GrowthData;
}) {
  const { t, lang } = useT();
  const { focus, setFocus } = useWorkspaceFocus(role);
  const [q, setQ] = useState("");
  const [bandFilter, setBandFilter] = useState<Band | "all">("all");
  const [openAccount, setOpenAccount] = useState<{ id: string; name: string } | null>(null);

  const myDeals = useMemo(() => {
    const query = q.trim().toLowerCase();
    return deals
      .filter((d) => {
        if (bandFilter !== "all" && d.band !== bandFilter) return false;
        if (!query) return true;
        const name = customerText(lang, d.customer).text.toLowerCase();
        return name.includes(query) || d.customer.toLowerCase().includes(query);
      })
      .slice()
      .sort((a, b) => BAND_ORDER[a.band] - BAND_ORDER[b.band] || b.amount - a.amount);
  }, [deals, q, bandFilter, lang]);

  return (
    <div className="space-y-4">

      <div>
        <div className="eyebrow">{t("cc.todayWork")}</div>
        <p className="mt-1 text-[12px] text-muted-foreground">{t("cc.todayWorkLead")}</p>
      </div>

      <label className="flex items-center gap-2 rounded-lg border border-input bg-muted/40 px-3 py-2">
        <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("cc.searchAccounts")}
          className="w-full bg-transparent text-[13px] outline-none placeholder:text-muted-foreground"
        />
      </label>

      <div className="flex flex-wrap gap-1.5 pb-1">
        <button
          onClick={() => setBandFilter("all")}
          className={cn(
            "rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ring-1 ring-inset",
            bandFilter === "all" 
              ? "bg-primary text-primary-foreground ring-primary" 
              : "bg-muted/50 text-muted-foreground ring-border hover:bg-muted"
          )}
        >
          {lang === "ja" ? "すべて" : "All"}
        </button>
        {(["red", "yellow", "green"] as Band[]).map((b) => (
          <button
            key={b}
            onClick={() => setBandFilter(b)}
            className={cn(
              "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ring-1 ring-inset",
              bandFilter === b
                ? (b === "red" ? "bg-band-red text-white ring-band-red" : b === "yellow" ? "bg-band-yellow text-white ring-band-yellow" : "bg-band-green text-white ring-band-green")
                : (b === "red" ? "bg-band-red/10 text-band-red ring-band-red/25 hover:bg-band-red/20" : b === "yellow" ? "bg-band-yellow/10 text-band-yellow ring-band-yellow/25 hover:bg-band-yellow/20" : "bg-band-green/10 text-band-green ring-band-green/25 hover:bg-band-green/20")
            )}
          >
            <div className={cn("h-1.5 w-1.5 rounded-full", bandFilter === b ? "bg-white" : (b === "red" ? "bg-band-red" : b === "yellow" ? "bg-band-yellow" : "bg-band-green"))} />
            {t(b === "red" ? "dash.atRisk" : b === "yellow" ? "dash.watch" : "dash.healthy")}
          </button>
        ))}
      </div>

      <div className="space-y-2">
        {myDeals.length === 0 && (
          <p className="px-1 py-6 text-center text-[12.5px] text-muted-foreground">{t("cc.noDeals")}</p>
        )}
        {myDeals.map((d) => {
          const name = customerText(lang, d.customer).text;
          const active = focus.dealId === d.deal_id;
          return (
            <Card
              key={d.deal_id}
              role="button"
              tabIndex={0}
              onClick={() => setFocus({ dealId: d.deal_id, customerId: d.customer_id, customerName: name })}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setFocus({ dealId: d.deal_id, customerId: d.customer_id, customerName: name });
                }
              }}
              className={cn(
                "cursor-pointer transition-colors",
                active ? "border-primary ring-1 ring-inset ring-primary" : "hover:border-primary/40",
              )}
            >
              <CardContent className="flex items-center justify-between gap-3 p-3">
                <div className="min-w-0">
                  <div className="truncate text-[13.5px] font-medium">{name}</div>
                  <div className="truncate text-[11.5px] text-muted-foreground">
                    {d.stage} · ¥{d.amount.toLocaleString("ja-JP")}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <BandPill band={d.band} />
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpenAccount({ id: d.customer_id, name });
                    }}
                    className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-primary hover:bg-primary/5"
                  >
                    <Building2 className="h-3 w-3" />
                    {t("cc.openAccount")}
                  </button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Full account read — the existing AccountView, now in a drawer beside the
          Copilot rather than on its own route. */}
      <Dialog open={!!openAccount} onOpenChange={(o) => !o && setOpenAccount(null)}>
        <DialogContent className="p-5">
          <DialogTitle className="sr-only">{openAccount?.name ?? t("cc.openAccount")}</DialogTitle>
          {openAccount && (
            <AccountView
              customerId={openAccount.id}
              role={role}
              compact
              onAskCopilot={() => {
                // Hand off to the Copilot grounded on this account's most urgent
                // open deal (falling back to the account itself), then close.
                const top = deals
                  .filter((d) => d.customer_id === openAccount.id)
                  .sort((a, b) => BAND_ORDER[a.band] - BAND_ORDER[b.band] || b.amount - a.amount)[0];
                setFocus(
                  top
                    ? { dealId: top.deal_id, customerId: openAccount.id, customerName: openAccount.name }
                    : { customerId: openAccount.id, customerName: openAccount.name },
                );
                setOpenAccount(null);
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
````

## File: .gitignore
````
# Byte-compiled / optimized / DLL files
__pycache__/
*.py[codz]
*$py.class

# C extensions
*.so

# Distribution / packaging
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
*.jsonl
lib/
lib64/
parts/
sdist/
var/
wheels/
share/python-wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST

# PyInstaller
#   Usually these files are written by a python script from a template
#   before PyInstaller builds the exe, so as to inject date/other infos into it.
*.manifest
*.spec

# Installer logs
pip-log.txt
pip-delete-this-directory.txt

# Unit test / coverage reports
htmlcov/
.tox/
.nox/
.coverage
.coverage.*
.cache
nosetests.xml
coverage.xml
*.cover
*.py.cover
.hypothesis/
.pytest_cache/
cover/

# Translations
*.mo
*.pot

# Django stuff:
*.log
local_settings.py
db.sqlite3
db.sqlite3-journal

# Flask stuff:
instance/
.webassets-cache

# Scrapy stuff:
.scrapy

# Sphinx documentation
docs/_build/

# PyBuilder
.pybuilder/
target/

# Jupyter Notebook
.ipynb_checkpoints

# IPython
profile_default/
ipython_config.py

# pyenv
#   For a library or package, you might want to ignore these files since the code is
#   intended to run in multiple environments; otherwise, check them in:
# .python-version

# pipenv
#   According to pypa/pipenv#598, it is recommended to include Pipfile.lock in version control.
#   However, in case of collaboration, if having platform-specific dependencies or dependencies
#   having no cross-platform support, pipenv may install dependencies that don't work, or not
#   install all needed dependencies.
# Pipfile.lock

# UV
#   Similar to Pipfile.lock, it is generally recommended to include uv.lock in version control.
#   This is especially recommended for binary packages to ensure reproducibility, and is more
#   commonly ignored for libraries.
# uv.lock

# poetry
#   Similar to Pipfile.lock, it is generally recommended to include poetry.lock in version control.
#   This is especially recommended for binary packages to ensure reproducibility, and is more
#   commonly ignored for libraries.
#   https://python-poetry.org/docs/basic-usage/#commit-your-poetrylock-file-to-version-control
# poetry.lock
# poetry.toml

# pdm
#   Similar to Pipfile.lock, it is generally recommended to include pdm.lock in version control.
#   pdm recommends including project-wide configuration in pdm.toml, but excluding .pdm-python.
#   https://pdm-project.org/en/latest/usage/project/#working-with-version-control
# pdm.lock
# pdm.toml
.pdm-python
.pdm-build/

# pixi
#   Similar to Pipfile.lock, it is generally recommended to include pixi.lock in version control.
# pixi.lock
#   Pixi creates a virtual environment in the .pixi directory, just like venv module creates one
#   in the .venv directory. It is recommended not to include this directory in version control.
.pixi

# PEP 582; used by e.g. github.com/David-OConnor/pyflow and github.com/pdm-project/pdm
__pypackages__/

# Celery stuff
celerybeat-schedule
celerybeat.pid

# Redis
*.rdb
*.aof
*.pid

# RabbitMQ
mnesia/
rabbitmq/
rabbitmq-data/

# ActiveMQ
activemq-data/

# SageMath parsed files
*.sage.py

# Environments
.env
.envrc
.node_modules/
.venv
env/
venv/
ENV/
env.bak/
venv.bak/
# Freeze cache
scripts/.freeze_cache/

# Spyder project settings
.spyderproject
.spyproject

# Rope project settings
.ropeproject

# mkdocs documentation
/site

# mypy
.mypy_cache/
.dmypy.json
dmypy.json

# Pyre type checker
.pyre/

# pytype static type analyzer
.pytype/

# Cython debug symbols
cython_debug/

# PyCharm
#   JetBrains specific template is maintained in a separate JetBrains.gitignore that can
#   be found at https://github.com/github/gitignore/blob/main/Global/JetBrains.gitignore
#   and can be added to the global gitignore or merged into this file.  For a more nuclear
#   option (not recommended) you can uncomment the following to ignore the entire idea folder.
# .idea/

# Abstra
#   Abstra is an AI-powered process automation framework.
#   Ignore directories containing user credentials, local state, and settings.
#   Learn more at https://abstra.io/docs
.abstra/

# Visual Studio Code
#   Visual Studio Code specific template is maintained in a separate VisualStudioCode.gitignore 
#   that can be found at https://github.com/github/gitignore/blob/main/Global/VisualStudioCode.gitignore
#   and can be added to the global gitignore or merged into this file. However, if you prefer, 
#   you could uncomment the following to ignore the entire vscode folder
# .vscode/
# Temporary file for partial code execution
tempCodeRunnerFile.py

# ---------------------------------------------------------------------------
# Demo: secrets and runtime artifacts (never commit these)
# ---------------------------------------------------------------------------
# Google OAuth client secret and the live token (refresh/access). Use the
# committed demo/credentials.json.example as a template instead.
demo/credentials.json
demo/token.json
# Files written at runtime by the create_file tool.
demo/output/
# Root-level Google OAuth secret + live token used by senpai's schedule_meeting.
/credentials.json
/token.json

# Ruff stuff:
.ruff_cache/

# PyPI configuration file
.pypirc

# Marimo
marimo/_static/
marimo/_lsp/
__marimo__/

# Streamlit
.streamlit/secrets.toml

# Large training/raw datasets — exceed GitHub's 100 MB limit, not needed at runtime
*.jsonl

# Seeded rep logins (plaintext demo passwords; regenerate via scripts/seed_rep_logins.py)
rep_credentials.txt

# Runtime-ingested overlay data (demo-only; committed seed stays canonical)
senpai/data/ingested/
senpai/knowledge/seed/*.ingested.json

# Documents the chatbot generates (PPTX/DOCX); demo-only output, not committed
senpai/data/generated/

# Raw source deck used to derive the brand template — large, not needed at runtime.
# Only the slimmed-down derived template (otsuka_template.pptx) is committed.
# senpai/data/templates/otsuka_source.pptx

# Node.js dependencies
node_modules/
#
````

## File: README.md
````markdown
# Senpai — Sales Knowledge & Onboarding Copilot (Otsuka, Phase 2)

Senpai makes the knowledge that lives in Otsuka's best salespeople available to every rep —
on demand and in context — while giving managers one place to read deal health and catch
dying deals early. It is a **fine-tuned, tool-calling assistant (exp3)** anchored to Otsuka's
real SPR data, not a generic sales chatbot.

The pitch in one line: **onboarding is the relatable face; pipeline reliability — "nobody
knows if a deal is real" — is the engine underneath.** The same deterministic deal-health
read that briefs a junior before a call also flags a manager's dying deal.

---

## Repository map

| Path | What it is | Owner |
|---|---|---|
| **`senpai/`** | **Our pipeline** — the deterministic deal-health engine on Otsuka's real SPR schema, plus the junior chat, manager chat, and manager dashboard. **Start here.** | this team |
| `Schema.md` | The real Otsuka SPR schema (4 tables) + how our pipeline maps to it | this team |
| `senpai/api/`, `web/`, `senpai/coach/`, `senpai/knowledge/` | A separate, in-progress **web-app experiment** (FastAPI + Next.js frontend, Sales Review Coach, Knowledge Explorer) | another team member |
| `demo/` | Phase-1 tool-calling demo (the exp3 Gradio showcase that proved the model) | this team |

> Our pipeline does **not** import or depend on the web-app experiment; the two are
> decoupled and can run independently. See `senpai/README.md` → *Isolation* for details.

---

## Quickstart (web app)

Run the **backend** and **frontend** in two separate terminals. `SENPAI_USE_LLM=1` switches
live Coach commentary ON (default off = deterministic only).

### Windows (PowerShell)

```powershell
# install deps (Python bridge + frontend)
.\.venv\Scripts\pip.exe install -r requirements.txt
cd web; npm install; cd ..
```

# Terminal 1 — Backend bridge (FastAPI) → <http://localhost:8000>

$env:SENPAI_USE_LLM = '1'
$env:SENPAI_TODAY   = '2026-07-03'        # pin scoring's "today" to the seed anchor
.\.venv\Scripts\python.exe -m uvicorn senpai.api.server:app --port 8000 --host 127.0.0.1

# Terminal 2 — Frontend (Next.js) → <http://localhost:3000>   (defaults to the :8000 backend)

cd web; npm run dev

```

### Linux / macOS (bash)

```bash
# install deps (Python bridge + frontend)
.venv/bin/pip install -r requirements.txt
( cd web && npm install )

# Terminal 1 — Backend bridge (FastAPI) → http://localhost:8000
export SENPAI_USE_LLM=1
export SENPAI_TODAY=2026-06-16            # pin scoring's "today" to the seed anchor
.venv/bin/python -m uvicorn senpai.api.server:app --port 8000 --host 127.0.0.1

# Terminal 2 — Frontend (Next.js) → http://localhost:3000   (defaults to the :8000 backend)
cd web && npm run dev
```

The deal-health engine and unit tests are **pure Python (no GPU)**. Live Senior Commentary
additionally needs a GPU-served model on `:8765` — see **[Web app: switching on live Coach
commentary](#web-app-frontend--backend--switching-on-live-coach-commentary)** below for the
model server, the `SENPAI_USE_LLM` switch, and the `.env` wiring.

**→ Full engineering reference, tool list, env vars, and verify steps:
[`senpai/README.md`](senpai/README.md).**
**→ The data shape we build against: [`Schema.md`](Schema.md).**

---

## Web app (frontend + backend) — switching on live Coach commentary

The Next.js web app (`web/`) talks to the FastAPI bridge (`senpai/api/server.py`), which in
turn streams the optional **Senior Commentary** from a GPU-served, OpenAI-compatible model
(llama.cpp `llama-server`). The deterministic Review Coach always works without a model; the
LLM only *rephrases* the same findings. Live commentary is **gated OFF by default** — you turn
it on with one backend env var.

> The web↔engine boundary, the "endpoint first, then types/api/fixture" rule, and the drift
> check (`scripts/check_contract.py`) are documented in [`docs/web-integration.md`](docs/web-integration.md).

Start three things, in order:

### 1. Model server (GPU box) — `:8765`

The model is served by `llama-server` on the GPU box and reached over an OpenAI-compatible
endpoint. The bridge reads the endpoint + model name from the **repo-root `.env`** (loaded
automatically by `senpai/config.py`):

```bash
# E:\my_stuff\OtsukaPhase2\.env
BASE_URL="http://127.0.0.1:8765/v1"                          # via SSH tunnel (see below)
MODEL="Qwen3.6-27B-Claude-Opus-Reasoning-Distilled"          # llama-server ignores this field; label only
```

**Connectivity (from this Windows box):** the direct Tailscale URL
`http://100.101.186.29:8765/v1` is **firewalled** — the host pings but the port refuses. Reach
the server through an SSH tunnel instead, then point `BASE_URL` at `127.0.0.1:8765` (as above):

```bash
ssh -N -L 8765:127.0.0.1:8765 team-a@100.101.186.29     # leave running in its own terminal
```

**Starting / restarting the model** (the 27B GGUF is periodically **OOM-killed** on the shared
GB10 — when the Assistant shows "Couldn't reach the server", relaunch it):

```bash
# from anywhere — launches detached on the GPU box
ssh team-a@100.101.186.29 'cd ~/Desktop/toolcallLM/qwen3 && \
  setsid bash -c "./serve_gguf.sh > llama-server.log 2>&1" </dev/null &'
```

Sanity check it's up (needs the tunnel): `curl http://127.0.0.1:8765/v1/models`.
Check it's alive on the box: `ssh team-a@100.101.186.29 'pgrep -af llama-server'`.
> A `couldn't bind … 0.0.0.0:8765` line in the llama-server log just means a **second** launch
> hit an already-running instance — the first one is fine.

### 2. Backend bridge (FastAPI) — `:8000`  ← **this is the switch**

```bash
# PowerShell (Windows)
$env:SENPAI_USE_LLM = '1'        # ← switches live commentary ON (default '0' = deterministic only)
$env:SENPAI_TODAY   = '2026-06-23'   # pin scoring's "today" to the seed anchor
python -m uvicorn senpai.api.server:app --port 8000 --host 127.0.0.1
```

```bash
# bash / macOS / Linux
export SENPAI_USE_LLM=1
export SENPAI_TODAY=2026-06-16
.venv/bin/python -m uvicorn senpai.api.server:app --port 8000 --host 127.0.0.1
```

- **`SENPAI_USE_LLM=1` is the on/off switch.** Without it, `/api/coach/narrate` returns
  `unavailable: llm_disabled` and the UI shows *"Couldn't reach the explanation model…"*.
- The bridge has **no `--reload`**: after editing `.env` (or any Python), **restart it** to pick
  up the change.
- Verify: `curl http://localhost:8000/api/health` → `{"status":"ok", …}`.

### 3. Frontend (Next.js) — `:3000`

```bash
cd web
npm install            # first time only
npm run dev            # → http://localhost:3000
```

The frontend points at the backend via `NEXT_PUBLIC_API_BASE`, which **defaults to
`http://localhost:8000`** — so if the bridge runs on :8000 you need no config. To target a
different host, create `web/.env.local`:

```bash
# web/.env.local
NEXT_PUBLIC_API_BASE="http://localhost:8000"
```

Then open **Review Coach → Get the senior's read**: with the backend switch on and the model
reachable, the commentary streams in live. With either off, the page falls back cleanly to the
deterministic coaching.

### Senior Commentary — what it does, and its contract

The commentary is an **experienced rep's interpretation** layered on the deterministic coach —
not a restatement of the six lenses. Before calling the model, the bridge builds a grounded
**context package** (`senpai/coach/context.py`): it resolves the customer named in the note to a
real deal, then assembles that deal's health, recent activity, quote/order history, prior
deals, and a similar past case. The model reasons over that context and answers in four short
sections (Situation Summary / What an Experienced Rep Would Focus On / Likely Customer Dynamics
/ Practical Advice).

| Property | Value |
|---|---|
| **Active model** | `Qwen3.6-27B-Claude-Opus-Reasoning-Distilled` (GGUF Q4_K_M, llama-server) — shown in the UI's `start`/`Generated by` badge |
| **Endpoint** | pinned to `BASE_URL` from `.env` (`http://100.101.186.29:8765/v1`). The request sets `allow_fallback=False` — it **never** silently switches to another model. |
| **Latency** | Reasoning is **disabled** (empty-`<think>` prefill) and output is capped at `LLM_NARRATE_MAX_TOKENS` (default 260) → ~15–22s, vs ~60–90s with reasoning on. |
| **Fallback behaviour** | If the endpoint is down/empty, the stream emits `unavailable` and the UI shows **"Senior commentary unavailable — the deterministic coaching above still stands."** No second model is used. |
| **Grounding** | Only real store records are used. If the note names no known customer, the UI shows no "Grounded in …" badge and the model is told to read from the note alone and invent nothing. |

Tunables (env): `LLM_NARRATE_MAX_TOKENS` (length/latency trade-off), `LLM_TIMEOUT` (per-read
stream timeout). The model name is a label only — llama-server serves whatever GGUF is loaded.

---

## What's inside the pipeline (at a glance)

- **Real SPR schema.** `senpai/data/gen_seed.py` generates byte-stable synthetic data in
  Otsuka's production shape (`deals`, `orders`, `quotes`, `sales_activities`), so the real
  data is a drop-in when we get access. `order_rank` (`1_Confirmed … 8_Cancelled`) is the spine.
- **Deterministic deal-health engine.** Seven rank-aware signals (staleness, rank stagnation,
  order-date passed, rank regression, missing decision-maker, stall language, low activity) →
  a 🔴🟡🟢 score with a Japanese reason for every signal. No number is ever invented by a model.
- **Report-reliability flags.** Surfaces deals whose recorded rank contradicts their activity
  signals (`optimism_mismatch`, `stale_active`, `close_date_passed`, …).
- **Web app over one shared engine.** A Next.js frontend (Review Coach, Knowledge Explorer,
  manager workspace, growth) on a FastAPI bridge — junior briefs/playbook/report drafting and
  manager at-risk deals, report digests, and coaching focus, all reading the same deterministic
  engine, with optional GPU-served Senior Commentary.

## Verify (no GPU)

```bash
export SENPAI_TODAY=2026-06-16
.venv/bin/pytest tests/test_scoring.py tests/test_flags.py tests/test_manager_tools.py
.venv/bin/python -m senpai.tools.impl        # one canned call per tool
```

## Phase-1 demo

The original tool-calling showcase (exp3 answering in natural language while calling real
tools) lives in [`demo/`](demo/) with its own run sheet at `demo/demo_script.md`.
````

## File: senpai/tools/schemas.py
````python
"""OpenAI function-calling schemas for Senpai's sales tools.

Same shape as demo/tools.py's TOOLS. These are the capabilities the junior
assistant (exp3) can call; every one is backed by the deterministic store /
scoring engine in senpai.tools.impl.
"""
from __future__ import annotations

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_spr",
            "description": "Look up deals and recent notes from the sales pipeline (SPR) "
                           "by customer name/ID or rep ID. Use this to prepare for a visit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Customer name or ID (e.g. 'アクメ商事' or 'C01')"},
                    "rep_id": {"type": "string", "description": "Rep ID, e.g. 'R05'"},
                    "deal_id": {"type": "string", "description": "Specific deal ID, e.g. 'D012'"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_deals",
            "description": "Grounded faceted search over real past/current deals. Filters by any "
                           "combination of: product_category, customer industry, customer size, "
                           "outcome (won/lost/open), order_rank, amount band, or a product code — "
                           "and reports the win/lost/open breakdown of the matches. Use this to "
                           "answer 'show me past <category> deals at <size>/<industry> companies "
                           "and how they went' BEFORE giving advice, so the answer is from data. "
                           "Filter values must be real values present in the data; if a filter "
                           "matches nothing, the tool lists the valid values to use.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_category": {"type": "string", "description": "Deal product category, e.g. 'サーバー', 'ソフトウェア', 'ネットワーク機器' (substring ok)"},
                    "industry": {"type": "string", "description": "Customer industry, e.g. '製造', '医療' (substring ok)"},
                    "size": {"type": "string", "description": "Customer size band, e.g. '中規模', '小規模'"},
                    "outcome": {"type": "string", "description": "'won', 'lost', or 'open' (derived from order_rank)"},
                    "order_rank": {"type": "string", "description": "Exact/substring order_rank, e.g. '3_A'"},
                    "min_amount": {"type": "number", "description": "Minimum total_order_amount (¥)"},
                    "max_amount": {"type": "number", "description": "Maximum total_order_amount (¥)"},
                    "product_code": {"type": "string", "description": "A specific product code the deal includes, e.g. 'MON27'"},
                    "limit": {"type": "integer", "description": "Max deals to list (default 10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_similar_deals",
            "description": "Find comparable past deals for a new or thin customer, matched on "
                           "industry, size and profile tags. Useful when the customer has little history.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Customer name or ID"},
                    "industry": {"type": "string", "description": "Industry (e.g. '製造', '医療')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_playbook",
            "description": "Retrieve senior reps' tactical advice for a situation, by keywords or "
                           "tags (e.g. '決定先延ばし', '値引き'). Returns attributed snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The situation in natural language"},
                    "tags": {"type": "array", "items": {"type": "string"},
                             "description": "Optional situation tags to match"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "Semantic search across CRM daily reports (日報) ONLY — not the "
                           "user's local files. Finds notes that mean the same thing as the "
                           "query even when worded differently (e.g. '予算が理由で停滞' also "
                           "surfaces 'コスト面で渋い'). ALWAYS pass `customer` (the account in "
                           "focus) for any account-specific question — this restricts the "
                           "search to that customer's own notes. Omit `customer` ONLY for "
                           "deliberate cross-account research; results then span all customers "
                           "and are labelled as such. If this comes back thin/generic, or the "
                           "user's phrasing could mean an actual document (e.g. names a file, "
                           "says 'the notes', 'the doc', or asks to add/edit/apply something "
                           "INTO them), also call search_workspace_documents — the real notes "
                           "may live in a local file, not a daily report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for, in natural language"},
                    "customer": {"type": "string", "description": "The account in focus (name or ID). "
                                 "Scopes the search to this customer's notes. Pass it whenever the "
                                 "question is about a specific account."},
                    "limit": {"type": "integer", "description": "Max notes to return (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_customer_environment",
            "description": "Get the customer's IT environment record (PCs, OS, network) — the "
                           "handoff information a rep needs before a technical visit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Customer name or ID"},
                },
                "required": ["customer"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_info",
            "description": "Get specs, price and a manual excerpt for a product by SKU or name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product": {"type": "string", "description": "Product SKU (e.g. 'MFP30') or name"},
                },
                "required": ["product"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_deal_health",
            "description": "Assess a deal's health: returns a red/yellow/green band, a risk score "
                           "and the concrete reasons behind it. Use to judge if a deal is really on track.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string", "description": "Deal ID, e.g. 'D012'"},
                },
                "required": ["deal_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "review_sales_note",
            "description": "Coach a junior on a raw meeting note or daily report. Returns what an "
                           "experienced rep would notice, missing info, risk signals, questions to ask "
                           "next, several possible next moves, and decision factors — it teaches "
                           "reasoning and never gives a single 'correct answer'. Pass the note text; "
                           "add deal_id to fold in that deal's structured signals.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "The meeting note / daily report text to review"},
                    "deal_id": {"type": "string", "description": "Optional related deal ID, e.g. 'D012'"},
                },
                "required": ["note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_daily_report",
            "description": "Draft an SPR-ready daily sales report (日報) in Japanese from a short "
                           "activity description and optional deal ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "activity": {"type": "string", "description": "What happened today, in natural language"},
                    "deal_id": {"type": "string", "description": "Related deal ID, if any"},
                },
                "required": ["activity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "route_to_expert",
            "description": "Find the right senior/expert rep to escalate a question to, matched on "
                           "their specialty tags, and draft a short intro message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to escalate"},
                    "tags": {"type": "array", "items": {"type": "string"},
                             "description": "Topic tags (e.g. 'ネットワーク', 'サーバー')"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_reports",
            "description": "Summarize a rep's recent reports and surface report-reliability flags "
                           "(stale/optimistic/missing-field deals). Manager-facing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rep_id": {"type": "string", "description": "Rep ID, e.g. 'R05'"},
                },
                "required": ["rep_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_seasonal_context",
            "description": "Get Japanese fiscal-year budget-timing context (the year ends in March) "
                           "to advise on close-timing and budget conversations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "integer", "description": "Month number 1-12 (default: current)"},
                },
                "required": [],
            },
        },
    },
    # --- Manager + shared tools ---------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "morning_briefing",
            "description": "The rep's prioritized to-do for today: their open deals ranked by "
                           "urgency × value, each with ONE concrete next action (e.g. follow up, "
                           "identify the decision-maker, re-confirm the close date). Includes a "
                           "predictive nudge for deals about to breach their contact cadence. "
                           "Omit rep_id for a whole-team view. Use this to answer 'what should I "
                           "do today?' / '今日やるべきことは?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rep_id": {"type": "string", "description": "Rep ID to brief, e.g. 'R12'. Omit for the whole team."},
                    "limit": {"type": "integer", "description": "Max actions to return (default 10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_at_risk_deals",
            "description": "List at-risk open deals across the whole team (or one rep), worst first. "
                           "Each line shows the owner, customer, risk score and the top reason. "
                           "Defaults to red deals; pass band='yellow' to include yellow too.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rep_id": {"type": "string", "description": "Optional rep ID to limit to one rep, e.g. 'R05'"},
                    "band": {"type": "string", "description": "'red' (default), 'yellow' (red+yellow), or 'green'"},
                    "limit": {"type": "integer", "description": "Max deals to return (default 10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "team_pipeline_overview",
            "description": "Team pipeline at a glance: open-deal count, total ¥ value, breakdown by "
                           "stage, red/yellow/green health split, and number of flagged reports.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rep_id": {"type": "string", "description": "Optional rep ID to scope to one rep"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "team_report_digest",
            "description": "Digest every rep's open deals into one manager view: the flagged/stale/"
                           "optimistic deals grouped by rep, worst first. Use to review the whole team at once.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rep_coaching_focus",
            "description": "Per-rep rollup (deal count, at-risk count, flagged count, average risk), sorted "
                           "so the reps who need coaching attention come first.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_message",
            "description": "Draft a short, editable Japanese message (a nudge to a rep or a client "
                           "follow-up). Pulls deal context when a deal_id is given. Never sends — the human edits and sends.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient name, e.g. '伊藤さん' or a client"},
                    "about": {"type": "string", "description": "What the message is about"},
                    "deal_id": {"type": "string", "description": "Optional related deal ID for context"},
                    "purpose": {"type": "string", "description": "Optional purpose, e.g. '進捗確認'"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for external information (industry trends, company/customer news, "
                           "competitor info). Use for facts not in the internal data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_research",
            "description": "Research the open web by ACTUALLY VISITING pages (a real crawler), then "
                           "answer grounded in what was on them. Auto-routes on the input: (a) a "
                           "website URL or bare domain → crawls that site and returns a pre-call "
                           "intel brief (company overview, products, recent news, IR/財務 docs, "
                           "talking points); (b) a question with no URL (e.g. '築地の営業会社トップ5') "
                           "→ web-searches it, crawls the top result sites, and answers with source "
                           "URLs. Every claim carries a source link. Prefer this over web_search "
                           "when the user pastes a URL or wants real page content, not just snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "input": {"type": "string",
                              "description": "A website URL (e.g. 'https://www.example.co.jp') OR a "
                                             "research question (e.g. '築地の営業支援会社を教えて')"},
                    "max_pages": {"type": "integer",
                                  "description": "Max pages per site to visit (default 6, capped at 12)"},
                    "max_sites": {"type": "integer",
                                  "description": "For a question: how many distinct sites to crawl (default 3, max 5)"},
                },
                "required": ["input"],
            },
        },
    },
    # --- Knowledge RAG + sales-action tools (ported from demo/tools.py) -------
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search the validated internal knowledge corpus — senior-rep "
                           "principles, approved coaching cases and the playbook — for advice "
                           "grounded in real interviews. Returns short attributed/cited snippets. "
                           "Prefer this over web_search for 'how should I handle…' questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The situation in natural language"},
                    "tags": {"type": "array", "items": {"type": "string"},
                             "description": "Optional situation tags (e.g. '値引き', '決定先延ばし')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search the Otsuka product catalog by category, price range, or keyword. "
                           "Returns matching products with code, name and unit price (JPY).",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string",
                                 "description": "Category term to match (e.g. '複合機', 'サーバー', 'PC')"},
                    "max_price": {"type": "number", "description": "Maximum unit price in JPY"},
                    "min_price": {"type": "number", "description": "Minimum unit price in JPY"},
                    "keyword": {"type": "string", "description": "Free-text term to match in name/specs"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_quote",
            "description": "Build a price quote (estimate) for one or more catalog products: line "
                           "totals, optional discount, tax and grand total. A draft — never sent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Products to quote.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sku": {"type": "string", "description": "Product code or name"},
                                "qty": {"type": "integer", "description": "Quantity"},
                            },
                            "required": ["sku", "qty"],
                        },
                    },
                    "discount_pct": {"type": "number", "description": "Discount percent on the subtotal (0-100)"},
                    "customer": {"type": "string", "description": "Customer/company name for the header"},
                    "tax_pct": {"type": "number", "description": "Sales-tax percent (default 10)"},
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_meeting",
            "description": "Book a meeting on the calendar in two steps so the rep stays in the "
                           "loop. First call with confirm=false (default) to return a draft for the "
                           "rep to review; only after the rep explicitly says to book it, call again "
                           "with confirm=true to create a real Google Calendar event. Resolve "
                           "relative dates to YYYY-MM-DD first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Meeting title"},
                    "date": {"type": "string", "description": "Date as YYYY-MM-DD"},
                    "start_time": {"type": "string", "description": "Start time as 24h HH:MM (JST)"},
                    "duration_hours": {"type": "number", "description": "Length in hours (default 1)"},
                    "attendees": {"type": "array", "items": {"type": "string"},
                                  "description": "Attendee names or emails"},
                    "description": {"type": "string", "description": "Optional agenda/notes"},
                    "confirm": {"type": "boolean",
                                "description": "Set true ONLY when the rep has explicitly confirmed; "
                                               "actually books the event. Default false returns a draft."},
                },
                "required": ["title", "date", "start_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Prepare an email draft to a recipient. Never actually sends — the human "
                           "edits and sends. Use for follow-ups / quote delivery messages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient name or email address"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_calendar",
            "description": "Get the schedule for a given day (YYYY-MM-DD or 'today'). Simulated demo data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "day": {"type": "string", "description": "Date as YYYY-MM-DD or 'today'"},
                },
                "required": ["day"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_graph",
            "description": "Answer relational, multi-hop questions over the sales knowledge graph "
                           "(customer→deal→activity→rep→product) that simple lookups can't. Intents: "
                           "'reps_who_win' (who has the best win-rate on deals filtered by category / "
                           "industry / activity type — e.g. 'reps who win サーバー deals in 製造業 after "
                           "a site survey'); 'account' (one customer's whole deal/rep/product network); "
                           "'connections' (how two entities are linked); 'similar' (deals related to a "
                           "deal_id by shared rep/product/industry).",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string",
                               "description": "'reps_who_win' | 'account' | 'connections' | 'similar'"},
                    "category": {"type": "string", "description": "Product category filter, e.g. 'サーバー'"},
                    "industry": {"type": "string", "description": "Customer industry filter, e.g. '製造'"},
                    "after_activity_type": {"type": "string",
                                            "description": "Require deals that had this activity type, e.g. '001_Scheduled'"},
                    "customer": {"type": "string", "description": "Customer name/ID (intent='account')"},
                    "deal_id": {"type": "string", "description": "Deal ID (intent='similar'), e.g. 'D012'"},
                    "entity_a": {"type": "string", "description": "First entity (intent='connections')"},
                    "entity_b": {"type": "string", "description": "Second entity (intent='connections')"},
                    "limit": {"type": "integer", "description": "Max rows (default 8)"},
                },
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "segment_intelligence",
            "description": "Answer AGGREGATE / thematic / portfolio questions across market "
                           "segments (product category × customer industry) that per-deal or "
                           "per-account lookups can't: win rates, the common FAILURE MODES "
                           "behind lost deals, and the recommended play per segment. Use for "
                           "questions like 'なぜ製造業のサーバー案件は負ける？', 'common failure "
                           "modes across our lost deals', 'which segment loses most and why', "
                           "'どのカテゴリの勝率が低い？'. Each segment answer is grounded in real "
                           "tallies from the deal-health engine and cites the evidence deal ids. "
                           "Pass category and/or industry to focus; omit both for a portfolio "
                           "overview.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "The manager's thematic question (used to pick relevant segments)"},
                    "category": {"type": "string", "description": "Product category filter, e.g. 'サーバー'"},
                    "industry": {"type": "string", "description": "Customer industry filter, e.g. '製造業'"},
                    "outcome": {"type": "string", "description": "'won' | 'lost' | 'all' (default 'all') — nudges ranking"},
                    "limit": {"type": "integer", "description": "Max segments to return (default 6)"},
                },
                "required": ["query"],
            },
        },
    },
    # --- Document generation: the chatbot's "do stuff" tools ------------------
    {
        "type": "function",
        "function": {
            "name": "generate_proposal",
            "description": "Generate a persuasive PowerPoint (.pptx) SALES PROPOSAL for a "
                           "specific deal, grounded in its SPR data. It follows a full "
                           "proposal arc (background → challenges → solution → ROI → next "
                           "steps), mapping the customer's real pain points against the "
                           "deal's real financials, quote, and same-category comparable "
                           "deals — persuasive framing, grounded numbers. Builds the file "
                           "directly in one call (no confirmation step). Use when the rep "
                           "asks to make a proposal/提案書 deck for a deal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string", "description": "The deal to build the proposal for, e.g. 'D012'"},
                    "lang": {"type": "string", "description": "'ja' (default) or 'en'"},
                    "confirm": {"type": "boolean",
                                "description": "Set true ONLY after the rep confirms; actually creates the file. Default false returns a preview, after which you MUST stop and ask the user for confirmation."},
                },
                "required": ["deal_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_ringisho",
            "description": "Generate a formal Japanese internal-approval document (稟議書) as "
                           "a Word file (.docx) for a specific deal, written from the "
                           "customer's IT-manager persona pitching their own CEO, using the "
                           "deal's real financials to justify solving the SPR-logged pain "
                           "points. Two-step: confirm=false (default) returns a preview; "
                           "confirm=true builds and saves the file. Use when the rep asks "
                           "for a 稟議書 / approval document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string", "description": "The deal to build the 稟議書 for, e.g. 'D012'"},
                    "confirm": {"type": "boolean",
                                "description": "Set true ONLY after the rep confirms; actually creates the file. Default false returns a preview, after which you MUST stop and ask the user for confirmation."},
                },
                "required": ["deal_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_pptx",
            "description": "Generate a general-purpose PowerPoint (.pptx) on ANY topic from a "
                           "natural-language prompt — not tied to a deal. The deck is authored "
                           "by the model and can be about anything (e.g. 'make a deck about "
                           "GTA 6'); no fixed slide count. Grounding is automatic: external/"
                           "factual topics (products, prices, 'best-of', comparisons, current "
                           "models) are web-grounded by default, and a customer grounds it in "
                           "internal records — you normally do NOT set use_web. Builds the file "
                           "directly in one call (no confirmation step). Use generate_proposal "
                           "instead for a deal-specific sales proposal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "What the presentation should be about"},
                    "title": {"type": "string", "description": "Optional title override"},
                    "use_web": {"type": "boolean", "description": "Override web grounding. Omit to auto-decide (external/factual topics are web-grounded automatically). Set false to force the model's own knowledge; true to force a web search."},
                    "customer": {"type": "string", "description": "Optional customer name/ID to ground the deck in internal records"},
                    "lang": {"type": "string", "description": "'ja' (default) or 'en'"},
                    "confirm": {"type": "boolean",
                                "description": "Set true ONLY after the rep confirms; actually creates the file. Default false returns a preview, after which you MUST stop and ask the user for confirmation."},
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_docx",
            "description": "Generate a general-purpose Word document (.docx) on ANY topic from "
                           "a natural-language prompt — not tied to a deal. Authored by the "
                           "model; can be about anything. Grounding is automatic: external/"
                           "factual topics are web-grounded by default, and a customer grounds "
                           "it in internal records — you normally do NOT set use_web. Builds the "
                           "file directly in one call (no confirmation step). Use "
                           "generate_ringisho instead for a deal-specific 稟議書.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "What the document should be about"},
                    "title": {"type": "string", "description": "Optional title override"},
                    "use_web": {"type": "boolean", "description": "Override web grounding. Omit to auto-decide (external/factual topics are web-grounded automatically). Set false to force the model's own knowledge; true to force a web search."},
                    "customer": {"type": "string", "description": "Optional customer name/ID to ground the document in internal records"},
                    "lang": {"type": "string", "description": "'ja' (default) or 'en'"},
                    "confirm": {"type": "boolean",
                                "description": "Set true ONLY after the rep confirms; actually creates the file. Default false returns a preview, after which you MUST stop and ask the user for confirmation."},
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_workspace_documents",
            "description": "Find and READ relevant local documents (PDF, DOCX, PPTX, "
                           "XLSX, TXT, Markdown) from the user's sandboxed workspace "
                           "folder, and return their text with per-file citations. Use "
                           "when the answer may live in the user's own files (a proposal "
                           "deck, meeting notes, a spreadsheet, a PDF) rather than the CRM "
                           "or the web — e.g. 'what did we send Endo Kogyo?', 'summarize my "
                           "notes on this account'. Read-only; never edits or deletes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "What to look for; matched against file names/paths. Empty returns the most recent documents."},
                    "limit": {"type": "integer",
                              "description": "Max documents to read (default/cap set by the server)."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_workspace_document",
            "description": "Create or modify a local text document (e.g. .txt, .md, .csv, .json) in the user's workspace. "
                           "This is the ONLY way to actually persist something into a local file — if the user asks to "
                           "add/append/apply/update/edit/save/反映/追加/適用/編集 information INTO a file or notes you "
                           "already found (e.g. via search_workspace_documents), you MUST call this tool with the full "
                           "merged content, not just describe the merge in your chat answer — never claim something was "
                           "saved or applied unless this tool actually ran. "
                           "You must pass confirm=False first to return a preview. Then ask the user to confirm. "
                           "If they confirm, run again with confirm=True to commit the write to disk.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The absolute path or relative path from the workspace to save the file."},
                    "content": {"type": "string", "description": "The text content to write into the file."},
                    "confirm": {"type": "boolean", "description": "Set true ONLY after the user confirms; actually writes the file. Default false returns a preview."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_workspace_document",
            "description": "Move or rename a local document in the user's workspace. "
                           "You must pass confirm=False first to return a preview. Then ask the user to confirm. "
                           "If they confirm, run again with confirm=True to commit the move. "
                           "Can be used to organize all types of files, including PDFs and PPTXs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string", "description": "The current path of the file."},
                    "dst": {"type": "string", "description": "The new path for the file."},
                    "confirm": {"type": "boolean", "description": "Set true ONLY after the user confirms; actually moves the file. Default false returns a preview."},
                },
                "required": ["src", "dst"],
            },
        },
    },
]


# --- Role-scoped tool subsets ----------------------------------------------
# Each front end passes its own list to stream_turn(). Built by name from TOOLS
# so a schema is defined exactly once.
_BY_NAME = {t["function"]["name"]: t for t in TOOLS}


def _pick(*names: str) -> list[dict]:
    return [_BY_NAME[n] for n in names]


# Junior assistant: the in-context coaching tools + web_search.
# (review_sales_note is intentionally excluded — it bridges to the friend-owned
#  coach experiment and is kept out of our chat surface for isolation.)
JUNIOR_TOOLS = _pick(
    "query_spr", "find_deals", "find_similar_deals", "retrieve_playbook", "search_knowledge",
    "search_notes", "lookup_customer_environment", "get_product_info", "search_products",
    "create_quote", "score_deal_health", "draft_daily_report", "schedule_meeting",
    "send_email", "get_calendar", "route_to_expert", "morning_briefing",
    "get_seasonal_context", "web_search", "web_research", "search_workspace_documents", "edit_workspace_document", "move_workspace_document",
    "generate_proposal", "generate_ringisho", "generate_pptx", "generate_docx",
)

# Manager: team analytics + drill-down + drafting + semantic/graph search + web.
MANAGER_TOOLS = _pick(
    "query_spr", "find_deals", "score_deal_health", "morning_briefing", "list_at_risk_deals",
    "team_pipeline_overview", "team_report_digest", "rep_coaching_focus",
    "search_knowledge", "search_notes", "query_graph", "segment_intelligence", "search_products",
    "create_quote", "schedule_meeting",
    "send_email", "get_calendar", "draft_message", "web_search", "web_research", "search_workspace_documents", "edit_workspace_document", "move_workspace_document",
    "generate_proposal", "generate_ringisho", "generate_pptx", "generate_docx",
)

# Research assistant ("tell me about this customer"): read-only lookups, internal
# first, with web_search to fill external gaps. No drafting/coaching tools — this
# is a grounded research surface, not a generic chat. Order mirrors the intended
# source priority (internal records → deal signals → web).
RESEARCH_TOOLS = _pick(
    "query_spr", "find_deals", "find_similar_deals", "score_deal_health", "search_notes",
    "lookup_customer_environment", "get_product_info", "segment_intelligence",
    "get_seasonal_context", "web_search", "web_research", "search_workspace_documents", "edit_workspace_document", "move_workspace_document",
)
````

## File: web/components/assistant/message.tsx
````typescript
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
import { documentUrl, type ResolveCandidate, type RetrievalTrace } from "@/lib/api";
import type { GeneratedDocument } from "@/lib/types";
import { cn } from "@/lib/utils";
import { RetrievalExplorer } from "@/components/assistant/retrieval-explorer";

export type ToolCall = { name: string; args: string; result: string; document?: GeneratedDocument; batchId?: string | null; intent?: string; outline?: { title: string }[]; internal?: boolean };
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
````

## File: senpai/tools/impl.py
````python
"""Tool implementations + dispatch — mirrors demo/tools.py's contract.

Every executor returns a SHORT string (what the model sees as the tool result)
and `dispatch` never raises, so the chat loop can't crash. All data comes from
the deterministic store / scoring engine, so these run GPU-free.

`python -m senpai.tools.impl` runs a canned call per tool (smoke test).
"""
from __future__ import annotations

import json
import re

from senpai import config
from senpai.data import store
from senpai.health.flags import deal_flags
from senpai.health.scoring import score_deal
from senpai.retrieval.knowledge import search_knowledge as _search_knowledge
from senpai.retrieval.playbook import find_similar_deals, retrieve_playbook
from senpai.tools.focus import session_focus
from senpai.tools.web import web_search
from senpai.tools.crawl import web_research


def _score_open_deals(rep_id: str = ""):
    """Score every open deal once (optionally limited to one rep). Returns a list
    of (deal, HealthResult, flags) — the shared backbone for the manager
    analytics tools and summarize_reports, so the scoring loop lives in one place."""
    deals = store.deals_for_rep(rep_id) if rep_id else store.open_deals()
    out = []
    for d in deals:
        if not config.is_open_rank(d.get("order_rank")):
            continue
        acts = store.activities_for_deal(d["deal_id"])
        res = score_deal(d, acts)
        flags = deal_flags(d, acts, health_band=res.band)
        out.append((d, res, flags))
    return out


def _resolve_customer(customer: str) -> dict | None:
    """Alias-aware: resolves JA / English / romaji / known-alias forms (e.g.
    'Aozora Services' -> あおぞらサービス) before any retrieval."""
    if not customer:
        return None
    return store.resolve_customer(customer)


def _deal_line(d: dict) -> str:
    # The deal_name (e.g. "藤本食品 複合機案件") and product_category are what let the
    # model pick the deal the rep actually named — a request for "複合機案件" must not
    # silently resolve to the biggest open deal. The name already carries the customer.
    cust = store.customer_name(d["customer_id"])
    label = (d.get("deal_name") or "").strip() or cust
    cat = (d.get("product_category") or "").strip()
    if cat:
        label = f"{label}（{cat}）"
    return (f"{d['deal_id']} {label} / 担当{store.rep_name(store.deal_rep_id(d))} / "
            f"{d['order_rank']} / ¥{d['total_order_amount']:,} / "
            f"完了予定{d['expected_order_date']}")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
def query_spr(customer: str = "", rep_id: str = "", deal_id: str = "") -> str:
    if deal_id:
        d = store.get_deal(deal_id)
        if not d:
            return f"案件 {deal_id} は見つかりません。"
        acts = store.activities_for_deal(deal_id)
        head = _deal_line(d)
        act_lines = [f"  ・{a['activity_date']} [{a['activity_type']}] {a['daily_report']}"
                     for a in acts[:3]]
        return head + ("\n直近の活動:\n" + "\n".join(act_lines) if act_lines else "")

    if customer:
        c = _resolve_customer(customer)
        if not c:
            return f"顧客「{customer}」は見つかりません。"
        deals = store.deals_for_customer(c["customer_id"])
        if not deals:
            return f"{c['name']} の案件はありません。"
        lines = [_deal_line(d) for d in deals]
        return f"{c['name']} の案件 {len(deals)}件:\n- " + "\n- ".join(lines)

    if rep_id:
        deals = store.deals_for_rep(rep_id)
        if not deals:
            return f"担当 {rep_id} の案件はありません。"
        lines = [_deal_line(d) for d in deals]
        return f"{store.rep_name(rep_id)} の案件 {len(deals)}件:\n- " + "\n- ".join(lines)

    return "customer / rep_id / deal_id のいずれかを指定してください。"


def find_deals(product_category: str = "", industry: str = "", size: str = "",
               outcome: str = "", order_rank: str = "", min_amount=None,
               max_amount=None, product_code: str = "", limit: int = 10) -> str:
    """Grounded faceted search over real past/current deals. Filters the actual SPR
    fields (deal product_category / order_rank / amount / product code, customer
    industry / size) and reports the win/lost/open breakdown of the matches, so the
    model answers 'show me past <category> deals at <size>/<industry> companies and
    how they went' from data — never from invention."""
    from senpai.retrieval.deals import deal_facets, find_deals as _find, outcome_breakdown
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    all_hits = _find(product_category=product_category, industry=industry, size=size,
                     outcome=outcome, order_rank=order_rank, min_amount=min_amount,
                     max_amount=max_amount, product_code=product_code, limit=0)
    cond = "／".join(str(x) for x in [product_category, industry, size, outcome,
                                      order_rank, product_code] if x) or "全条件"
    if not all_hits:
        f = deal_facets()
        return ("条件に合う案件は見つかりませんでした。指定可能な値:\n"
                f"- 商品カテゴリ: {'、'.join(f['product_category'])}\n"
                f"- 業種: {'、'.join(f['industry'])}\n"
                f"- 規模: {'、'.join(f['size'])}\n"
                f"- 受注ランク: {'、'.join(f['order_rank'])}\n"
                "- 結果(outcome): won / lost / open")
    bd = outcome_breakdown(all_hits)
    head = (f"該当案件【{cond}】{len(all_hits)}件 "
            f"(受注{bd['won']}／失注{bd['lost']}／進行中{bd['open']}):")
    lines = []
    for d in all_hits[:limit]:
        cust = store.get_customer(d["customer_id"]) or {}
        lines.append(f"{d['deal_id']} {store.customer_name(d['customer_id'])}"
                     f"（{cust.get('industry', '-')}/{cust.get('size', '-')}）"
                     f" {d.get('product_category', '-')} / {d.get('order_rank', '-')}"
                     f" / ¥{d.get('total_order_amount', 0):,}")
    return head + "\n- " + "\n- ".join(lines)


def find_similar_deals_tool(customer: str = "", industry: str = "") -> str:
    cid = ""
    if customer:
        c = _resolve_customer(customer)
        if c:
            cid = c["customer_id"]
    hits = find_similar_deals(customer_id=cid, industry=industry)
    if not hits:
        return "類似案件は見つかりませんでした。"
    lines = [_deal_line(d) for d in hits]
    return "類似案件:\n- " + "\n- ".join(lines)


def retrieve_playbook_tool(query: str = "", tags=None) -> str:
    if isinstance(tags, str):
        tags = [tags]
    hits = retrieve_playbook(query=query, tags=tags or [])
    if not hits:
        return "該当するプレイブックがありません。route_to_expert の利用を検討してください。"
    lines = []
    for e in hits:
        entry_id = e.get("entry_id", "Unknown")
        lines.append(f"[{'/'.join(e['situation_tags'])}] {e['text']}(出典: Playbook {entry_id})")
    return "プレイブック:\n- " + "\n- ".join(lines)


def lookup_customer_environment(customer: str = "") -> str:
    c = _resolve_customer(customer)
    if not c:
        return f"顧客「{customer}」は見つかりません。"
    env = store.get_environment(c["customer_id"])
    if not env:
        return f"{c['name']} の環境情報は未登録です。"
    return (f"{c['name']} の環境: PC={env['pc']} / OS={env['os']} / "
            f"ネットワーク={env['network']} / 備考: {env['notes']}")


def get_product_info(product: str = "") -> str:
    p = store.get_product(product.upper()) if product else None
    if not p:
        p = next((x for x in store.all_products()
                  if product and product in x["product_name"]), None)
    if not p:
        names = ", ".join(x["product_name"] for x in store.all_products())
        return f"製品「{product}」は見つかりません。取扱: {names}"
    return (f"{p['product_name']} ({p['product_code']} / {p['manufacturer_model_number']}) "
            f"— ¥{p['standard_unit_price']:,}\n"
            f"分類: {p['major']} > {p['mid']} > {p['minor']}\n"
            f"仕様: {p['specs']}\nマニュアル抜粋: {p['manual_ja']}")


def score_deal_health(deal_id: str = "") -> str:
    d = store.get_deal(deal_id)
    if not d:
        return f"案件 {deal_id} は見つかりません。"
    acts = store.activities_for_deal(deal_id)
    res = score_deal(d, acts)
    emoji = {"red": "🔴", "yellow": "🟡", "green": "🟢"}[res.band]
    reasons = res.top_reasons(3)
    body = "／".join(reasons) if reasons else "目立ったリスク信号なし"
    return f"{emoji} {res.band}(リスク{res.score}/100): {body}"


def draft_daily_report(activity: str = "", deal_id: str = "") -> str:
    deal = store.get_deal(deal_id) if deal_id else None
    cust = store.customer_name(deal["customer_id"]) if deal else "(顧客未指定)"
    rank = deal["order_rank"] if deal else "-"
    next_action = "次回アクションを記入してください"
    if deal:
        res = score_deal(deal, store.activities_for_deal(deal_id))
        if res.band == "red":
            next_action = "健全度が赤。上長同席での再提案を打診"
    return ("【日報ドラフト】\n"
            f"顧客: {cust}\n"
            f"案件: {deal_id or '-'} / 受注ランク: {rank}\n"
            f"活動内容: {activity}\n"
            f"次アクション: {next_action}")


def review_sales_note(note: str = "", deal_id: str = "") -> str:
    """Bridge to the Sales Review Coach (a separate, friend-owned experiment under
    senpai.coach). Kept here only so the coach's own tests can reach it; it is NOT
    part of our chat tool surface. The coach is imported lazily so our pipeline's
    import graph never depends on it."""
    if not (note or "").strip():
        return "レビューするメモ・日報の本文を入力してください。"
    from senpai.coach.review import format_review, review_note   # lazy: keep us decoupled
    deal = store.get_deal(deal_id) if deal_id else None
    notes = store.notes_for_deal(deal_id) if deal else None
    report = store.report_for_deal(deal_id) if deal else None
    review = review_note(note, deal=deal, notes=notes, report=report)
    return format_review(review)


def route_to_expert(question: str = "", tags=None) -> str:
    if isinstance(tags, str):
        tags = [tags]
    tags = tags or []
    experts = [r for r in store.all_reps() if r["role"] in ("senior", "expert")]
    best, best_score = None, -1
    for r in experts:
        score = sum(1 for t in tags
                    if any(t in s or s in t for s in r["specialty_tags"]))
        score += sum(1 for s in r["specialty_tags"] if question and s in question)
        if r["is_top_performer"]:
            score += 0.5
        if score > best_score:
            best, best_score = r, score
    if not best:
        return "適切な担当が見つかりませんでした。"
    return (f"エキスパート紹介: {best['name']}({'/'.join(best['specialty_tags'])})\n"
            f"紹介メッセージ案: 「{best['name']}さん、{question} の件でご相談です。"
            "お手すきの際にご助言いただけますか。」")


def summarize_reports(rep_id: str = "") -> str:
    if not store.daily_reports_for_rep(rep_id):
        return f"担当 {rep_id} のレポートはありません。"
    scored = _score_open_deals(rep_id)
    lines = [f"{store.rep_name(rep_id)} のオープン案件 {len(scored)}件の要約:"]
    flagged = 0
    for d, _res, flags in scored:
        if flags:
            flagged += 1
            msgs = "／".join(f.message for f in flags[:2])
            lines.append(f"⚠ {d['deal_id']} {store.customer_name(d['customer_id'])}: {msgs}")
    lines.append(f"信頼性フラグの立った案件: {flagged}件")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Manager-facing analytics tools (all grounded in the deterministic engine)
# ---------------------------------------------------------------------------
_BAND_EMOJI = {"red": "🔴", "yellow": "🟡", "green": "🟢"}


def morning_briefing(rep_id: str = "", limit: int = 10) -> str:
    """The rep's prioritized next-best-action worklist for today (or the whole
    team if no rep). Thin wrapper over senpai.briefing."""
    from senpai.briefing import format_briefing
    from senpai.briefing import morning_briefing as _briefing
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    items = _briefing(rep_id=rep_id, limit=limit)
    return format_briefing(items, rep_id=rep_id)


def list_at_risk_deals(rep_id: str = "", band: str = "", limit: int = 10) -> str:
    """At-risk open deals across the team (or one rep), worst first. Defaults to
    red; pass band='yellow' (includes red+yellow) to widen."""
    scored = _score_open_deals(rep_id)
    if band == "yellow":
        keep = {"red", "yellow"}
    elif band in ("red", "green"):
        keep = {band}
    else:
        keep = {"red"}
    rows = sorted((t for t in scored if t[1].band in keep),
                  key=lambda t: t[1].score, reverse=True)
    if not rows:
        return "該当する要注意案件はありません。"
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    lines = []
    for d, res, _flags in rows[:limit]:
        reason = (res.top_reasons(1) or ["—"])[0]
        lines.append(f"{_BAND_EMOJI[res.band]} {d['deal_id']} "
                     f"{store.customer_name(d['customer_id'])} / 担当{store.rep_name(store.deal_rep_id(d))} / "
                     f"リスク{res.score} / {reason}")
    head = f"要注意案件 {len(rows)}件中 上位{min(limit, len(rows))}件:"
    return head + "\n- " + "\n- ".join(lines)


def team_pipeline_overview(rep_id: str = "") -> str:
    """Team pipeline at a glance: counts, ¥, stage spread, health split, flags."""
    scored = _score_open_deals(rep_id)
    if not scored:
        return "オープン案件がありません。"
    total = len(scored)
    pipeline = sum(d.get("total_order_amount", 0) for d, _, _ in scored)
    by_band = {"red": 0, "yellow": 0, "green": 0}
    by_rank: dict[str, int] = {}
    flagged = 0
    for d, res, flags in scored:
        by_band[res.band] += 1
        by_rank[d["order_rank"]] = by_rank.get(d["order_rank"], 0) + 1
        if flags:
            flagged += 1
    rank_str = "、".join(f"{r}:{n}" for r, n in sorted(by_rank.items()))
    scope = f"{store.rep_name(rep_id)} の" if rep_id else "チーム全体の"
    return (f"{scope}パイプライン概況:\n"
            f"- オープン案件: {total}件 / 想定金額: ¥{pipeline:,}\n"
            f"- 健全度: 🔴{by_band['red']} / 🟡{by_band['yellow']} / 🟢{by_band['green']}\n"
            f"- ランク別: {rank_str}\n"
            f"- 信頼性フラグの立った案件: {flagged}件")


def team_report_digest() -> str:
    """All reps' open deals digested into one manager view: flagged deals grouped
    by rep, worst first."""
    scored = _score_open_deals()
    by_rep: dict[str, list] = {}
    for d, res, flags in scored:
        if flags:
            by_rep.setdefault(store.deal_rep_id(d), []).append((d, res, flags))
    if not by_rep:
        return "信頼性フラグの立った案件はありません。チーム全体が健全です。"
    order = sorted(by_rep.items(), key=lambda kv: len(kv[1]), reverse=True)
    lines = [f"全担当の日報ダイジェスト（要注意 {sum(len(v) for v in by_rep.values())}件）:"]
    for rep_id, items in order:
        lines.append(f"\n【{store.rep_name(rep_id)}】フラグ{len(items)}件")
        for d, _res, flags in sorted(items, key=lambda t: t[1].score, reverse=True)[:5]:
            msg = (flags[0].message if flags else "—")
            lines.append(f"  ⚠ {d['deal_id']} {store.customer_name(d['customer_id'])}: {msg}")
    return "\n".join(lines)


def rep_coaching_focus() -> str:
    """Per-rep rollup so a manager sees where to spend coaching time."""
    scored = _score_open_deals()
    agg: dict[str, dict] = {}
    for d, res, flags in scored:
        a = agg.setdefault(store.deal_rep_id(d), {"deals": 0, "risk": 0, "red": 0, "flagged": 0})
        a["deals"] += 1
        a["risk"] += res.score
        if res.band == "red":
            a["red"] += 1
        if flags:
            a["flagged"] += 1
    if not agg:
        return "オープン案件がありません。"
    rows = sorted(agg.items(), key=lambda kv: (kv[1]["red"], kv[1]["flagged"]), reverse=True)
    lines = ["コーチング優先度（要注意の多い担当順）:"]
    for rep_id, a in rows:
        avg = round(a["risk"] / a["deals"]) if a["deals"] else 0
        lines.append(f"- {store.rep_name(rep_id)}: 案件{a['deals']} / "
                     f"🔴{a['red']} / フラグ{a['flagged']} / 平均リスク{avg}")
    return "\n".join(lines)


def draft_message(to: str = "", about: str = "", deal_id: str = "",
                  purpose: str = "") -> str:
    """Draft a short, editable Japanese message (rep nudge or client follow-up).
    Pulls deal context when deal_id is given. Never sends — human stays in the loop."""
    ctx = ""
    if deal_id:
        d = store.get_deal(deal_id)
        if d:
            res = score_deal(d, store.activities_for_deal(deal_id))
            ctx = (f"（{deal_id} {store.customer_name(d['customer_id'])} / {d['order_rank']} / "
                   f"健全度{_BAND_EMOJI[res.band]}{res.band}）")
    topic = about or purpose or "案件の状況確認"
    recipient = to or "担当者"
    body = (f"{recipient} 様\n\n"
            f"お疲れさまです。{topic} の件、現状を共有いただけますか。{ctx}\n"
            "次回の意思決定事項と完了予定日のすり合わせができればと思います。\n"
            "よろしくお願いいたします。")
    return f"【メッセージ下書き（送信はされません・編集してください）】\n{body}"


_FY_CONTEXT = {
    "q4": "1〜3月は年度末。予算消化の最後の好機。クロージングを強く。",
    "q1": "4〜6月は新年度。新規予算が付く時期。早期の種まきを。",
    "q2": "7〜9月は中間期。下期予算の検討が始まる。提案の仕込みを。",
    "q3": "10〜12月は下期序盤。年度末に向け案件を積み上げる時期。",
}


def get_seasonal_context(month: int = 0) -> str:
    m = int(month) if month else config.today().month
    if m in (1, 2, 3):
        key, label = "q4", "第4四半期(年度末)"
    elif m in (4, 5, 6):
        key, label = "q1", "第1四半期"
    elif m in (7, 8, 9):
        key, label = "q2", "第2四半期"
    else:
        key, label = "q3", "第3四半期"
    return f"{m}月 — {label}: {_FY_CONTEXT[key]}"


# ---------------------------------------------------------------------------
# Sales demo tools — ported from demo/tools.py, re-grounded on the real store
# ---------------------------------------------------------------------------
def _resolve_product(product: str) -> dict | None:
    """Resolve a product by code (e.g. 'MFP30') or a (fuzzy) name match."""
    if not product:
        return None
    p = store.get_product(str(product).strip().upper())
    if p:
        return p
    pl = str(product).strip().lower()
    for x in store.all_products():
        if pl == x["product_name"].lower():
            return x
    for x in store.all_products():
        if pl in x["product_name"].lower() or x["product_name"].lower() in pl:
            return x
    return None


def search_products(category: str = "", max_price: float = None,
                    min_price: float = None, keyword: str = "") -> str:
    """Search the real Otsuka product catalog by category / price band / keyword."""
    hits = []
    for p in store.all_products():
        cat = f"{p.get('major', '')} {p.get('mid', '')} {p.get('minor', '')}"
        if category and category.strip() not in cat:
            continue
        price = p.get("standard_unit_price", 0)
        if max_price is not None and price > float(max_price):
            continue
        if min_price is not None and price < float(min_price):
            continue
        if keyword:
            k = keyword.strip()
            if k not in p["product_name"] and k not in p.get("specs", ""):
                continue
        hits.append(p)
    if not hits:
        return "条件に合う製品は見つかりませんでした。"
    hits.sort(key=lambda p: p.get("standard_unit_price", 0))
    lines = [f"{p['product_code']} — {p['product_name']} — ¥{p['standard_unit_price']:,}"
             f"（{p.get('mid', p.get('major', ''))}）" for p in hits]
    return f"該当製品 {len(hits)}件:\n- " + "\n- ".join(lines)


def create_quote(items, discount_pct: float = 0, customer: str = "",
                 tax_pct: float = 10) -> str:
    """Build a price quote (estimate) from real catalog products: line totals,
    optional discount, tax, grand total. Never persisted — the rep edits/sends."""
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except json.JSONDecodeError:
            return "[error] 見積項目を解析できませんでした。"
    if not isinstance(items, list) or not items:
        return "[error] 見積する製品がありません。"
    lines, skipped, subtotal = [], [], 0
    for it in items:
        if not isinstance(it, dict):
            continue
        p = _resolve_product(it.get("sku") or it.get("name") or it.get("product") or "")
        qty = int(it.get("qty", 1) or 1)
        if not p:
            skipped.append(str(it.get("sku") or it.get("name") or it.get("product")))
            continue
        price = p.get("standard_unit_price", 0)
        line_total = price * qty
        subtotal += line_total
        lines.append(f"  {qty} × {p['product_name']} @ ¥{price:,} = ¥{line_total:,}")
    if not lines:
        return f"[error] 指定された製品が見つかりませんでした: {', '.join(skipped)}"
    discount_pct = float(discount_pct or 0)
    tax_pct = float(tax_pct if tax_pct is not None else 10)
    discount = round(subtotal * discount_pct / 100)
    taxed_base = subtotal - discount
    tax = round(taxed_base * tax_pct / 100)
    total = taxed_base + tax
    header = f"見積書（{customer}様）" if customer else "見積書"
    out = [f"【{header}・ドラフト／送信はされません】", "明細:", *lines,
           f"小計: ¥{subtotal:,}"]
    if discount:
        out.append(f"値引 ({discount_pct:g}%): -¥{discount:,}")
    out.append(f"消費税 ({tax_pct:g}%): ¥{tax:,}")
    out.append(f"合計: ¥{total:,}")
    if skipped:
        out.append(f"（未登録のため除外: {', '.join(skipped)}）")
    return "\n".join(out)


def schedule_meeting(title: str = "", date: str = "", start_time: str = "",
                     duration_hours: float = 1, attendees=None,
                     description: str = "", confirm: bool = False) -> str:
    """Two-step booking so the rep stays in the loop. With confirm=false (default)
    it only returns a draft — nothing is scheduled. With confirm=true it books a
    real event via the Google Calendar API; if calendar auth/creds are missing it
    degrades to a simulated confirmation so the workspace never breaks."""
    if not (title and date and start_time):
        return "[error] title / date / start_time を指定してください。"
    if isinstance(attendees, str):
        attendees = [a.strip() for a in attendees.split(",") if a.strip()]
    attendees = attendees or []
    who = f" / 参加者{len(attendees)}名" if attendees else ""
    dur = float(duration_hours or 1)
    agenda = f"\n議題: {description}" if description else ""

    if not confirm:
        return (f"【予定ドラフト（未確定）】「{title}」{date} {start_time} JST "
                f"／{dur:g}時間{who}{agenda}"
                "\n確定する場合は confirm=true で再度依頼してください。")

    try:
        from senpai.tools import gcal  # lazy: a missing google lib must not break import
        ok, link = gcal.create_event(
            title=title, date=date, start_time=start_time, duration_hours=dur,
            attendees=attendees, description=description,
        )
        if ok:
            tail = f"\n{link}" if link else ""
            return (f"【予定を登録しました】「{title}」{date} {start_time} JST "
                    f"／{dur:g}時間{who}{agenda}{tail}")
    except Exception:  # noqa: BLE001 — fall back to a simulated confirmation
        pass
    return (f"【予定を登録しました（シミュレーション）】「{title}」{date} {start_time} JST "
            f"／{dur:g}時間{who}{agenda}")


def send_email(to: str = "", subject: str = "", body: str = "") -> str:
    """Prepare an email draft. Never actually sends — human stays in the loop."""
    if not to:
        return "[error] 宛先 (to) を指定してください。"
    return (f"【メール下書き（送信はされません）】\n宛先: {to}\n件名: {subject}\n\n{body}")


_CALENDAR_CANNED = [
    "10:00 朝礼／案件確認",
    "13:00 顧客訪問（デモ）",
    "16:30 提案資料の作成",
]


def get_calendar(day: str = "today") -> str:
    """Today's (or a given day's) schedule. Simulated demo data."""
    d = config.today().isoformat() if str(day).lower() in ("today", "") else day
    return f"{d} の予定:\n- " + "\n- ".join(_CALENDAR_CANNED)


def search_knowledge(query: str = "", tags=None, limit: int = 4) -> str:
    """RAG over the validated knowledge corpus (principles + approved coaching
    items + playbook). Returns short, attributed/cited snippets to ground answers."""
    if isinstance(tags, str):
        tags = [tags]
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 4
    hits = _search_knowledge(query=query, tags=tags or [], limit=limit)
    from senpai.retrieval import trace as _trace
    _trace.record(
        "knowledge_keyword", scope="all", query=query,  # corpus is general, not per-account
        items=[{"id": kind, "customer": None, "score": int(score), "text": text}
               for score, kind, text in hits])
    if not hits:
        return ("該当する社内ナレッジが見つかりませんでした。"
                "route_to_expert の利用を検討してください。")
    lines = [f"[{kind}] {text}" for _score, kind, text in hits]
    return "社内ナレッジ:\n- " + "\n- ".join(lines)


def search_notes(query: str = "", limit: int = 5, customer: str = "") -> str:
    """Semantic search over the field's daily reports (日報). Finds activities that
    *mean* the same thing as the query, not just share keywords — e.g. a search for
    『予算が理由で停滞』 surfaces 「コスト面で渋い」notes too. Returns dated, attributed
    snippets with their deal/customer + retrieval score so the rep can drill in.

    Grounding P0 — account scoping: pass `customer` (the account in focus) to
    restrict the search to that customer's own notes (the default for any
    account-specific question). If `customer` is omitted, we still try to detect a
    customer named in the query and scope to it; only when no account can be
    resolved do we fall back to a cross-account search (clearly labelled). A scoped
    search never widens to other customers."""
    from senpai.retrieval.semantic import semantic_search
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 5
    # Clamp the result count: the notes are the bulk of the synthesis prompt AND of
    # what the model then quotes back, so an over-fetch (the model sometimes asks for
    # 10+) dominates Assistant latency at ~9 tok/s. The top semantically-ranked notes
    # carry the signal; the tail just lengthens the answer. Keep it tight.
    limit = max(1, min(limit, 6))

    # Resolve the account in focus: explicit arg first, then a customer named in the
    # query; None ⇒ no account resolved ⇒ cross-account fallback (preserves behavior).
    cust = None
    if customer:
        cust = store.resolve_customer(customer) or store.get_customer(customer)
    if not cust and query:
        cust = store.match_customer_in_text(query)
    cid = cust.get("customer_id") if cust else None

    from senpai.retrieval import semantic as _sem
    from senpai.retrieval import trace as _trace
    hits = semantic_search(query, corpus="activities", limit=limit, customer_id=cid)

    # Observability: record exactly what was retrieved (Retrieval Explorer spine).
    _trace.record(
        "notes_semantic",
        scope=(f"account:{cid}" if cid else "all"),
        query=query, mode=_sem.mode(),
        customer=(cust.get("name") if cust else None),
        items=[{"id": f"{h.get('deal_id', '-')}@{h.get('activity_date', '?')}",
                "customer_id": h.get("customer_id", ""),
                "customer": store.customer_name(h.get("customer_id", "")) or h.get("customer_id", ""),
                "score": round(float(h.get("score", 0)), 4),
                "text": h.get("snippet", "")} for h in hits])

    if not hits:
        if cid:
            return f"{cust.get('name', cid)} の日報で該当するものは見つかりませんでした。"
        return "該当する日報は見つかりませんでした。"

    scope = (f"（{cust.get('name')} に限定）" if cid
             else "（全社横断・特定顧客に絞れず）")
    lines = []
    for h in hits:
        cn = store.customer_name(h.get("customer_id", "")) or h.get("customer_id", "")
        lines.append(f"{h.get('activity_date', '?')}・{h.get('deal_id', '-')}（{cn}）"
                     f"[score {h.get('score', 0):.3f}]: {h.get('snippet', '')}")
    return f"関連する日報{scope}:\n- " + "\n- ".join(lines)


def query_graph(intent: str = "reps_who_win", category: str = "", industry: str = "",
                after_activity_type: str = "", customer: str = "", deal_id: str = "",
                entity_a: str = "", entity_b: str = "", limit: int = 8) -> str:
    """Multi-hop questions over the customer→deal→activity→rep→product graph.
    intent: 'reps_who_win' | 'account' | 'connections' | 'similar'."""
    from senpai.graph import query as gq
    from senpai.retrieval import trace as _trace
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 8
    # account intent is customer-scoped; the relational intents are cross-account
    # by design (and are research/manager-only per the governance table).
    _trace.record("graph", scope=(f"account:{customer}" if intent == "account" and customer else "all"),
                  intent=intent, query=" ".join(x for x in [category, industry, customer, deal_id] if x))

    if intent == "reps_who_win":
        rows = gq.reps_who_win(category=category, industry=industry,
                               after_activity_type=after_activity_type)[:limit]
        if not rows:
            return "条件に合う実績が見つかりませんでした。"
        cond = "／".join(x for x in [category, industry, after_activity_type] if x) or "全体"
        lines = [f"{r['rep_name']}（{r['rep_id']}）勝率{r['win_rate']*100:.0f}% "
                 f"（{r['won']}/{r['closed']}件）例: {', '.join(r['example_deal_ids'][:3])}"
                 for r in rows]
        return f"勝ちパターン分析【{cond}】:\n- " + "\n- ".join(lines)

    if intent == "account":
        g = gq.account_graph(customer)
        if g.get("status") != "found":
            return f"顧客「{customer}」は見つかりません。"
        reps = "、".join(r["name"] for r in g["reps"]) or "—"
        prods = "、".join(p["name"] for p in g["products"]) or "—"
        deals = "\n  ".join(f"{d['deal_id']} {d['name']}（{d['rank']}/{d['outcome']}・"
                            f"¥{d['amount']:,}）" for d in g["deals"][:limit]) or "—"
        return (f"{g['name']}（{g['industry']}/{g['size']}）の関係図:\n"
                f"担当: {reps}\n製品: {prods}\n案件:\n  {deals}")

    if intent == "connections":
        r = gq.connections(entity_a, entity_b)
        if r.get("status") != "found":
            return f"「{entity_a}」と「{entity_b}」を結ぶ経路は見つかりませんでした。"
        path = " → ".join(f"{n['label']}[{n['kind']}]" for n in r["path"])
        return f"{r['hops']}ホップの経路: {path}"

    if intent == "similar":
        rows = gq.similar_by_graph(deal_id, limit=limit)
        if not rows:
            return f"{deal_id} に関連する案件は見つかりませんでした。"
        lines = [f"{r['deal_id']} {r['name']}（{r['outcome']}・関連度{r['score']}）" for r in rows]
        return f"{deal_id} と関係の深い案件:\n- " + "\n- ".join(lines)

    return f"[error] 未知のintent: {intent}（reps_who_win/account/connections/similar）"


# ---------------------------------------------------------------------------
# Document generation — the chatbot's "do stuff" tools (PPTX / DOCX)
# ---------------------------------------------------------------------------
# All four are two-step-confirm gated like schedule_meeting: confirm=false returns a
# preview (no file written); confirm=true builds the file under config.GENERATED_DIR,
# registers it for download, and returns a short confirmation. senpai.documents is
# imported lazily so a missing python-pptx/docx can never break tool import.
import hashlib as _hashlib

# Authored specs for the general tools, cached between the preview and confirm calls
# (keyed by request) so confirm=true reuses the same content the rep just reviewed.
_GEN_SPEC_CACHE: dict[str, dict] = {}


def _yen(n) -> str:
    try:
        return f"¥{int(n):,}"
    except (TypeError, ValueError):
        return "¥0"


def _deck_outline(slides: list[dict]) -> str:
    """Render a deck's headings + subheadings for the success message, so the rep
    sees the structure that was built (titles as headings, bullets/subtitle as
    sub-items) even though the file is generated directly."""
    lines: list[str] = []
    for i, s in enumerate(slides):
        lines.append(f"  {i + 1}. {s.get('title', '')}")
        subs = [str(b) for b in (s.get("bullets") or []) if str(b).strip()]
        if not subs and s.get("subtitle"):
            subs = [ln for ln in str(s["subtitle"]).splitlines() if ln.strip()]
        lines.extend(f"     - {b}" for b in subs)
    return "\n".join(lines)


def generate_proposal(deal_id: str = "", lang: str = "ja", confirm: bool = False) -> str:
    """4-slide PPTX sales proposal grounded in a deal's SPR data. Builds directly
    (no confirmation step) — the call commits the file in one round."""
    from senpai.documents import proposal, registry
    from senpai.documents.context import build_document_context
    if not deal_id:
        return "[error] deal_id を指定してください。"
    ctx = build_document_context(deal_id)
    if ctx is None:
        return f"案件 {deal_id} は見つかりません。"
    res = proposal.generate(deal_id, lang=lang)
    if res is None:
        return f"案件 {deal_id} は見つかりません。"
    path, _ctx, spec = res
    rec = registry.register("proposal", path, deal_id=deal_id)
    slides = spec.get("slides", [])
    outline = _deck_outline(slides)
    return (f"提案書(PPTX・{len(slides)}スライド)を生成しました: {rec['filename']}（{ctx.customer}様）。\n"
            f"構成:\n{outline}")


def generate_ringisho(deal_id: str = "", confirm: bool = False) -> str:
    """Formal 稟議書 DOCX (customer IT-manager -> CEO) grounded in deal data. Two-step."""
    from senpai.documents import registry, ringisho
    from senpai.documents.context import build_document_context
    if not deal_id:
        return "[error] deal_id を指定してください。"
    ctx = build_document_context(deal_id)
    if ctx is None:
        return f"案件 {deal_id} は見つかりません。"
    if not confirm:
        pv = ctx.to_preview()
        pains = "、".join(pv["pain_points"]) or "（SPRに課題記録なし）"
        deal_label = (ctx.deal_name or ctx.customer) + (f"（{ctx.product_category}）" if ctx.product_category else "")
        return (f"【プレビュー】{ctx.customer}様 情報システム部の稟議書(DOCX)\n"
                f"- 対象案件: {ctx.deal_id} {deal_label}\n"
                f"- 背景・課題: {pains}\n"
                f"- 投資額: {_yen(pv['investment'])}\n"
                "- 構成: 背景・課題 / 提案内容 / 投資額と効果 / 結論・承認依頼\n"
                "【システム指示】プレビューが生成されました。これ以上ツールを呼び出さず、このプレビュー内容をユーザーに提示し、作成を実行してよいか確認してください。ユーザーが同意した場合のみ、次のターンで confirm=true に設定して再度呼び出してください。")
    res = ringisho.generate(deal_id)
    if res is None:
        return f"案件 {deal_id} は見つかりません。"
    path, _ctx = res
    rec = registry.register("ringisho", path, deal_id=deal_id)
    return f"稟議書(DOCX)を生成しました: {rec['filename']}（{ctx.customer}様）。"


# Conversation-grounding budget. RECENT_FLOOR snippets are always kept (immediate
# context — the current request and the tool result that just landed); the remaining
# slots up to MAX_SNIPPETS are filled by relevance to the request, not recency.
_CONVO_BUDGET = 4000
_CONVO_MAX_SNIPPETS = 8
_CONVO_RECENT_FLOOR = 3


def _truncate_on_boundary(text: str, limit: int) -> str:
    """Trim `text` to <= `limit` chars, cutting at the nearest natural boundary
    (snippet break → paragraph → line → sentence → word) instead of mid-string, so a
    fact — a company name, a quote figure — is never severed in half. A blind
    `text[:limit]` can drop the second half of '村田印刷' or '¥1,200,000'. Only honors
    a boundary that still keeps most of the budget; adds an elision marker."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    for sep in ("\n---\n", "\n\n", "\n", "。", ". ", "、", " "):
        cut = head.rfind(sep)
        if cut >= limit * 0.6:   # a break too early would waste most of the budget
            return head[:cut].rstrip() + " …"
    return head.rstrip() + " …"


# Latin/number words and CJK character bigrams. A script-agnostic stand-in for word
# segmentation so relevance scoring works WITHOUT a morphological analyzer (janome is
# only an optional dep, and its whitespace fallback can't split Japanese, which has no
# spaces). Bigrams give '村田印刷' the shared keys 村田/田印/印刷 across query & snippet.
_LATIN_NUM_RE = re.compile(r"[a-z0-9](?:[a-z0-9,.]*[a-z0-9])?")
_CJK_RUN_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿]+")


def _relevance_tokens(text: str) -> set[str]:
    text = (text or "").lower()
    toks = set(_LATIN_NUM_RE.findall(text))
    for run in _CJK_RUN_RE.findall(text):
        if len(run) == 1:
            toks.add(run)
        else:
            toks.update(run[i:i + 2] for i in range(len(run) - 1))
    return toks


def _snippet_relevance(query_tokens: set[str], text: str) -> float:
    """Relevance of a snippet to the current request: fraction of the request's
    content tokens it covers. 0.0 when there is no query signal or no overlap."""
    if not query_tokens:
        return 0.0
    toks = _relevance_tokens(text)
    if not toks:
        return 0.0
    return len(query_tokens & toks) / len(query_tokens)


def _conversation_grounding(prompt: str) -> str:
    """Context already established in this session — prior tool results (e.g. a
    workspace file we read) and assistant answers — so a doc that references 'the
    company/quote we just discussed' grounds on it instead of being invented. Reads
    the live conversation the chat loop publishes (senpai.tools.conversation).

    Kept compact: the doc author only needs the entity in focus and the facts around
    it, not the whole transcript. System messages and failed/empty tool results are
    dropped; the current request is included so intent is explicit.

    Selection is relevance-ranked, not just the tail — recency alone drops the entity
    in focus once a few turns intervene (a side question, extra tool calls), which is
    exactly the ungrounded-deck regression this grounding exists to prevent. The most
    recent RECENT_FLOOR snippets are always kept (immediate context); the rest of the
    budget goes to the OLDER snippets that best match the request. With no query
    signal it degrades to pure recency (the prior behavior)."""
    from senpai.tools import conversation as _conv
    convo = _conv.conversation()
    if not convo:
        return ""
    # (position, formatted-text), dropping system + failed/empty tool results.
    snippets: list[tuple[int, str]] = []
    for i, m in enumerate(convo):
        role, content = m.get("role"), m.get("content")
        if role == "system" or not isinstance(content, str) or not content.strip():
            continue
        if role == "tool":
            if content.startswith("[error]") or "見つかりません" in content:
                continue
            snippets.append((i, content.strip()))
        elif role == "assistant":
            snippets.append((i, content.strip()))
        elif role == "user":
            snippets.append((i, f"（依頼）{content.strip()}"))
    if not snippets:
        return ""

    query_tokens = _relevance_tokens(prompt)
    recent = {i for i, _ in snippets[-_CONVO_RECENT_FLOOR:]}
    older = [(i, t) for i, t in snippets if i not in recent]
    # Score each older snippet once; rank by relevance, then recency for ties.
    scored = sorted(
        ((_snippet_relevance(query_tokens, t), i, t) for i, t in older),
        key=lambda s: (s[0], s[1]), reverse=True)
    budget_n = max(0, _CONVO_MAX_SNIPPETS - len(recent))
    # Keep only older snippets that actually match the request; with no query signal
    # (query_tokens empty) fall back to recency so we never return nothing.
    keep_older = [(i, t) for score, i, t in scored[:budget_n]
                  if score > 0 or not query_tokens]
    chosen = sorted(
        [(i, t) for i, t in snippets if i in recent] + keep_older,
        key=lambda it: it[0])
    joined = "\n---\n".join(t for _, t in chosen)
    return _truncate_on_boundary(joined, _CONVO_BUDGET)


def _workspace_grounding(query: str) -> str:
    """Relevant LOCAL documents for `query`, or '' when nothing genuinely matched.
    Gated on a real filename/path match (score > 0), not the finder's recency
    fallback, so an unrelated deck ('best gaming laptops') isn't padded with random
    files. Read-only, sandboxed — the entity may live only in the rep's own files."""
    if not (query or "").strip():
        return ""
    try:
        from senpai.workspace import workspace_evidence
        from senpai.workspace.gather import _format
        res = workspace_evidence(query, limit=3)
    except Exception:  # noqa: BLE001 — grounding is best-effort
        return ""
    if not res.get("documents"):
        return ""
    if not any((f.get("score") or 0) > 0 for f in res.get("found", [])):
        return ""
    return _format(res)


def _gather_grounding(prompt: str, customer: str, use_web: bool) -> str:
    """Best-effort context for the general doc tools, gathered in priority order so
    the deck grounds on what the rep is actually referencing:
      1. the live conversation — a company/quote/deal discussed earlier this session
      2. the rep's own local documents (workspace) that match the topic
      3. internal CRM records for a named customer
      4. a live web_search (external/factual topics)
    Any layer may be empty (then the model uses general knowledge). Conversation and
    workspace come first because they carry the specific entity in focus — that is
    what stops a 'proposal for <company we just read from a file>' from being
    hallucinated as a generic deck under the wrong company name."""
    parts: list[str] = []

    convo_ctx = _conversation_grounding(prompt)
    if convo_ctx:
        parts.append(f"【これまでの会話・確定済みの文脈】\n{convo_ctx}")

    ws = _workspace_grounding(prompt or customer)
    if ws:
        parts.append(f"【ローカル文書（あなたのファイル）】\n{ws}")

    # CRM, in order of trust:
    #   1. an explicit customer arg — authoritative.
    #   2. the entity the conversation already RESOLVED (SessionFocus) — also
    #      authoritative: it comes from ids real tool results emitted (a deal we
    #      looked up, a customer we queried), so 'that company we discussed' is a
    #      lookup, not a re-inference. A deal in focus grounds on that specific deal.
    #   3. as a LAST resort, a fuzzy name match on the prompt — but only when the
    #      workspace didn't already pin the entity, since a local-file company must
    #      not pull an unrelated CRM customer (the wrong-company-name bug).
    cust = _resolve_customer(customer) if customer else None
    crm = ""
    if cust:
        crm = query_spr(customer=cust["customer_id"])
    else:
        focus = session_focus()
        if focus.deal_id:
            crm = query_spr(deal_id=focus.deal_id)
        elif focus.customer_id:
            crm = query_spr(customer=focus.customer_id)
        elif not ws:
            fuzzy = store.match_customer_in_text(prompt)
            if fuzzy:
                crm = query_spr(customer=fuzzy["customer_id"])
    if crm:
        parts.append(f"【社内データ】\n{crm}")

    if use_web:
        try:
            parts.append(f"【Web検索】\n{web_search(query=prompt)}")
        except Exception:  # noqa: BLE001 — grounding is best-effort
            pass
    return "\n\n".join(p for p in parts if p)


# External/factual cues in a free-prompt deck/doc — the topics that go stale in a
# model's weights (products, prices, "best-of" picks, current models, comparisons).
# When present, a general deck is grounded in a live web_search unless the caller
# says otherwise. Internal decks (a customer is named) ground in records instead.
_WEB_SIGNAL_RE = re.compile(
    r"best|top|latest|newest|current|cheap|price|budget|under|vs\b|versus|compare|"
    r"comparison|review|ranking|recommend|spec|market|trend|news|deal|20(2[3-9]|[3-9]\d)|"
    r"おすすめ|比較|最新|価格|相場|予算|以内|ランキング|レビュー|選び方|市場|"
    r"トレンド|ニュース|スペック|円",
    re.IGNORECASE,
)


def _auto_web(prompt: str) -> bool:
    """True when a free-prompt deck/doc should be web-grounded by default: the topic
    reads as external/factual/current, so the model's own knowledge is likely stale."""
    return bool(_WEB_SIGNAL_RE.search(prompt or ""))


def _resolve_use_web(use_web, prompt: str, customer: str) -> bool:
    """Decide grounding. Explicit True/False from the caller wins. When unspecified
    (None), auto-enable web for external/factual prompts, but not when the deck is
    scoped to a customer (that grounds in internal records instead)."""
    if use_web is not None:
        return bool(use_web)
    if customer:
        return False
    return _auto_web(prompt)


def _gen_key(kind: str, prompt: str, customer: str, use_web: bool, grounding: str = "") -> str:
    return _hashlib.md5(
        f"{kind}|{prompt}|{customer}|{use_web}|{grounding}".encode()).hexdigest()


def _author_spec(kind: str, prompt: str, customer: str, use_web: bool, lang: str):
    """Author (or reuse cached) a deck/doc spec for the general tools. None if the
    model is unavailable. The cache key includes the gathered grounding so the same
    prompt in a different conversation (different entity in focus) re-authors rather
    than returning a stale, differently-grounded deck."""
    from senpai.documents import author
    grounding = _gather_grounding(prompt, customer, use_web)
    key = _gen_key(kind, prompt, customer, use_web, grounding)
    spec = _GEN_SPEC_CACHE.get(key)
    if spec is not None:
        return spec
    spec = (author.author_deck if kind == "pptx" else author.author_doc)(
        prompt, grounding=grounding, lang=lang)
    if spec is not None:
        _GEN_SPEC_CACHE[key] = spec
    return spec


def generate_pptx(prompt: str = "", title: str = "", use_web=None,
                  customer: str = "", lang: str = "ja", confirm: bool = False) -> str:
    """General-purpose PPTX from a free prompt (LLM-authored). No fixed slide count.
    Builds directly (no confirmation step) — the call commits the file in one round.
    Grounding is automatic: external/factual topics are web-grounded by default; a
    named customer grounds it in internal records. Needs the model."""
    from senpai.documents import author, registry
    from senpai.documents.render import output_path, render_pptx
    if not (prompt or "").strip():
        return "[error] プレゼンの主題(prompt)を指定してください。"
    if not author._use_llm():
        return "本機能はモデル(LLM)が必要です（SENPAI_USE_LLM=1 とモデルサーバ）。"
    spec = _author_spec("pptx", prompt, customer, _resolve_use_web(use_web, prompt, customer), lang)
    if spec is None:
        return "本機能はモデル(LLM)が必要です。現在モデルに接続できません。"
    slides = spec.get("slides", [])
    if title and slides:
        slides[0]["title"] = title
    path = output_path("pptx", title or spec.get("_title") or prompt[:30], "pptx")
    render_pptx(spec, path)
    rec = registry.register("pptx", path)
    outline = _deck_outline(slides)
    return (f"プレゼン(PPTX)を生成しました: {rec['filename']}（{len(slides)}スライド）。\n"
            f"構成:\n{outline}")


def generate_docx(prompt: str = "", title: str = "", use_web=None,
                  customer: str = "", lang: str = "ja", confirm: bool = False) -> str:
    """General-purpose DOCX from a free prompt (LLM-authored). Grounding is automatic:
    external/factual topics are web-grounded by default; a named customer grounds it
    in internal records. Needs the model."""
    from senpai.documents import author, registry
    from senpai.documents.render import output_path, render_docx
    if not (prompt or "").strip():
        return "[error] 文書の主題(prompt)を指定してください。"
    if not author._use_llm():
        return "本機能はモデル(LLM)が必要です（SENPAI_USE_LLM=1 とモデルサーバ）。"
    spec = _author_spec("docx", prompt, customer, _resolve_use_web(use_web, prompt, customer), lang)
    if spec is None:
        return "本機能はモデル(LLM)が必要です。現在モデルに接続できません。"
    sections = spec.get("sections", [])
    if not confirm:
        outline = "\n".join(f"  - {s.get('heading', '')}" for s in sections)
        return (f"【プレビュー】DOCX「{title or spec.get('_title') or prompt}」{len(sections)}セクション:\n"
                f"{outline}\n【システム指示】プレビューが生成されました。これ以上ツールを呼び出さず、このプレビュー内容をユーザーに提示し、作成を実行してよいか確認してください。ユーザーが同意した場合のみ、次のターンで confirm=true に設定して再度呼び出してください。")
    if title:
        spec["title"] = title
    path = output_path("docx", title or spec.get("_title") or prompt[:30], "docx")
    render_docx(spec, path)
    rec = registry.register("docx", path)
    return f"文書(DOCX)を生成しました: {rec['filename']}（{len(sections)}セクション）。"


# ---------------------------------------------------------------------------
# Dispatch (mirrors demo/tools.py)
# ---------------------------------------------------------------------------
def segment_intelligence(query: str = "", category: str = "", industry: str = "",
                         outcome: str = "all", limit: int = 6) -> str:
    """Aggregate/thematic answers across category×industry market segments — win
    rates, common failure modes, recommended plays — grounded in the deal-health
    engine and citing evidence deal ids. GPU-free (committed reports or in-memory
    deterministic build)."""
    from senpai.graph import communities
    from senpai.retrieval import trace as _trace
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 6
    reports = communities.select(query=query, category=category, industry=industry,
                                 outcome=outcome, limit=limit)
    _trace.record("segment_intelligence", scope="all",
                  items=[{"id": r["id"], "score": r.get("win_rate")} for r in reports],
                  query=" ".join(x for x in [query, category, industry] if x), n=len(reports))
    if not reports:
        return "該当するセグメント（カテゴリ×業界）が見つかりませんでした。"
    return "\n\n".join(communities.format_report(r) for r in reports)


def search_workspace_documents(query: str = "", limit: int = 0) -> str:
    """Find and read relevant LOCAL documents (PDF/DOCX/PPTX/XLSX/TXT/MD) from the
    sandboxed workspace, returning their text with per-file citations. Runs on the
    orchestration engine: one `find` fans out into parallel `extract` tasks. READ-ONLY.
    The chat loop's synthesis round reduces the returned documents into the answer."""
    from senpai.retrieval import trace as _trace
    from senpai.workspace import workspace_evidence
    lim = None
    try:
        lim = int(limit) if limit else None
    except (TypeError, ValueError):
        lim = None
    res = workspace_evidence(query, limit=lim)
    _trace.record("workspace", scope="local_files",
                  items=[{"id": d["rel"], "score": d.get("chars")} for d in res["documents"]],
                  query=query, n=len(res["documents"]))
    from senpai.workspace.gather import _format
    return _format(res)


def edit_workspace_document(path: str, content: str, confirm: bool = False) -> str:
    """Modifies or creates a local text document in the workspace.
    To prevent data loss, `confirm=True` must be explicitly passed to commit the write;
    otherwise, a preview is returned for the user to review.
    """
    from senpai.workspace import sandbox
    try:
        safe_p = sandbox.safe_path(path)
    except sandbox.SandboxError as e:
        return f"エラー: パスが無効または境界外です ({e})"
    
    if safe_p.suffix.lower() not in (".txt", ".md", ".json", ".csv"):
        return f"エラー: テキストファイル（.txt, .md, .json, .csv等）のみ編集可能です。指定された拡張子: {safe_p.suffix}"
    
    if not confirm:
        return (f"【ファイル編集プレビュー（保存されていません）】\n"
                f"対象: {sandbox.rel(safe_p)}\n"
                f"新しい内容:\n{content}\n\n"
                f"よろしければ確認して「保存して」と指示してください（confirm=True を指定して再実行します）。")
    
    try:
        safe_p.parent.mkdir(parents=True, exist_ok=True)
        safe_p.write_text(content, encoding="utf-8")
        from senpai.retrieval import trace as _trace
        _trace.record("workspace_edit", scope="local_files",
                      items=[{"id": sandbox.rel(safe_p), "score": len(content)}],
                      query=path, n=1)
        return f"ファイル {sandbox.rel(safe_p)} を保存しました。"
    except Exception as e:
        return f"ファイルの保存中にエラーが発生しました: {e}"


def move_workspace_document(src: str, dst: str, confirm: bool = False) -> str:
    """Move or rename a local document in the workspace.
    To prevent data loss, `confirm=True` must be explicitly passed to commit the move;
    otherwise, a preview is returned for the user to review.
    """
    from senpai.workspace import sandbox
    try:
        s = sandbox.safe_path(src)
        d = sandbox.safe_path(dst)
    except sandbox.SandboxError as e:
        return f"エラー: パスが無効または境界外です ({e})"
    
    if not s.exists():
        return f"エラー: 移動元のファイルが存在しません: {src}"
    
    if not confirm:
        return (f"【ファイル移動プレビュー（実行されていません）】\n"
                f"移動元: {sandbox.rel(s)}\n"
                f"移動先: {sandbox.rel(d)}\n\n"
                f"よろしければ確認して「移動して」と指示してください（confirm=True を指定して再実行します）。")
    
    try:
        new_path = sandbox.move_within(src, dst)
        from senpai.retrieval import trace as _trace
        _trace.record("workspace_move", scope="local_files",
                      items=[{"id": new_path, "score": 1}],
                      query=f"{src} -> {dst}", n=1)
        return f"ファイルを移動しました: {sandbox.rel(s)} -> {new_path}"
    except Exception as e:
        return f"ファイルの移動中にエラーが発生しました: {e}"


_DISPATCH = {
    "query_spr": query_spr,
    "find_deals": find_deals,
    "find_similar_deals": find_similar_deals_tool,
    "retrieve_playbook": retrieve_playbook_tool,
    "lookup_customer_environment": lookup_customer_environment,
    "get_product_info": get_product_info,
    "score_deal_health": score_deal_health,
    "review_sales_note": review_sales_note,
    "draft_daily_report": draft_daily_report,
    "route_to_expert": route_to_expert,
    "summarize_reports": summarize_reports,
    "get_seasonal_context": get_seasonal_context,
    # Manager + shared tools
    "morning_briefing": morning_briefing,
    "list_at_risk_deals": list_at_risk_deals,
    "team_pipeline_overview": team_pipeline_overview,
    "team_report_digest": team_report_digest,
    "rep_coaching_focus": rep_coaching_focus,
    "draft_message": draft_message,
    "web_search": web_search,
    "web_research": web_research,
    # Sales demo tools (ported from demo/tools.py, re-grounded on the store)
    "search_products": search_products,
    "create_quote": create_quote,
    "schedule_meeting": schedule_meeting,
    "send_email": send_email,
    "get_calendar": get_calendar,
    "search_knowledge": search_knowledge,
    "search_notes": search_notes,
    "query_graph": query_graph,
    "segment_intelligence": segment_intelligence,
    "search_workspace_documents": search_workspace_documents,
    "edit_workspace_document": edit_workspace_document,
    "move_workspace_document": move_workspace_document,
    # Document generation (the chatbot's "do stuff" tools)
    "generate_proposal": generate_proposal,
    "generate_ringisho": generate_ringisho,
    "generate_pptx": generate_pptx,
    "generate_docx": generate_docx,
}


def dispatch(name: str, arguments: dict | str) -> str:
    """Execute a tool by name with arguments (dict or JSON string). Always
    returns a string; never raises (so the chat loop can't crash)."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return f"[error] could not parse arguments for {name}: {arguments!r}"
    if not isinstance(arguments, dict):
        arguments = {}
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"[error] unknown tool: {name}"
    try:
        return str(fn(**arguments))
    except TypeError as e:
        return f"[error] bad arguments for {name}: {e}"
    except Exception as e:  # noqa: BLE001 — must never crash on a tool
        return f"[error] {name} failed: {e}"


if __name__ == "__main__":
    # Pick a deliberately dead deal so score/flags show real risk.
    for n, a in [
        ("query_spr", {"deal_id": "D001"}),
        ("query_spr", {"rep_id": "R05"}),
        ("find_deals", {"product_category": "サーバー", "size": "中規模", "outcome": "won", "limit": 5}),
        ("find_similar_deals", {"customer": "C01"}),
        ("retrieve_playbook", {"query": "お客様が決定を先延ばし", "tags": ["決定先延ばし"]}),
        ("search_notes", {"query": "予算が厳しく決裁が止まっている", "limit": 3}),
        ("lookup_customer_environment", {"customer": "C01"}),
        ("get_product_info", {"product": "MFP30"}),
        ("score_deal_health", {"deal_id": "D001"}),
        ("review_sales_note", {"note": "お客様は社内で検討してから連絡するとのこと。"}),
        ("draft_daily_report", {"activity": "アクメ商事を訪問しデモを実施", "deal_id": "D001"}),
        ("route_to_expert", {"question": "ネットワーク更改の構成相談", "tags": ["ネットワーク"]}),
        ("summarize_reports", {"rep_id": "R05"}),
        ("get_seasonal_context", {"month": 2}),
        ("morning_briefing", {"rep_id": "R12", "limit": 5}),
        ("list_at_risk_deals", {"limit": 5}),
        ("query_graph", {"intent": "reps_who_win", "category": "サーバー"}),
        ("query_graph", {"intent": "account", "customer": "C28"}),
        ("segment_intelligence", {"query": "製造業のサーバー案件はなぜ負ける？", "outcome": "lost"}),
        ("segment_intelligence", {"query": "どのカテゴリの勝率が低い？"}),
        ("team_pipeline_overview", {}),
        ("team_report_digest", {}),
        ("rep_coaching_focus", {}),
        ("draft_message", {"to": "伊藤さん", "about": "D003の進捗", "deal_id": "D003"}),
        ("web_search", {"query": "製造業 IT投資 動向"}),
        # Document tools: preview (no file) is deterministic; the grounded build is
        # GPU-free, the general tools need a model so they print their guard message.
        ("generate_proposal", {"deal_id": "D001"}),
        ("generate_proposal", {"deal_id": "D001", "confirm": True}),
        ("generate_ringisho", {"deal_id": "D001", "confirm": True}),
        ("generate_pptx", {"prompt": "GTA 6 の発売展望", "use_web": False}),
        ("generate_docx", {"prompt": "社内向けセキュリティ研修の概要"}),
    ]:
        print(f"\n### {n}({a})\n{dispatch(n, a)}")
````

## File: senpai/config.py
````python
"""Central configuration for Senpai.

Holds the model-server connection details (shared with the Phase-1 demo), the
filesystem paths to the seed data, and — most importantly — the *tunable* deal-
health scoring parameters. Everything the scoring engine treats as a threshold
lives here so the rules stay auditable and adjustable in one place (no magic
numbers buried in the engine).

Env:
  BASE_URL      default http://127.0.0.1:8765/v1   (vLLM OpenAI endpoint)
  MODEL         default exp3
  LLM_TIMEOUT   default 120 (seconds) — per-request inference timeout
  LLM_STREAM    default 1 — stream tokens from the server when supported
  LLM_MAX_TOKENS default 1024 — cap on generated tokens for narration
  SENPAI_TODAY  default unset → date.today(); set YYYY-MM-DD to pin the
                "current date" used by scoring (handy for a reproducible demo
                against the committed seed data, whose reference is 2026-06-16).
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

def _load_dotenv() -> None:
    """Load .env files into os.environ (stdlib only; never overrides an already-set
    var). config is the first senpai import in every entrypoint, so doing this here
    means BASE_URL/MODEL/etc. take effect everywhere — including the FastAPI bridge.
    Loads the repo-root `.env` first, then `senpai/.env` (handy for keeping
    ingestion keys like OPENAI_BASE_URL/OPENAI_API_KEY next to the package);
    repo-root wins on conflicts because setdefault keeps the first value seen."""
    here = Path(__file__).resolve().parent
    for env in (here.parent / ".env", here / ".env"):
        if not env.exists():
            continue
        for raw in env.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()

# --- Model server -----------------------------------------------------------
# Any OpenAI-compatible endpoint works here: vLLM (`vllm serve … --port 8765`),
# llama.cpp's `llama-server`, and ollama's `/v1` are all drop-in compatible.
# Only this URL + MODEL change between backends; both come from the repo-root
# .env (loaded above) or process env.
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8765/v1")
FALLBACK_BASE_URL = os.environ.get("FALLBACK_BASE_URL", "http://100.101.186.29:8766/v1")
MODEL = os.environ.get("MODEL", "exp3")
FALLBACK_MODEL = os.environ.get("FALLBACK_MODEL", "toolmind_exp3_final")
MAX_TOOL_ROUNDS = 15


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- Inference tunables -----------------------------------------------------
LLM_TIMEOUT = _env_float("LLM_TIMEOUT", 120.0)        # seconds, per request
LLM_MAX_TOKENS = _env_int("LLM_MAX_TOKENS", 1024)
# Senior Commentary budget. Default sized for the fast live path (thinking OFF):
# enough for a flowing conversational read, not long-form. If NARRATE_THINK is
# enabled (reasoning ON, for a pre-warmed cache when the GPU is free), raise this
# to ~2400 so the hidden <think> block plus the answer both fit without truncation.
LLM_NARRATE_MAX_TOKENS = _env_int("LLM_NARRATE_MAX_TOKENS", 600)
# Reasoning on Senior Commentary. OFF by default: on the shared ~11 tok/s box a
# <think> block adds ~2 min/call, too slow for a live demo. Flip on (with a higher
# LLM_NARRATE_MAX_TOKENS) for offline/pre-warmed generation where quality wins.
NARRATE_THINK = os.environ.get("SENPAI_NARRATE_THINK", "0").lower() not in ("0", "false", "no", "")
LLM_STREAM = os.environ.get("LLM_STREAM", "1").lower() not in ("0", "false", "no", "")
# Assistant tool-loop reasoning. Both the tool-selection rounds and the final
# synthesis run the reasoning distill's <think> phase, which dominates Assistant
# latency on the shared ~11 tok/s box. ON skips it (empty-think prefill) across
# the whole loop — same lever the narrate path uses. Measured ~1.9x faster
# overall (up to ~3x on tool + short-answer turns), with tool selection and
# provenance preserved; the only cost seen was an occasional numeric paraphrase
# slip in long answers. Default ON; set SENPAI_TOOLLOOP_NOTHINK=0 to restore the
# slower, fully-reasoned loop.
TOOLLOOP_NO_THINK = os.environ.get("SENPAI_TOOLLOOP_NOTHINK", "1").lower() not in ("0", "false", "no", "")
# Dynamic reasoning router for the Assistant synthesis round (senpai/llm/routing.py).
# "deterministic" (default) routes FAST vs REASONING by the tools used + query
# intent — reasoning is added back only where it helps (numeric/synthesis), while
# retrieval stays fast. "off" reverts to the static TOOLLOOP_NO_THINK behaviour.
# Later: "atlas" / "classifier" / "llm" — swap in get_reasoning_router(), no
# change to the execution loop. Tool-selection rounds are always fast regardless.
REASONING_ROUTER = os.environ.get("SENPAI_REASONING_ROUTER", "deterministic").strip().lower()
# Model decomposition: serve the FAST (no_think) final synthesis from the smaller
# FALLBACK model (8B Q4) instead of the primary 27B — validated ~2.7x faster at
# grounding parity (docs/phase25_session_log.md). THINK synthesis stays on the 27B
# for its mentorship narrative. OFF by default; SENPAI_FAST_SYNTH_FALLBACK=1 routes
# FAST synthesis to the 8B. (Tool selection always stays on the primary 27B.)
FAST_SYNTH_FALLBACK = os.environ.get("SENPAI_FAST_SYNTH_FALLBACK", "0").lower() not in ("0", "false", "no", "")
# Latency-first override: route ALL synthesis (FAST + THINK) to the 8B, not just
# FAST. The 27B THINK synthesis was the slow path (~150s); the 8B does it far
# faster at a quality cost. Implies the fallback endpoint is the 8B.
SYNTH_ALL_FALLBACK = os.environ.get("SENPAI_SYNTH_ALL_8B", "0").lower() not in ("0", "false", "no", "")

# --- Atlas (spark) serving knobs --------------------------------------------
# The served model is now the atlas 35B (Qwen3.6-35B-A3B-NVFP4, spark/atlas on
# :8888). Two atlas-specific behaviours feed every create() call (see
# senpai/llm/client.py::_gen_kwargs):
#   1. Reasoning is toggled via the chat template's `enable_thinking` kwarg
#      (passed through extra_body→chat_template_kwargs), NOT the old empty
#      <think> prefill — atlas ignores the prefill.
#   2. Sampling MUST be set explicitly. With no sampling params atlas decodes
#      greedily and degenerates into repetition loops ("3. 3. 3.") on long
#      output; the recommended Qwen3 non-thinking sampling fixes it.
LLM_TOP_P = _env_float("SENPAI_LLM_TOP_P", 0.95)
LLM_TOP_K = _env_int("SENPAI_LLM_TOP_K", 20)
# Final-answer (synthesis) temperature. Non-zero on purpose: greedy (0.0) long
# generation degenerates on this NVFP4 model. Tool-selection rounds stay greedy
# (short, structured output — no degeneration, more deterministic tool picks).
SYNTH_TEMPERATURE = _env_float("SENPAI_SYNTH_TEMPERATURE", 0.7)

# --- Review Coach grounding controls ----------------------------------------
# Grounding-audit P0: similar past cases are CROSS-CUSTOMER by construction
# (find_similar_cases injects another customer's closed deal ~99% of the time),
# which risks narrative contamination — the model reasoning from analogy rather
# than this customer's own evidence. Disabled by default while we verify grounding.
# Corpus principles (playbooks) are kept; they are a separate, evaluated axis.
COACH_USE_SIMILAR_CASES = os.environ.get("SENPAI_COACH_SIMILAR_CASES", "0").lower() not in ("0", "false", "no", "")
COACH_USE_CORPUS = os.environ.get("SENPAI_COACH_CORPUS", "1").lower() not in ("0", "false", "no", "")

# --- Paths ------------------------------------------------------------------
PKG_DIR = Path(__file__).resolve().parent
SEED_DIR = PKG_DIR / "data" / "seed"
INDEX_DIR = PKG_DIR / "data" / "index"   # committed dense-embedding vectors (build_index.py)
# Committed Segment-Intelligence community reports (build_communities.py). Like the
# dense index, this is a committed build artifact so the runtime is GPU-free — the
# deterministic stats can always be recomputed, and the optional LLM narratives ride
# along. Missing file → senpai.graph.communities rebuilds deterministically in-memory.
COMMUNITIES_PATH = INDEX_DIR / "communities.json"
# A category×industry leaf segment is only emitted as its own report when it has at
# least this many CLOSED deals (won+lost); thinner leaves are represented by their
# parent category rollup, which always aggregates every deal in the category.
SEGMENT_MIN_DEALS = _env_int("SENPAI_SEGMENT_MIN_DEALS", 5)
# Sidecar dir for runtime-ingested rows (daily reports, etc.). Gitignored and
# loaded as an OVERLAY on top of SEED_DIR by senpai.data.store — the committed
# seed stays canonical/byte-stable; ingested data is demo-only and never merged.
INGESTED_DIR = PKG_DIR / "data" / "ingested"
# Output dir for documents the chatbot generates (PPTX proposals, DOCX 稟議書, and
# the general-purpose pptx/docx tools). Gitignored and demo-only, like INGESTED_DIR;
# created on first write. The committed seed is never touched by document generation.
GENERATED_DIR = PKG_DIR / "data" / "generated"

# Cross-chat memory: durable, entity-anchored Observations (the judgments a chat
# reached, NOT transcripts), keyed by Subject so a later chat about the same deal can
# reason from them. Gitignored and demo-only. The JSONL file is a storage STUB behind
# the ObservationStore seam (senpai.orchestration.memory); the persistence layer's DB
# is just another implementation of that interface and replaces this file wholesale.
MEMORY_DIR = PKG_DIR / "data" / "memory"
OBSERVATIONS_PATH = MEMORY_DIR / "observations.jsonl"

# Persistent copilot chat history: durable, per-user conversation transcripts so a
# rep can close the tab and resume a past chat exactly where it left off. A single
# SQLite file (stdlib sqlite3, WAL mode) keyed by conversation_id — deliberately
# SEPARATE from senpai.data.store's seed/overlay tables so chat writes never drop
# store's lru_cache. Gitignored and demo-only, like INGESTED_DIR; created on first
# use. The stored blob is an opaque client-owned transcript the server never parses.
CHAT_DB_PATH = INGESTED_DIR / "chat_history.db"

# --- Workspace (sandboxed local document access) ----------------------------
# The Workspace capability reaches OUTSIDE the seed DB — it finds and reads real
# local documents (PDF/DOCX/PPTX/XLSX/TXT/MD) and returns structured evidence into
# the orchestration EvidenceBundle. It is strictly READ-ONLY and confined to
# WORKSPACE_ROOT: every path is resolved and must stay inside that root (no
# traversal, no symlink escape). Points at a real local docs folder; override with
# SENPAI_WORKSPACE_ROOT. list_documents() prunes VCS/build dirs and our own
# `generated` output so machine artifacts don't feed back in as grounding.
WORKSPACE_ROOT = Path(
    os.environ.get("SENPAI_WORKSPACE_ROOT", r"E:\my_stuff\Otsuka_backup")
).resolve()
# Extensions the Workspace will find/extract (read-only). Lowercase, with dot.
WORKSPACE_EXTS = tuple(
    e.strip().lower() for e in os.environ.get(
        "SENPAI_WORKSPACE_EXTS", ".pdf,.docx,.pptx,.xlsx,.txt,.md,.png,.jpg,.jpeg,.gif").split(",") if e.strip())
# Runtime fan-out cap: a `find` never expands into more than this many parallel
# `extract` tasks, so one query can't read an unbounded tree.
WORKSPACE_MAX_FILES = _env_int("SENPAI_WORKSPACE_MAX_FILES", 12)
# Per-document extracted-text cap (chars) — keeps the evidence bundle bounded and
# the reasoner context safe, mirroring the chat loop's 1500-char tool truncation.
WORKSPACE_MAX_CHARS = _env_int("SENPAI_WORKSPACE_MAX_CHARS", 4000)
# Skip absurdly large files before we even open them (bytes).
WORKSPACE_MAX_BYTES = _env_int("SENPAI_WORKSPACE_MAX_BYTES", 25_000_000)

# Committed brand template for generated PPTX decks: an Otsuka proposal deck with
# all content slides stripped, leaving only its slide masters/layouts/theme (the
# Meiryo UI font + corporate styling). render.render_pptx opens this as the base
# so generated decks inherit Otsuka branding. If absent, rendering falls back to
# python-pptx's blank default (keeps tests/CI green without the committed asset).
PPTX_TEMPLATE_PATH = PKG_DIR / "data" / "templates" / "otsuka_template.pptx"


def fiscal_year_quarter(d_iso: str) -> tuple[int, int]:
    """Japanese fiscal year/quarter for a YYYY-MM-DD date (FY starts in April).
    Single source of truth shared by gen_seed (seed authoring) and ingestion
    (runtime activity records) so both stay in the same fiscal calendar."""
    y, m, _ = (int(x) for x in d_iso.split("-"))
    fy = y if m >= 4 else y - 1
    q = {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3,
         1: 4, 2: 4, 3: 4}[m]
    return fy, q


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "")


# --- Retrieval (hybrid semantic search) -------------------------------------
# Dense embeddings run on CPU via fastembed (ONNX); corpus vectors are precomputed
# and committed under INDEX_DIR, so only the query is embedded at runtime. Hybrid
# search fuses BM25 + dense via Reciprocal Rank Fusion. Everything degrades to
# BM25 (then keyword) when the libs/vectors are missing — mirrors SENPAI_USE_LLM.
EMBED_MODEL = os.environ.get(
    "SENPAI_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
# Dense layer on by default; set SENPAI_USE_EMBEDDINGS=0 for a hermetic BM25-only run
# (tests / no-network CI). semantic.py still no-ops dense if fastembed/vectors absent.
USE_EMBEDDINGS = _env_bool("SENPAI_USE_EMBEDDINGS", True)
USE_RERANKER = _env_bool("SENPAI_USE_RERANKER", False)   # optional cross-encoder, off by default
RRF_K = _env_int("SENPAI_RRF_K", 60)                     # Reciprocal Rank Fusion constant
# Fusion weights — dense carries more weight than lexical BM25 because, on these
# short Japanese notes, the embedding model is the stronger signal for paraphrases.
BM25_WEIGHT = _env_float("SENPAI_BM25_WEIGHT", 1.0)
DENSE_WEIGHT = _env_float("SENPAI_DENSE_WEIGHT", 3.0)

# --- Multimodal ingestion (senpai/ingestion) --------------------------------
# Audio (STT) and image (vision/OCR) run via an OpenAI-compatible *multimodal*
# endpoint — OPENAI_BASE_URL + OPENAI_API_KEY (e.g. Groq's free tier; the local
# exp3 is text-only). Model ids default to Groq's free models; override per env.
INGEST_BASE_URL = os.environ.get("OPENAI_BASE_URL")            # None → api.openai.com
INGEST_API_KEY = os.environ.get("OPENAI_API_KEY")
INGEST_AUDIO_MODEL = os.environ.get("INGEST_AUDIO_MODEL", "whisper-large-v3")
INGEST_VISION_MODEL = os.environ.get(
    "INGEST_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
INGEST_STRUCT_MODEL = os.environ.get(
    "INGEST_STRUCT_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")


def have_multimodal() -> bool:
    """True when a usable multimodal key is configured (not missing/placeholder)."""
    return bool(INGEST_API_KEY) and INGEST_API_KEY not in ("dummy", "")

# Fixed anchor used by data/gen_seed.py so the committed seed JSON is byte-stable
# no matter what day it is regenerated. Scoring uses today() (below), which on the
# authoring date equals this anchor.
REFERENCE_DATE = date(2026, 6, 16)


def today() -> date:
    """The 'current date' scoring reasons against. Override with SENPAI_TODAY
    for a perfectly reproducible demo against the committed seed."""
    raw = os.environ.get("SENPAI_TODAY")
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return date.today()


# --- Order-rank model (mirrors the production `deals.order_rank` values) -----
# The real SPR schema ranks every deal on this 8-point scale. We treat ranks 2–6
# as the live pipeline, 1 as won, and 7–8 as dead. Lower prefix number = stronger
# (closer to a confirmed order).
ORDER_RANKS = ["1_Confirmed", "2_A+", "3_A", "4_B", "5_C", "6_P", "7_Lost", "8_Cancelled"]
OPEN_RANKS = {"2_A+", "3_A", "4_B", "5_C", "6_P"}   # live pipeline
WON_RANKS = {"1_Confirmed"}
DEAD_RANKS = {"7_Lost", "8_Cancelled"}


def rank_num(order_rank: str | None) -> int:
    """Numeric prefix of an order_rank ('3_A' → 3); unknown/NULL → 99."""
    try:
        return int(str(order_rank).split("_", 1)[0])
    except (ValueError, AttributeError):
        return 99


def is_open_rank(order_rank: str | None) -> bool:
    return order_rank in OPEN_RANKS


# --- Deal-health scoring parameters (all tunable) ---------------------------
# Per-rank health benchmarks: (max healthy days at this rank, expected contact
# cadence in days). A deal sitting longer than the benchmark accrues risk points.
RANK_BENCHMARKS: dict[str, tuple[int, int]] = {
    "2_A+": (21, 7),
    "3_A":  (30, 10),
    "4_B":  (45, 14),
    "5_C":  (60, 21),
    "6_P":  (60, 21),
}

# Ranks strong enough that a decision-maker really should be identified by now.
DECISION_MAKER_RANKS = {"2_A+", "3_A", "4_B"}

# Titles in sales_activities.business_card_info that count as a decision-maker contact.
DECISION_MAKER_TITLES = ["社長", "代表", "取締役", "役員", "本部長", "部長", "課長",
                         "責任者", "マネージャー", "CIO", "情シス長"]

# Ranks the rep is signalling as likely to close — used for the optimism-mismatch
# reliability flag (strong rank but red health = report doesn't match reality).
OPTIMISTIC_RANKS = {"2_A+", "3_A"}

# Japanese stall lexicon — phrases that, in the latest daily_report, signal a stall.
STALL_LEXICON = ["検討します", "予算が", "時期を見て", "上と相談", "持ち帰り", "また連絡", "見送り", "様子見"]

# Words that, when present in a note, mean a competitor is in play (a *factor* the
# rep should reason about, not a gap). Used by the Sales Review Coach.
COMPETITION_LEXICON = ["競合", "他社", "相見積", "コンペ", "比較中", "比較検討", "リプレイス", "切り替え"]

# Risk-score band thresholds (score is 0–100, higher = worse).
RED_THRESHOLD = 55      # score >= 55  → red
YELLOW_THRESHOLD = 25   # 25 <= score < 55 → yellow ; < 25 → green


def band_for_score(score: int) -> str:
    """Map a 0–100 risk score to a traffic-light band."""
    if score >= RED_THRESHOLD:
        return "red"
    if score >= YELLOW_THRESHOLD:
        return "yellow"
    return "green"
````

## File: web/components/workspace/workspace.tsx
````typescript
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
  SquarePen,
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
            tools: [...m.tools, { name: e.name, args: e.args, result: e.result, document: e.document, batchId: e.batchId, intent: e.intent, outline: e.outline, internal: e.internal }],
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
      {/* Conversation controls pinned to the top of the chat pane, where
          they are immediately discoverable — instead of being buried inside the
          composer toolbar next to Mic/Attach/Send. */}
      <div className="flex items-center justify-between shrink-0 pt-3 pb-2 pr-1">
        <div>
          <button
            onClick={clearThread}
            disabled={busy}
            title={lang === "ja" ? "新しい会話" : "New chat"}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground hover:bg-muted disabled:opacity-50"
          >
            <SquarePen className="h-3.5 w-3.5" />
            <span className="font-medium">{lang === "ja" ? "新規" : "New chat"}</span>
          </button>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setHistoryOpen(true)}
            title={lang === "ja" ? "チャット履歴" : "Chat history"}
            className="inline-flex h-8 items-center gap-1 rounded-lg border border-border bg-card px-2.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground hover:bg-muted"
          >
            <History className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{lang === "ja" ? "履歴" : "History"}</span>
          </button>
        </div>
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
      <div className="sticky bottom-0 -mx-1 bg-background/85 px-1 pb-4 pt-3 backdrop-blur">
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
                {messages.length > 0 && (
                  <button
                    onClick={clearThread}
                    disabled={busy}
                    title={lang === "ja" ? "クリア" : "Clear"}
                    className="inline-flex h-8 items-center gap-1 rounded-lg border border-border bg-card px-2.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground hover:bg-muted disabled:opacity-50"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    <span className="hidden sm:inline">{lang === "ja" ? "クリア" : "Clear"}</span>
                  </button>
                )}
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
````

## File: senpai/llm/client.py
````python
"""OpenAI client + tool-calling loop for exp3 — ported from demo/app.py.

Keeps the demo's proven behaviour: native OpenAI `tool_calls` with a safe
`_parse_xlam` fallback for the XLAM-style text the model sometimes emits. The
tool loop is factored into `stream_turn` (used by the Gradio chat) and a thin
`simple_complete` (used by narration). Network/parse failures are surfaced as
strings or raised for the caller to fall back on — nothing here crashes the app.
"""
from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterator

from openai import OpenAI

from senpai import config
from senpai.llm import usage as _usage
from senpai.tools.impl import dispatch, _truncate_on_boundary
from senpai.tools import conversation as _conversation
from senpai.orchestration.scheduler import AdaptiveScheduler, ToolCall as SchedToolCall
from senpai.orchestration.engine import ExecutionEngine
from senpai.agent.capabilities import build_registry

_SCHEDULER = AdaptiveScheduler()
_ENGINE = ExecutionEngine(build_registry())
from senpai.tools.schemas import TOOLS

# A single OpenAI-compatible client. `timeout`/`max_retries` keep a slow or down
# inference server (vLLM/ollama) from hanging the API — callers fall back to the
# deterministic render on any error.
client = OpenAI(
    base_url=config.BASE_URL,
    api_key="dummy",
    timeout=config.LLM_TIMEOUT,
    max_retries=0,
)

fallback_client = OpenAI(
    base_url=config.FALLBACK_BASE_URL,
    api_key="dummy",
    timeout=config.LLM_TIMEOUT,
    max_retries=0,
)


def _synth_route(no_think: bool):
    """Hybrid model-decomposition router for the *final synthesis* round only.

    FAST (no_think) synthesis → the smaller FALLBACK model (8B Q4); THINK synthesis
    → the primary (27B), whose mentorship narrative we keep. Gated by
    `config.FAST_SYNTH_FALLBACK` (OFF by default, so the live path is unchanged —
    everything stays on the 27B). Tool *selection* never calls this; it is always
    the primary. Returns (synthesis_client, model_id, alt_client, alt_model) where
    `alt_*` is the other endpoint to fail over to. The Fast/Think decision itself
    stays with the existing reasoning router — this only picks who writes the
    already-decided FAST answer."""
    # SYNTH_ALL_FALLBACK: route ALL synthesis (FAST + THINK) to the 8B — latency
    # over accuracy. Otherwise the FAST→8B / THINK→27B hybrid.
    if config.SYNTH_ALL_FALLBACK or (no_think and config.FAST_SYNTH_FALLBACK):
        return fallback_client, config.FALLBACK_MODEL, client, config.MODEL
    return client, config.MODEL, fallback_client, config.FALLBACK_MODEL


def _parse_xlam(content: str | None):
    """exp3 sometimes emits XLAM-style `[func(a=1, b='x'), ...]` as plain text
    instead of OpenAI tool_calls. Parse it safely with `ast` (literal args only,
    never code). Returns a list of (name, args_dict) or None."""
    if not content:
        return None
    text = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip().strip("`")
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        node = ast.parse(text[start:end + 1], mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(node, ast.List):
        return None
    calls = []
    for el in node.elts:
        if isinstance(el, ast.Call) and isinstance(el.func, ast.Name):
            try:
                kwargs = {kw.arg: ast.literal_eval(kw.value) for kw in el.keywords}
            except (ValueError, SyntaxError):
                continue
            calls.append((el.func.id, kwargs))
    return calls or None


# Atlas (spark) controls reasoning via the chat template's `enable_thinking`
# kwarg, surfaced to the OpenAI SDK through extra_body→chat_template_kwargs.
# (The old empty-<think> assistant prefill — the only lever on the previous
# llama-server build — is a NO-OP on atlas: it still emits a <think> phase.)
# Atlas also requires explicit sampling: with none it decodes greedily and
# degenerates into repetition loops on long output. `_gen_kwargs` carries both
# into every create() call; `no_think=True` disables the reasoning phase.
def _gen_kwargs(no_think: bool) -> dict:
    return {
        "top_p": config.LLM_TOP_P,
        "extra_body": {
            "chat_template_kwargs": {"enable_thinking": not no_think},
            "top_k": config.LLM_TOP_K,
        },
    }


def _prep(messages: list[dict], no_think: bool) -> list[dict]:
    # Reasoning is now toggled via _gen_kwargs(enable_thinking); the messages
    # pass through unchanged (the empty-<think> prefill did nothing on atlas).
    return messages


def _record_stream_usage(usage_obj, msgs: list[dict], output: str, *,
                         model: str, endpoint: str, label: str) -> None:
    """Record token usage for a streamed call: measured from the server's
    usage-only final chunk when present, else a clearly-flagged estimate over the
    prompt + accumulated output."""
    if usage_obj is not None:
        _usage.record(model, endpoint,
                      getattr(usage_obj, "prompt_tokens", 0) or 0,
                      getattr(usage_obj, "completion_tokens", 0) or 0,
                      label=label, streamed=True)
        return
    prompt_text = "\n".join(str(m.get("content", "")) for m in msgs)
    _usage.record(model, endpoint,
                  _usage._estimate_tokens(prompt_text),
                  _usage._estimate_tokens(output),
                  label=label, streamed=True, estimated=True)


def simple_complete(messages: list[dict], temperature: float = 0.3,
                    max_tokens: int | None = None, *, no_think: bool = False,
                    allow_fallback: bool = True, fast_decomp: bool = False,
                    label: str = "complete") -> str:
    """One plain completion, no tools. Raises on transport error so callers
    (e.g. narration) can fall back to a templated string. Strips any
    `<think>...</think>` reasoning span (the served model is a reasoning
    distill) so callers get only the final coaching text. `no_think` disables the
    reasoning phase (low latency); `allow_fallback=False` pins the request to the
    primary endpoint and re-raises instead of silently switching models."""
    msgs = _prep(messages, no_think)
    primary_c, primary_m, alt_c, alt_m = (
        _synth_route(no_think) if fast_decomp else (client, config.MODEL, fallback_client, config.FALLBACK_MODEL))
    try:
        resp = primary_c.chat.completions.create(
            model=primary_m, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, **_gen_kwargs(no_think),
        )
        _usage.record_response(resp, model=primary_m, endpoint="primary", label=label)
    except Exception as e:
        if not allow_fallback:
            raise
        print(f"⚠️ Primary server {primary_m} failed ({e}). Trying fallback...")
        resp = alt_c.chat.completions.create(
            model=alt_m, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, **_gen_kwargs(no_think),
        )
        _usage.record_response(resp, model=alt_m, endpoint="fallback", label=label)
    content = resp.choices[0].message.content or ""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    return content.strip()


def _delta_reasoning(delta) -> str | None:
    """Some OpenAI-compatible servers (llama.cpp's llama-server, DeepSeek, vLLM
    with `--reasoning-parser`) split chain-of-thought into a separate
    `reasoning_content` field and leave `content`/`delta.content` empty until the
    answer begins. The openai SDK exposes such non-standard fields on
    `model_extra`; older builds attach them directly. Check both."""
    rc = getattr(delta, "reasoning_content", None)
    if rc is None:
        extra = getattr(delta, "model_extra", None)
        if extra:
            rc = extra.get("reasoning_content")
    return rc


def stream_complete(messages: list[dict], temperature: float = 0.3,
                    max_tokens: int | None = None, *, no_think: bool = False,
                    allow_fallback: bool = True, fast_decomp: bool = False,
                    label: str = "stream") -> Iterator[str]:
    """Stream a completion token-by-token from the OpenAI-compatible server.
    Yields a `<think>…</think>` reasoning span (when the backend emits one)
    followed by the answer deltas — a single text stream callers can split on
    `</think>`. Backends that inline `<think>` in `content` (vLLM/ollama) flow
    straight through unchanged; backends that put reasoning in a separate
    `reasoning_content` field (llama.cpp) are reconstructed into the same shape,
    so the thinking phase stays visible instead of streaming nothing.
    `no_think` disables reasoning for low latency; `allow_fallback=False` pins the
    request to the primary endpoint and re-raises instead of switching models.
    `fast_decomp=True` opts this call into the hybrid synthesis route (FAST → 8B)
    when `config.FAST_SYNTH_FALLBACK` is on — used by FAST grounded summaries
    (e.g. /research), not by narration. Raises on transport error so callers can
    fall back."""
    msgs = _prep(messages, no_think)
    primary_c, primary_m, alt_c, alt_m = (
        _synth_route(no_think) if fast_decomp else (client, config.MODEL, fallback_client, config.FALLBACK_MODEL))
    # include_usage asks the server for a final usage-only chunk so token
    # accounting on the streaming path is measured, not estimated.
    _opts = {"stream_options": {"include_usage": True}}
    used_model, used_endpoint = primary_m, "primary"
    try:
        stream = primary_c.chat.completions.create(
            model=primary_m, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, stream=True,
            **_opts, **_gen_kwargs(no_think),
        )
    except Exception as e:
        if not allow_fallback:
            raise
        print(f"⚠️ Synthesis server {primary_m} failed ({e}). Trying {alt_m}...")
        used_model, used_endpoint = alt_m, "fallback"
        stream = alt_c.chat.completions.create(
            model=alt_m, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, stream=True,
            **_opts, **_gen_kwargs(no_think),
        )
    think_open = think_closed = False
    _usage_obj = None
    _out_chars: list[str] = []
    for chunk in stream:
        if getattr(chunk, "usage", None):
            _usage_obj = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if not delta:
            continue
        reasoning = _delta_reasoning(delta)
        if reasoning:
            _out_chars.append(reasoning)
            if not think_open:
                think_open = True
                yield "<think>"
            yield reasoning
        if delta.content:
            _out_chars.append(delta.content)
            if think_open and not think_closed:
                think_closed = True
                yield "</think>"
            yield delta.content
    _record_stream_usage(_usage_obj, msgs, "".join(_out_chars),
                         model=used_model, endpoint=used_endpoint, label=label)


def stream_turn(convo: list[dict], tools: list[dict] | None = None):
    """Generator driving one user turn through the tool loop. Yields
    (tool_log, answer_or_None) after each round; the final yield has the answer.
    `convo` is mutated in place with assistant/tool messages (demo semantics).
    `tools` selects which tool schemas the model may call (defaults to all TOOLS);
    each front end passes its own role-scoped subset."""
    tools = tools if tools is not None else TOOLS
    tool_log: list[tuple[str, str, str]] = []
    answer = None
    for _ in range(config.MAX_TOOL_ROUNDS):
        try:
            resp = client.chat.completions.create(
                model=config.MODEL, messages=convo, tools=tools,
                tool_choice="auto", temperature=0.1, **_gen_kwargs(True),
            )
            _usage.record_response(resp, model=config.MODEL, endpoint="primary", label="tool_loop")
        except Exception as e:
            print(f"⚠️ Primary server failed in tool loop ({e}). Trying fallback...")
            try:
                resp = fallback_client.chat.completions.create(
                    model=config.FALLBACK_MODEL, messages=convo, tools=tools,
                    tool_choice="auto", temperature=0.1, **_gen_kwargs(True),
                )
                _usage.record_response(resp, model=config.FALLBACK_MODEL, endpoint="fallback", label="tool_loop")
            except Exception as fe:
                answer = f"⚠️ サーバーエラー: {e} (Fallback: {fe})"
                break

        msg = resp.choices[0].message
        if msg.tool_calls:
            calls = [(tc.id, tc.function.name, tc.function.arguments)
                     for tc in msg.tool_calls]
        else:
            parsed = _parse_xlam(msg.content)
            calls = [(f"call_{len(tool_log) + i}", name, json.dumps(args))
                     for i, (name, args) in enumerate(parsed)] if parsed else []

        if not calls:
            if tool_log:
                last_name, _, last_result = tool_log[-1]
                if last_name in _ACTION_TOOLS or last_name.startswith("generate_"):
                    answer = last_result
                    break
            answer = (msg.content or "").strip() or "(no response)"
            break

        convo.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": cid, "type": "function",
             "function": {"name": name, "arguments": args}}
            for cid, name, args in calls]})
        for cid, name, args in calls:
            result = dispatch(name, args)
            tool_log.append((name, _fmt_args(args), result))
            convo.append({"role": "tool", "tool_call_id": cid, "content": result})
        yield tool_log, None
    else:
        if tool_log:
            last_name, _, last_result = tool_log[-1]
            if last_name in _ACTION_TOOLS or last_name.startswith("generate_"):
                answer = last_result
        answer = answer or "⚠️ ツール呼び出しの上限に達しました。"
    yield tool_log, answer


def _fallback_answer(substantive: list[tuple[str, str]]) -> str:
    """A grounded last resort when synthesis yields nothing: the most recent
    substantive tool result, presented plainly. Empty when nothing useful was
    gathered (then the caller keeps the honest '(no response)')."""
    return substantive[-1][1] if substantive else ""


_ENTITY_DEAL_RE = re.compile(r"\bD\d{3,}\b")
_ENTITY_CUST_RE = re.compile(r"\bC\d{2,}\b")


def _multi_entity_gather_calls(user_msg: str) -> list[tuple[str, str, str]]:
    """Deterministic fan-out for 'compare A, B, C' turns. If the user's message names
    ≥2 DISTINCT, KNOWN entity ids (deals D### / customers C##, validated against the
    store — same id discipline as SessionFocus), return the full gather bundle for all
    of them so the scheduler runs it in a SINGLE parallel round. The served model emits
    only one tool_call per response under the full prompt (verified), so it can't batch
    these itself.

    The bundle is grouped by tool — every deal's `score_deal_health`, then every deal's
    `query_spr`, then each standalone customer's `query_spr` — but since all are
    parallel-safe reads they execute concurrently in one round (no need to phase health
    before records: there is no dependency between them). Customers get records only
    (deal health needs a deal id).

    Returns [] when the pattern doesn't apply → the normal loop runs unchanged. Scoped
    intentionally narrow: explicit ids only, the compare pattern only."""
    if not user_msg:
        return []
    from senpai.data import store  # lazy
    used: set[str] = set()
    deal_ids: list[str] = []
    cust_ids: list[str] = []
    for did in _ENTITY_DEAL_RE.findall(user_msg):
        if did not in used and store.get_deal(did):
            used.add(did)
            deal_ids.append(did)
    for cid in _ENTITY_CUST_RE.findall(user_msg):
        if cid not in used and store.get_customer(cid):
            used.add(cid)
            cust_ids.append(cid)
    if len(used) < 2:   # threshold is DISTINCT entities, not calls
        return []
    gathers: list[tuple[str, dict]] = []
    gathers += [("score_deal_health", {"deal_id": d}) for d in deal_ids]  # all health, grouped
    gathers += [("query_spr", {"deal_id": d}) for d in deal_ids]          # then all deal records
    gathers += [("query_spr", {"customer": c}) for c in cust_ids]         # then customer records
    return [(f"exp_{i}", name, json.dumps(args, ensure_ascii=False))
            for i, (name, args) in enumerate(gathers)]


_WS_AFFIRM_RE = None  # lazy-loaded below (avoids import cost when unused)


def _pending_workspace_edit_confirm(convo: list[dict]) -> tuple[str, str] | None:
    """Deterministic confirm-continuation for a pending `edit_workspace_document`
    preview (confirm=False). If the newest user message is a bare affirmation
    ("apply", "保存して", "はい"...) and the most recent assistant tool call was an
    unconfirmed edit_workspace_document, return (path, content) to re-commit with
    confirm=True ourselves — never left to the model to remember or, worse, to
    free-generate a "saved!" answer without ever calling the tool again (the exact
    bug this closes: a write claimed in prose with no tool call behind it)."""
    global _WS_AFFIRM_RE
    if _WS_AFFIRM_RE is None:
        from senpai.planner.selection import _AFFIRM_RE  # lazy: avoid import cycles
        _WS_AFFIRM_RE = _AFFIRM_RE
    user_msg = next((m.get("content") for m in reversed(convo)
                     if m.get("role") == "user" and m.get("content")), "")
    if not user_msg or not _WS_AFFIRM_RE.search(user_msg.strip()):
        return None
    for m in reversed(convo):
        if m.get("role") != "assistant":
            continue
        calls = m.get("tool_calls") or []
        edit_calls = [tc for tc in calls if tc["function"]["name"] == "edit_workspace_document"]
        if not edit_calls:
            continue  # nearest assistant tool turn wasn't an edit — nothing pending
        try:
            args = json.loads(edit_calls[-1]["function"]["arguments"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if args.get("confirm"):
            return None  # already committed — nothing left to confirm
        path, content = args.get("path"), args.get("content")
        return (path, content) if path and content else None
    return None


# Phrasing that signals "mutate a real local file" (apply/add/edit/update/save
# against a file/note/doc) rather than just asking about its contents. Used to
# nudge the model toward actually calling edit_workspace_document instead of
# just describing the merge in prose with no write behind it.
_WORKSPACE_WRITE_INTENT_RE = re.compile(
    r"\b(?:apply|add|append|edit|update|save|write|put)\b.{0,40}\b(?:file|note|notes|doc|document)\b|"
    r"\b(?:file|note|notes|doc|document)\b.{0,20}\b(?:apply|edit|update|add)\b|"
    r"(?:ファイル|メモ|ノート|文書).{0,15}(?:追加|追記|編集|更新|保存|反映|適用)|"
    r"(?:追加|追記|編集|更新|保存|反映|適用).{0,15}(?:ファイル|メモ|ノート|文書)",
    re.IGNORECASE)

_WORKSPACE_WRITE_NUDGE = (
    "（システム注記：ユーザーはローカルファイルへの反映を求めています。まだ "
    "edit_workspace_document が呼ばれていません。他のツールでの説明だけで終わらせず、"
    "変更後の全文を content に入れて edit_workspace_document を confirm=False で呼び出し、"
    "プレビューを提示してください。)"
)


def _wants_workspace_write(user_msg: str) -> bool:
    return bool(user_msg) and bool(_WORKSPACE_WRITE_INTENT_RE.search(user_msg))


def _is_substantive(result: str) -> bool:
    """True when a tool result carries usable info (not an error / not-found). Drives
    both the answer fallback and the unproductive-round spiral guard — so a tool that
    keeps returning real data (multi-entity fan-out) is never mistaken for a spiral."""
    return not (result.startswith("[error]") or "見つかりません" in result
                or "ありません" in result[:20])


def _route_final_answer(convo, tools, tool_log, role, fallback_text: str = ""):
    """Decide FAST vs REASONING for the synthesis round via the ReasoningRouter,
    emit a `routing` event (observability), then stream the answer. Tool-selection
    stays fast regardless; only this round is dynamically routed. When the router
    is "off" we fall back to the static TOOLLOOP_NO_THINK behaviour. `fallback_text`
    is surfaced if synthesis comes back empty, so a turn never shows a blank."""
    no_think = config.TOOLLOOP_NO_THINK
    if config.REASONING_ROUTER and config.REASONING_ROUTER != "off":
        try:
            from senpai.llm.routing import get_reasoning_router, RoutingRequest
            user_msg = next((m.get("content") for m in reversed(convo)
                             if m.get("role") == "user" and m.get("content")), "")
            decision = get_reasoning_router().route(RoutingRequest(
                message=user_msg or "", role=role or "junior",
                tools_used=[name for name, _a, _r in tool_log], rounds=len(tool_log)))
            yield {"type": "routing", "think": decision.think,
                   "reason": decision.reason, "confidence": round(decision.confidence, 2),
                   "mode": "reasoning" if decision.think else "fast"}
            no_think = not decision.think
        except Exception:  # noqa: BLE001 — a router fault must never break the turn
            pass  # fall back to the static TOOLLOOP_NO_THINK default
    # Observability: surface which model writes this (already-decided) synthesis,
    # so the hybrid eval can record FAST→8B / THINK→27B ground truth.
    _sc, _sm, _, _ = _synth_route(no_think)
    yield {"type": "synth", "model_id": _sm,
           "tier": "atlas", "no_think": no_think}
    yield from _stream_final_answer(convo, tools, no_think=no_think,
                                    fallback_text=fallback_text)


# Sentinel tool for the "finish-tool" loop. With tool_choice="required" the model
# must emit a tool call every round, so it can never burn time generating a
# throwaway answer just to signal "no more tools" (the old double-generation). When
# it has enough — or the question needs no internal tool — it calls `finish`, which
# we intercept (never dispatched) and hand to the single routed synthesis round.
_FINISH_TOOL = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": (
            "回答に必要な情報が揃ったら、または社内ツールが不要な質問なら、これを呼ぶこと。"
            "回答文は自分で書かず finish を呼ぶ。finish を呼ぶと最終回答の生成に進む。 "
            "Call this as soon as you have enough to answer, or when no internal tool "
            "is needed. Do NOT write the answer yourself — calling finish triggers the "
            "final answer."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

# Action tools that commit a side effect or produce a deliverable (a file, a booked
# meeting, a quote/email draft, a workspace file write/move) rather than retrieve facts.
_ACTION_TOOLS = {"schedule_meeting", "create_quote", "send_email",
                 "edit_workspace_document", "move_workspace_document"}


def _is_terminal_action(name: str, result: str) -> bool:
    """True when an action tool actually COMMITTED (file generated, meeting booked,
    draft produced, workspace file written) — meaning the turn is done and the model
    must not be allowed to re-invoke it. A confirm=false PREVIEW (which asks the rep
    to confirm first) and a failed call are NOT terminal, so the loop keeps going in
    those cases.

    This is what stops the model from re-calling generate_pptx (or re-writing a
    workspace file) every round and emitting duplicates: once the deliverable is
    committed, the turn ends on that result — the tool's own grounded text becomes
    the answer, leaving no room for the model to embellish or fabricate on top of it
    (the earlier bug: claiming a save happened with no commit behind it at all)."""
    if not (name in _ACTION_TOOLS or name.startswith("generate_")):
        return False
    if "プレビュー" in result or "confirm=true" in result.lower():
        return False  # a preview/draft awaiting the rep's confirmation
    if result.startswith("[error]") or "見つかりません" in result:
        return False  # a failed call — let the model recover
    return True


def stream_chat_turn(convo: list[dict], tools: list[dict] | None = None,
                     role: str | None = None):
    """Web-facing tool loop that *streams the final answer* token-by-token.

    Same loop as `stream_turn` (kept intact for the Gradio apps), but instead of
    a single blocking final completion it streams the answering round so the web
    Assistant feels as live as Review Coach. Yields typed event dicts:
      {"type": "tool", "name", "args", "result"}   — one per executed tool
      {"type": "routing", "think", "reason", "confidence", "mode"}  — synthesis mode
      {"type": "delta", "text"}                     — answer tokens as they arrive
      {"type": "answer", "text"}                    — the full answer (terminal)
    `convo` is mutated in place (demo semantics). Reasoning (`<think>…</think>`)
    is stripped so only the user-facing answer streams. `role` feeds the router."""
    tools = tools if tools is not None else TOOLS
    tool_log: list[tuple[str, str, str]] = []
    # Loop-intelligence bookkeeping (per turn): the results already gathered, keyed by
    # (name, canonical-args), plus each tool's count of consecutive UNPRODUCTIVE rounds
    # (ran but returned nothing substantive). Capping unproductive rounds — not total
    # rounds — is deliberate: a tool fetching distinct entities (query_spr for D133,
    # D012, D168) keeps returning real data so it never trips the cap, while a
    # rephrasing spiral (search X→Y→Z, all empty) trips it after two dry rounds.
    # `substantive` keeps the best real tool output so a turn can always answer.
    executed: dict[tuple[str, str], str] = {}
    tool_unproductive: dict[str, int] = {}
    tool_total_rounds: dict[str, int] = {}
    substantive: list[tuple[str, str]] = []   # (tool_name, result) worth answering from
    from senpai.documents import registry as _docs
    from senpai.retrieval import trace as _trace
    from senpai.tools import crawl_trace as _crawl
    _trace.start()  # begin a retrieval trace for this turn (Retrieval Explorer)
    _docs.start()   # begin the per-turn generated-document buffer (download chips)
    _crawl.start()  # begin the per-turn web-crawl trace (web_research browse feed)

    # Tool-selection rounds must KEEP the <think> phase: this reasoning-distill
    # needs to reason before it will emit a tool call. Prefilling an empty
    # <think></think> here makes it skip deliberation and *narrate* the call as
    # prose ("Action: scheduling meeting…") instead of emitting a real tool_call —
    # so nothing runs and the UI shows no tool. (Verified A/B: empty-think → 0 tool
    # calls; think-on → schedule_meeting fires.) The latency knob only applies to
    # the FINAL answer round, which has its own fast/think routing below.
    # finish-tool loop: force a tool call every round (tool_choice="required") so the
    # model never generates a throwaway answer. `finish` is offered alongside the
    # real tools; calling it (or emitting no real tool) ends the loop → synthesis.
    sel_tools = [*tools, _FINISH_TOOL]
    sel_msgs = lambda: _prep(convo, False)
    user_msg = next((m.get("content") for m in reversed(convo)
                     if m.get("role") == "user" and m.get("content")), "")
    # One-shot guard for the write-intent nudge below — fires at most once per
    # turn so a model that still won't call edit_workspace_document can't loop
    # forever; it falls through to a normal (honest, tool-free) answer instead.
    write_nudge_used = False
    for round_i in range(config.MAX_TOOL_ROUNDS):
        last_round = round_i == config.MAX_TOOL_ROUNDS - 1

        # Deterministic confirm-continuation: a bare "apply"/"保存して"/"はい" right
        # after a pending edit_workspace_document preview re-commits that EXACT write
        # ourselves, with confirm=True — the model never gets a chance to skip the
        # call and free-generate a "saved!" answer instead (see _pending_workspace_edit_confirm).
        pending_edit = _pending_workspace_edit_confirm(convo) if round_i == 0 else None
        # Deterministic multi-entity fan-out: on the FIRST round, if the user named ≥2
        # known entities ("compare D133, D012, D168"), issue the gather reads ourselves
        # in ONE parallel round rather than letting the model dribble them out one per
        # round (it emits a single tool_call per response under the full prompt). The
        # scheduler runs them concurrently; the loop then proceeds normally.
        expanded = [] if pending_edit else (_multi_entity_gather_calls(user_msg) if round_i == 0 else [])
        if pending_edit:
            path, content = pending_edit
            calls = [("confirm_edit_0", "edit_workspace_document",
                      json.dumps({"path": path, "content": content, "confirm": True},
                                ensure_ascii=False))]
        elif expanded:
            calls = expanded
        else:
            # tool_choice: FORCE a tool on the first round (the model must gather before
            # it can answer, and must not burn a round writing a throwaway answer). Once
            # we have evidence, relax to "auto" so the model can cleanly STOP — forcing
            # "required" every round is what makes it contort its final answer into a
            # bogus tool argument (the answer-as-arg leak) instead of just finishing.
            #
            # NB: parallel tool calls need "auto"+thinking-off (verified: "required"
            # applies XGrammar structural enforcement that caps output at ONE
            # <tool_call>). But the full operational system prompt suppresses batching
            # regardless (a minimal prompt fans out; this one emits one call even with an
            # explicit batch instruction), so keeping round-0 "required" costs no
            # parallelism we'd otherwise get, and buys the gather guarantee. Deterministic
            # fan-out for the compare pattern is handled by the expander above.
            tool_choice = "required" if not tool_log else "auto"
            try:
                resp = client.chat.completions.create(
                    model=config.MODEL, messages=sel_msgs(), tools=sel_tools,
                    tool_choice=tool_choice, temperature=0.1, **_gen_kwargs(True),
                )
            except Exception as e:  # noqa: BLE001
                print(f"⚠️ Primary server failed in tool loop ({e}). Trying fallback...")
                try:
                    resp = fallback_client.chat.completions.create(
                        model=config.FALLBACK_MODEL, messages=sel_msgs(), tools=sel_tools,
                        tool_choice=tool_choice, temperature=0.1, **_gen_kwargs(True),
                    )
                except Exception as fe:  # noqa: BLE001
                    yield {"type": "answer", "text": f"⚠️ サーバーエラー: {e} (Fallback: {fe})"}
                    return

            msg = resp.choices[0].message
            if msg.tool_calls:
                calls = [(tc.id, tc.function.name, tc.function.arguments)
                         for tc in msg.tool_calls]
            else:
                parsed = _parse_xlam(msg.content)
                calls = [(f"call_{len(tool_log) + i}", name, json.dumps(args))
                         for i, (name, args) in enumerate(parsed)] if parsed else []

        # Drop the `finish` sentinel — it is never dispatched. The model is done when
        # it calls finish (or emits no real tool) → hand to the routed synthesis round
        # (FAST→8B / THINK→27B), which generates the answer ONCE, streamed.
        real_calls = [(cid, name, args) for cid, name, args in calls if name != "finish"]
        # Guard the answer-as-arg leak: under forced tool_choice the model sometimes
        # packs its whole final answer (plus a stray <function=finish>/<tool_call> tag)
        # into a tool ARGUMENT instead of finishing. Dispatching that runs a bogus
        # query AND makes the turn generate the answer twice. Drop such calls; if
        # nothing real remains the model is effectively done → clean synthesis below.
        real_calls = [(cid, name, args) for cid, name, args in real_calls
                      if not _is_finish_leak(name, args)]
        if not real_calls:
            if tool_log:
                last_name, _, last_result = tool_log[-1]
                if last_name in _ACTION_TOOLS or last_name.startswith("generate_"):
                    yield {"type": "answer", "text": last_result}
                    return
            # The model thinks it's done (finish / no tool), but the user actually
            # asked to mutate a real file and no edit_workspace_document call has
            # happened yet this turn — that combination is exactly the bug where the
            # model free-generates a "saved!" answer with no write behind it. Nudge
            # once instead of letting it finalize.
            if (not write_nudge_used and _wants_workspace_write(user_msg)
                    and not any(name == "edit_workspace_document" for name, _, _ in tool_log)):
                write_nudge_used = True
                convo.append({"role": "system", "content": _WORKSPACE_WRITE_NUDGE})
                continue
            yield from _route_final_answer(convo, tools, tool_log, role, _fallback_answer(substantive))
            return

        convo.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": cid, "type": "function",
             "function": {"name": name, "arguments": args}}
            for cid, name, args in real_calls]})

        # Split into FRESH calls (worth running) and the rest (already gathered this
        # turn, or over the per-tool cap). Stale calls are NOT dispatched — they get
        # a terse "already have this" tool response so the model stops re-searching,
        # and they never hit the engine, the timeline, or the synthesis grounding.
        fresh, fresh_ids = [], set()
        for cid, name, args in real_calls:
            key = (name, _canon_args(args))
            # Freshness: not an exact repeat (dedup) AND this tool hasn't spiraled —
            # i.e. it hasn't run _TOOL_ROUND_CAP consecutive rounds WITHOUT producing
            # anything substantive. Distinct-entity fan-out (query_spr for D133/D012/
            # D168 across rounds) keeps returning real data, so it never trips the cap;
            # a rephrasing spiral (search X→Y→Z, all empty) trips it after two dry rounds.
            # Multiple calls of the same tool WITHIN one round all pass (fan-out intact).
            if key not in executed and tool_unproductive.get(name, 0) < _TOOL_ROUND_CAP and tool_total_rounds.get(name, 0) < 4:
                fresh.append((cid, name, args))
                fresh_ids.add(cid)

        sched_calls = [SchedToolCall(id=cid, name=name, arguments=args) for cid, name, args in fresh]
        plan = _SCHEDULER.schedule(sched_calls)

        # Drain any residual traces left over in the main thread before threading
        _trace.drain()
        _docs.drain()
        _crawl.drain()

        # Run the ExecutionPlan in parallel via the Engine
        def _ignore_events(evt: dict) -> None:
            pass
        # Snapshot generated-document ids BEFORE the run so a new file can be
        # attributed to its tool call by diffing the process-global registry. This
        # is robust across the threaded SSE path: Starlette resumes this sync
        # generator on different anyio threadpool threads between yields, so the
        # per-turn ContextVar buffer (_docs.start/drain) set on an earlier `next()`
        # is invisible here (different context) and comes back empty. registry._DOCS
        # is a plain module global shared by all threads, so the diff always sees it.
        docs_before = set(_docs._DOCS.keys())
        # Publish the live conversation so grounding-aware tools (generate_pptx/docx)
        # can ground on what's already in focus this session — a company/quote read
        # from a local file, a deal looked up earlier — instead of hallucinating.
        # Set here, in the same synchronous block as the engine run (no yield between),
        # so copy_context() in the engine carries it into the worker threads.
        _conversation.set_conversation(convo)
        bundle = _ENGINE.run(plan, _ignore_events) if fresh else None
        new_doc_ids = [d for d in _docs._DOCS if d not in docs_before]

        # Reconstruct the tool_log and yield UI events just like the sequential loop.
        # We preserve the order of `real_calls`.
        batch_id = f"batch_{id(plan)}" if len(fresh) > 1 else None

        # Per-round productivity, to update the unproductive-round spiral guard below.
        ran_fresh: set[str] = set()
        productive_fresh: set[str] = set()

        for cid, name, args in real_calls:
            key = (name, _canon_args(args))
            if cid not in fresh_ids:
                # Duplicate / over-cap: satisfy the API (every tool_call id needs a
                # response) but don't dispatch, don't surface a card, don't pad the
                # grounding — just nudge the model to answer with what it has.
                cached = executed.get(
                    key, "（取得済み。これ以上検索せず、収集済みの情報で回答してください。）")
                convo.append({"role": "tool", "tool_call_id": cid, "content": cached})
                continue

            ev_frag = bundle.get(cid) if bundle else None
            result = ev_frag.data.get("text", "[error] Missing execution result") if ev_frag else "[error] Task skipped"

            # TRUNCATE IF MASSIVE (prevents parallel calls from blowing up context
            # window). Cut on a natural boundary, not mid-string, so a fact — a company
            # name, a quote figure — isn't severed where the model then reads half of it.
            if len(result) > 1500:
                result = _truncate_on_boundary(result, 1500) + "\n... [truncated for length]"
            executed[key] = result
            # Remember genuinely informative results so the turn can always answer,
            # even if the synthesis round comes back empty (see _route_final_answer),
            # and track per-round productivity for the spiral guard.
            ran_fresh.add(name)
            if _is_substantive(result):
                productive_fresh.add(name)
                substantive.append((name, result))

            tool_log.append((name, _fmt_args(args), result))
            convo.append({"role": "tool", "tool_call_id": cid, "content": result})

            ev = {"type": "tool", "name": name, "args": _fmt_args(args), "result": result, "batchId": batch_id}

            # Since threads might have dumped into the shared contextvar (or their own),
            # this is a known limitation in M1 for tracing parallel tasks. We do a global drain here.
            # In a future phase, ToolCapability will attach traces to Evidence natively.
            retrieval = _trace.drain()
            if retrieval:
                ev["retrieval"] = retrieval
            # Attach the pages web_research browsed this round (gated on the tool so
            # crawl pages can't misattribute to a different tool in the batch). Powers
            # the browser-sim replay on the tool card.
            if name == "web_research":
                crawled = _crawl.drain()
                if crawled:
                    ev["crawl"] = crawled
            # Attach the file this call produced. A generated document is a WRITE
            # deliverable (generate_*/action tools), which the scheduler runs
            # serially — so there is at most one per round, and the newest new id
            # belongs to this terminal call.
            if new_doc_ids and (name.startswith("generate_") or name in _ACTION_TOOLS):
                doc = _docs.get(new_doc_ids[-1])
                if doc:
                    ev["document"] = {"doc_id": doc["doc_id"], "kind": doc["kind"],
                                      "filename": doc["filename"], "download_url": doc["download_url"]}
            yield ev

            if _is_terminal_action(name, result):
                # The deliverable is done (file built / meeting booked / draft made).
                # End the turn on its result so the model can't re-invoke it and
                # produce duplicates — and skip the redundant synthesis round.
                yield {"type": "answer", "text": result}
                return

        # Spiral-guard bookkeeping: a tool that produced something substantive this
        # round resets to 0; one that ran but produced nothing counts an unproductive
        # round. The cap then short-circuits only sustained DRY repetition (a rephrasing
        # spiral), never productive multi-entity fan-out.
        for name in ran_fresh:
            tool_unproductive[name] = 0 if name in productive_fresh else tool_unproductive.get(name, 0) + 1
            tool_total_rounds[name] = tool_total_rounds.get(name, 0) + 1

        # Every call this round was a repeat → the model is spinning. Stop looping
        # and synthesize from what we already gathered instead of burning rounds.
        if not fresh:
            if (not write_nudge_used and _wants_workspace_write(user_msg)
                    and not any(name == "edit_workspace_document" for name, _, _ in tool_log)):
                write_nudge_used = True
                convo.append({"role": "system", "content": _WORKSPACE_WRITE_NUDGE})
                continue
            yield from _route_final_answer(convo, tools, tool_log, role, _fallback_answer(substantive))
            return

        if last_round:
            # Hit the tool budget — force a final answer from what we have.
            if tool_log:
                last_name, _, last_result = tool_log[-1]
                if last_name in _ACTION_TOOLS or last_name.startswith("generate_"):
                    yield {"type": "answer", "text": last_result}
                    return
            yield from _route_final_answer(convo, tools, tool_log, role, _fallback_answer(substantive))
            return


def _stream_final_answer(convo: list[dict], tools: list[dict] | None, *,
                         no_think: bool = False, fallback_text: str = "",
                         label: str = "synthesis", _retry: bool = False):
    """Stream one tool-free completion as the answer, stripping any reasoning.
    Emits `delta` events live and a terminal `answer` with the full text.
    `no_think` prefills an empty think block so the reasoning distill skips its
    <think> phase and answers immediately (the dominant latency win)."""
    full, emitted = "", 0
    msgs = _prep(convo, no_think)
    synth_c, synth_m, alt_c, alt_m = _synth_route(no_think)
    try:
        stream = synth_c.chat.completions.create(
            model=synth_m, messages=msgs, temperature=config.SYNTH_TEMPERATURE,
            max_tokens=config.LLM_MAX_TOKENS, stream=True,
            stream_options={"include_usage": True}, **_gen_kwargs(no_think),
        )
    except Exception:  # noqa: BLE001 — fall back to a single blocking answer
        try:
            resp = alt_c.chat.completions.create(
                model=alt_m, messages=msgs, temperature=config.SYNTH_TEMPERATURE,
                max_tokens=config.LLM_MAX_TOKENS, **_gen_kwargs(no_think),
            )
            _usage.record_response(resp, model=alt_m, endpoint="fallback", label=label)
            text = re.sub(r"<think>.*?</think>", "",
                          resp.choices[0].message.content or "", flags=re.DOTALL).strip()
            yield {"type": "answer", "text": text or "(no response)"}
        except Exception as fe:  # noqa: BLE001
            yield {"type": "answer", "text": f"⚠️ サーバーエラー: {fe}"}
        return

    _usage_obj = None
    for chunk in stream:
        if getattr(chunk, "usage", None):
            _usage_obj = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None) if delta else None
        if not piece:
            continue
        full += piece
        # Strip any echoed reasoning span; only stream what follows it.
        if "</think>" in full:
            answer = full.split("</think>", 1)[1].lstrip("\n ")
        elif "<think>" in full:
            answer = ""
        else:
            answer = full
        new = answer[emitted:]
        if new:
            emitted += len(new)
            yield {"type": "delta", "text": new}

    _record_stream_usage(_usage_obj, msgs, full,
                         model=synth_m, endpoint="primary", label=label)
    final = re.sub(r"<think>.*?</think>", "", full, flags=re.DOTALL).strip()
    if final:
        yield {"type": "answer", "text": final}
        return
    # Empty answer — the reasoning phase ate the whole token budget, OR disabled
    # thinking broke the generation on this specific prompt (Atlas anomaly).
    # Retry ONCE with the INVERTED thinking mode.
    if not _retry:
        yield from _stream_final_answer(convo, tools, no_think=not no_think,
                                        fallback_text=fallback_text, _retry=True)
        return
    # Still empty even without thinking → surface the gathered evidence directly
    # rather than a blank turn. Only fall back to "(no response)" when we truly have
    # nothing.
    yield {"type": "answer", "text": fallback_text or "(no response)"}


def _fmt_args(arguments) -> str:
    try:
        d = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        return ", ".join(f"{k}={v!r}" for k, v in d.items())
    except Exception:
        return str(arguments)


_FINISH_LEAK_MARKERS = ("function=finish", "<tool_call>", "</think>", "</function>")
# Real tool args are short ({"deal_id":"D016"}, {"customer":"豊田製作所"}). An argument
# blob far larger than that is the model dumping its prose answer into a field.
_LEAK_ARG_LEN = 600


def _is_finish_leak(name: str, arguments) -> bool:
    """True when the model packed its final answer / a finish sentinel into a tool
    ARGUMENT instead of finishing cleanly (a `tool_choice=required` contortion). Such a
    call must not be dispatched — it runs a bogus query and double-generates the answer.
    Detected by a stray finish/think/tool_call marker or an answer-sized arg blob."""
    args = arguments if isinstance(arguments, str) else json.dumps(arguments or {}, ensure_ascii=False)
    low = args.lower()
    if any(mark in low for mark in _FINISH_LEAK_MARKERS):
        return True
    return len(args) > _LEAK_ARG_LEN


def _canon_args(arguments) -> str:
    """Order-independent, whitespace-normalized args form, for deduping tool calls
    within a turn ({"a":1,"b":2} and {"b":2,"a":1} collapse to one key)."""
    try:
        d = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        return json.dumps(d, sort_keys=True, ensure_ascii=False)
    except Exception:
        return str(arguments)


# A tool that reappears in more than this many ROUNDS in one turn is almost always
# the model spiraling (rephrasing the same query across turns). Past the cap, further
# calls are short-circuited to a "you already have this" nudge instead of a real
# dispatch. Counting rounds (not calls) still allows a single round to fan out many
# parallel calls (the "search 4 laptops at once" case).
_TOOL_ROUND_CAP = 2
````

## File: senpai/api/server.py
````python
"""FastAPI bridge — exposes the existing Senpai engines as JSON for the web UI.

Run:
    uvicorn senpai.api.server:app --reload --port 8000

Every handler is a thin serialiser over functions the Streamlit apps already
call. Nothing here changes scoring, coaching, or the knowledge pipeline; it only
reshapes their results into JSON the Next.js frontend consumes.

Design contract (kept stable for the frontend):
    GET  /api/health
    GET  /api/dashboard           team rows + KPIs + reliability flags
    GET  /api/deals/{deal_id}     one deal: signals, flags, notes, report
    POST /api/coach/review        free-text note -> a senior's reasoning scaffold
    GET  /api/coach/examples      seed notes for the demo "try one" state
    GET  /api/knowledge/principles
    GET  /api/knowledge/sources
    GET  /api/knowledge/items
    POST /api/knowledge/generate          {principle_id} -> draft item
    POST /api/knowledge/items/{id}/review {action, reviewer, notes}
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from senpai import config
from senpai.api import auth
from senpai.coach.cases import find_similar_cases
from senpai.coach.context import build_commentary_context
from senpai.coaching import coaching_workspace
from senpai.coach.profile import rep_coaching_profile, team_coaching_profiles
from senpai.coach.progress import rep_progress
from senpai.growth import junior_reps, rep_growth
from senpai.coach.review import (
    commentary_prompt,
    format_review,
    narrate_review,
    narration_prompt,
    narration_prompt_en,
    review_note,
)
from senpai.data import store
from senpai.data import chat_store
from senpai.health.flags import deal_flags
from senpai.health.scoring import score_deal
from senpai.knowledge import generate as kgen
from senpai.knowledge import review as kreview
from senpai.knowledge import store as kstore
from senpai.research import shaping as _shaping
from senpai.retrieval.playbook import find_similar_deals
from senpai.tools.web import web_search_typed

app = FastAPI(title="Senpai API", version="1.0", docs_url="/api/docs")

# The Next.js dev server runs on a different origin; allow it (and any, for the
# demo). Tighten ALLOWED_ORIGINS in production via env if needed.
_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_CHIP = {"red": "🔴", "yellow": "🟡", "green": "🟢"}

# The six reasoning lenses of the Coach, with the English chrome the UI labels
# them by. Keys match CoachReview fields; the UI renders these in order.
COACH_SECTIONS = [
    {"key": "observations", "ja": "経験豊富な営業が気づくこと", "en": "What a senior notices", "icon": "eye"},
    {"key": "missing_info", "ja": "確認できていない情報", "en": "Missing information", "icon": "search"},
    {"key": "risks", "ja": "リスクの兆候", "en": "Risk signals", "icon": "alert"},
    {"key": "questions", "ja": "次に聞くとよい質問", "en": "Questions to ask next", "icon": "message"},
    {"key": "next_actions", "ja": "取りうる次の一手", "en": "Possible next moves", "icon": "route"},
    {"key": "decision_factors", "ja": "判断に影響する要因", "en": "What should drive the choice", "icon": "scale"},
]

TEACH_NOTE = ("正解を一つ示すものではありません。先輩なら何に注目するか、"
              "その思考の型を提示します。状況に応じて自分で選んでください。")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _today() -> date:
    return config.today()


def _last_activity_date(acts: list[dict]) -> str | None:
    """Most recent activity_date for a deal (acts are newest-first)."""
    return next((a.get("activity_date") for a in acts if a.get("activity_date")), None)


def _scored_row(d: dict, today: date) -> tuple[dict, list[dict]]:
    acts = store.activities_for_deal(d["deal_id"])
    res = score_deal(d, acts, today=today)
    flags = deal_flags(d, acts, health_band=res.band, today=today)
    rep = store.rep_name(store.deal_rep_id(d))
    customer = store.customer_name(d["customer_id"])
    last = _last_activity_date(acts)
    stale_days = (today - date.fromisoformat(last)).days if last else None
    
    cd_history = d.get("close_date_history", [])
    slips = max(0, len(cd_history) - 1)
    
    row = {
        "deal_id": d["deal_id"],
        "customer": customer,
        "customer_id": d["customer_id"],
        "rep": rep,
        "stage": d.get("order_rank", ""),
        "amount": d.get("total_order_amount", 0),
        "band": res.band,
        "chip": _CHIP[res.band],
        "score": res.score,
        "days_stale": stale_days,
        "close_date": d.get("expected_order_date"),
        "slips": slips,
        "n_flags": len(flags),
        "decision_maker_identified": d.get("decision_maker_identified", False),
        "rep_close_likelihood": d.get("rep_close_likelihood"),
    }
    flag_rows = [
        {
            "deal_id": d["deal_id"],
            "customer": customer,
            "rep": rep,
            "severity": f.severity,
            "flag": f.name,
            "message": f.message,
        }
        for f in flags
    ]
    return row, flag_rows


def _build_timeline(deal_id: str, acts: list[dict]) -> list[dict]:
    """Chronological event log for a deal — Pillar 2, Experience. Folds the deal's
    sales activities, its quote, and any orders into one ascending timeline, and
    marks stretches of silence (>30 days) so juniors and managers can *see* how
    the deal actually moved. Pure read-over of existing records; the frontend
    localizes the type labels."""
    events: list[dict] = []
    for a in acts:
        d = a.get("activity_date")
        if not d:
            continue
        events.append({
            "date": d,
            "kind": "activity",
            "type": a.get("activity_type", ""),
            "title": a.get("business_card_info") or "",
            "detail": a.get("daily_report") or "",
            "amount": None,
        })
    q = store.quote_for_deal(deal_id)
    if q and q.get("quoted_at"):
        events.append({
            "date": q["quoted_at"], "kind": "quote", "type": q.get("quote_type", ""),
            "title": q.get("product_mid_category") or q.get("product_major_category") or "",
            "detail": "", "amount": q.get("quote_amount"),
        })
    for o in store.orders_for_deal(deal_id):
        if o.get("ordered_at"):
            events.append({
                "date": o["ordered_at"], "kind": "order", "type": "",
                "title": o.get("product_name") or "", "detail": o.get("supplier") or "",
                "amount": o.get("total_sales_amount"),
            })

    events.sort(key=lambda e: e["date"])

    # Insert silence markers between consecutive events more than 30 days apart.
    out: list[dict] = []
    prev: date | None = None
    for ev in events:
        try:
            cur = date.fromisoformat(ev["date"])
        except (ValueError, TypeError):
            cur = None
        if prev and cur and (cur - prev).days > 30:
            out.append({"date": prev.isoformat(), "kind": "gap", "type": "",
                        "title": "", "detail": "", "amount": None,
                        "days": (cur - prev).days})
        out.append(ev)
        if cur:
            prev = cur
    return out


def _principle_payload(p) -> dict:
    return {
        "principle_id": p.principle_id,
        "statement": p.statement,
        "tags": p.tags,
        "status": p.status,
        "interview_ids": p.interview_ids,
        "n_interviews": len(p.interview_ids),
        "support": [asdict(c) for c in p.support],
        "corroborating_surveys": [asdict(c) for c in p.corroborating_surveys],
        "added_by": p.added_by,
        "added_at": p.added_at,
    }


def _item_payload(it) -> dict:
    p = kstore.get_principle(it.provenance.principle_id)
    d = it.to_dict()
    d["confidence"] = it.confidence(p)
    d["principle_statement"] = p.statement if p else ""
    d["n_interviews"] = len(p.interview_ids) if p else 0
    return d


# ---------------------------------------------------------------------------
# system
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok", "today": _today().isoformat(),
            "pinned": bool(os.environ.get("SENPAI_TODAY"))}


# ---------------------------------------------------------------------------
# auth — simple demo signup/login (persisted, hashed accounts; see senpai.api.auth)
# ---------------------------------------------------------------------------
class SignupRequest(BaseModel):
    username: str          # login handle
    password: str
    name: str              # the new rep's display name
    manager_id: str        # the existing senior/expert they report to


class LoginRequest(BaseModel):
    username: str
    password: str


def _manager_pool() -> list[dict]:
    """The senior/expert reps a new junior can report to — the assignable manager
    pool. Any senior/expert qualifies (assignment is org-based via reports_to,
    not derived from existing coaching threads)."""
    return [{"employee_id": r["employee_id"], "name": r["name"], "role": r["role"],
             "department": r.get("department", ""), "division": r.get("division", "")}
            for r in store.all_reps() if r.get("role") in ("senior", "expert")]


@app.get("/api/reps/managers")
def reps_managers():
    """The manager pool for the junior signup picker: who's your manager?"""
    return {"managers": _manager_pool()}


@app.post("/api/auth/signup")
def auth_signup(req: SignupRequest):
    """Register a NEW junior. Creates a fresh seed-shape junior rep (no deals or
    coaching yet), assigned to an existing manager (reports_to), then an account
    linked to it. 400 on blank fields, a taken username, or an invalid manager.

    The new rep inherits the manager's department/division so it slots into the
    org cleanly. See store.append_rep / store.next_employee_id."""
    name, username = (req.name or "").strip(), (req.username or "").strip()
    if not name or not username or not req.password:
        raise HTTPException(400, "name, username and password are required")
    manager = store.get_rep(req.manager_id)
    if manager is None or manager.get("role") not in ("senior", "expert"):
        raise HTTPException(400, "choose your manager")
    if auth.username_exists(username):
        raise HTTPException(400, "username already taken")

    employee_id = store.next_employee_id()
    store.append_rep({
        "employee_id": employee_id,
        "name": name,
        "role": "junior",
        "department": manager.get("department", ""),
        "division": manager.get("division", ""),
        "specialty_tags": [],
        "is_top_performer": False,
        "reports_to": req.manager_id,
    })
    try:
        user = auth.create_user(username, req.password, "junior", employee_id=employee_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"token": auth.issue_token(), **user}


@app.post("/api/auth/login")
def auth_login(req: LoginRequest):
    """Authenticate. 401 on bad credentials. Returns a session token plus the
    account's username, role, and employee_id (role picks the experience; the
    employee_id scopes the data to that rep)."""
    user = auth.verify_user(req.username, req.password)
    if user is None:
        raise HTTPException(401, "invalid username or password")
    return {"token": auth.issue_token(), **user}


# ---------------------------------------------------------------------------
# documents — download a file the chatbot generated (PPTX/DOCX)
# ---------------------------------------------------------------------------
_DOC_MEDIA = {
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@app.get("/api/documents/{doc_id}")
def download_document(doc_id: str):
    """Serve a generated document by id. Only files in the registry are reachable —
    the endpoint never accepts a raw path. The chat tool event carries the doc_id."""
    from senpai.documents import registry
    rec = registry.get(doc_id)
    if rec is None or not os.path.exists(rec["path"]):
        raise HTTPException(404, f"document {doc_id} not found")
    ext = os.path.splitext(rec["filename"])[1].lower()
    return FileResponse(rec["path"], filename=rec["filename"],
                        media_type=_DOC_MEDIA.get(ext, "application/octet-stream"))


# ---------------------------------------------------------------------------
# dashboard
# ---------------------------------------------------------------------------
@app.get("/api/dashboard")
def dashboard(rep: str | None = None, manager: str | None = None):
    today = _today()
    # A manager sees only their team (coachees + assigned juniors); None = all.
    team = {store.rep_name(e) for e in store.team_of(manager)} if manager else None
    rows, flagged = [], []
    for d in store.open_deals():
        if team is not None and store.rep_name(store.deal_rep_id(d)) not in team:
            continue
        row, frows = _scored_row(d, today)
        rows.append(row)
        flagged.extend(frows)
    if rep and rep != "(all)":
        rows = [r for r in rows if r["rep"] == rep]
        flagged = [f for f in flagged if f["rep"] == rep]

    order = {"high": 0, "medium": 1, "low": 2}
    flagged.sort(key=lambda r: order.get(r["severity"], 3))
    reps = sorted(team) if team is not None else \
        sorted({store.rep_name(store.deal_rep_id(d)) for d in store.open_deals()})
    kpis = {
        "open_deals": len(rows),
        "at_risk": sum(1 for r in rows if r["band"] == "red"),
        "watch": sum(1 for r in rows if r["band"] == "yellow"),
        "healthy": sum(1 for r in rows if r["band"] == "green"),
        "flagged_reports": len(flagged),
        "pipeline_total": sum(r["amount"] for r in rows),
    }
    return {"today": today.isoformat(), "kpis": kpis, "deals": rows,
            "flags": flagged, "reps": reps}


@app.get("/api/deals/{deal_id}")
def deal_detail(deal_id: str):
    d = store.get_deal(deal_id)
    if d is None:
        raise HTTPException(404, f"deal {deal_id} not found")
    today = _today()
    acts = store.activities_for_deal(deal_id)
    res = score_deal(d, acts, today=today)
    flags = deal_flags(d, acts, health_band=res.band, today=today)
    return {
        "deal": {
            "deal_id": d["deal_id"],
            "customer": store.customer_name(d["customer_id"]),
            "customer_id": d["customer_id"],
            "rep": store.rep_name(store.deal_rep_id(d)),
            "stage": d.get("order_rank", ""),
            "amount": d.get("total_order_amount", 0),
            "expected_close_date": d.get("expected_order_date"),
            "last_contact_date": _last_activity_date(acts),
            "decision_maker_identified": d.get("decision_maker_identified", False),
            "rep_close_likelihood": d.get("rep_close_likelihood"),
            "close_date_history": d.get("close_date_history", []),
            "stage_history": d.get("stage_history", []),
            "products": [d["product_category"]] if d.get("product_category") else [],
        },
        "score": res.score,
        "band": res.band,
        "signals": [asdict(s) for s in sorted(res.signals, key=lambda x: x.points, reverse=True)],
        "flags": [asdict(f) for f in flags],
        "notes": [
            {
                "note_id": f"{deal_id}-{i}",
                "date": a.get("activity_date"),
                "channel": a.get("activity_type", ""),
                "text": a.get("daily_report", ""),
            }
            for i, a in enumerate(acts)
        ],
        "timeline": _build_timeline(deal_id, acts),
        "report": None,
    }


# ---------------------------------------------------------------------------
# coach
# ---------------------------------------------------------------------------
class CoachRequest(BaseModel):
    note: str
    deal_id: str | None = None
    narrate: bool = False
    lang: str = "ja"  # narration output language ("ja" | "en") — presentation only
    conversation_id: str | None = None  # reuse a built context across re-narrates

class TranslateRequest(BaseModel):
    text: str
    target_lang: str

@app.post("/api/translate")
def translate_text(req: TranslateRequest):
    from senpai.llm.client import simple_complete
    prompt = f"Translate the following text to {req.target_lang}. Return ONLY the translated text. Do not include any other commentary. Original text:\n\n{req.text}"
    translated = simple_complete([{"role": "user", "content": prompt}], temperature=0.0)
    return {"translated_text": translated}


# Optional LLM narration. Off unless SENPAI_USE_LLM is truthy, so the coach
# stays deterministic by default; when on, the served model only *rephrases*
# the deterministic findings (never adds facts), with fallback baked in.
USE_LLM = os.environ.get("SENPAI_USE_LLM", "0").lower() not in ("0", "false", "", "no")


@app.post("/api/coach/review")
@app.post("/api/coach/review")
def coach_review(req: CoachRequest):
    deal = store.get_deal(req.deal_id) if req.deal_id else None
    acts = store.activities_for_deal(req.deal_id) if deal else None
    r = review_note(req.note, deal=deal, notes=acts, report=None)

    # Phase 3: Data vs Reality Check intercept
    reality_check_text = None
    if deal and acts is not None:
        today = _today()
        res = score_deal(deal, acts, today=today)
        flags = deal_flags(deal, acts, health_band=res.band, today=today)
        
        has_optimism_mismatch = any(f.name == "optimism_mismatch" for f in flags)
        rep_likelihood = deal.get("rep_close_likelihood")
        
        if has_optimism_mismatch or (rep_likelihood == "high" and res.band == "red"):
            flag_msgs = [f.message for f in flags if f.name == "optimism_mismatch"]
            reason = flag_msgs[0] if flag_msgs else "担当の見込みとデータの健全度が食い違っています。"
            reality_check_text = f"🚨 データと実態のズレを検知: {reason} 抜け漏れがないか再確認してください。"

    # Phase 1 & 2: Account Context Resolution
    from senpai.matsuda import build_account_context
    customer = None
    if deal:
        customer = store.get_customer(deal.get("customer_id"))
    else:
        customer = store.match_customer_in_text(req.note)

    account_context_payload = None
    if customer:
        try:
            ctx = build_account_context(customer["customer_id"])
            account_context_payload = ctx.to_llm_payload()
        except Exception:
            pass

    narration = None
    llm_model = None
    if USE_LLM and req.narrate:
        out = narrate_review(r, use_llm=True)
        if out and out.strip() != format_review(r).strip():
            narration = out
            llm_model = config.MODEL

    sections = list(COACH_SECTIONS)
    result_dict = {s["key"]: getattr(r, s["key"]) for s in COACH_SECTIONS}

    if reality_check_text:
        sections.insert(0, {
            "key": "reality_check",
            "ja": "データと実態のズレ",
            "en": "Data vs Reality Check",
            "icon": "alert"
        })
        result_dict["reality_check"] = [reality_check_text]

    ctx_text, ctx_meta = build_commentary_context(
        req.note, deal_id=req.deal_id, today=_today(), lang=req.lang)

    return {
        "teach_note": TEACH_NOTE,
        "sections": sections,
        "used_deal": r.used_deal,
        "result": result_dict,
        "narration": narration,
        "llm_model": llm_model,
        "account_context": account_context_payload,
        "resolution": {
            "customer": ctx_meta.get("customer"),
            "deal_id": ctx_meta.get("deal_id"),
            "confidence": ctx_meta.get("confidence", "none"),
            "match_method": ctx_meta.get("match_method", "none"),
            "grounded": ctx_meta.get("has_customer_context", False),
        },
        "explanations": [e.to_dict() for e in getattr(r, "explanations", [])],
    }


def _sse(obj: dict) -> str:
    """Encode one Server-Sent Event frame."""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


# Reasoning tags vary by sampling: the model emits either <think> or <thinking>
# (and the matching close). Match both spellings so a reasoning block is never
# leaked into the user-facing answer.
# Reasoning markers this distilled model may emit before its actual answer.
# Besides <think>/<thinking> it sometimes wraps its scratchpad in <analysis> or
# <reasoning> — all must be stripped so the chain-of-thought never leaks into a
# senior's read or a research summary.
_THINK_CLOSE = re.compile(r"</(?:think(?:ing)?|analysis|reasoning)>", re.IGNORECASE)
_THINK_OPEN = re.compile(r"<(?:think(?:ing)?|analysis|reasoning)>", re.IGNORECASE)


def _strip_reasoning(full: str) -> str | None:
    """The answer portion of a partial stream with any reasoning block removed.

    Returns None while still inside an unclosed <think>/<thinking> block (the
    caller surfaces a 'thinking' indicator); otherwise the visible answer text."""
    m = _THINK_CLOSE.search(full)
    if m:
        return full[m.end():].lstrip("\n -")
    if _THINK_OPEN.search(full):
        return None
    return full


@app.post("/api/coach/narrate")
def coach_narrate(req: CoachRequest):
    """Stream the Senior Commentary token-by-token (SSE).

    This is an experienced rep's *interpretation* layered on the deterministic
    coach — grounded in a retrieved business-context package (customer, deal
    health, activity, history, similar cases), NOT a restatement of the lenses.
    Reasoning is OFF by default (fast live path); set SENPAI_NARRATE_THINK=1 to let
    the model think first (slower, richer) — either way any <think>/<thinking>
    block is stripped before streaming. The request is pinned to the primary GGUF
    endpoint — on any failure we emit an explicit `unavailable`. Event types:
      start | context | thinking | delta | done | unavailable
    The frontend renders deltas live and shows "Senior commentary unavailable" on
    `unavailable`."""
    if not USE_LLM:
        return StreamingResponse(
            iter([_sse({"type": "unavailable", "reason": "llm_disabled"})]),
            media_type="text/event-stream",
        )

    # Conversation cache: re-narrating the SAME deal+note in a session reuses the
    # already-built deterministic context package (review_note + commentary context)
    # instead of recomputing it. The build is cheap, but caching keeps the grounded
    # context byte-identical across re-narrates and signals provenance to the UI.
    conversation_id = (req.conversation_id or "default").strip() or "default"
    cache = _COACH_CONTEXTS.get(conversation_id)
    cached_flag = bool(cache and cache["deal_id"] == req.deal_id and cache["note"] == req.note
                       and cache["lang"] == req.lang)
    if cached_flag:
        r, context_text, ctx_meta = cache["r"], cache["context_text"], cache["meta"]
    else:
        deal = store.get_deal(req.deal_id) if req.deal_id else None
        acts = store.activities_for_deal(req.deal_id) if deal else None
        r = review_note(req.note, deal=deal, notes=acts, report=None)
        context_text, ctx_meta = build_commentary_context(
            req.note, deal_id=req.deal_id, today=_today(), lang=req.lang)
        _COACH_CONTEXTS[conversation_id] = {
            "deal_id": req.deal_id, "note": req.note, "lang": req.lang,
            "r": r, "context_text": context_text, "meta": ctx_meta}
    prompt = commentary_prompt(req.note, r, context_text,
                               ctx_meta["has_customer_context"], lang=req.lang,
                               customer_name=ctx_meta.get("customer"),
                               deal_id=ctx_meta.get("deal_id"))

    # Workspace continuity: a grounded review puts its deal/customer "in focus" for
    # the shared conversation, so a follow-up chat turn stays scoped to it.
    if ctx_meta.get("has_customer_context"):
        _seed_chat_focus(conversation_id, ctx_meta.get("customer_id"),
                         ctx_meta.get("customer"), ctx_meta.get("deal_id"))

    def gen():
        from senpai.llm import client
        yield _sse({"type": "start", "model": config.MODEL,
                    "endpoint": config.BASE_URL, "conversation_id": conversation_id})
        # Workspace: this stream produces a `review` artifact. Entity is the
        # resolved deal when one was grounded (deterministic; never a name guess).
        _meta = {"type": "artifact_meta", "kind": "review"}
        if ctx_meta.get("deal_id"):
            _meta["entity_ref"] = {"type": "deal", "id": ctx_meta["deal_id"],
                                   "name": ctx_meta.get("customer")}
        yield _sse(_meta)
        # Tell the UI what real records the read is grounded in (or that none matched).
        yield _sse({"type": "context", "grounded": ctx_meta["has_customer_context"],
                    "customer": ctx_meta["customer"], "deal_id": ctx_meta["deal_id"],
                    "confidence": ctx_meta.get("confidence", "none"),
                    "match_method": ctx_meta.get("match_method", "none"),
                    "candidates": ctx_meta.get("ambiguous_candidates", []),
                    "cached": cached_flag})
        # Customer still unresolved (the note named an ambiguous / near-miss
        # company). Don't generate a senior's read yet — the rep must first pick
        # which customer. Generating now would (a) waste a ~15s call on a read the
        # rep discards, and (b) show a read before the choice is even made. Stop
        # after the candidates; the pick re-runs this grounded.
        if not ctx_meta["has_customer_context"] and ctx_meta.get("ambiguous_candidates"):
            yield _sse({"type": "awaiting_choice"})
            yield _sse({"type": "done", "model": config.MODEL})
            return
        full, emitted, last_think = "", 0, 0
        try:
            for piece in client.stream_complete(
                [{"role": "user", "content": prompt}],
                temperature=0.5, max_tokens=config.LLM_NARRATE_MAX_TOKENS,
                no_think=not config.NARRATE_THINK, allow_fallback=False,
            ):
                full += piece
                answer = _strip_reasoning(full)                 # hide any reasoning block
                if answer:
                    new = answer[emitted:]
                    if new:
                        emitted += len(new)
                        yield _sse({"type": "delta", "text": new})
                elif answer is None and len(full) - last_think >= 48:
                    last_think = len(full)
                    yield _sse({"type": "thinking", "chars": len(full)})
            if emitted:
                yield _sse({"type": "done", "model": config.MODEL})
            else:
                # Reasoning consumed the whole budget before any answer token (a
                # long <think> block on a contended GPU). Retry once with thinking
                # off so the rep always gets a grounded read, never a blank.
                fb, fb_emitted = "", 0
                for piece in client.stream_complete(
                    [{"role": "user", "content": prompt}],
                    temperature=0.5, max_tokens=config.LLM_NARRATE_MAX_TOKENS,
                    no_think=True, allow_fallback=False,
                ):
                    fb += piece
                    ans = _strip_reasoning(fb)
                    new = ans[fb_emitted:] if ans else ""
                    if new:
                        fb_emitted += len(new)
                        yield _sse({"type": "delta", "text": new})
                if fb_emitted:
                    yield _sse({"type": "done", "model": config.MODEL})
                else:
                    yield _sse({"type": "unavailable", "reason": "empty"})
        except Exception:  # noqa: BLE001 — primary endpoint down/timeout (no fallback)
            yield _sse({"type": "unavailable", "reason": "unreachable"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# chat — the tool-calling assistant (junior / manager), streamed over SSE
# ---------------------------------------------------------------------------
# This exposes the SAME tool loop the Streamlit/Gradio chats use (stream_turn +
# the role-scoped tool schemas) to the web product. The model autonomously calls
# the deterministic sales tools — and web_search — grounding every answer in
# store data. Tools are imported here; the openai-backed client is imported
# lazily inside the generator so this module stays importable without a server.
from senpai.tools.schemas import JUNIOR_TOOLS, MANAGER_TOOLS, RESEARCH_TOOLS


# Concise system prompts (mirror senpai/apps/*_chat.py; inlined so we don't import
# gradio). today() is read per-request so a pinned SENPAI_TODAY is respected.
def _junior_system() -> str:
    return (
        "あなたは大塚商会の新人営業を支える『先輩(senpai)』アシスタントです。"
        "社内営業の専門アシスタントであると同時に、汎用アシスタントとしても役立ちます。\n"

        "【社内・顧客・案件・製品に関する質問】"
        "必ずツール(query_spr / search_knowledge / search_products / score_deal_health など)で"
        "社内データ(SPR・プレイブック・顧客環境・案件健全度)を確認してから答えてください。"
        "「どう対応すべきか」を問われたら、まず search_knowledge で社内ナレッジ"
        "(先輩の原則・承認済み事例・プレイブック)を引き、指定された構造化出典ID（例: Playbook PB12）を"
        "そのまま添えること。顧客・会社・製品・案件に関する質問は、回答前に必ず query_spr / "
        "search_knowledge / search_products のいずれかを呼び出して確認すること。"
        "ツールを呼ばずに『社内データに無い』と述べてはいけません。"
        "社内の数値は与えられたものだけを使い、人名や提供者名は絶対に推測・生成しないこと。"
        "製品の相談には search_products / create_quote、訪問調整には schedule_meeting、"
        "連絡文の準備には send_email を使えます(いずれも下書きで、送信・確定はしません)。"
        "社内案件で自信が持てない時は route_to_expert で先輩に橋渡ししてください。"
        "ツールが必要な操作（予定調整・見積作成・検索・社内データ確認など）では、"
        "『〜します』と手順を説明したり、呼び出し内容を文章で書き出したりせず、"
        "直接ツールを呼び出すこと。ツール結果が返ってから簡潔に回答する。"
        "独立した複数の情報が必要なときは、ツールを1つずつ順番に呼ばず、"
        "1ターンでまとめて並行呼び出しして往復回数を減らすこと。\n"

        "【文書作成（PPTX / DOCX）】\n"
        "提案書、稟議書、スライド(PPTX)、文書(DOCX)の作成を依頼されたら、"
        "絶対に口頭で「作成してよいですか？」と許可を求めるのではなく、**直ちに該当ツールを `confirm=False` で呼び出してプレビューを出力**してください。\n"
        "プレビューを見たユーザーが「はい」「作成して」と同意したターンでは、**直ちに同じツールを `confirm=True` で呼び出し**、ファイルを生成してください。\n"
        "ツールを使わずにプレビューを自作（ハルシネーション）したり、Pythonコードを出力することは固く禁じます。\n"

        "【一般的な質問（社外の事実・為替・市場価格・一般知識など）】"
        "汎用アシスタントとして、断らずに役立つ回答をしてください。"
        "市場価格・在庫・為替レート・ニュース・最新の製品仕様や型番など、時間とともに変わる"
        "事実や具体的な数値は、記憶から答えてはいけない。必ず web_search を呼び、結果の出典(URL)"
        "を添えて回答すること。web_search を呼べない/結果が得られない場合はその旨を明示し、"
        "不確かな価格・型番・数値を創作しないこと。"
        "用語の定義や一般的な概念など、時間で変わらない安定した知識のみ、あなたの知識で直接答えてよい。"
        "『社内データに無い』という理由だけで一般的な質問を断ってはいけません。\n"

        "【口調】"
        "経験豊富な先輩として、新人に寄り添い『なぜそうするのか』まで噛み砕いて教える、"
        "丁寧で面倒見のよい語り口。一歩先輩の視点で導く。\n"

        "【共通】"
        "質問の言語に合わせて回答する（英語の質問には英語で答える）。"
        "回答は読みやすいMarkdownで整える: 区切りには短い**太字の見出しラベル**"
        "（例: **状況:** …）や見出しを使い、列挙は箇条書きにし、簡潔かつ実務的にまとめる。"
        f"本日は {_today().isoformat()} です。"
    )


def _manager_system() -> str:
    return (
        "あなたは大塚商会の営業マネージャーを支えるアシスタントです。"
        "チーム運営の専門アシスタントであると同時に、汎用アシスタントとしても役立ちます。\n"

        "【チーム・案件・社内データに関する質問】"
        "チーム全体の案件健全度・日報・パイプラインを把握し、リスクの高い案件や"
        "コーチングが必要な担当を、必ずツールで取得した社内データに基づいて示します。"
        "数字は与えられたものだけを使い、創作しないこと。コーチングの根拠は "
        "search_knowledge で社内ナレッジ(先輩の原則・承認済み事例・プレイブック)を引き、"
        "指定された構造化出典ID（例: Playbook PB12）をそのまま添えて示すこと。"
        "絶対に人名や提供者名を推測・生成しないでください。"
        "製品の確認や見積例には search_products / create_quote、"
        "調整や連絡文の準備には schedule_meeting / send_email を使えます"
        "(いずれも下書きで、送信・確定はしません)。"
        "ツールが必要な操作では、『〜します』と手順を説明したり呼び出し内容を文章で"
        "書き出したりせず、直接ツールを呼び出すこと。ツール結果が返ってから簡潔に回答する。"
        "独立した複数の情報が必要なときは、ツールを1つずつ順番に呼ばず、1ターンでまとめて"
        "並行呼び出しして往復回数を減らすこと。\n"

        "【文書作成（PPTX / DOCX）】\n"
        "提案書、稟議書、スライド(PPTX)、文書(DOCX)の作成を依頼されたら、"
        "絶対に口頭で「作成してよいですか？」と許可を求めるのではなく、**直ちに該当ツールを `confirm=False` で呼び出してプレビューを出力**してください。\n"
        "プレビューを見たユーザーが「はい」「作成して」と同意したターンでは、**直ちに同じツールを `confirm=True` で呼び出し**、ファイルを生成してください。\n"
        "ツールを使わずにプレビューを自作（ハルシネーション）したり、Pythonコードを出力することは固く禁じます。\n"

        "【一般的な質問（社外の事実・為替・市場価格・一般知識など）】"
        "汎用アシスタントとして、断らずに役立つ回答をしてください。"
        "市場価格・在庫・為替レート・ニュース・最新の製品仕様など、時間とともに変わる事実や"
        "具体的な数値は記憶から答えず、必ず web_search を呼んで出典(URL)を添えること。"
        "web_search を呼べない/結果が無い場合はその旨を明示し、不確かな数値を創作しないこと。"
        "時間で変わらない安定した一般知識のみ、あなたの知識で直接答えてよい。"
        "『社内データに無い』という理由だけで一般的な質問を断ってはいけません。\n"

        "【口調】"
        "経験豊富なマネージャーを支える有能なスタッフ・アナリストとして、対等で簡潔に、"
        "要点と数字を先に出す。指導や説教はせず、相手の経験を前提に判断材料を提供することに徹する。\n"

        "【共通】"
        "質問の言語に合わせて回答する。"
        "回答は読みやすいMarkdownで整える: 区切りには短い**太字の見出しラベル**"
        "（例: **要点:** …）や見出しを使い、列挙は箇条書きにし、簡潔にまとめる。"
        f"本日は {_today().isoformat()} です。"
    )


def _research_system() -> str:
    # The research assistant answers "tell me about / research this customer"
    # questions. Strict source priority — internal first, web only to fill gaps —
    # so it stays a grounded research tool, NOT a generic chatbot.
    return (
        "あなたは大塚商会の営業担当が顧客訪問前に使う『顧客リサーチ』アシスタントです。"
        "顧客について調べる質問に、必ずツールを使って答えます。\n"
        "厳守する調査手順（この順序を逆にしないこと）:\n"
        "1. まず query_spr で社内の顧客・案件情報を確認する（英語/ローマ字の社名でも"
        "そのまま渡せば内部で名寄せされる。例: 'Aozora Services'）。\n"
        "2. 案件があれば score_deal_health で健全度、find_similar_deals で類似案件、"
        "lookup_customer_environment でIT環境、get_product_info で製品情報を補う。"
        "顧客が分かった後のこれらの補完ツールは互いに独立しているので、1つずつではなく"
        "1ターンでまとめて並行呼び出しし、往復回数を減らすこと。\n"
        "3. 社内情報で答えられない外部情報（事業内容・業界動向・競合・最新ニュース）が"
        "必要なときに限り web_search を使う。\n"
        "回答ルール: 社内データを最優先で示し、その後に外部情報を添える。"
        "社内に記録がない場合はその旨を明記し、事実を創作しない。"
        "web_search の結果は出典（URL）を添えて引用する。"
        "日本語で、要点を構造化して簡潔に答えます。"
        f"本日は {_today().isoformat()} です。"
    )


_CHAT_ROLES = {
    "junior": (JUNIOR_TOOLS, _junior_system),
    "manager": (MANAGER_TOOLS, _manager_system),
    "research": (RESEARCH_TOOLS, _research_system),
}


@dataclass
class ResearchBundle:
    query: str
    target: str
    resolution: dict
    customer: dict | None = None
    active_deal_id: str | None = None
    active_deal: dict | None = None
    deals: list[dict] = field(default_factory=list)
    activities: list[dict] = field(default_factory=list)
    environment: dict | None = None
    products: list[dict] = field(default_factory=list)
    similar_deals: list[dict] = field(default_factory=list)
    web: dict | None = None
    provenance: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


_RESEARCH_PREFIXES = [
    r"^\s*tell\s+me\s+about\s+",
    r"^\s*research\s+",
    r"^\s*background\s+on\s+",
    r"^\s*find\s+out\s+about\s+",
    r"^\s*what\s+should\s+i\s+know\s+about\s+",
    r"^\s*use\s+web_search\s+and\s+tell\s+me\s+about\s+",
    r"^\s*switch\s+to\s+",
]

_RESEARCH_CONTEXTS: dict[str, ResearchBundle] = {}
# Conversation caches (mirror _RESEARCH_CONTEXTS) so a multi-turn session keeps its
# context across turns: the Assistant remembers the account in focus; Review Coach
# reuses the built commentary-context package for the same deal instead of rebuilding.
_CHAT_CONTEXTS: dict[str, dict] = {}        # conversation_id -> {customer_id, customer, deal_id}
_COACH_CONTEXTS: dict[str, dict] = {}       # conversation_id -> {deal_id, note, r, context_text, meta}
_DEAL_ID_RE = re.compile(r"\bD\d{3}\b", flags=re.IGNORECASE)


def _seed_chat_focus(conversation_id: str | None, customer_id: str | None,
                     customer: str | None, deal_id: str | None) -> None:
    """Cross-seed the chat 'account in focus' from a skill turn (a /review or
    /account brief) so a later bare chat follow-up — "what should I do about
    this?" — stays scoped to the same customer even though the user never
    re-typed the name. This is what makes the Workspace one continuous
    conversation across skills and chat, rather than a row of isolated requests.

    Deterministic: the focus is the entity the skill already resolved (or the
    deal's own customer), never a name guess."""
    if not conversation_id:
        return
    if not customer_id and deal_id:
        d = store.get_deal(deal_id)
        if d:
            customer_id = d["customer_id"]
            customer = customer or store.customer_name(customer_id)
    if not customer_id:
        return
    _CHAT_CONTEXTS[conversation_id] = {
        "customer_id": customer_id, "customer": customer, "deal_id": deal_id}
_FOLLOWUP_RE = re.compile(
    r"^\s*(what|who|when|why|how|which|are|is|do|does|should)\b|"
    r"\b(risk|risks|decision maker|last meeting|products?|next|happened|activity|activities)\b|"
    # Japanese continuation/question cues (no word boundaries in Japanese): follow-ups
    # about the account already in focus — 次/何をすべき/リスク/直近/決裁 etc.
    r"(次|今後|何を|どう|なぜ|いつ|誰|リスク|決裁|直近|前回|製品|案件|べき|他には|では)",
    flags=re.IGNORECASE,
)


def _research_target(message: str) -> str:
    target = (message or "").strip()
    for pat in _RESEARCH_PREFIXES:
        target = re.sub(pat, "", target, flags=re.IGNORECASE)
    return target.strip(" \t\r\n?？。.")


def _deal_id_in_text(message: str) -> str | None:
    m = _DEAL_ID_RE.search(message or "")
    return m.group(0).upper() if m else None


# Explicit "look in my local files" intent. When the user scopes the question to
# their own documents, the turn should be answered from the Workspace tool and NOT
# wander into the CRM/internal-record tools — that scope-bleed is what makes a simple
# "what's in my file" spiral through query_spr/search_notes. Kept narrow: it must
# name files/documents/the workspace, not merely mention "generate a file".
_FILE_SCOPE_RE = re.compile(
    # Possessive/locative framing around files/documents — "my files", "in the
    # documents", "search my docs" — NOT bare "a document" (that's generate_docx).
    r"\b(?:my|the|these|those)\s+(?:files?|documents?|docs?)\b|"
    r"\b(?:in|from|search|read|check|open|look(?:ing)?\s+(?:in|at|through))\s+"
    r"(?:my|the|these|those)?\s*(?:files?|documents?|folder)\b|"
    r"\bworkspace\b|\blocal files?\b|"
    r"(?:私の|自分の|マイ)(?:ファイル|資料|ドキュメント|文書)|"
    r"(?:ファイル|資料|ドキュメント|文書)(?:の中|内|から|を見|を調|を検索|を確認|に|にある)|"
    r"ワークスペース|ローカル(?:ファイル|文書)",
    re.IGNORECASE,
)


# Analytical / ranking intent — questions that need CRM + scoring, not a file read.
# When present, we do NOT lock the turn to workspace-only even if it mentions "files":
# "best performing company among my files" wants analysis (deal health / SPR), which
# the local notes don't contain. Leaving file-scope off keeps ALL tools available
# (workspace AND CRM), so the model can ground on files yet still rank via CRM,
# instead of spinning on filename-only search over notes that hold no metrics.
_ANALYTICAL_RE = re.compile(
    r"\b(?:best|top|worst|highest|lowest|rank(?:ing|ed)?|compare|comparison|"
    r"which\s+(?:is|are|one|deal|company|customer)|best[- ]performing|"
    r"performance|revenue|win\s*rate|pipeline)\b|"
    r"(?:一番|最も|最高|最良|最悪|ランキング|比較|順位|パフォーマンス|業績|勝率|売上|"
    r"どれが|どちらが|どの(?:案件|会社|顧客))",
    re.IGNORECASE,
)


def _is_file_scoped(message: str) -> bool:
    msg = message or ""
    # Ranking/performance intent overrides file-scope: it needs CRM, not just files.
    if _ANALYTICAL_RE.search(msg):
        return False
    return bool(_FILE_SCOPE_RE.search(msg))


# Planner intent → the LLMPlanner (capability graph), not the ReAct loop. Covers
# document GENERATION (proposal / deck / docx …), workspace NOTE writes, and workspace
# ORGANIZE. The detection lives in senpai.planner.selection (the planner owns intent);
# these thin aliases keep the router readable and the names stable for tests. Ordinary
# tool asks ("draft an email", "make a quote", "tell me about X") stay in the chat
# loop; 稟議 (ringisho) has its own tool and is excluded.
from senpai.planner.selection import (
    is_document_goal as _is_document_goal,
    is_planner_goal as _is_planner_goal,
)


def _is_followup(message: str, has_context: bool) -> bool:
    if not has_context or _deal_id_in_text(message):
        return False
    text = (message or "").strip()
    if not text or len(text) > 220:
        return False
    if any(re.search(pat, text, flags=re.IGNORECASE) for pat in _RESEARCH_PREFIXES):
        return False
    return bool(_FOLLOWUP_RE.search(text))


# Japanese research cues. Kept narrow on purpose: paired with a customer-resolution
# check below so coaching questions ("値引きについて教えて") never get hijacked.
_RESEARCH_CUES_JA = ("について教えて", "について調べて", "のことを教えて",
                     "の情報を教えて", "を調べて", "について知りたい",
                     "リサーチ", "背景を教えて")


def _is_research_intent(message: str) -> bool:
    """True when the message is a customer-research request *and* names a customer
    we actually have. Auto-routes those turns to the source-grounded research
    pipeline; everything else stays in the tool-calling loop."""
    msg = (message or "").strip()
    has_cue = (
        any(re.search(p, msg, flags=re.IGNORECASE) for p in _RESEARCH_PREFIXES)
        or any(cue in msg for cue in _RESEARCH_CUES_JA)
    )
    if not has_cue:
        return False
    target = _research_target(msg)
    if not target:
        return False
    return store.resolve_customer_detailed(target).status in ("resolved", "ambiguous")


# Shaping helpers live canonically in senpai.research.shaping (M3 consolidation):
# these are thin server-side aliases preserving the existing call sites + the
# implicit _today() default. The bodies are no longer duplicated here.
def _public_customer(c: dict | None) -> dict | None:
    return _shaping.public_customer(c)


def _deal_summary(d: dict) -> dict:
    return _shaping.deal_summary(d, _today())


def _activity_summary(a: dict) -> dict:
    return _shaping.activity_summary(a)


def _products_for_deals(deals: list[dict]) -> list[dict]:
    return _shaping.products_for_deals(deals)


def _deal_resolution(deal: dict) -> dict:
    c = store.get_customer(deal["customer_id"])
    return {
        "status": "resolved",
        "query": deal["deal_id"],
        "customer": _public_customer(c),
        "candidates": [],
    }


def _build_deal_context_bundle(message: str, target: str, deal: dict) -> ResearchBundle:
    customer = store.get_customer(deal["customer_id"])
    raw_activities = store.activities_for_deal(deal["deal_id"])
    bundle = ResearchBundle(
        query=message,
        target=target,
        resolution=_deal_resolution(deal),
        customer=_public_customer(customer),
        active_deal_id=deal["deal_id"],
        active_deal=_deal_summary(deal),
        deals=[_deal_summary(deal)],
        activities=[_activity_summary(a) for a in raw_activities[:20]],
        environment=store.get_environment(deal["customer_id"]),
        products=_products_for_deals([deal]),
        similar_deals=[_deal_summary(d) for d in find_similar_deals(
            customer_id=deal["customer_id"],
            industry=(customer or {}).get("industry", ""),
        )[:3]],
    )
    bundle.provenance.extend([
        {"source": "active_deal_context", "priority": 1, "deal_id": deal["deal_id"]},
        {"source": "internal_records", "priority": 1, "status": "found"},
        {"source": "deals", "priority": 2, "count": 1},
        {"source": "activities", "priority": 3, "count": len(bundle.activities),
         "truncated": len(raw_activities) > len(bundle.activities)},
        {"source": "environment", "priority": 4,
         "status": "found" if bundle.environment else "not_found"},
    ])
    return bundle


def _open_deals(deals: list[dict]) -> list[dict]:
    return [d for d in deals if config.is_open_rank(d.get("order_rank"))]


def _deal_choices_answer(deals: list[dict]) -> str:
    lines = ["この顧客にはアクティブな案件が複数あります。どの案件について調べるか、案件IDで指定してください。"]
    for d in sorted(deals, key=lambda x: x.get("total_order_amount", 0), reverse=True):
        s = _deal_summary(d)
        lines.append(
            f"- {s['deal_id']}: {s['customer']} / {s['stage']} / "
            f"¥{s['amount']:,} / {s['product_category']} / health={s['health']['band']}"
        )
    return "\n".join(lines)


def _source_event(key: str, label: str, status: str, count: int | None = None,
                  detail: str = "") -> str:
    obj = {"type": "source", "key": key, "label": label, "status": status}
    if count is not None:
        obj["count"] = count
    if detail:
        obj["detail"] = detail
    return _sse(obj)


def _build_research_bundle(message: str, target: str, resolution) -> ResearchBundle:
    bundle = ResearchBundle(
        query=message,
        target=target,
        resolution=resolution.to_dict(),
        customer=_public_customer(resolution.customer),
    )
    if resolution.status != "resolved" or not resolution.customer:
        return bundle

    cid = resolution.customer["customer_id"]
    raw_deals = store.deals_for_customer(cid)
    raw_activities = store.activities_for_customer(cid)
    bundle.deals = [_deal_summary(d) for d in raw_deals]
    bundle.activities = [_activity_summary(a) for a in raw_activities[:20]]
    bundle.environment = store.get_environment(cid)
    bundle.products = _products_for_deals(raw_deals)
    bundle.similar_deals = [_deal_summary(d) for d in find_similar_deals(
        customer_id=cid, industry=resolution.customer.get("industry", ""))[:3]]
    bundle.provenance.extend([
        {"source": "internal_records", "priority": 1, "status": "found"},
        {"source": "deals", "priority": 2, "count": len(bundle.deals)},
        {"source": "activities", "priority": 3, "count": len(bundle.activities),
         "truncated": len(raw_activities) > len(bundle.activities)},
        {"source": "environment", "priority": 4,
         "status": "found" if bundle.environment else "not_found"},
    ])
    return bundle


# --- Orchestration-backed builders (M1) -------------------------------------
# Same signatures and identical output as the two legacy builders above, but the
# gather runs on the orchestration engine (six research capabilities, a small DAG)
# instead of an inline sequence. The legacy builders are kept as the parity oracle
# for the golden tests (tests/test_research_parity.py); these are what the live
# `/research` path calls. See senpai.research and docs/orchestration-architecture.md.
def _build_research_bundle_orch(message: str, target: str, resolution) -> ResearchBundle:
    if resolution.status != "resolved" or not resolution.customer:
        return ResearchBundle(query=message, target=target,
                              resolution=resolution.to_dict(),
                              customer=_public_customer(resolution.customer))
    from senpai.research import research_bundle_fields
    fields = research_bundle_fields(
        mode="customer", query=message, target=target,
        resolution=resolution.to_dict(), customer=_public_customer(resolution.customer),
        customer_id=resolution.customer["customer_id"], deal_id=None,
        industry=resolution.customer.get("industry", ""), today=_today())
    return ResearchBundle(**fields)


def _build_deal_context_bundle_orch(message: str, target: str, deal: dict) -> ResearchBundle:
    from senpai.research import research_bundle_fields
    customer = store.get_customer(deal["customer_id"])
    fields = research_bundle_fields(
        mode="deal", query=message, target=target, resolution=_deal_resolution(deal),
        customer=_public_customer(customer), customer_id=deal["customer_id"],
        deal_id=deal["deal_id"], industry=(customer or {}).get("industry", ""),
        today=_today())
    return ResearchBundle(**fields)


def _research_summary_prompt(bundle: ResearchBundle) -> str:
    return (
        "You are Senpai's customer research summarizer for Otsuka salespeople.\n"
        "Use ONLY the JSON evidence bundle below. Do not add facts from memory.\n"
        "Internal records have higher priority than web results. If web results are present, "
        "label them as external. If internal records are missing, say that clearly.\n"
        "Answer in concise Japanese with sections useful before a sales conversation.\n\n"
        f"Evidence bundle:\n{json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2)}"
    )


def _ambiguity_answer(candidates: list[dict]) -> str:
    lines = ["該当する可能性のある顧客が複数あります。誤った顧客情報を使わないため、候補を選んでください。"]
    for c in candidates:
        aliases = "、".join(c.get("matched_aliases") or [])
        suffix = f"（一致: {aliases}）" if aliases else ""
        lines.append(f"- {c.get('customer_id')}: {c.get('name')}{suffix}")
    return "\n".join(lines)


def _emit_bundle_sources(bundle: ResearchBundle, cached: bool = False):
    yield _source_event("internal_records", "Internal Records", "found", count=1,
                        detail="cached" if cached else "")
    yield _source_event("deals", "Deals", "found" if bundle.deals else "not_found",
                        count=len(bundle.deals), detail="cached" if cached else "")
    yield _source_event("activities", "Activities",
                        "found" if bundle.activities else "not_found",
                        count=len(bundle.activities), detail="cached" if cached else "")
    yield _source_event("environment", "Environment",
                        "found" if bundle.environment else "not_found",
                        detail="cached" if cached else "")
    yield _source_event("web_search", "Web Search", "skipped",
                        detail="active_deal_context" if bundle.active_deal_id else "internal_record_found")


def _summarize_research_bundle(bundle: ResearchBundle):
    try:
        from senpai.llm.client import stream_complete, fallback_client, _synth_route
        # Research summaries are always FAST grounded restatement → a hybrid 8B
        # target. Surface which model synthesizes (FAST→8B when the flag is on).
        _sc, _sm, _, _ = _synth_route(True)
        yield _sse({"type": "synth", "model_id": _sm,
                    "tier": "8B" if _sc is fallback_client else "27B", "no_think": True})
        text = ""
        for piece in stream_complete(
            [{"role": "user", "content": _research_summary_prompt(bundle)}],
            temperature=0.2,
            max_tokens=config.LLM_MAX_TOKENS,
            no_think=True,
            allow_fallback=False,
            fast_decomp=True,
        ):
            text += piece
        text = (_strip_reasoning(text) or "").strip()
        yield _sse({"type": "answer", "text": text or "リサーチ結果を生成できませんでした。"})
        yield _sse({"type": "done", "model": config.MODEL})
    except Exception:  # noqa: BLE001 - research must not silently use fallback
        yield _sse({"type": "unavailable", "reason": "llm_unreachable"})
        yield _sse({"type": "done", "model": config.MODEL})


def research_stream(req: ChatRequest):
    conversation_id = (getattr(req, "conversation_id", None) or "default").strip() or "default"
    cached_bundle = _RESEARCH_CONTEXTS.get(conversation_id)
    target = _research_target(req.message)
    deal_id = _deal_id_in_text(req.message)
    use_cached = _is_followup(req.message, bool(cached_bundle))

    yield _sse({"type": "start", "model": config.MODEL,
                "endpoint": config.BASE_URL, "role": "research",
                "conversation_id": conversation_id})
    # Workspace: this stream produces a `research` artifact. Entity (if any) is
    # surfaced later via the resolve/context events as the customer is grounded.
    yield _sse({"type": "artifact_meta", "kind": "research"})

    if use_cached and cached_bundle:
        cached_bundle.query = req.message
        yield _sse({"type": "context", "status": "active",
                    "conversation_id": conversation_id,
                    "deal_id": cached_bundle.active_deal_id,
                    "customer": cached_bundle.customer,
                    "cached": True})
        for ev in _emit_bundle_sources(cached_bundle, cached=True):
            yield ev
        yield from _summarize_research_bundle(cached_bundle)
        return

    if deal_id:
        deal = store.get_deal(deal_id)
        if not deal:
            yield _sse({"type": "resolve", "status": "not_found", "query": deal_id,
                        "customer": None, "candidates": []})
            yield _source_event("internal_records", "Internal Records", "not_found")
            yield _sse({"type": "unavailable", "reason": "deal_not_found"})
            yield _sse({"type": "done", "model": config.MODEL})
            return
        bundle = _build_deal_context_bundle_orch(req.message, deal_id, deal)
        _RESEARCH_CONTEXTS[conversation_id] = bundle
        yield _sse({"type": "resolve", **bundle.resolution})
        yield _sse({"type": "context", "status": "active",
                    "conversation_id": conversation_id, "deal_id": deal_id,
                    "customer": bundle.customer, "cached": False})
        for ev in _emit_bundle_sources(bundle):
            yield ev
        yield _sse({"type": "deal_ids", "deal_ids": [deal_id]})
        yield from _summarize_research_bundle(bundle)
        return

    resolution = store.resolve_customer_detailed(target)
    if resolution.status == "not_found":
        # The target may be an action/verb-wrapped request ("create a quotation
        # for akebono") rather than a bare name. Locate the customer named inside
        # the message so we hit internal records (and surface ambiguity) instead
        # of falling through to a web search.
        in_text = store.resolve_customer_in_text(req.message)
        if in_text.status != "not_found":
            resolution = in_text
    res_obj = resolution.to_dict()
    yield _sse({"type": "resolve", **res_obj})

    if resolution.status == "ambiguous":
        yield _source_event("internal_records", "Internal Records", "ambiguous",
                            count=len(res_obj["candidates"]))
        yield _source_event("deals", "Deals", "skipped")
        yield _source_event("activities", "Activities", "skipped")
        yield _source_event("environment", "Environment", "skipped")
        yield _source_event("web_search", "Web Search", "skipped",
                            detail="ambiguous_customer")
        # No textual "which one?" answer: the `resolve` candidates above drive a
        # deterministic picker in the UI (both the /research card and the chat
        # bubble). Emitting an answer too would duplicate the picker as a redundant
        # markdown table — and would pre-empt the picker before the rep has chosen.
        yield _sse({"type": "done", "model": config.MODEL})
        return

    if resolution.status == "resolved" and resolution.customer:
        raw_deals = store.deals_for_customer(resolution.customer["customer_id"])
        active_deals = _open_deals(raw_deals)
        if len(active_deals) > 1:
            yield _source_event("internal_records", "Internal Records", "found", count=1)
            yield _source_event("deals", "Deals", "ambiguous", count=len(active_deals),
                                detail="multiple_active_deals")
            yield _source_event("activities", "Activities", "skipped")
            yield _source_event("environment", "Environment", "skipped")
            yield _source_event("web_search", "Web Search", "skipped",
                                detail="select_deal_first")
            yield _sse({"type": "deal_choices", "status": "ambiguous",
                        "deals": [_deal_summary(d) for d in active_deals]})
            yield _sse({"type": "answer", "text": _deal_choices_answer(active_deals)})
            yield _sse({"type": "done", "model": config.MODEL})
            return
        if len(active_deals) == 1:
            bundle = _build_deal_context_bundle_orch(req.message, target, active_deals[0])
            _RESEARCH_CONTEXTS[conversation_id] = bundle
            yield _sse({"type": "context", "status": "active",
                        "conversation_id": conversation_id,
                        "deal_id": bundle.active_deal_id,
                        "customer": bundle.customer,
                        "cached": False})
            for ev in _emit_bundle_sources(bundle):
                yield ev
            yield _sse({"type": "deal_ids", "deal_ids": [bundle.active_deal_id]})
            yield from _summarize_research_bundle(bundle)
            return

    bundle = _build_research_bundle_orch(req.message, target, resolution)

    if resolution.status == "resolved":
        for ev in _emit_bundle_sources(bundle):
            yield ev
        # Emit deal ids so the client can show them in the evidence drawer.
        if bundle.deals:
            deal_ids = [d["deal_id"] for d in bundle.deals if d.get("deal_id")]
            if deal_ids:
                yield _sse({"type": "deal_ids", "deal_ids": deal_ids})
    else:
        yield _source_event("internal_records", "Internal Records", "not_found")
        yield _source_event("deals", "Deals", "skipped")
        yield _source_event("activities", "Activities", "skipped")
        yield _source_event("environment", "Environment", "skipped")
        # Web fallback stays on the direct seam (web_search_typed): it is a single
        # external call, not gather orchestration, and existing tests patch this
        # symbol. The engine-backed WebCapability is exercised by the golden tests.
        web = web_search_typed(f"{target} company overview latest news")
        bundle.web = web
        bundle.provenance.append({"source": "web_search", "priority": 2,
                                  "status": web.get("status"), "query": web.get("query")})
        yield _sse({"type": "web", **web})
        yield _source_event("web_search", "Web Search",
                            "found" if web.get("status") == "found" else "error",
                            count=len(web.get("results") or []),
                            detail=web.get("reason", ""))
        if web.get("status") != "found":
            yield _sse({"type": "unavailable",
                        "reason": "no_internal_record_and_web_unavailable"})
            yield _sse({"type": "done", "model": config.MODEL})
            return

    yield from _summarize_research_bundle(bundle)


class ChatMessage(BaseModel):
    role: str       # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []          # prior user/assistant turns (no system)
    role: str = "junior"                     # "junior" | "manager"
    conversation_id: str | None = None
    context: str = ""                        # attached-file text (chat-over-attachment)
    deal_id: str | None = None               # deal picked from the selector (structured)


@app.post("/api/chat")
def chat(req: ChatRequest):
    """Stream one assistant turn through the tool loop (SSE).

    The model decides which tools to call; each executed tool is surfaced to the
    UI (name, args, result) before the final answer is sent. Grounded entirely in
    the deterministic store/scoring engine plus web_search. Event types:
      start | tool | delta | answer | done | error
    The final answer streams token-by-token (`delta` events) so the Assistant
    feels as live as Review Coach. On any model/transport failure the loop emits
    a single `answer` with the error text (never a crash).

    Research intent ("tell me about / research <customer>") is auto-detected and
    routed to the dedicated, source-grounded `research_stream` — one Assistant
    surface, the right pipeline behind it."""
    if req.role == "research" or _is_research_intent(req.message):
        return StreamingResponse(
            research_stream(req),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Planner goal ("make a proposal for …", "organize my files", "save this as a
    # note") → route the SAME chat turn through the LLMPlanner: it selects a capability
    # graph (Conversation / Workspace / CRM / Knowledge / Web / Documents / Write /
    # Organize), runs it on the engine, and returns the artifact. No /plan prefix — a
    # normal prompt just works. An attached file rides along as conversation context; a
    # selector-picked deal is authoritative. Everything else stays in the ReAct loop.
    if _is_planner_goal(req.message, req.history):
        convo: list[dict] = []
        for m in req.history:
            if m.role in ("user", "assistant") and m.content:
                convo.append({"role": m.role, "content": m.content})
        if req.context.strip():
            convo.append({"role": "user",
                          "content": f"【添付ファイルの内容】\n{req.context.strip()}"})
        convo.append({"role": "user", "content": req.message})
        sel_deal = (req.deal_id or "").strip().upper() or None
        return StreamingResponse(
            _plan_stream(req.message, convo, req.role, deal_id=sel_deal),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    tools, system_fn = _CHAT_ROLES.get(req.role, _CHAT_ROLES["junior"])

    # Conversation context cache: remember the account in focus so follow-ups that
    # don't re-name the customer ("what should I do next?", "what happened recently
    # with this account?") stay scoped to the same customer. This also drives the
    # Phase-1 account-scoped retrieval: the cached customer is injected into the
    # system prompt so the model passes it to search_notes.
    conversation_id = (req.conversation_id or "default").strip() or "default"
    cached_ctx = _CHAT_CONTEXTS.get(conversation_id)
    cust = store.match_customer_in_text(req.message)
    msg_deal = _deal_id_in_text(req.message)
    sel_deal = (req.deal_id or "").strip().upper() or None
    active: dict | None = None
    cached_flag = False
    selected_flag = False
    if sel_deal and (sd := store.get_deal(sel_deal)):
        # Deal picked from the selector — authoritative. Skip prose parsing and,
        # crucially, tell the model it is already identified so it doesn't spend a
        # tool round re-resolving the customer/deal.
        active = {"customer_id": sd["customer_id"],
                  "customer": store.customer_name(sd["customer_id"]), "deal_id": sel_deal}
        selected_flag = True
    elif cust:
        active = {"customer_id": cust["customer_id"], "customer": cust.get("name"),
                  "deal_id": msg_deal or (cached_ctx or {}).get("deal_id")}
    elif msg_deal and (d := store.get_deal(msg_deal)):
        active = {"customer_id": d["customer_id"],
                  "customer": store.customer_name(d["customer_id"]), "deal_id": msg_deal}
    elif cached_ctx and _is_followup(req.message, True):
        active, cached_flag = cached_ctx, True
    if active and active.get("customer_id"):
        _CHAT_CONTEXTS[conversation_id] = active

    # Ambiguous customer stem (e.g. "marusan" → 4 丸三 companies) and nothing else
    # pinned it down → surface the candidates instead of guessing one's facts.
    amb_candidates: list[dict] = []
    if not active:
        for c in store.ambiguous_match_in_text(req.message):
            d = next((x for x in store.deals_for_customer(c["customer_id"])
                      if config.is_open_rank(x.get("order_rank"))), None)
            amb_candidates.append({"customer_id": c["customer_id"],
                                   "name": c.get("name", ""),
                                   "deal_id": d["deal_id"] if d else None})

    system = system_fn()
    if active and active.get("customer"):
        focus = active["customer"] + (f"（案件 {active['deal_id']}）" if active.get("deal_id") else "")
        if selected_flag:
            # The user already pinned the exact deal. Use it directly — no
            # identification searches — so the turn resolves in as few rounds as
            # possible.
            system += (f"\n\n【選択中の案件】ユーザーは {focus} を明示的に選択済み。"
                       f"案件IDが必要なツール（generate_proposal 等）には "
                       f"deal_id='{active['deal_id']}' をそのまま渡すこと。案件や顧客を"
                       f"特定するための追加検索(query_spr/search_notes)は不要 — すでに確定している。")
        else:
            system += (f"\n\n【現在の対象顧客】{focus}。アカウント固有の質問では、"
                       f"search_notes に customer='{active['customer']}' を渡し、この顧客の"
                       f"記録に限定して回答すること。")
    # An ambiguous customer (amb_candidates) short-circuits to the picker below
    # before the LLM runs, so no ambiguity clause is added to the system prompt.

    # File-scoped question → pin the turn to the Workspace tool. Without this the
    # model bleeds into CRM/internal-record tools ("yamato" → a wrong customer
    # lookup) even though the answer is in a local file. Explicit scope, one tool.
    if _is_file_scoped(req.message):
        system += ("\n\n【スコープ: ローカル文書】ユーザーは自分のファイル/資料に限定して"
                   "質問している。search_workspace_documents だけを使い、その結果のみに基づいて"
                   "回答すること。CRM・社内記録のツール(query_spr/search_notes/find_deals 等)は"
                   "呼ばない。文書に答えが無ければ、その旨を述べる（推測しない）。")

    convo: list[dict] = [{"role": "system", "content": system}]
    for m in req.history:
        if m.role in ("user", "assistant") and m.content:
            convo.append({"role": m.role, "content": m.content})
    # An attached file's extracted text rides along as context for THIS turn only
    # (not persisted into history). The model answers the question grounded in it.
    user_content = req.message
    if req.context.strip():
        user_content = (
            "【添付ファイルの内容 / Attached file content】\n"
            f"{req.context.strip()}\n\n"
            "【質問 / Question】\n"
            f"{req.message}"
        )
    convo.append({"role": "user", "content": user_content})

    def gen():
        from senpai.llm.client import stream_chat_turn  # lazy: keep import light
        yield _sse({"type": "start", "model": config.MODEL,
                    "endpoint": config.BASE_URL, "role": req.role,
                    "conversation_id": conversation_id})
        if active:
            yield _sse({"type": "context", "status": "active",
                        "conversation_id": conversation_id,
                        "customer": active.get("customer"),
                        "deal_id": active.get("deal_id"), "cached": cached_flag})
        elif amb_candidates:
            # Ambiguous customer and nothing else pinned it down → surface the
            # candidates and STOP. The deterministic picker is the whole response;
            # running the LLM here only produces a redundant "which one?" message
            # that duplicates the picker and pre-empts the rep's choice. The pick
            # re-runs this turn in place, grounded on the chosen customer.
            yield _sse({"type": "resolve", "status": "ambiguous",
                        "query": req.message, "candidates": amb_candidates})
            yield _sse({"type": "done", "model": config.MODEL})
            return
        try:
            for ev in stream_chat_turn(convo, tools=tools, role=req.role):
                yield _sse(ev)
            yield _sse({"type": "done", "model": config.MODEL})
        except Exception as e:  # noqa: BLE001 — never crash the stream
            yield _sse({"type": "error", "reason": str(e)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Persistent chat history ------------------------------------------------
# Durable copilot transcripts so a rep can close the tab and resume a past chat.
# The frontend owns the transcript (it's the only place the full-fidelity WMsg[]
# and skill/artifact cards exist), so it POSTs an opaque JSON `blob` here after each
# completed turn; the server only reads the small header fields for listing. Storage
# is SQLite via senpai.data.chat_store — separate from the seed/overlay `store`.
# Identity is passed explicitly as employee_id (like /api/coach/rep-profile/{id});
# the streaming /api/chat endpoint above is intentionally left untouched.
class SaveConversationRequest(BaseModel):
    employee_id: str
    role: str = "junior"
    title: str
    blob: str
    message_count: int = 0


class RenameConversationRequest(BaseModel):
    title: str


# --- Live web-research / site-intel crawl (the /intel browser-sim feed) ------
class IntelCrawlRequest(BaseModel):
    input: str                 # a URL/bare-domain OR a research question
    max_pages: int = 6
    max_sites: int = 3


def _intel_crawl_stream(req: IntelCrawlRequest):
    """SSE generator for the live browser feed. Runs the crawler in a worker thread
    (Playwright's sync API needs a thread with no event loop) and relays each page it
    visits to the client in real time via a queue, then a final `intel` brief event.

    Event types: start | research_plan | crawl_page | crawl_status | intel | error | done
    """
    import queue
    import threading
    from senpai.tools import crawl as _cr

    text = (req.input or "").strip()
    yield _sse({"type": "start", "input": text,
                "mode": "site" if _cr.looks_like_url(text) else "question"})
    if not text:
        yield _sse({"type": "error", "reason": "empty_input"})
        yield _sse({"type": "done"})
        return

    q: "queue.Queue[dict | None]" = queue.Queue(maxsize=256)  # room for scroll-frame bursts

    def emit(ev: dict) -> None:
        try:
            q.put(ev, timeout=1.0)
        except Exception:
            pass  # a slow/gone client must never wedge the crawl

    def worker() -> None:
        try:
            mp = max(1, min(int(req.max_pages), 12))
            if _cr.looks_like_url(text):
                url = text if text.startswith(("http://", "https://")) else "https://" + text
                if not _cr.is_safe_url(url):
                    q.put({"type": "error", "reason": "unsafe_or_unreachable_url", "url": url})
                    return
                intel = _cr.crawl_site(url, max_pages=mp, max_depth=2, emit=emit)
                if not intel.get("ok"):
                    q.put({"type": "error", "reason": intel.get("reason", "no_pages")})
                    return
                brief = _cr.build_brief(intel, use_llm=USE_LLM, emit=emit)
                q.put({"type": "intel", "markdown": brief["markdown"],
                       "sources": brief["sources"], "backend": intel["backend"],
                       "assets": {"products": len(intel["products"]),
                                  "news": len(intel["news"]), "pdfs": len(intel["pdfs"])},
                       "pdfs": intel["pdfs"][:12]})
            else:
                bundle = _cr.research_web(text, max_sites=max(1, min(int(req.max_sites), 5)),
                                          max_pages_per_site=min(mp, 3), emit=emit)
                answer = _cr._research_answer(bundle, use_llm=USE_LLM)
                sources = [{"url": p["url"], "title": p["title"]}
                           for c in bundle["crawls"] for p in c["pages"]]
                q.put({"type": "intel", "markdown": answer, "sources": sources,
                       "sites": bundle["sites"], "backend": "requests"})
        except Exception as e:  # noqa: BLE001 — surface, never crash the stream
            q.put({"type": "error", "reason": str(e)})
        finally:
            q.put(None)  # sentinel: worker done

    threading.Thread(target=worker, daemon=True).start()
    while True:
        ev = q.get()
        if ev is None:
            break
        yield _sse(ev)
    yield _sse({"type": "done"})


@app.post("/api/intel/crawl")
def intel_crawl(req: IntelCrawlRequest):
    """Stream a live website crawl → grounded intel brief (the /intel browser-sim)."""
    return StreamingResponse(
        _intel_crawl_stream(req), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/chat/history")
def chat_history_list(employee_id: str, role: str = "junior"):
    """List one user's saved conversations (headers only), newest first."""
    return {"conversations": chat_store.list_conversations(employee_id, role)}


@app.get("/api/chat/history/{conversation_id}")
def chat_history_get(conversation_id: str):
    """Fetch one full conversation (header + opaque blob) for resume."""
    convo = chat_store.get_conversation(conversation_id)
    if convo is None:
        raise HTTPException(404, f"conversation {conversation_id} not found")
    return convo


@app.put("/api/chat/history/{conversation_id}")
def chat_history_save(conversation_id: str, req: SaveConversationRequest):
    """Create or update a conversation (autosaved after each turn). Returns header."""
    title = req.title.strip() or "Untitled chat"
    return chat_store.upsert_conversation(
        conversation_id=conversation_id,
        employee_id=req.employee_id,
        role=req.role,
        title=title,
        blob=req.blob,
        message_count=req.message_count,
    )


@app.patch("/api/chat/history/{conversation_id}")
def chat_history_rename(conversation_id: str, req: RenameConversationRequest):
    """Rename a conversation."""
    title = req.title.strip()
    if not title:
        raise HTTPException(400, "title is required")
    if not chat_store.rename_conversation(conversation_id, title):
        raise HTTPException(404, f"conversation {conversation_id} not found")
    return {"ok": True, "conversation_id": conversation_id, "title": title}


@app.delete("/api/chat/history/{conversation_id}")
def chat_history_delete(conversation_id: str):
    """Delete a conversation."""
    if not chat_store.delete_conversation(conversation_id):
        raise HTTPException(404, f"conversation {conversation_id} not found")
    return {"ok": True, "conversation_id": conversation_id}


# --- LLMPlanner: goal -> capability graph -> document ------------------------
# The minimal planner surface (milestone 1: document generation). Unlike /api/chat
# (a ReAct tool loop), this translates ONE goal into a static capability plan, runs
# it on the shared ExecutionEngine, and returns the artifact. Same event shapes as
# chat (tool / document / answer) so the existing frontend renders it unchanged.
class PlanRequest(BaseModel):
    message: str                             # the document goal
    history: list[ChatMessage] = []          # prior user/assistant turns (for grounding)
    role: str = "junior"
    conversation_id: str | None = None


# Which gather capabilities count as "internal company data" for the UI's
# grounding badge — mirrors TOOL_LABEL's `internal` flag in the frontend
# (web/components/assistant/message.tsx), which the badge is computed from.
_CAP_INTERNAL = {"crm": True, "knowledge": True, "conversation": False,
                 "workspace": False, "web": False}


def _plan_stream(goal: str, convo: list[dict], role: str, deal_id: str | None = None):
    """Shared planner SSE generator: goal → capability graph → engine → artifact.
    Emits the same `plan | tool | document | answer | done` events used by /api/chat,
    so both the dedicated /api/plan surface and the auto-routed chat turn render
    identically. `deal_id` (selector pick) is authoritative when provided.

    Tool cards stream LIVE as each capability finishes (via `run_document_goal`'s
    `emit` callback, drained off a queue exactly like the /crew researcher/coach
    lanes) rather than all landing in one burst after the whole plan has already
    finished — otherwise the turn reads as the answer/file appearing before any
    tool was actually called, when in fact they ran first; the UI just never saw
    them until everything was already done."""
    import queue
    import threading

    from senpai.orchestration import events as oevents
    from senpai.planner import run_document_goal

    yield _sse({"type": "start", "model": config.MODEL,
                "endpoint": config.BASE_URL, "role": role, "surface": "planner"})

    # An ambiguous customer stem in the goal (e.g. "matsuda" → several 松田
    # companies) and no selector-picked deal to override it → surface the picker
    # and STOP, exactly like /api/chat and /api/agent/crew do. Otherwise the
    # planner silently falls through to an ungrounded free deck (no CRM entity),
    # which reads as the model hallucinating instead of asking which company.
    if not deal_id and not store.match_customer_in_text(goal):
        amb_candidates = []
        for c in store.ambiguous_match_in_text(goal):
            d = next((x for x in store.deals_for_customer(c["customer_id"])
                      if config.is_open_rank(x.get("order_rank"))), None)
            amb_candidates.append({"customer_id": c["customer_id"],
                                   "name": c.get("name", ""),
                                   "deal_id": d["deal_id"] if d else None})
        if amb_candidates:
            yield _sse({"type": "resolve", "status": "ambiguous",
                        "query": goal, "candidates": amb_candidates})
            yield _sse({"type": "done", "model": config.MODEL})
            return

    q: "queue.Queue" = queue.Queue()
    box: dict = {}

    def worker() -> None:
        try:
            box["result"] = run_document_goal(
                goal, conversation=convo, role=role, deal_id=deal_id,
                emit=lambda ev: q.put(ev))
        except Exception as e:  # noqa: BLE001 — never crash the stream
            box["error"] = str(e)
        finally:
            q.put({"type": "_worker_done"})

    threading.Thread(target=worker, daemon=True).start()

    doc_kind = "pptx"
    while True:
        ev = q.get()
        etype = ev.get("type")
        if etype == "_worker_done":
            break
        if etype == "selection.ready":
            sel = ev["selection"]
            doc_kind = sel["doc_kind"]
            # The capability graph the planner chose (the UI may render it; unknown
            # to the current chat handler, which safely ignores it).
            yield _sse({"type": "plan", "goal": goal, "doc_kind": sel["doc_kind"],
                        "capabilities": sel["capabilities"], "reason": sel.get("reason", ""),
                        "target": sel.get("target"), "deal_id": sel.get("deal_id"),
                        "tasks": ev["plan"]})
            # Focus chip: the resolved entity, so the account context stays visible.
            if sel.get("target") or sel.get("deal_id"):
                yield _sse({"type": "context", "status": "active",
                            "customer": sel.get("target"), "deal_id": sel.get("deal_id"),
                            "cached": False})
        elif etype == oevents.TASK_COMPLETED:
            tid = ev.get("task_id", "")
            if ev.get("status") not in ("ok", "partial"):
                continue
            data = ev.get("data") or {}
            if tid in _CAP_INTERNAL:
                if not data.get("text"):
                    continue  # gathered nothing — no card, same as before
                # `name` is the stable capability id, not a pre-baked Japanese
                # string — the frontend's TOOL_LABEL picks ja/en the same way it
                # already does for every ReAct-loop tool, so this reads in
                # whichever language the UI is set to, not Japanese-only.
                yield _sse({"type": "tool", "name": tid, "args": f"「{goal}」",
                            "result": "根拠を収集しました。",
                            "internal": _CAP_INTERNAL.get(tid, False)})
            elif tid == "documents" and data.get("document"):
                # A "proposal" is deal-grounded (real CRM financials/products/
                # comparables); pptx/docx are free-authored — same internal/
                # general split as generate_proposal vs generate_pptx/docx.
                yield _sse({"type": "tool", "name": "documents",
                            "args": f"kind={doc_kind}", "result": data.get("text", ""),
                            "document": data["document"],
                            "outline": data.get("outline") or [],
                            "internal": doc_kind == "proposal"})

    result = box.get("result")
    if result is None:
        yield _sse({"type": "error", "reason": box.get("error", "planner failed")})
        yield _sse({"type": "done", "model": config.MODEL})
        return

    text = result.get("text", "") or "資料を生成できませんでした。"
    outline = result.get("outline") or []
    if outline:
        titles = "\n".join(f"{i}. {s.get('title', '')}" for i, s in enumerate(outline, 1)
                           if s.get("title"))
        if titles:
            text = f"{text}\n\n構成:\n{titles}"
    yield _sse({"type": "answer", "text": text})
    yield _sse({"type": "done", "model": config.MODEL})


@app.post("/api/plan")
def plan_document(req: PlanRequest):
    """Plan a document goal into a capability graph, execute it, stream the result.
    The dedicated planner surface; `/api/chat` also auto-routes document goals here."""
    convo: list[dict] = []
    for m in req.history:
        if m.role in ("user", "assistant") and m.content:
            convo.append({"role": m.role, "content": m.content})
    convo.append({"role": "user", "content": req.message})
    return StreamingResponse(
        _plan_stream(req.message, convo, req.role),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Multi-agent crew -------------------------------------------------------
# A small crew of role-specialised agents (Researcher / Coach / Strategist)
# analyse one deal together — the "not a chatbot" surface. Researcher and Coach
# run in parallel; the Strategist merges their findings. Triggered from the chat
# workspace via /crew (deal) and /team (manager fan-out). See senpai.agent.crew.
class CrewRequest(BaseModel):
    deal_id: str | None = None
    message: str | None = None      # free text ("fujimoto") — resolved to a deal


@app.post("/api/agent/crew")
def agent_crew(req: CrewRequest):
    """Stream a multi-agent crew analysis of one deal (SSE). Accepts an explicit
    deal_id, or free `message` text that is resolved to the customer's worst open
    deal. Event types: crew | agent | agent_tool | final | done | error"""
    from senpai.agent import crew

    deal_id = (req.deal_id or "").strip()
    short_circuit: list[dict] | None = None
    if not deal_id:
        target = crew.resolve_crew_target(req.message or "")
        if target["status"] == "resolved":
            deal_id = target["deal_id"]
        elif target["status"] == "ambiguous":
            # Same picker the chat/research surfaces use — let the rep choose rather
            # than guess. The query shown is the matched stem ("fujimoto"), not the
            # whole sentence. The CrewTurn re-runs this with the chosen deal_id.
            short_circuit = [
                {"type": "resolve", "status": "ambiguous",
                 "query": target.get("stem") or (req.message or ""),
                 "candidates": target["candidates"]},
                {"type": "done"}]
        else:
            short_circuit = [{"type": "error", "reason": "not_found"}, {"type": "done"}]

    def gen():
        try:
            if short_circuit is not None:
                for ev in short_circuit:
                    yield _sse(ev)
                return
            for ev in crew.run_crew(deal_id):
                yield _sse(ev)
        except Exception as e:  # noqa: BLE001 — never crash the stream
            yield _sse({"type": "error", "reason": str(e)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/agent/team")
def agent_team():
    """Stream a manager fan-out — one analyst agent per rep in parallel, then a team
    lead synthesis (SSE). Same event contract as /api/agent/crew."""
    from senpai.agent import crew

    def gen():
        try:
            for ev in crew.run_team():
                yield _sse(ev)
        except Exception as e:  # noqa: BLE001 — never crash the stream
            yield _sse({"type": "error", "reason": str(e)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/coach/similar-cases")
def coach_similar_cases(req: CoachRequest):
    """Real past deals that rhyme with the current situation — Pillar 2,
    Experience. Read-only retrieval over closed deals; each case carries its
    outcome and the validated principle it teaches (see senpai.coach.cases)."""
    deal = store.get_deal(req.deal_id) if req.deal_id else None
    cases = find_similar_cases(req.note, deal=deal, max_n=3, today=_today())
    return {"cases": cases}


@app.get("/api/coach/examples")
def coach_examples():
    # Each seed example is anchored to a REAL, stable deal_id, so "try one" always
    # runs the grounded path (build_commentary_context resolves the deal at high
    # confidence) — never the "no matching customer" fallback. The notes are
    # deliberately customer-AGNOSTIC: the seed regenerates (deal_id is stable but
    # its customer/dates are not), so naming a company in the note text would
    # eventually mismatch the deal's actual customer. The deal_id alone grounds it.
    return {
        "examples": [
            {
                "title": "前向きだが決裁者が不明",
                "deal_id": "D001",
                "note": "担当者は前向きで『ほぼ決まり』との感触。受注確度は高いと見ている。"
                        "ただ決裁者にはまだ会えていない。",
                "hint": "高い確度が案件の実態・決裁者の状況と噛み合っているか",
            },
            {
                "title": "競合と比較中",
                "deal_id": "D021",
                "note": "競合製品と比較中。価格が高いと言われ、見積は提示済み。"
                        "次回までに再提案する予定。",
                "hint": "価格勝負に流される前に差別化軸を考える",
            },
            {
                "title": "初回訪問・IT環境を確認",
                "deal_id": "D016",
                "note": "初回訪問。先方のPC環境とネットワーク構成を一通り確認できた。"
                        "担当者は忙しそうだった。",
                "hint": "情報収集に走り、関係構築と決裁者の把握が後回しに",
            },
            {
                "title": "部長は前向き",
                "deal_id": "D008",
                "note": "部長は前向きで好感触。現場のIT担当にはまだ会えていない。",
                "hint": "決裁者の感触だけで成約間近と判断していないか",
            },
        ]
    }


# ---------------------------------------------------------------------------
# account intelligence — account-level (not deal-level) reasoning
# ---------------------------------------------------------------------------
@app.get("/api/customers/resolve")
def resolve_customer(q: str):
    """Deterministic name→customer resolution (alias-aware, never a name guess).
    Used by the Workspace /account skill to turn a typed name into a customer_id.
    Returns {status: resolved|ambiguous|not_found, query, customer, candidates}."""
    return store.resolve_customer_detailed((q or "").strip()).to_dict()


class SmartResolveRequest(BaseModel):
    query: str
    lang: str = "ja"


@app.post("/api/customers/smart-resolve")
def smart_resolve_customer(body: SmartResolveRequest):
    """Intelligent customer resolution: deterministic first, fuzzy near-miss second,
    LLM ranking third.

    Returns:
      { status: "resolved"|"ambiguous"|"not_found",
        query, customer, candidates, suggested_id? }

    - `suggested_id`: the candidate the model considers most likely (may differ from
      candidates[0] after sorting). Only present when the LLM is available.
    - `candidates`: always sorted by LLM confidence when LLM available, else
      deterministic order.
    """
    q = (body.query or "").strip()
    lang = body.lang or "ja"
    if not q:
        return {"status": "not_found", "query": q, "customer": None, "candidates": []}

    # 1. Deterministic resolve — exact / alias
    res = store.resolve_customer_detailed(q)
    if res.status == "resolved":
        return {**res.to_dict(), "suggested_id": res.customer["customer_id"]}

    candidates = []
    if res.status == "ambiguous":
        candidates = res.candidates  # already found via alias index

    # 2. Fuzzy near-miss — enrich "not_found" with difflib candidates
    if not candidates:
        # Build candidates by scoring each alias key the same way fuzzy_match_customer_in_text
        # does: slide a window the length of the key over the query and take the best ratio.
        # Threshold 0.68 and top-5 cap keeps noise out of the LLM prompt.
        import difflib
        FUZZY_THRESHOLD = 0.68
        MAX_CANDIDATES = 5
        scored: list[tuple[float, str]] = []  # (score, customer_id)
        low = q.lower()
        seen_cids: set[str] = set()
        for key, ids in store._alias_index().items():
            if len(key) < 4 or len(ids) != 1:
                continue
            cid = next(iter(ids))
            if cid in seen_cids:
                continue
            klen = len(key)
            best = 0.0
            if klen > len(low):
                best = difflib.SequenceMatcher(None, key, low, autojunk=False).ratio()
            else:
                for start in range(len(low) - klen + 1):
                    r = difflib.SequenceMatcher(None, key, low[start:start + klen], autojunk=False).ratio()
                    if r > best:
                        best = r
            if best >= FUZZY_THRESHOLD:
                seen_cids.add(cid)
                scored.append((best, cid))

        scored.sort(key=lambda x: (-x[0], x[1]))
        from senpai.data.store import CustomerCandidate, get_customer
        candidates = [
            CustomerCandidate(
                customer_id=cid,
                name=(get_customer(cid) or {}).get("name", cid),
                matched_aliases=[],
            )
            for _, cid in scored[:MAX_CANDIDATES]
            if get_customer(cid)
        ]
        if not candidates:
            return {"status": "not_found", "query": q, "customer": None,
                    "candidates": [], "suggested_id": None}


    # 3. LLM ranking — ask the model which candidate best matches the user's query
    suggested_id: str | None = None
    sorted_candidates = candidates  # default: original order

    if USE_LLM and len(candidates) > 1:
        try:
            from senpai.llm import client as llm_client
            names_block = "\n".join(
                f"  {i+1}. {c.customer_id}: {c.name}"
                for i, c in enumerate(candidates)
            )
            if lang == "ja":
                prompt = (
                    f"ユーザーが入力したキーワードは「{q}」です。\n"
                    f"以下の顧客候補の中から、最も可能性が高い顧客を1つ選んでください。\n"
                    f"顧客リスト:\n{names_block}\n\n"
                    "回答形式: 顧客IDのみを返してください（例: C06）。説明不要。"
                )
            else:
                prompt = (
                    f"The user typed: \"{q}\"\n"
                    f"From the following customers, pick the single best match:\n"
                    f"{names_block}\n\n"
                    "Reply with only the customer_id (e.g. C06). No explanation."
                )
            answer = llm_client.simple_complete(
                [{"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=16, no_think=True,
            ).strip()
            # Extract the first Cxx token from the answer
            import re as _re
            m = _re.search(r"C\d+", answer)
            if m:
                suggested_id = m.group(0)
                # Re-sort: put the suggested candidate first
                sorted_candidates = sorted(
                    candidates,
                    key=lambda c: (0 if c.customer_id == suggested_id else 1, c.customer_id),
                )
        except Exception:  # noqa: BLE001 — LLM failure must never break the picker
            pass

    return {
        "status": "ambiguous" if len(candidates) > 1 else "resolved",
        "query": q,
        "customer": sorted_candidates[0].__dict__ if len(candidates) == 1 else None,
        "candidates": [{"customer_id": c.customer_id, "name": c.name}
                       for c in sorted_candidates],
        "suggested_id": suggested_id or (sorted_candidates[0].customer_id if sorted_candidates else None),
    }



@app.get("/api/account/{customer_id}")
def account(customer_id: str):
    """One grounded roll-up of a whole customer relationship: headline aggregates,
    account health, relationship-trajectory patterns and expansion opportunities.
    Deterministic; see senpai.account."""
    from senpai.account import build_account_summary
    s = build_account_summary(customer_id, today=_today())
    if s is None:
        raise HTTPException(404, f"customer {customer_id} not found")
    return s.to_dict()


@app.post("/api/account/{customer_id}/commentary")
def account_commentary(customer_id: str, lang: str = "ja",
                       conversation_id: str | None = None):
    """Stream a senior account-manager's read of the whole relationship (SSE).
    Grounded in the deterministic account context package; reasoning disabled for
    low latency, pinned to the primary endpoint (no silent fallback). Event types:
      start | context | delta | done | unavailable"""
    from senpai.account import account_commentary_prompt
    from senpai.account.gather import gather_account_context

    if not USE_LLM:
        return StreamingResponse(
            iter([_sse({"type": "unavailable", "reason": "llm_disabled"})]),
            media_type="text/event-stream",
        )

    # Gather runs on the orchestration engine (M3); identical (context_text, meta).
    context_text, ctx_meta = gather_account_context(customer_id, lang=lang, today=_today())
    if not ctx_meta["has_account"]:
        return StreamingResponse(
            iter([_sse({"type": "unavailable", "reason": "account_not_found"})]),
            media_type="text/event-stream",
        )
    prompt = account_commentary_prompt(context_text, lang=lang)

    # Workspace continuity: pulling an account brief puts that customer "in focus"
    # for the shared conversation, so a follow-up chat turn stays scoped to it.
    _seed_chat_focus(conversation_id, customer_id, ctx_meta.get("customer"), None)

    def gen():
        from senpai.llm import client
        yield _sse({"type": "start", "model": config.MODEL, "endpoint": config.BASE_URL})
        # Workspace: this stream produces an `account_brief` artifact.
        yield _sse({"type": "artifact_meta", "kind": "account_brief",
                    "entity_ref": {"type": "account", "id": customer_id,
                                   "name": ctx_meta.get("customer")}})
        yield _sse({"type": "context", "customer": ctx_meta["customer"],
                    "customer_id": customer_id, "score": ctx_meta["score"],
                    "band": ctx_meta["band"]})
        # Transparency: surface the deterministic strategic stance (tier + region +
        # the rationale for why it was chosen) so the rep sees it alongside the read.
        if ctx_meta.get("strategy"):
            yield _sse({"type": "strategy", **ctx_meta["strategy"]})
        full, emitted = "", 0
        try:
            for piece in client.stream_complete(
                [{"role": "user", "content": prompt}],
                temperature=0.5, max_tokens=config.LLM_NARRATE_MAX_TOKENS,
                no_think=True, allow_fallback=False,
            ):
                full += piece
                if "</think>" in full:
                    answer = full.split("</think>", 1)[1].lstrip("\n ")
                elif "<think>" in full:
                    answer = ""
                else:
                    answer = full
                new = answer[emitted:]
                if new:
                    emitted += len(new)
                    yield _sse({"type": "delta", "text": new})
            if emitted:
                yield _sse({"type": "done", "model": config.MODEL})
            else:
                yield _sse({"type": "unavailable", "reason": "empty"})
        except Exception:  # noqa: BLE001 — primary endpoint down/timeout (no fallback)
            yield _sse({"type": "unavailable", "reason": "unreachable"})

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# manager coaching workspace ("where should I coach today?")
# ---------------------------------------------------------------------------
@app.get("/api/coaching")
def coaching(manager: str | None = None):
    """Manager's daily workspace — Needs Coaching queue, team trends, Confidence
    vs Reality, and a weekly digest. Read-only aggregation over the existing
    deal-health + flags engines; see senpai.coaching. `manager` (an employee_id)
    scopes it to that manager's team; omit for the whole team."""
    rep_ids = store.team_of(manager) if manager else None
    return coaching_workspace(today=_today(), rep_ids=rep_ids)


@app.get("/api/coach/rep-profile/{employee_id}")
def coach_rep_profile(employee_id: str):
    """Per-rep coaching profile (the 1:1 page): recurring weaknesses grounded in
    real deals + a validated principle + a real case + an action, plus strengths,
    talking points and coaching-thread status. See senpai.coach.profile."""
    return rep_coaching_profile(employee_id, today=_today())


@app.get("/api/coach/rep-profiles")
def coach_rep_profiles(manager: str | None = None):
    """Team rollup: one compact profile per rep, worst-needing-coaching first.
    `manager` (an employee_id) limits it to that manager's team."""
    rep_ids = store.team_of(manager) if manager else None
    return {"reps": team_coaching_profiles(today=_today(), rep_ids=rep_ids)}


@app.get("/api/coach/team")
def coach_team(manager: str | None = None):
    """A manager's 'My team' roster — every rep on their team (coachees + assigned
    juniors), each with their open-deal count. Unlike the rep-profiles rollup this
    KEEPS zero-deal reps, so a freshly-assigned junior is visible. Empty team when
    `manager` is omitted."""
    ids = store.team_of(manager) if manager else set()
    reps = []
    for eid in ids:
        rep = store.get_rep(eid) or {}
        open_deals = sum(1 for d in store.deals_for_rep(eid)
                         if config.is_open_rank(d.get("order_rank")))
        reps.append({
            "employee_id": eid,
            "name": rep.get("name", eid),
            "role": rep.get("role", ""),
            "open_deals": open_deals,
        })
    reps.sort(key=lambda r: (-r["open_deals"], r["employee_id"]))
    return {"reps": reps}


@app.get("/api/coach/rep-progress/{employee_id}")
def coach_rep_progress(employee_id: str, windows: int = 4):
    """Longitudinal coaching progress for a rep — per-fiscal-year weakness rates,
    per-issue trend, and whether past coaching was acted on. See coach.progress."""
    return rep_progress(employee_id, today=_today(), windows=windows)


@app.get("/api/coach/threads")
def coach_threads(rep_id: str | None = None, deal_id: str | None = None):
    """Manager↔rep coaching threads, filtered by rep or deal (newest first)."""
    if deal_id:
        rows = store.coaching_threads_for_deal(deal_id)
    elif rep_id:
        rows = store.coaching_threads_for_rep(rep_id)
    else:
        rows = store.all_coaching_threads()
    return {"threads": rows}


# ---------------------------------------------------------------------------
# growth (Pillar 3 — Motivation)
# ---------------------------------------------------------------------------
@app.get("/api/growth")
def growth(rep: str | None = None):
    """A junior's 'My Growth' picture — reviews, principles touched, coaching
    streak, monthly activity, and skill progression. Read-only over the store;
    see senpai.growth. `rep` is an employee_id; defaults to the first junior."""
    juniors = junior_reps()
    eid = rep or (juniors[0]["employee_id"] if juniors else "")
    return {
        "growth": rep_growth(eid, today=_today()),
        "juniors": [{"employee_id": r["employee_id"], "name": r["name"]} for r in juniors],
    }


# ---------------------------------------------------------------------------
# knowledge
# ---------------------------------------------------------------------------
@app.get("/api/knowledge/sources")
def knowledge_sources():
    return {"sources": [asdict(s) for s in kstore.all_sources()]}


@app.get("/api/knowledge/principles")
def knowledge_principles():
    ps = [_principle_payload(p) for p in kstore.all_principles()]
    return {
        "principles": ps,
        "counts": {
            "total": len(ps),
            "approved": sum(1 for p in ps if p["status"] == "approved"),
            "pending": sum(1 for p in ps if p["status"] != "approved"),
            "two_source": sum(1 for p in ps if p["n_interviews"] >= 2),
        },
    }


@app.get("/api/knowledge/items")
def knowledge_items():
    items = [_item_payload(it) for it in kstore.all_items()]
    return {
        "items": items,
        "counts": {
            "total": len(items),
            "approved": sum(1 for i in items if i["review"]["status"] == "approved"),
            "pending": sum(1 for i in items if i["review"]["status"] in ("draft", "needs_edit")),
        },
    }


class GenerateRequest(BaseModel):
    principle_id: str
    use_llm: bool = False


@app.post("/api/knowledge/generate")
def knowledge_generate(req: GenerateRequest):
    p = kstore.get_principle(req.principle_id)
    if p is None:
        raise HTTPException(404, f"principle {req.principle_id} not found")
    if p.status != "approved":
        raise HTTPException(400, "only approved principles may seed a draft")
    item = kgen.generate_item(p, use_llm=req.use_llm)
    kstore.save_item(item)
    return {"item": _item_payload(item)}


class AddPrincipleRequest(BaseModel):
    statement: str               # the tacit knowledge / advice (the principle)
    situation: str = ""          # the context the manager is grounding it in
    tags: list[str] = []         # → Coach retrieval
    added_by: str = "manager"


@app.post("/api/knowledge/principles")
def knowledge_add_principle(req: AddPrincipleRequest):
    """Manager-contributed tacit knowledge → a Layer-1 Principle (status
    'candidate'), grounded in a manager-note Source. Written to the ingested
    overlay (committed seed untouched); flows through the existing review queue
    to become an approved principle juniors can see. See senpai.knowledge."""
    from senpai.knowledge.schema import Citation, Principle, Source

    statement = (req.statement or "").strip()
    if not statement:
        raise HTTPException(400, "statement is required")

    sid = kstore.next_source_id()
    kstore.save_source(Source(
        source_id=sid, kind="manager_note", participant_role="manager",
        date=_today().isoformat(), notes=req.situation.strip(),
    ))
    pid = kstore.next_principle_id()
    principle = Principle(
        principle_id=pid, statement=statement,
        support=[Citation(source_id=sid, quote=(req.situation.strip() or statement))],
        tags=[t.strip() for t in req.tags if t.strip()],
        status="candidate", added_by=req.added_by or "manager",
    )
    kstore.save_principle(principle)
    return {"principle": _principle_payload(principle)}


class ReviewRequest(BaseModel):
    action: str          # approve | request_edit | reject
    reviewer: str = "web_reviewer"
    notes: str = ""


@app.post("/api/knowledge/items/{item_id}/review")
def knowledge_item_review(item_id: str, req: ReviewRequest):
    fn = {"approve": kreview.approve, "request_edit": kreview.request_edit,
          "reject": kreview.reject}.get(req.action)
    if fn is None:
        raise HTTPException(400, f"unknown action {req.action}")
    try:
        item = fn(item_id, req.reviewer, req.notes)
    except KeyError:
        raise HTTPException(404, f"item {item_id} not found")
    return {"item": _item_payload(item)}


# --- Multimodal ingestion ---------------------------------------------------
async def _uploads_to_raw_text(
    audio: UploadFile | None, image: UploadFile | None, text: str | None,
) -> str:
    """Transcribe/OCR any uploads and join with raw text. Shared by /api/extract
    (chat-over-attachment) and /api/ingest (structured draft). Raises 400 if empty."""
    import os
    import tempfile

    from senpai.ingestion import multimodal as mm

    parts: list[str] = []
    for upload, extract in ((audio, mm.transcribe_audio), (image, mm.extract_text_from_image)):
        if upload is None:
            continue
        suffix = os.path.splitext(upload.filename or "")[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await upload.read())
            tmp_path = tmp.name
        try:
            out = extract(tmp_path)
            if out:
                parts.append(out)
        finally:
            os.unlink(tmp_path)

    if text and text.strip():
        parts.append(text.strip())

    if not parts:
        raise HTTPException(400, "provide at least one of: audio, image, text")
    return "\n\n".join(parts)


@app.post("/api/extract")
async def extract_text(
    audio: UploadFile | None = File(default=None),
    image: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
):
    """Extract plain text from an attachment for chat context.

    Voice note → transcript, image → OCR, or raw text — returns just `raw_text`.
    Unlike /api/ingest this does NOT run structured-activity extraction: the
    workspace chat attaches this text as context and lets the user ask about it.
    Data ingestion is a separate flow (/api/ingest, /api/ingest/save)."""
    raw = await _uploads_to_raw_text(audio, image, text)
    return {"raw_text": raw}


@app.post("/api/ingest")
async def ingest(
    audio: UploadFile | None = File(default=None),
    image: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
):
    """Capture → structured sales-activity draft.

    Accepts a voice note (audio), a business-card/whiteboard photo (image),
    and/or raw text — any combination — and returns an editable draft matching
    the `sales_activities` schema (activity_type, daily_report, business_card_info,
    customer_challenge, product_major_category). Wraps senpai.ingestion.multimodal
    unchanged; falls back to deterministic mock extraction offline (no multimodal
    API key). The draft is NOT persisted — the caller reviews/edits it, then POSTs
    it to /api/ingest/save."""
    from senpai.ingestion import multimodal as mm

    raw = await _uploads_to_raw_text(audio, image, text)
    draft = mm.extract_structured_activity(raw)
    return {"raw_text": raw, "draft": draft, "multimodal": config.have_multimodal()}


class SaveActivityRequest(BaseModel):
    draft: dict                  # edited ActivityDraft (activity_type, daily_report, …)
    customer_id: str
    deal_id: str
    employee_id: str


@app.post("/api/ingest/save")
def ingest_save(req: SaveActivityRequest):
    """Persist a reviewed daily-report draft as a real sales_activities row.

    Builds the record in exact seed shape (correct Japanese fiscal year/quarter,
    rep dept/division, derived order stats) and appends it to the gitignored
    overlay (senpai/data/ingested/) — the committed seed is never mutated. The new
    activity is immediately visible to scoring/timeline for the running process."""
    if not store.get_deal(req.deal_id):
        raise HTTPException(404, f"deal {req.deal_id} not found")
    if not store.get_customer(req.customer_id):
        raise HTTPException(404, f"customer {req.customer_id} not found")
    from senpai.ingestion import persist
    record = persist.save_activity(req.draft, req.customer_id, req.deal_id, req.employee_id)
    return {"saved": True, "activity": record}


# ===========================================================================
# ADMIN PORTAL  (internal-only; NO auth by design — see the plan's caveat).
# Read-only reshapes over existing engines + one reassignment write + the
# Graph-RAG showcase feed. Kept in this flat file to match the rest of the API.
# ===========================================================================
_MANAGER_ROLES = ("senior", "expert")


def _is_manager(rep: dict) -> bool:
    return rep.get("role") in _MANAGER_ROLES


def _account_emp_ids() -> set[str]:
    """Employee ids that have a login account."""
    return {u.get("employee_id") for u in auth.list_users() if u.get("employee_id")}


def _open_deal_count(employee_id: str) -> int:
    return sum(1 for d in store.deals_for_rep(employee_id)
               if config.is_open_rank(d.get("order_rank")))


def _direct_reports(manager_id: str) -> list[dict]:
    """The canonical org chart the admin portal manages: reps whose reports_to is
    this manager. reports_to is the single editable source of truth here (see the
    plan) — distinct from store.team_of, which unions coaching threads for the
    product's coaching views."""
    return [r for r in store.all_reps() if r.get("reports_to") == manager_id]


def _rep_row(rep: dict, accounts: set[str]) -> dict:
    """A rep enriched for the admin tables: manager name, team size, login flag."""
    eid = rep.get("employee_id", "")
    mgr_id = rep.get("reports_to") or ""
    mgr = store.get_rep(mgr_id) if mgr_id else None
    return {
        "employee_id": eid,
        "name": rep.get("name", eid),
        "role": rep.get("role", ""),
        "department": rep.get("department", ""),
        "division": rep.get("division", ""),
        "reports_to": mgr_id,
        "manager_name": (mgr or {}).get("name", "") if mgr else "",
        "is_manager": _is_manager(rep),
        "team_size": len(_direct_reports(eid)) if _is_manager(rep) else 0,
        "has_account": eid in accounts,
        "open_deals": _open_deal_count(eid),
        "is_top_performer": bool(rep.get("is_top_performer")),
    }


@app.get("/api/admin/overview")
def admin_overview():
    """Headline counts + health for the admin home."""
    from senpai.graph import communities as _comm
    from senpai.knowledge import store as _kstore
    reps = store.all_reps()
    managers = [r for r in reps if _is_manager(r)]
    juniors = [r for r in reps if r.get("role") == "junior"]
    accounts = auth.list_users()
    try:
        pending = max(len(_kstore.all_items()) - len(_kstore.approved_items()), 0)
    except Exception:  # noqa: BLE001
        pending = 0
    usage_totals = _usage_summary()["totals"]
    return {
        "reps": len(reps),
        "managers": len(managers),
        "juniors": len(juniors),
        "accounts": len(accounts),
        "deals": len(store.all_deals()),
        "open_deals": len(store.open_deals()),
        "communities": len(_comm.load_reports()),
        "knowledge_pending": pending,
        "tokens_total": usage_totals["total_tokens"],
        "llm_calls": usage_totals["calls"],
    }


@app.get("/api/admin/reps")
def admin_reps():
    """Every rep (seed + overlay), enriched — the People table."""
    accounts = _account_emp_ids()
    rows = [_rep_row(r, accounts) for r in store.all_reps()]
    rows.sort(key=lambda r: (not r["is_manager"], r["employee_id"]))
    return {"reps": rows, "managers": [
        {"employee_id": r["employee_id"], "name": r["name"]}
        for r in rows if r["is_manager"]]}


@app.get("/api/admin/org")
def admin_org():
    """Managers with their teams + an Unassigned bucket — the org/assignment view."""
    accounts = _account_emp_ids()
    reps = store.all_reps()
    managers = [r for r in reps if _is_manager(r)]
    placed: set[str] = set()
    groups = []
    for m in sorted(managers, key=lambda r: r["employee_id"]):
        mid = m["employee_id"]
        team_rows = sorted(_direct_reports(mid), key=lambda r: r.get("employee_id", ""))
        placed.update(r["employee_id"] for r in team_rows)
        groups.append({
            "manager": _rep_row(m, accounts),
            "team": [_rep_row(r, accounts) for r in team_rows],
        })
    unassigned = [_rep_row(r, accounts) for r in reps
                  if not r.get("reports_to") and not _is_manager(r)]
    unassigned.sort(key=lambda r: r["employee_id"])
    return {"groups": groups, "unassigned": unassigned,
            "manager_pool": [{"employee_id": m["employee_id"], "name": m.get("name", "")}
                             for m in managers]}


class ReassignRequest(BaseModel):
    manager_id: str


@app.post("/api/admin/reps/{employee_id}/reassign")
def admin_reassign(employee_id: str, req: ReassignRequest):
    """Move a rep under a manager by rewriting reports_to (see store.set_reports_to)."""
    try:
        store.set_reports_to(employee_id, req.manager_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"rep": _rep_row(store.get_rep(employee_id) or {}, _account_emp_ids())}


@app.get("/api/admin/activity")
def admin_activity(limit: int = 100):
    """Reverse-chronological system activity: latest coaching-thread messages and
    daily reports. Best-effort, capped."""
    events: list[dict] = []
    for t in store.all_coaching_threads():
        msgs = t.get("messages") or []
        if not msgs:
            continue
        last = msgs[-1]
        events.append({
            "type": "coaching",
            "date": last.get("date", ""),
            "rep": t.get("employee_id", ""),
            "manager": t.get("manager_id", ""),
            "deal": t.get("deal_id", ""),
            "text": (last.get("text", "") or "")[:200],
        })
    for rep in store.all_reps():
        eid = rep.get("employee_id", "")
        for dr in store.daily_reports_for_rep(eid)[-3:]:
            events.append({
                "type": "daily_report",
                "date": dr.get("activity_date", ""),
                "rep": eid,
                "customer": dr.get("customer_id", ""),
                "deal": dr.get("deal_id", ""),
                "text": (dr.get("daily_report", "") or "")[:200],
            })
    events.sort(key=lambda e: e.get("date", ""), reverse=True)
    return {"events": events[:limit]}


@app.get("/api/admin/accounts")
def admin_accounts():
    """Login accounts (public shape) joined to rep names — who can sign in."""
    out = []
    for u in auth.list_users():
        eid = u.get("employee_id")
        rep = store.get_rep(eid) if eid else None
        out.append({**u, "rep_name": (rep or {}).get("name", "")})
    return {"accounts": out}


@app.get("/api/admin/pipeline-health")
def admin_pipeline_health():
    """System-wide deal health from the grounded community layer: where the
    business is losing (lowest win-rate leaves) and the failure-signal mix."""
    from collections import Counter
    from senpai.graph import communities as _comm
    reports = _comm.load_reports()
    leaves = [r for r in reports if r.get("level") == "leaf"]
    signals: Counter = Counter()
    for r in leaves:
        for s in r.get("top_failure_signals", []):
            name = s.get("signal") if isinstance(s, dict) else s
            count = s.get("count", 1) if isinstance(s, dict) else 1
            if name:
                signals[name] += count
    segments = sorted(
        [{"category": r.get("category", ""), "industry": r.get("industry", ""),
          "n_deals": r.get("n_deals", 0), "n_won": r.get("n_won", 0),
          "n_lost": r.get("n_lost", 0), "n_open": r.get("n_open", 0),
          "win_rate": r.get("win_rate", 0.0),
          "top_failure_signals": r.get("top_failure_signals", [])}
         for r in leaves],
        key=lambda s: (s["win_rate"], -s["n_lost"]))
    totals = {
        "n_deals": sum(r.get("n_deals", 0) for r in leaves),
        "n_won": sum(r.get("n_won", 0) for r in leaves),
        "n_lost": sum(r.get("n_lost", 0) for r in leaves),
        "n_open": sum(r.get("n_open", 0) for r in leaves),
    }
    return {"totals": totals,
            "failure_signals": [{"signal": k, "count": v} for k, v in signals.most_common()],
            "lowest_win_segments": segments[:10]}


@app.get("/api/admin/system-status")
def admin_system_status():
    """Operational snapshot for 'is the demo healthy'."""
    from senpai.retrieval import semantic as _sem
    try:
        retrieval_mode = _sem.mode()
    except Exception:  # noqa: BLE001
        retrieval_mode = "unknown"
    ingested = config.INGESTED_DIR
    overlays = sorted(p.name for p in ingested.glob("*.json")) if ingested.exists() else []
    return {
        "use_llm": USE_LLM,
        "today": str(_today()),
        "retrieval_mode": retrieval_mode,
        "endpoints": {
            "primary": {"base_url": config.BASE_URL, "model": config.MODEL},
            "fallback": {"base_url": config.FALLBACK_BASE_URL, "model": config.FALLBACK_MODEL},
        },
        "flags": {
            "FAST_SYNTH_FALLBACK": config.FAST_SYNTH_FALLBACK,
            "SYNTH_ALL_FALLBACK": config.SYNTH_ALL_FALLBACK,
        },
        "data": {"reps": len(store.all_reps()), "deals": len(store.all_deals()),
                 "overlays": overlays},
    }


def _usage_summary() -> dict:
    from senpai.llm import usage as _u
    return _u.summary()


@app.get("/api/admin/usage")
def admin_usage():
    """LLM token accounting: totals, per-day, by model, by feature, recent calls."""
    return _usage_summary()


# --- Visualization (Graph-RAG showcase) ------------------------------------
def _node_label(nid: str, data: dict) -> str:
    kind = data.get("kind", "")
    if kind in ("category", "industry", "acttype") and ":" in nid:
        return nid.split(":", 1)[-1]
    return data.get("name") or nid


@app.get("/api/admin/graph")
def admin_graph(kind: str | None = None):
    """The real NetworkX graph serialized for react-force-graph. Optional ?kind=
    filters to one node kind (edges kept only between surviving nodes)."""
    from senpai.graph import build as _build
    G = _build.graph()
    nodes = []
    for nid, data in G.nodes(data=True):
        k = data.get("kind", "")
        if kind and k != kind:
            continue
        nodes.append({"id": nid, "kind": k, "label": _node_label(nid, data),
                      "degree": G.degree(nid), "outcome": data.get("outcome"),
                      "category": data.get("category"), "industry": data.get("industry")})
    keep = {n["id"] for n in nodes}
    links = [{"source": u, "target": v, "rel": d.get("rel", "")}
             for u, v, d in G.edges(data=True) if u in keep and v in keep]
    return {"nodes": nodes, "links": links, "stats": _build.stats()}


@app.get("/api/admin/communities")
def admin_communities():
    """The 44 grounded communities (7 category rollups + 37 thick leaves)."""
    from senpai.graph import communities as _comm
    return {"communities": [dict(r) for r in _comm.load_reports()]}


def _est_tokens(text: str) -> int:
    """One consistent token estimate applied to BOTH pipelines in the head-to-head,
    so the comparison is a measured ratio of measured quantities."""
    from senpai.llm import usage as _u
    return _u._estimate_tokens(text)


def _run_graph_rag_stream(query: str):
    """SSE generator: animate the graph query, stream the real retrieval trace,
    and end with a MEASURED (never fabricated) Graph-RAG-vs-traditional scorecard."""
    import time
    from senpai.graph import query as _gq
    from senpai.graph import communities as _comm
    from senpai.retrieval import semantic as _sem
    from senpai.retrieval import trace as _trace

    yield _sse({"type": "start", "query": query})

    # --- Graph side: community selection + a representative graph query --------
    _trace.start()
    t0 = time.perf_counter()
    segments = _comm.select(query, limit=5)
    reps_rows = _gq.reps_who_win(min_deals=2)[:5]
    graph_ms = (time.perf_counter() - t0) * 1000.0
    graph_ctx = "\n\n".join(_comm.format_report(s) for s in segments)

    # Emit the nodes the graph actually consulted (honest: these are the segments
    # and the reps/deals behind the answer), so the UI can light them up.
    for s in segments:
        yield _sse({"type": "node_visited", "kind": "community",
                    "label": f'{s.get("category","")} × {s.get("industry","") or "—"}',
                    "n_deals": s.get("n_deals", 0), "win_rate": s.get("win_rate", 0.0)})
        time.sleep(0.4)  # Visual delay to animate traversal
    for row in reps_rows:
        rep_id = row.get("rep_id") or row.get("rep") or row.get("employee_id") or "?"
        yield _sse({"type": "node_visited", "kind": "rep", "label": rep_id,
                    "won": row.get("won", 0), "closed": row.get("closed", 0)})
        time.sleep(0.3)
        for did in (row.get("example_deal_ids") or row.get("deals") or [])[:3]:
            yield _sse({"type": "edge_traversed", "source": rep_id, "target": did,
                        "rel": "OWNS"})
            time.sleep(0.2)

    trace_items = _trace.drain()
    for ev in trace_items:
        yield _sse({"type": "retrieved", **ev})

    # --- Traditional side: the real hybrid retriever on the SAME query ---------
    t0 = time.perf_counter()
    trad = _sem.semantic_search(query, corpus="activities", limit=8)
    trad_ms = (time.perf_counter() - t0) * 1000.0
    trad_ctx = "\n\n".join(x.get("text", "") or x.get("snippet", "") for x in trad)
    try:
        trad_mode = _sem.mode()
    except Exception:  # noqa: BLE001
        trad_mode = "hybrid"

    graph_sample = [{"label": f'{s.get("category","")} × {s.get("industry","") or "—"}',
                     "n_deals": s.get("n_deals", 0), "win_rate": s.get("win_rate", 0.0)}
                    for s in segments]
    trad_sample = [{"customer": x.get("customer_id", ""), "deal": x.get("deal_id", ""),
                    "score": round(x.get("score", 0.0), 3),
                    "snippet": (x.get("snippet") or x.get("text", ""))[:80]}
                   for x in trad[:6]]
    yield _sse({"type": "comparison", "measured": True, "query": query,
                "graph": {"label": "Graph RAG (communities + graph)",
                          "chunks": len(segments),
                          "context_chars": len(graph_ctx),
                          "context_tokens": _est_tokens(graph_ctx),
                          "latency_ms": round(graph_ms, 1),
                          "note": f"grounded over {len(_comm.load_reports())} communities",
                          "sample": graph_sample},
                "traditional": {"label": f"Traditional retrieval ({trad_mode})",
                                "chunks": len(trad),
                                "context_chars": len(trad_ctx),
                                "context_tokens": _est_tokens(trad_ctx),
                                "latency_ms": round(trad_ms, 1),
                                "note": "raw daily-report chunks",
                                "sample": trad_sample}})
    yield _sse({"type": "done"})


class GraphRagRequest(BaseModel):
    query: str


@app.post("/api/admin/graph-rag/run")
def admin_graph_rag_run(req: GraphRagRequest):
    """Stream a live Graph-RAG run (SSE): graph traversal, real retrieval trace,
    and a measured head-to-head vs traditional retrieval."""
    return StreamingResponse(_run_graph_rag_stream(req.query or ""),
                             media_type="text/event-stream")
````
