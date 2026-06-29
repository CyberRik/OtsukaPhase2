"use client";

import { cn } from "@/lib/utils";

// ─── Execution model ──────────────────────────────────────────────────────────
// A major phase (one agent) is a quiet section. The agent NAME is secondary
// metadata (small, muted); the WORK being done is the primary read. Each tool call
// is a step: ● while it's the current step, ✓ once complete. No icons, no emoji —
// typography and whitespace carry the hierarchy (Cursor/Linear-style).
export interface PhaseTool {
  name: string;
  summary: string;
}
export interface ExecutionPhase {
  id: string;
  label: string; // agent name — rendered as muted section metadata only
  emoji: string; // kept on the type for the event contract; never rendered
  status: "pending" | "running" | "done";
  tools: PhaseTool[];
  resultHint?: string;
}

export function ExecutionLog({ phases }: { phases: ExecutionPhase[] }) {
  // Only sections that have actually started carry weight on screen.
  const visible = phases.filter((p) => p.status !== "pending");
  if (visible.length === 0) return null;
  return (
    <div className="flex flex-col gap-4">
      {visible.map((phase) => (
        <Section key={phase.id} phase={phase} />
      ))}
    </div>
  );
}

function Section({ phase }: { phase: ExecutionPhase }) {
  return (
    <div className="flex flex-col gap-1.5">
      {/* Agent name — secondary metadata */}
      <div className="select-none text-[10px] font-medium uppercase tracking-[0.13em] text-muted-foreground/45">
        {phase.label}
      </div>

      {/* The work — the primary read */}
      <div className="flex flex-col gap-[3px]">
        {phase.tools.map((tl, i) => {
          const running = phase.status === "running" && i === phase.tools.length - 1;
          return (
            <div key={`${tl.name}-${i}`} className="flex items-baseline gap-2.5">
              <span
                className={cn(
                  "w-3 shrink-0 select-none text-center font-mono text-[11px] leading-none",
                  running ? "text-primary" : "text-muted-foreground/40",
                )}
              >
                {running ? <span className="execution-pulse">●</span> : "✓"}
              </span>
              <span
                className={cn(
                  "min-w-0 text-[13px] leading-snug",
                  running ? "text-foreground" : "text-foreground/70",
                )}
              >
                {tl.summary || tl.name}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
