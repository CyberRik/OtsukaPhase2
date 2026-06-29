"use client";

import { useEffect, useRef } from "react";
import { Building2, UserSearch } from "lucide-react";
import { crewStream, teamStream, type CrewEvent, type ResolveCandidate } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useCachedState } from "@/lib/chat-store";
import { AnswerMd } from "@/components/assistant/message";
import { ExecutionLog, type ExecutionPhase } from "@/components/agent/agent-lane";

// Inline multi-agent execution — triggered by /crew or /team.
//
// UX model: a hierarchical execution checklist. Each major phase (an agent) is a
// parent task with a checkpoint indicator (□ → ◧ → ☑); its tool calls render as
// indented ✓ subtasks while the phase runs, then collapse to a summary row. The
// final brief is the hero. State is cached per turn so switching tabs and back
// restores everything without re-running the crew.
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

  const [started, setStarted] = useCachedState<boolean>(`${key}:started`, false);
  const [phases, setPhases] = useCachedState<ExecutionPhase[]>(`${key}:phases`, []);
  const [brief, setBrief] = useCachedState<string>(`${key}:brief`, "");
  const [statusLine, setStatusLine] = useCachedState<string>(`${key}:statusline`, "");
  const [candidates, setCandidates] = useCachedState<ResolveCandidate[]>(`${key}:cands`, []);
  const [pickQuery, setPickQuery] = useCachedState<string>(`${key}:pq`, "");
  const [status, setStatus] = useCachedState<"running" | "done" | "error">(`${key}:status`, "running");

  const startedRef = useRef(false);
  const ctrlRef = useRef<AbortController | null>(null);

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
    setStatusLine(lang === "ja" ? "分析を準備中..." : "Preparing analysis...");

    const ctrl = new AbortController();
    ctrlRef.current = ctrl;

    const onEvent = (e: CrewEvent) => {
      switch (e.type) {
        case "crew": {
          // Seed one parent phase per agent, all pending.
          setPhases(
            e.agents.map((a) => ({
              id: a.id,
              label: a.label,
              emoji: a.emoji,
              status: "pending" as const,
              tools: [],
            })),
          );
          const name = e.deal_name || e.customer;
          setStatusLine(
            name
              ? lang === "ja" ? `${name} を分析中...` : `Analyzing ${name}...`
              : lang === "ja" ? "チームを分析中..." : "Analyzing team...",
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
          // The strategist has no tools, so narrate its (otherwise silent) phase.
          if (e.status === "running" && e.id === "strategist") {
            setStatusLine(lang === "ja" ? "戦略を統合中..." : "Synthesizing strategy...");
          }
          setPhases((prev) =>
            prev.map((p) => {
              if (p.id !== e.id) return p;
              if (e.status === "running") return { ...p, status: "running" };
              if (e.status === "done") return { ...p, status: "done", resultHint: hintFrom(e.contribution) };
              if (e.status === "error") return { ...p, status: "done" };
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
          setStatusLine(lang === "ja" ? "分析完了" : "Analysis complete");
          break;

        case "error":
          setStatus("error");
          setStatusLine(lang === "ja" ? "エラーが発生しました" : "Something went wrong");
          break;
      }
    };

    run(onEvent, { signal: ctrl.signal }).then(() => setStatus((s) => (s === "error" ? s : "done")));
  };

  useEffect(() => {
    if (startedRef.current || started) return;
    startedRef.current = true;
    if (mode === "team") start((on, o) => teamStream(on, o));
    else start((on, o) => crewStream({ message: query }, on, o));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pick = (c: ResolveCandidate) => {
    if (c.deal_id) start((on, o) => crewStream({ dealId: c.deal_id! }, on, o));
    else start((on, o) => crewStream({ message: c.name }, on, o));
  };

  const picking = candidates.length > 0 && phases.length === 0;

  return (
    <div className="flex w-full flex-col gap-2.5 py-0.5">
      {/* Live status headline — a small square pulses next to it while running */}
      {statusLine && (
        <p className="flex items-center gap-2 text-[13px] font-normal leading-snug text-muted-foreground">
          {status === "running" && (
            <span className="execution-pulse inline-block h-2.5 w-2.5 shrink-0 rounded-[3px] bg-primary" />
          )}
          {statusLine}
        </p>
      )}

      {/* Ambiguous customer picker (restored: band-yellow header + chip buttons) */}
      {picking && (
        <div className="rounded-lg border border-band-yellow/40 bg-band-yellow/[0.06] p-3">
          <div className="mb-1.5 flex items-center gap-1.5 text-[11.5px] font-semibold text-band-yellow">
            <UserSearch className="h-3.5 w-3.5" />
            {lang === "ja"
              ? `「${pickQuery || query || ""}」は複数の顧客に一致します。どの顧客ですか？`
              : `"${pickQuery || query || ""}" matches several customers — which one?`}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {candidates.map((c) => (
              <button
                key={c.customer_id}
                onClick={() => pick(c)}
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

      {/* Error with no phases — crew could not find target */}
      {status === "error" && phases.length === 0 && !picking && (
        <p className="text-[12.5px] text-conf-low">
          {mode === "deal" && query ? t("crew.notFound") : t("crew.failed")}
        </p>
      )}

      {/* Hierarchical execution checklist */}
      {phases.length > 0 && <ExecutionLog phases={phases} />}

      {/* Final artifact — the hero; appears once all work finishes */}
      {brief && status === "done" && (
        <div className="mt-1 animate-in fade-in duration-300">
          <div className="mb-3 mt-1 h-px bg-border/50" />
          <p className="eyebrow mb-3">{mode === "team" ? t("crew.team.brief") : t("crew.deal.brief")}</p>
          <AnswerMd text={brief} />
        </div>
      )}
    </div>
  );
}
