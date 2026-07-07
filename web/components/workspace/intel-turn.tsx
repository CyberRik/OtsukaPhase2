"use client";

import { useEffect, useRef } from "react";
import { Globe, Lock, FileText, Newspaper, Package, FileSpreadsheet } from "lucide-react";
import { intelCrawlStream, type IntelCrawlEvent, type CrawlPage } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useCachedState } from "@/lib/chat-store";
import { AnswerMd } from "@/components/assistant/message";
import { downloadMessageAsDocx, downloadMessageAsXlsx } from "@/lib/artifact-export";
import { ExecutionTimeline, type ExecutionPhase } from "@/components/agent/agent-lane";

type Found = { products: number; news: number; pdfs: number };
const NO_FOUND: Found = { products: 0, news: 0, pdfs: 0 };

export function IntelTurn({
  turnId,
  conversationId,
  query,
}: {
  turnId: number;
  conversationId: string;
  query: string;
}) {
  const { lang } = useT();
  const key = `ws:intel:${conversationId}:${turnId}`;

  const [started,      setStarted]      = useCachedState<boolean>(`${key}:started`, false);
  const [pages,        setPages]        = useCachedState<CrawlPage[]>(`${key}:pages`, []);
  const [brief,        setBrief]        = useCachedState<string>(`${key}:brief`, "");
  const [status,       setStatus]       = useCachedState<"running" | "done" | "error">(`${key}:status`, "running");
  const [plan,         setPlan]         = useCachedState<{ query: string; sites: string[] } | null>(`${key}:plan`, null);
  const [showArtifact, setShowArtifact] = useCachedState<boolean>(`${key}:show`, false);
  const [collapsed,    setCollapsed]    = useCachedState<boolean>(`${key}:collapsed`, false);

  // Live browser-feed state. `frame` holds only the LATEST screenshot (overwritten
  // each tick, never accumulated) so the store stays light while the view animates.
  const [frame,        setFrame]        = useCachedState<string>(`${key}:frame`, "");
  const [frameCount,   setFrameCount]   = useCachedState<number>(`${key}:fc`, 0);
  const [currentUrl,   setCurrentUrl]   = useCachedState<string>(`${key}:curl`, "");
  const [found,        setFound]        = useCachedState<Found>(`${key}:found`, NO_FOUND);

  const startedRef  = useRef(false);
  const ctrlRef     = useRef<AbortController | null>(null);
  const collapseRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (startedRef.current || started) return;
    startedRef.current = true;
    setStarted(true);
    setStatus("running");
    setPages([]);
    setBrief("");
    setFrame("");
    setFrameCount(0);
    setCurrentUrl("");
    setFound(NO_FOUND);
    setShowArtifact(false);
    setCollapsed(false);

    if (collapseRef.current) clearTimeout(collapseRef.current);
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;

    intelCrawlStream(query, (e: IntelCrawlEvent) => {
      switch (e.type) {
        case "research_plan":
          setPlan({ query: e.query, sites: e.sites || [] });
          break;
        case "crawl_frame":
          // The live feed: swap in the newest scroll frame.
          setFrame(e.screenshot_b64);
          setFrameCount((n) => n + 1);
          setCurrentUrl(e.url);
          break;
        case "crawl_page":
          setCurrentUrl(e.url);
          if (e.found) setFound(e.found);
          setPages((prev) => {
            // Store metadata only — visuals come from the live frame, not per-page
            // screenshots, so the cache never balloons.
            const slim: CrawlPage = { ...e, screenshot_b64: undefined };
            const at = prev.findIndex((p) => p.url === e.url);
            if (at >= 0) {
              const next = [...prev];
              next[at] = slim;
              return next;
            }
            return [...prev, slim];
          });
          break;
        case "intel":
          setBrief(e.markdown);
          if (e.assets) setFound(e.assets);
          break;
        case "error":
          setStatus("error");
          break;
      }
    }, { signal: ctrl.signal }).then(() => {
      setStatus((s) => (s === "error" ? s : "done"));
      if (ctrlRef.current && !ctrlRef.current.signal.aborted) {
        setTimeout(() => setShowArtifact(true), 300);
        collapseRef.current = setTimeout(() => setCollapsed(true), 1400);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => () => { if (collapseRef.current) clearTimeout(collapseRef.current); }, []);

  // Crawl pages → execution-timeline phases (the textual story beside the feed).
  const phases: ExecutionPhase[] = [];
  if (plan) {
    phases.push({
      id: "plan",
      label: lang === "ja" ? "リサーチ計画" : "Research Plan",
      emoji: "📋",
      status: "done",
      tools: plan.sites.map((s) => ({ name: "target", summary: s })),
    });
  }
  if (pages.length > 0 || status === "running") {
    phases.push({
      id: "crawl",
      label: lang === "ja" ? "サイトを巡回中" : "Crawling site",
      emoji: "🕸️",
      status: status === "running" ? "running" : "done",
      tools: pages.map((p) => ({ name: "page", summary: p.title || p.url })),
    });
  }

  const running = status === "running";
  const showFeed = (running || (!!frame && !collapsed)) && status !== "error";
  const hostname = safeHost(currentUrl || query);
  const activeAgentName = lang === "ja" ? "WEBリサーチャー" : "WEB RESEARCHER";

  return (
    <div className="flex gap-3">
      <style>{`@keyframes intelScan{0%{transform:translateY(-120%)}100%{transform:translateY(1100%)}}@keyframes intelSweep{0%{transform:translateX(-100%)}100%{transform:translateX(500%)}}`}</style>
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-navy text-white">
        <Globe className="h-[18px] w-[18px]" />
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
          {activeAgentName}
        </div>

        <div className="flex w-full flex-col gap-3 py-0.5">
          {status === "error" && phases.length === 0 && (
            <p className="text-[12.5px] text-conf-low">
              {lang === "ja" ? "クロールに失敗しました" : "Crawl failed"}
            </p>
          )}

          {phases.length > 0 && (
            <ExecutionTimeline
              phases={phases}
              collapsed={collapsed}
              onToggle={() => setCollapsed((v) => !v)}
              lang={lang}
            />
          )}

          {/* Live browser feed */}
          {showFeed && (
            <div className="overflow-hidden rounded-xl border border-border bg-card shadow-[0_8px_30px_-12px_rgba(16,24,40,0.35)] animate-in fade-in zoom-in-95 duration-300">
              {/* chrome bar */}
              <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-3 py-2">
                <div className="flex gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-full bg-destructive/50" />
                  <span className="h-2.5 w-2.5 rounded-full bg-warning/50" />
                  <span className="h-2.5 w-2.5 rounded-full bg-success/50" />
                </div>
                <div className="ml-1 flex min-w-0 flex-1 items-center gap-1.5 rounded-md bg-background/70 px-2 py-1 font-mono text-[10.5px] text-muted-foreground">
                  <Lock className="h-3 w-3 shrink-0 text-success/70" />
                  <span className="truncate">{hostname}</span>
                </div>
                {running ? (
                  <span className="flex shrink-0 items-center gap-1.5 rounded-full bg-destructive/10 px-2 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide text-destructive">
                    <span className="relative flex h-1.5 w-1.5">
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-destructive opacity-70" />
                      <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-destructive" />
                    </span>
                    Live
                  </span>
                ) : (
                  <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {lang === "ja" ? "取得済" : "Captured"}
                  </span>
                )}
              </div>

              {/* loading shimmer under chrome */}
              <div className="h-0.5 w-full overflow-hidden bg-transparent">
                {running && <div className="h-full w-1/5 rounded-full bg-primary/70" style={{ animation: "intelSweep 1.3s ease-in-out infinite" }} />}
              </div>

              {/* viewport */}
              <div className="relative aspect-[16/10] overflow-hidden bg-muted/20">
                {frame ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    key={frameCount}
                    src={`data:image/jpeg;base64,${frame}`}
                    alt="Live crawler view"
                    className="h-full w-full object-cover object-top animate-in fade-in duration-200"
                  />
                ) : (
                  <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-muted-foreground">
                    <Globe className="h-6 w-6 animate-pulse" />
                    <span className="font-mono text-[11px]">
                      {lang === "ja" ? "ページを読み込み中…" : "loading page…"}
                    </span>
                  </div>
                )}

                {/* scan line + focus ring while live */}
                {running && frame && (
                  <>
                    <div className="pointer-events-none absolute inset-x-0 top-0 h-16 bg-gradient-to-b from-primary/25 to-transparent" style={{ animation: "intelScan 2.1s linear infinite" }} />
                    <div className="pointer-events-none absolute inset-0 ring-1 ring-inset ring-primary/20" />
                  </>
                )}

                {/* bottom status strip */}
                <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/55 to-transparent px-3 pb-1.5 pt-6 text-[10.5px] font-medium text-white/90">
                  <span className="truncate">
                    {running
                      ? (lang === "ja" ? `巡回中 · ${pages.length + (frame ? 1 : 0)} ページ目` : `browsing · page ${pages.length + (frame ? 1 : 0)}`)
                      : (lang === "ja" ? `${pages.length} ページを取得` : `${pages.length} pages captured`)}
                  </span>
                  <span className="font-mono opacity-80">{frameCount} ▮</span>
                </div>
              </div>

              {/* found-asset counters */}
              <div className="flex items-center gap-4 border-t border-border bg-muted/30 px-3 py-1.5 text-[11px] text-muted-foreground">
                <Counter icon={<Package className="h-3 w-3" />} n={found.products} label={lang === "ja" ? "製品" : "products"} />
                <Counter icon={<Newspaper className="h-3 w-3" />} n={found.news} label={lang === "ja" ? "ニュース" : "news"} />
                <Counter icon={<FileText className="h-3 w-3" />} n={found.pdfs} label="PDF" />
              </div>
            </div>
          )}

          {/* Final brief — the hero */}
          {brief && status === "done" && showArtifact && (
            <div className="mt-5 animate-in fade-in duration-500 fill-mode-both slide-in-from-bottom-2">
              <div className="mb-5 h-px w-8 bg-border" />
              <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                <p className="eyebrow">{lang === "ja" ? "顧客ブリーフ" : "Customer Brief"}</p>
                <span className="flex items-center gap-2">
                  <button
                    onClick={() => { void downloadMessageAsXlsx(brief, lang, { slug: "intel-brief" }); }}
                    title={lang === "ja" ? "Excel (.xlsx) で書き出す" : "Export to Excel (.xlsx)"}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-[11.5px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                  >
                    <FileSpreadsheet className="h-3.5 w-3.5" />
                    Excel
                  </button>
                  <button
                    onClick={() => { void downloadMessageAsDocx(brief, lang, { slug: "intel-brief" }); }}
                    title={lang === "ja" ? "Word (.docx) で書き出す" : "Export to Word (.docx)"}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-[11.5px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                  >
                    <FileText className="h-3.5 w-3.5" />
                    Word
                  </button>
                </span>
              </div>
              <AnswerMd text={brief} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Counter({ icon, n, label }: { icon: React.ReactNode; n: number; label: string }) {
  return (
    <span className={`flex items-center gap-1 tabular-nums transition-colors ${n > 0 ? "text-foreground" : ""}`}>
      {icon}
      <span className="font-semibold">{n}</span>
      <span className="text-muted-foreground">{label}</span>
    </span>
  );
}

function safeHost(s: string): string {
  const v = (s || "").trim();
  if (!v) return "";
  try {
    return new URL(v.startsWith("http") ? v : `https://${v}`).hostname + new URL(v.startsWith("http") ? v : `https://${v}`).pathname.replace(/\/$/, "");
  } catch {
    return v;
  }
}
