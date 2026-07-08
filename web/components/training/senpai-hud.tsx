"use client";

import { useEffect, useRef } from "react";
import { Lightbulb } from "lucide-react";
import { cn } from "@/lib/utils";

export interface Whisper {
  id: number;
  text: string;
  tone: "risk" | "info" | "win";
  flag?: string; // the deterministic risk-flag key behind this objection, if any
}

/**
 * Coach's read — the deterministic counterpart to each objection. As the
 * committee raises polite concerns, this panel names the concrete risk flag
 * (from the deal-health engine) that drives each one, in the same
 * trigger → evidence vocabulary the explainability cards use elsewhere. No
 * mascot, no "guardian" — it's the coaching layer, presented soberly.
 */
export function SenpaiHud({ whispers, lang }: { whispers: Whisper[]; lang: string }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [whispers.length]);

  return (
    <div className="flex h-full flex-col rounded-2xl border border-border bg-card">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Lightbulb className="h-4 w-4 text-primary" />
        <div>
          <div className="text-[13.5px] font-semibold text-foreground">
            {lang === "ja" ? "コーチの解説" : "Coach's read"}
          </div>
          <div className="text-[11px] text-muted-foreground">
            {lang === "ja" ? "反対意見の裏にあるリスク指標" : "The risk signal behind each objection"}
          </div>
        </div>
      </div>
      <div ref={scrollRef} className="flex-1 space-y-2 overflow-y-auto px-4 py-3">
        {whispers.length === 0 && (
          <p className="text-[12px] leading-relaxed text-muted-foreground">
            {lang === "ja"
              ? "シミュレーションを開始すると、各反対意見が「どの健全度フラグ」に対応するかをここで解説します。"
              : "Once the simulation runs, each objection is mapped here to the exact deal-health flag that triggered it."}
          </p>
        )}
        {whispers.map((w) => (
          <div
            key={w.id}
            className={cn(
              "animate-in fade-in slide-in-from-bottom-2 rounded-lg border px-3 py-2 text-[12.5px] leading-relaxed",
              w.tone === "risk" && "border-band-red/25 bg-band-red/[0.04]",
              w.tone === "win" && "border-band-green/25 bg-band-green/[0.05]",
              w.tone === "info" && "border-border bg-background",
            )}
          >
            {w.flag && (
              <span className="mb-1 inline-block rounded bg-muted px-1.5 py-0.5 font-mono text-[9.5px] font-semibold uppercase tracking-wide text-muted-foreground">
                {w.flag}
              </span>
            )}
            <p className="font-jp text-foreground/90">{w.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
