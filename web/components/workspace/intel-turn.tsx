"use client";

import { useEffect, useRef } from "react";
import { Globe, Lock, FileText, Newspaper, Package, Check, Loader2, AlertTriangle, ChevronRight } from "lucide-react";
import { intelCrawlStream, type IntelCrawlEvent, type CrawlPage, type IntelSource } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useCachedState } from "@/lib/chat-store";
import { AnswerMd } from "@/components/assistant/message";
import { ExecutionTimeline, type ExecutionPhase } from "@/components/agent/agent-lane";

export function IntelTurn({
  turnId,
  conversationId,
  query,
}: {
  turnId: number;
  conversationId: string;
  query: string;
}) {
  const { t, lang } = useT();
  const key = `ws:intel:${conversationId}:${turnId}`;

  const [started,      setStarted]      = useCachedState<boolean>(`${key}:started`, false);
  const [pages,        setPages]        = useCachedState<CrawlPage[]>(`${key}:pages`, []);
  const [brief,        setBrief]        = useCachedState<string>(`${key}:brief`, "");
  const [status,       setStatus]       = useCachedState<"running" | "done" | "error">(`${key}:status`, "running");
  const [plan,         setPlan]         = useCachedState<{query: string; sites: string[]} | null>(`${key}:plan`, null);
  const [showArtifact, setShowArtifact] = useCachedState<boolean>(`${key}:show`, false);
  const [collapsed,    setCollapsed]    = useCachedState<boolean>(`${key}:collapsed`, false);

  const startedRef   = useRef(false);
  const ctrlRef      = useRef<AbortController | null>(null);
  const collapseRef  = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (startedRef.current || started) return;
    startedRef.current = true;
    setStarted(true);
    setStatus("running");
    setPages([]);
    setBrief("");
    setShowArtifact(false);
    setCollapsed(false);

    if (collapseRef.current) clearTimeout(collapseRef.current);
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;

    intelCrawlStream(query, (e: IntelCrawlEvent) => {
      switch (e.type) {
        case "start":
          break;
        case "research_plan":
          setPlan({ query: e.query, sites: e.sites || [] });
          break;
        case "crawl_page":
          setPages((prev) => {
            const exists = prev.findIndex(p => p.url === e.url);
            if (exists >= 0) {
              const next = [...prev];
              next[exists] = { ...e };
              return next;
            }
            return [...prev, { ...e }];
          });
          break;
        case "intel":
          setBrief(e.markdown);
          break;
        case "error":
          setStatus("error");
          break;
        case "done":
          break;
      }
    }, { signal: ctrl.signal }).then(() => {
      setStatus((s) => (s === "error" ? s : "done"));
      if (ctrlRef.current && !ctrlRef.current.signal.aborted) {
        setTimeout(() => setShowArtifact(true), 300);
        collapseRef.current = setTimeout(() => setCollapsed(true), 1100);
      }
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => () => { if (collapseRef.current) clearTimeout(collapseRef.current); }, []);

  // Map the crawling pages into execution phases for the Timeline component.
  const phases: ExecutionPhase[] = [];
  
  if (plan) {
    phases.push({
      id: "plan",
      label: lang === "ja" ? "リサーチ計画" : "Research Plan",
      emoji: "📋",
      status: "done",
      tools: plan.sites.map(s => ({
        name: "target",
        summary: s
      }))
    });
  }

  if (pages.length > 0 || status === "running") {
    phases.push({
      id: "crawl",
      label: lang === "ja" ? "サイトを巡回中" : "Crawling sites",
      emoji: "🕸️",
      status: status === "running" ? "running" : "done",
      tools: pages.map(p => ({
        name: "page",
        summary: p.title || p.url,
      }))
    });
  }

  const activeAgentName = lang === "ja" ? "WEBリサーチャー" : "WEB RESEARCHER";
  
  const latestScreenshotPage = [...pages].reverse().find((p) => p.screenshot_b64);

  return (
    <div className="flex gap-3">
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

          {/* Browser Simulator Frame */}
          {latestScreenshotPage && (!collapsed || status === "running") && (
            <div className="mt-1 overflow-hidden rounded-lg border border-border shadow-sm animate-in fade-in zoom-in-95 duration-300">
              <div className="flex items-center gap-1.5 bg-muted/50 px-3 py-1.5 border-b border-border">
                <div className="flex gap-1.5">
                  <div className="h-2.5 w-2.5 rounded-full bg-destructive/60" />
                  <div className="h-2.5 w-2.5 rounded-full bg-warning/60" />
                  <div className="h-2.5 w-2.5 rounded-full bg-success/60" />
                </div>
                <div className="ml-2 flex-1 truncate rounded-md bg-background/50 px-2 py-0.5 text-[10px] text-muted-foreground font-mono">
                  {latestScreenshotPage.url}
                </div>
              </div>
              <div className="relative aspect-video bg-muted/20">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={`data:image/jpeg;base64,${latestScreenshotPage.screenshot_b64}`}
                  alt="Crawler view"
                  className="w-full h-full object-cover object-top"
                />
                {status === "running" && (
                  <div className="absolute inset-0 border-2 border-primary/20 animate-pulse pointer-events-none" />
                )}
              </div>
            </div>
          )}

          {brief && status === "done" && showArtifact && (
            <div className="mt-5 animate-in fade-in duration-500 fill-mode-both slide-in-from-bottom-2">
              <div className="mb-5 h-px w-8 bg-border" />
              <p className="eyebrow mb-4">
                {lang === "ja" ? "顧客ブリーフ" : "Customer Brief"}
              </p>
              <AnswerMd text={brief} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
