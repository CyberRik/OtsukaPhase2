"use client";

// Execution rail — the premium presentational layer over the real task-DAG
// events (senpai/orchestration/events.py, forwarded 1:1 by workspace.tsx's
// ChatTurn adapter into Msg.executionLanes). Every number and label here comes
// from data already flowing through that pipe — nothing is fabricated for
// effect. Used only for planner-driven turns (document generation / multi-
// capability gather); ReAct-loop chat turns have no executionLanes and keep
// their existing accordion in message.tsx untouched.

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import {
  Building2, ChevronDown, ChevronRight, Database, Download, FileText,
  FolderTree, Globe, Package, Presentation, ShieldCheck, Sparkles, type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { documentUrl } from "@/lib/api";
import type { GeneratedDocument } from "@/lib/types";
import {
  phaseLabel, translateToolSummary, parseDocumentProgress,
  type ExecutionPhase,
} from "@/components/agent/agent-lane";

const CAP_ICON: Record<string, LucideIcon> = {
  conversation: Sparkles,
  workspace: FileText,
  crm: Database,
  knowledge: ShieldCheck,
  solutions: Package,
  web: Globe,
  documents: Presentation,
  workspace_write: FileText,
  workspace_organize: FolderTree,
};

// ─── useCountUp ────────────────────────────────────────────────────────────
// requestAnimationFrame count from the previous render's value to `target`.
// Reads as "caused by the arrival" of a real number, not a canned animation.
export function useCountUp(target: number, durationMs = 250): number {
  const [value, setValue] = useState(target);
  const fromRef = useRef(target);
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    const from = fromRef.current;
    if (from === target || reduceMotion) {
      fromRef.current = target;
      setValue(target);
      return;
    }
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / durationMs);
      setValue(Math.round(from + (target - from) * p));
      if (p < 1) raf = requestAnimationFrame(tick);
      else fromRef.current = target;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, durationMs]);

  return value;
}

