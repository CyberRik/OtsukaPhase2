"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import type { RingiPersona } from "@/lib/types";
import { PERSONAS, personaName } from "./personas";

export interface FeedLine {
  id: number;
  persona: RingiPersona;
  text: string;
  streaming: boolean;
}

/**
 * Chronological dialogue log — the live transcript of the boardroom. Streams
 * word-by-word with a blinking caret on the active line and auto-scrolls.
 */
export function SpeechFeed({ lines, lang }: { lines: FeedLine[]; lang: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: "smooth" });
  }, [lines.length, lines[lines.length - 1]?.text]);

  return (
    <div className="rounded-2xl border border-border bg-card">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
        <span className="eyebrow text-muted-foreground">
          {lang === "ja" ? "議事ライブ" : "Live transcript"}
        </span>
      </div>
      <div ref={ref} className="max-h-[240px] space-y-3 overflow-y-auto px-4 py-3">
        {lines.length === 0 && (
          <p className="py-6 text-center text-[12px] text-muted-foreground">
            {lang === "ja" ? "「シミュレーション開始」を押してください。" : "Press “Run simulation” to begin."}
          </p>
        )}
        {lines.map((l) => {
          const meta = PERSONAS[l.persona];
          return (
            <div key={l.id} className="flex gap-2.5">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted text-[15px]">
                {meta.emoji}
              </div>
              <div className="flex-1">
                <span className="text-[11px] font-semibold text-foreground">{personaName(l.persona, lang)}</span>
                <p className={cn("font-jp text-[13px] leading-relaxed", l.persona === "senpai" ? "text-band-yellow" : "text-foreground/90")}>
                  {l.text}
                  {l.streaming && <span className="ml-0.5 inline-block h-3.5 w-1 animate-pulse bg-foreground/40 align-middle" />}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
