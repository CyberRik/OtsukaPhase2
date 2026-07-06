"use client";

import { useEffect, useState } from "react";
import { Lock, Globe } from "lucide-react";
import type { CrawlFrame, CrawlPage } from "@/lib/api";

// Post-hoc "browser replay" for a web_research crawl that ran inside a chat turn.
// The tool blocks to completion before its frames arrive (unlike the /intel path,
// which streams them live), so we replay the captured scroll sequence as an
// auto-advancing feed — same look, played back once the browse is done.
export function CrawlReplay({
  frames,
  pages,
  lang,
}: {
  frames: CrawlFrame[];
  pages: CrawlPage[];
  lang: "ja" | "en";
}) {
  // Prefer the streamed scroll frames; fall back to any per-page screenshots.
  const shots: CrawlFrame[] = frames.length
    ? frames
    : pages
        .filter((p) => p.screenshot_b64)
        .map((p) => ({ url: p.url, index: p.index || 0, screenshot_b64: p.screenshot_b64! }));

  const [i, setI] = useState(0);

  useEffect(() => {
    if (shots.length <= 1) return;
    const id = setInterval(() => setI((x) => (x + 1) % shots.length), 750);
    return () => clearInterval(id);
  }, [shots.length]);

  if (!shots.length) return null;
  const cur = shots[Math.min(i, shots.length - 1)];
  const host = safeHost(cur.url);
  const nPages = pages.length || new Set(shots.map((s) => s.url)).size;

  return (
    <div className="my-2 max-w-md overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      {/* chrome bar */}
      <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-3 py-1.5">
        <div className="flex gap-1.5">
          <span className="h-2 w-2 rounded-full bg-destructive/50" />
          <span className="h-2 w-2 rounded-full bg-warning/50" />
          <span className="h-2 w-2 rounded-full bg-success/50" />
        </div>
        <div className="ml-1 flex min-w-0 flex-1 items-center gap-1.5 rounded-md bg-background/70 px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
          <Lock className="h-2.5 w-2.5 shrink-0 text-success/70" />
          <span className="truncate">{host}</span>
        </div>
        <span className="flex shrink-0 items-center gap-1 text-[9.5px] font-medium uppercase tracking-wide text-muted-foreground">
          <Globe className="h-3 w-3" />
          {lang === "ja" ? "巡回リプレイ" : "browse replay"}
        </span>
      </div>

      {/* frame */}
      <div className="relative aspect-[16/10] overflow-hidden bg-muted/20">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          key={i}
          src={`data:image/jpeg;base64,${cur.screenshot_b64}`}
          alt="Crawled page"
          className="h-full w-full object-cover object-top animate-in fade-in duration-300"
        />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/55 to-transparent px-2.5 pb-1 pt-5 text-[10px] font-medium text-white/90">
          <span>{lang === "ja" ? `${nPages} ページを巡回` : `browsed ${nPages} pages`}</span>
          <span className="font-mono opacity-80">{i + 1}/{shots.length}</span>
        </div>
      </div>
    </div>
  );
}

function safeHost(s: string): string {
  const v = (s || "").trim();
  if (!v) return "";
  try {
    const u = new URL(v.startsWith("http") ? v : `https://${v}`);
    return u.hostname + u.pathname.replace(/\/$/, "");
  } catch {
    return v;
  }
}
