"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

export interface Whisper {
  id: number;
  text: string;
  tone: "risk" | "info" | "win";
}

/**
 * The "Guardian Angel" HUD. As the committee objects, Senpai streams a plain
 * translation of each polite Japanese objection into the concrete sales
 * data-point (risk flag) that caused it — turning the black box into coaching.
 */
export function SenpaiHud({ whispers, lang }: { whispers: Whisper[]; lang: string }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [whispers.length]);

  return (
    <div className="flex h-full flex-col rounded-2xl border border-band-yellow/25 bg-band-yellow/[0.04]">
      <div className="flex items-center gap-2 border-b border-band-yellow/20 px-4 py-3">
        <span className="text-[22px] leading-none">🪽</span>
        <div>
          <div className="text-[14px] font-bold text-foreground">
            {lang === "ja" ? "先輩ガーディアン" : "Senpai Guardian"}
          </div>
          <div className="text-[11px] text-muted-foreground">
            {lang === "ja" ? "反対の裏にあるデータを翻訳" : "Translating objections → data"}
          </div>
        </div>
      </div>
      <div ref={scrollRef} className="flex-1 space-y-2.5 overflow-y-auto px-4 py-3">
        {whispers.length === 0 && (
          <p className="text-[12px] leading-relaxed text-muted-foreground">
            {lang === "ja"
              ? "会議が始まると、私が顧客の本音をここで解説します。"
              : "When the meeting starts, I'll decode what the customer really means, here."}
          </p>
        )}
        {whispers.map((w) => (
          <div
            key={w.id}
            className={cn(
              "animate-in fade-in slide-in-from-bottom-2 rounded-xl border px-3 py-2 text-[12.5px] leading-relaxed",
              w.tone === "risk" && "border-band-red/25 bg-band-red/[0.05] text-foreground",
              w.tone === "win" && "border-band-green/25 bg-band-green/[0.06] text-foreground",
              w.tone === "info" && "border-border bg-card text-foreground",
            )}
          >
            <span className="mr-1 font-semibold text-band-yellow">
              {lang === "ja" ? "先輩:" : "Senpai:"}
            </span>
            <span className="font-jp">{w.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
