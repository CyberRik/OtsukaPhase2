"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { Building2, UserSearch, GraduationCap, Briefcase, Search, Target, Users } from "lucide-react";
import { crewStream, teamStream, type CrewEvent, type ResolveCandidate } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useCachedState } from "@/lib/chat-store";
import { AnswerMd } from "@/components/assistant/message";
import { translateToolSummary, type ExecutionPhase } from "@/components/agent/agent-lane";
import { cn } from "@/lib/utils";

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

  const startedRef   = useRef(false);
  const ctrlRef      = useRef<AbortController | null>(null);

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
              if (e.status === "done")    return { ...p, status: "done", resultHint: hintFrom(e.contribution), contribution: e.contribution };
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

  const agentDisplayName = (p: ExecutionPhase) =>
    lang === "en" && AGENT_NAMES_EN[p.id] ? AGENT_NAMES_EN[p.id] : p.label;

  const AGENT_ICONS: Record<string, ReactNode> = {
    researcher: <Search className="h-3.5 w-3.5" />,
    coach: <Target className="h-3.5 w-3.5" />,
    analyst: <Users className="h-3.5 w-3.5" />,
  };

  const conversationPhases = phases.filter(
    (p) => p.contribution && p.id !== "strategist" && p.id !== "team_lead",
  );

  const synthesizedFrom = () => {
    const names = conversationPhases.map(agentDisplayName);
    if (names.length === 0) return "";
    const joined =
      lang === "ja"
        ? names.join("、")
        : names.length === 1
          ? names[0]
          : `${names.slice(0, -1).join(", ")} & ${names[names.length - 1]}`;
    return lang === "ja" ? `${joined}の所見をもとに統合` : `Synthesized from ${joined}`;
  };

  const tier1Phases = phases.filter((p) => p.id !== "strategist" && p.id !== "team_lead");
  const tier2Phases = phases.filter((p) => p.id === "strategist" || p.id === "team_lead");

  const renderPhase = (p: ExecutionPhase) => {
    const isPending = p.status === "pending";
    const isRunning = p.status === "running";
    
    return (
      <div
        key={p.id}
        className={cn(
          "relative flex gap-3 duration-500 fill-mode-both",
          isPending ? "opacity-50" : "animate-in fade-in slide-in-from-bottom-1"
        )}
      >
        <div className={cn(
          "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border shadow-sm relative z-0 transition-colors duration-300",
          isRunning ? "border-primary/50 bg-primary/10 text-primary" : "border-border bg-card text-muted-foreground"
        )}>
          {AGENT_ICONS[p.id] ?? <UserSearch className="h-3.5 w-3.5" />}
        </div>
        <div className="min-w-0 flex-1 rounded-xl border border-border bg-card/60 p-3.5 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
          <div className="mb-1.5 flex items-center gap-2">
            <span className={cn(
              "text-[11px] font-semibold uppercase tracking-[0.06em]",
              isRunning ? "text-primary" : "text-muted-foreground"
            )}>
              {agentDisplayName(p)}
            </span>
            {isRunning && <span className="execution-pulse inline-block h-1.5 w-1.5 rounded-full bg-primary/70 shrink-0" />}
          </div>
          
          {/* Tool Steps */}
          {!isPending && p.tools.length > 0 && (
            <div className="flex flex-col gap-1.5 mt-2.5">
              {p.tools.map((tl, i) => {
                const isCurrentStep = isRunning && i === p.tools.length - 1;
                return (
                  <div key={`${tl.name}-${i}`} className="animate-in fade-in slide-in-from-top-1 flex items-baseline gap-2 duration-300">
                    <span className={cn(
                      "w-3 shrink-0 select-none text-center font-mono text-[10px] leading-none transition-colors duration-400",
                      isCurrentStep ? "text-primary" : "text-muted-foreground/40"
                    )}>
                      {isCurrentStep ? (
                        <span className="execution-pulse inline-block">●</span>
                      ) : (
                        <span className="animate-checkmark-pop inline-block">✓</span>
                      )}
                    </span>
                    <span className={cn(
                      "text-[12px] leading-snug transition-colors duration-400",
                      isCurrentStep ? "text-foreground" : "text-muted-foreground/60"
                    )}>
                      {translateToolSummary(tl.summary || tl.name, lang)}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Contribution */}
          {p.contribution && p.id !== "strategist" && p.id !== "team_lead" && (
            <div className={cn("mt-3.5 pt-3.5", p.tools.length > 0 && "border-t border-border/50")}>
              <AnswerMd text={p.contribution} />
            </div>
          )}
        </div>
      </div>
    );
  };

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

          {/* Integrated Agent Phases */}
          {phases.length > 0 && (
            <div className="relative flex flex-col gap-4 py-2">
              {/* Connecting line for data stream */}
              <div className="absolute left-[13px] top-6 bottom-6 w-[2px] bg-border/40 overflow-hidden rounded-full z-0">
                {tier2Phases.some(p => p.status === "running") && (
                  <div 
                    key="handoff-flash"
                    className="absolute inset-x-0 -top-[30%] h-[30%] w-full bg-gradient-to-b from-transparent via-primary to-transparent animate-flash-down" 
                  />
                )}
              </div>

              {phases.map(renderPhase)}
            </div>
          )}

          {/* Final artifact — the hero; appears once all work finishes */}
          {brief && status === "done" && showArtifact && (
            <div className="mt-5 animate-in fade-in duration-500 fill-mode-both slide-in-from-bottom-2">
              <div className="mb-5 h-px w-8 bg-border" />
              <p className="eyebrow mb-1">{mode === "team" ? t("crew.team.brief") : t("crew.deal.brief")}</p>
              {conversationPhases.length > 0 && (
                <p className="mb-4 text-[11.5px] text-muted-foreground/70">{synthesizedFrom()}</p>
              )}
              <AnswerMd text={brief} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
