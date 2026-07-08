"use client";

import { cn } from "@/lib/utils";
import type { RingiPersona } from "@/lib/types";
import { PERSONAS, personaName, personaRole } from "./personas";

/**
 * One seat at the boardroom table. Glows with the shared `.execution-pulse`
 * idiom (opacity-only, no CPU-heavy spin) while the persona is speaking, and
 * shows their latest / streaming line beneath the avatar.
 */
export function PersonaCard({
  persona, speaking, done, line, lang, className,
}: {
  persona: RingiPersona;
  speaking: boolean;
  done: boolean;
  line: string;
  lang: string;
  className?: string;
}) {
  const meta = PERSONAS[persona];
  return (
    <div
      className={cn(
        "flex w-[210px] flex-col items-center rounded-2xl border bg-card px-4 py-3 text-center transition-all duration-300",
        meta.seat,
        speaking ? cn("ring-2 shadow-lift scale-[1.03]", meta.glow) : "shadow-card",
        !speaking && done ? "opacity-100" : "",
        !speaking && !done ? "opacity-70" : "",
        className,
      )}
    >
      <div className="relative">
        <div
          className={cn(
            "flex h-14 w-14 items-center justify-center rounded-full font-jp text-[24px] font-semibold leading-none",
            meta.disc,
            speaking && "execution-pulse",
          )}
        >
          {meta.mono}
        </div>
        {speaking && (
          <span className="absolute -right-0.5 -top-0.5 flex h-3 w-3">
            <span className="execution-pulse absolute inline-flex h-full w-full rounded-full bg-primary/70" />
            <span className="relative inline-flex h-3 w-3 rounded-full bg-primary" />
          </span>
        )}
      </div>
      <div className="mt-2 text-[15px] font-bold text-foreground">{personaName(persona, lang)}</div>
      <div className={cn("mt-1 rounded-full px-2 py-0.5 text-[10px] font-semibold", meta.chip)}>
        {personaRole(persona, lang)}
      </div>
      {line && (
        <p className="mt-2 line-clamp-4 font-jp text-[12px] leading-relaxed text-muted-foreground">
          {line}
          {speaking && <span className="ml-0.5 inline-block h-3 w-1 animate-pulse bg-foreground/40 align-middle" />}
        </p>
      )}
    </div>
  );
}
