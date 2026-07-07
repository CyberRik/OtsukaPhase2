"use client";

import { cn } from "@/lib/utils";
import type { RingiPersona } from "@/lib/types";
import { PersonaCard } from "./persona-card";

type Lines = Partial<Record<RingiPersona, string>>;

/**
 * The customer's closed-door meeting table. Three committee seats arranged in a
 * triangle around an elliptical table — Shacho (top), Kacho (bottom-left),
 * Bucho (bottom-right). Collapses to a stack on narrow screens.
 */
export function BoardroomRing({
  speaking, lines, spoke, lang,
}: {
  speaking: RingiPersona | null;
  lines: Lines;
  spoke: Set<RingiPersona>;
  lang: string;
}) {
  const seat = (p: RingiPersona) => (
    <PersonaCard
      persona={p}
      speaking={speaking === p}
      done={spoke.has(p)}
      line={lines[p] ?? ""}
      lang={lang}
    />
  );

  return (
    <div className="relative">
      {/* Desktop: triangle around the table */}
      <div className="relative mx-auto hidden h-[420px] w-full max-w-[720px] md:block">
        {/* Elliptical table */}
        <div className="absolute left-1/2 top-1/2 h-[190px] w-[420px] -translate-x-1/2 -translate-y-1/2 rounded-[50%] border border-border bg-gradient-to-b from-muted/60 to-muted/20 shadow-inner">
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="eyebrow text-muted-foreground/70">
              {lang === "ja" ? "稟議 · 意思決定会議" : "Ringi · Consensus Table"}
            </span>
          </div>
        </div>
        <div className="absolute left-1/2 top-0 -translate-x-1/2">{seat("shacho")}</div>
        <div className="absolute bottom-0 left-0">{seat("kacho")}</div>
        <div className="absolute bottom-0 right-0">{seat("bucho")}</div>
      </div>

      {/* Mobile: stacked */}
      <div className="flex flex-col items-center gap-3 md:hidden">
        <div className={cn("flex items-center justify-center")}>{seat("shacho")}</div>
        <div className="flex flex-wrap justify-center gap-3">
          {seat("kacho")}
          {seat("bucho")}
        </div>
      </div>
    </div>
  );
}