function elapsedLabel(phases: ExecutionPhase[]): string | null {
  const starts = phases.map((p) => p.startedAt).filter((n): n is number => !!n);
  if (starts.length === 0) return null;
  const ends = phases.map((p) => p.endedAt).filter((n): n is number => !!n);
  const allDone = phases.every((p) => p.status === "done");
  const end = allDone && ends.length ? Math.max(...ends) : Date.now();
  const ms = end - Math.min(...starts);
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

// ─── CapabilityCard ────────────────────────────────────────────────────────
export function CapabilityCard({ phase, lang, index }: {
  phase: ExecutionPhase; lang: "ja" | "en"; index: number;
}) {
  const [open, setOpen] = useState(false);
  const reduceMotion = useReducedMotion();
  const Icon = CAP_ICON[phase.id] ?? Sparkles;
  const label = phaseLabel(phase, lang);
  const isRunning = phase.status === "running";
  const isDone = phase.status === "done";
  const count = useCountUp(phase.citationCount ?? 0);

  return (
    <motion.div
      layout
      initial={reduceMotion ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: reduceMotion ? 0 : index * 0.07, duration: 0.25 }}
      className={cn(
        "relative flex min-w-[168px] flex-col gap-1.5 overflow-hidden rounded-lg border p-2.5 transition-colors",
        isRunning && "border-primary/30 bg-primary/[0.03] rail-shimmer",
        isDone && "border-border bg-card",
        phase.status === "pending" && "border-border/60 bg-muted/20 opacity-50",
      )}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 text-left"
      >
        <Icon className={cn("h-3.5 w-3.5 shrink-0", isRunning ? "text-primary" : "text-foreground/50")} />
        <span className={cn("min-w-0 flex-1 truncate text-[12px] leading-snug", isRunning ? "font-medium text-foreground" : "text-foreground/70")}>
          {label}
        </span>
        {isRunning && <span className="execution-pulse inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-primary/70" />}
        {isDone && phase.citationCount ? (
          <span className="shrink-0 rounded-full bg-primary/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-primary">
            {count}
          </span>
        ) : null}
        {phase.tools.length > 0 && (
          open
            ? <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
            : <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
        )}
      </button>
      <AnimatePresence>
        {open && phase.tools.length > 0 && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="flex flex-col gap-1 overflow-hidden pl-[22px]"
          >
            {phase.tools.map((tl, i) => (
              <span key={i} className="text-[11px] leading-snug text-muted-foreground">
                {translateToolSummary(tl.summary || tl.name, lang)}
              </span>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ─── EvidenceBundleNode ────────────────────────────────────────────────────
// Shared-element (layoutId) convergence: each done capability's evidence token
// animates from the card row into this bundle node via framer-motion's
// automatic position/scale interpolation — no hand-rolled coordinates.
export function EvidenceBundleNode({ phases, lang }: { phases: ExecutionPhase[]; lang: "ja" | "en" }) {
  const doneGather = phases.filter((p) => p.group !== "documents" && p.status === "done");
  const total = useCountUp(doneGather.reduce((s, p) => s + (p.citationCount ?? 0), 0));
  if (doneGather.length === 0) return null;

  return (
    <div className="flex items-center gap-2 border-t border-border/50 pt-2">
      <div className="flex -space-x-1.5">
        {doneGather.map((p) => (
          <motion.div
            key={p.id}
            layoutId={`evidence-${p.id}`}
            className="flex h-5 w-5 items-center justify-center rounded-full border border-background bg-primary/15 text-[9px] font-semibold text-primary"
            title={phaseLabel(p, lang)}
          >
            {(p.citationCount ?? 0) > 0 ? p.citationCount : "✓"}
          </motion.div>
        ))}
      </div>
      <span className="text-[11.5px] text-muted-foreground">
        {lang === "ja" ? `根拠 ${total} 件を集約` : `${total} pieces of evidence gathered`}
      </span>
    </div>
  );
}

// ─── DocumentGenerationHero ────────────────────────────────────────────────
export function DocumentGenerationHero({ phase, lang, document }: {
  phase: ExecutionPhase; lang: "ja" | "en"; document?: GeneratedDocument;
}) {
  const steps = phase.tools.map((tl) => parseDocumentProgress(tl.summary || tl.name));
  const total = steps.find((s) => s.kind === "outline")?.total ?? 0;
  const slides = steps.filter((s) => s.kind === "slide" || s.kind === "section") as
    Extract<ReturnType<typeof parseDocumentProgress>, { kind: "slide" | "section" }>[];
  const rendering = steps.some((s) => s.kind === "rendering");
  const progressPct = total > 0 ? Math.min(100, Math.round((slides.length / total) * 100)) : (rendering ? 100 : 0);

  if (document) {
    return (
      <a
        href={documentUrl(document.download_url)}
        download={document.filename}
        className="flex items-center gap-2.5 rounded-lg border border-primary/40 bg-primary/[0.06] px-3 py-2.5 text-[12.5px] font-medium text-primary transition-colors hover:bg-primary/10"
      >
        <Download className="h-4 w-4 shrink-0" />
        {lang === "ja" ? "ダウンロード" : "Download"}
        <span className="font-mono text-[11px] text-muted-foreground">{document.filename}</span>
      </a>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3">
      <div className="flex items-center gap-2 text-[12px] font-medium text-foreground">
        <Presentation className="h-3.5 w-3.5 text-primary" />
        {lang === "ja" ? "資料を生成中" : "Generating document"}
        {total > 0 && <span className="font-mono text-[10.5px] text-muted-foreground">{slides.length}/{total}</span>}
      </div>
      {total > 0 && (
        <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-primary transition-[width] duration-300" style={{ width: `${progressPct}%` }} />
        </div>
      )}
      <div className="flex flex-col gap-1">
        <AnimatePresence initial={false}>
          {slides.map((s, i) => (
            <motion.div
              key={`${s.kind}-${s.index}`}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: Math.min(i, 8) * 0.06, duration: 0.2 }}
              className="flex items-center gap-2 text-[11.5px]"
            >
              <span className="w-4 shrink-0 text-center font-mono text-[10px] text-foreground/40">{s.index}</span>
              <span className="min-w-0 truncate text-foreground/80">{s.title}</span>
            </motion.div>
          ))}
        </AnimatePresence>
        {rendering && (
          <div className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
            <span className="execution-pulse inline-block h-1.5 w-1.5 rounded-full bg-primary/70" />
            {lang === "ja" ? "レンダリング中…" : "Rendering…"}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── ReasoningTicker ───────────────────────────────────────────────────────
// Replaces the generic "Thinking…" spinner for turns that have real capability
// data to narrate: "Grounded on N sources" once any gather phase lands,
// crossfading to "Composing…" once the answer starts streaming. Turns with no
// executionLanes keep the plain spinner in message.tsx untouched.
export function ReasoningTicker({ phases, composing, lang }: {
  phases: ExecutionPhase[]; composing: boolean; lang: "ja" | "en";
}) {
  const grounded = phases.filter((p) => p.group !== "documents" && p.status === "done");
  const sourceCount = grounded.reduce((s, p) => s + (p.citationCount ?? 0), 0);
  const stage = composing
    ? (lang === "ja" ? "回答を作成中…" : "Composing response…")
    : grounded.length > 0
      ? (lang === "ja" ? `${sourceCount}件の根拠を確認` : `Grounded on ${sourceCount} sources`)
      : (lang === "ja" ? "考え中…" : "Thinking…");

  return (
    <div className="relative inline-flex h-5 items-center overflow-hidden text-[13px] font-medium text-foreground">
      <AnimatePresence mode="wait">
        <motion.span
          key={stage}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.2 }}
        >
          {stage}
        </motion.span>
      </AnimatePresence>
    </div>
  );
}

// ─── ExecutionRail ─────────────────────────────────────────────────────────
export function ExecutionRail({ phases, lang, collapsed, onToggle, document }: {
  phases: ExecutionPhase[]; lang: "ja" | "en"; collapsed: boolean; onToggle: () => void;
  document?: GeneratedDocument;
}) {
  if (phases.length === 0) return null;
  const allDone = phases.every((p) => p.status === "done");
  const anyRunning = phases.some((p) => p.status === "running");
  const gather = phases.filter((p) => p.group !== "documents");
  const terminal = phases.find((p) => p.group === "documents");
  const sourceCount = gather.reduce((s, p) => s + (p.citationCount ?? 0), 0);
  const elapsed = elapsedLabel(phases);

  if (collapsed) {
    return (
      <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
        <span className="text-foreground/30">✓</span>
        <span>
          {lang === "ja"
            ? `${sourceCount}件の根拠 · ${gather.length}件を並列実行 · ${elapsed ?? ""}`
            : `${sourceCount} sources · ${gather.length} capabilities in parallel · ${elapsed ?? ""}`}
        </span>
        <button onClick={onToggle} className="inline-flex items-center gap-1 text-[11.5px] text-muted-foreground/70 hover:text-muted-foreground transition-colors">
          <ChevronDown className="h-3 w-3" />
          {lang === "ja" ? "詳細を表示" : "View execution"}
        </button>
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col gap-3 rounded-xl border border-border/60 p-3", anyRunning && "rail-glow")}>
      <div className="flex flex-wrap gap-2">
        {gather.map((p, i) => (
          <CapabilityCard key={p.id} phase={p} lang={lang} index={i} />
        ))}
      </div>
      <EvidenceBundleNode phases={phases} lang={lang} />
      {terminal && (
        terminal.id === "documents"
          ? <DocumentGenerationHero phase={terminal} lang={lang} document={document} />
          : <CapabilityCard phase={terminal} lang={lang} index={gather.length} />
      )}
      {allDone && (
        <button onClick={onToggle} className="inline-flex items-center gap-1 self-start text-[11.5px] text-muted-foreground/60 hover:text-muted-foreground transition-colors">
          <ChevronDown className="h-3 w-3 rotate-180" />
          {lang === "ja" ? "折りたたむ" : "Collapse"}
        </button>
      )}
    </div>
  );
}
