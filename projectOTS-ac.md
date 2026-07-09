rch, Target, Users, FileSpreadsheet, FileText } from "lucide-react";
import { crewStream, teamStream, type CrewEvent, type ResolveCandidate } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useCachedState } from "@/lib/chat-store";
import { AnswerMd } from "@/components/assistant/message";
import { downloadMessageAsDocx, downloadMessageAsXlsx } from "@/lib/artifact-export";
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
              <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                <p className="eyebrow">{mode === "team" ? t("crew.team.brief") : t("crew.deal.brief")}</p>
                <span className="flex items-center gap-2">
                  <button
                    onClick={() => { void downloadMessageAsXlsx(brief, lang, { slug: mode === "team" ? "team-brief" : "deal-brief" }); }}
                    title={lang === "ja" ? "Excel (.xlsx) で書き出す" : "Export to Excel (.xlsx)"}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-[11.5px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                  >
                    <FileSpreadsheet className="h-3.5 w-3.5" />
                    Excel
                  </button>
                  <button
                    onClick={() => { void downloadMessageAsDocx(brief, lang, { slug: mode === "team" ? "team-brief" : "deal-brief" }); }}
                    title={lang === "ja" ? "Word (.docx) で書き出す" : "Export to Word (.docx)"}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-[11.5px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                  >
                    <FileText className="h-3.5 w-3.5" />
                    Word
                  </button>
                </span>
              </div>
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
````

## File: prompt.txt
````
1. お客様のC01について、最近ネットが遅くて業務に支障が出ていると相談を受けました。また、PCもWindows 8時代のもので古いです。予算にはシビアです。どのような提案をすべきですか？ (product)

2. 

I am conducting a massive quarterly pipeline audit and need you to gather an immense amount of data across various sectors, accounts, and historical strategies. Do not answer until you have executed all of the following research steps:
1. Look up the SPR pipelines for three specific reps: 'R01', 'R05', and 'R12'.
2. Query the exact current deal status for the following three customers individually: 'アクメ商事', 'グローバルテック', and '未来工業'.
3. Perform a semantic note search for EACH of those three customers looking for the phrase "budget slashed" or "予算削減". 
4. Find similar comparable deals for 'アクメ商事' (in the '製造' industry) and for 'グローバルテック' (in the 'IT' industry) to see how we've handled them in the past.
5. Run four separate faceted searches for past deals:
   - 'サーバー' deals in '製造' that were 'won'.
   - 'ソフトウェア' deals in '医療' that were 'lost'.
   - 'ネットワーク機器' deals in '金融' that were 'open' with an amount over 10,000,000 JPY.
   - Any deals containing the product code 'MON27'.
6. Check our playbook for four different tactical scenarios individually:
   - Scenario 1: '決定先延ばし' (decision postponed)
   - Scenario 2: '値引き' (discounting)
   - Scenario 3: '競合優位' (competitor advantage)
   - Scenario 4: '担当者変更' (change in point of contact)
Only once you have successfully pulled all of this data from the tools, synthesize it into a massive, heavily detailed quarterly review report. (20 tools)

3. I am conducting a massive quarterly pipeline audit and need you to gather an immense amount of data across various sectors, accounts, and historical strategies. Do not answer until you have executed all of the following research steps:
1. Look up the SPR pipelines for three specific reps: 'R01', 'R05', and 'R12'.
2. Query the exact current deal status for the following three customers individually: 'アクメ商事', 'グローバルテック', and '未来工業'.
3. Perform a semantic note search for EACH of those three customers looking for the phrase "budget slashed" or "予算削減".
4. Find similar comparable deals for 'アクメ商事' (in the '製造' industry) and for 'グローバルテック' (in the 'IT' industry) to see how we've handled them in the past.
5. Run four separate faceted searches for past deals:
   - 'サーバー' deals in '製造' that were 'won'.
   - 'ソフトウェア' deals in '医療' that were 'lost'.
   - 'ネットワーク機器' deals in '金融' that were 'open' with an amount over 10,000,000 JPY.
   - Any deals containing the product code 'MON27'.
6. Check our playbook for four different tactical scenarios individually:
   - Scenario 1: '決定先延ばし' (decision postponed)
   - Scenario 2: '値引き' (discounting)
   - Scenario 3: '競合優位' (competitor advantage)
   - Scenario 4: '担当者変更' (change in point of contact)
7. Also web search for the latest enterprise IT budget trend benchmarks for Japanese manufacturing SMEs in 2026, and web search separately for current cyber insurance pricing trends for mid-market firms.
Only once you have successfully pulled all of this data from the tools, synthesize it into a massive, heavily detailed quarterly review report, and generate it as a docx document. (21 tools + docx — regression test for the hybrid router: a trailing "generate it as a docx" must NOT hijack this into the one-shot planner; it must stay in the ReAct loop, run every distinct lookup, and only then generate the docx.)
````

## File: senpai/documents/export.py
````python
"""Export an HTML deck (senpai/documents/html_render.py) to PDF and editable PPTX.

Both exports drive the same headless Chromium that senpai/tools/crawl.py already uses
(Playwright), so no new runtime stack. Everything here is synchronous and expects to be
called from the sync tool layer (the same context crawl_site runs in); if Chromium is
unavailable it degrades gracefully — `export_html_deck` returns which artifacts it managed
to produce and the caller falls back to the native python-pptx renderer.

PDF path: `page.pdf()` of the print-media HTML — pixel-perfect, one slide per page.

PPTX path (the "editable text over a faithful background" strategy):
  1. Measure every `.pptx-text` element's box + computed font (via page.evaluate).
  2. Hide those text elements and screenshot each `.slide` → a full-bleed background that
     carries all the decoration (accent bars, cards, charts, table rules) but no text.
  3. Build a 16:9 PPTX: each slide = the background picture + one NATIVE python-pptx
     text box per measured element, positioned by px→EMU conversion, with the figure
     tokens re-bolded in navy (render._STAT_RE convention). Result looks ~identical to the
     HTML yet every word is real, selectable and editable in PowerPoint.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

from senpai.documents.html_render import SLIDE_W, SLIDE_H, _STAT_RE

# Standard PowerPoint 16:9 canvas = 13.333in × 7.5in. Our HTML slide is SLIDE_W×SLIDE_H
# CSS px at 96 dpi, i.e. exactly that canvas, so 1 px = 9525 EMU and 1 px = 0.75 pt.
_EMU_PER_PX = 9525
_PT_PER_PX = 0.75
_SLIDE_W_EMU = SLIDE_W * _EMU_PER_PX   # 12,192,000
_SLIDE_H_EMU = SLIDE_H * _EMU_PER_PX   # 6,858,000

# A JP-friendly typeface that ships with Windows/Mac PowerPoint, so the editable text
# renders correctly on the user's machine even though Chromium laid it out in Noto.
_PPTX_FONT = "Yu Gothic"

# One evaluate() over the whole document: per slide, its notes + every editable text run's
# box (relative to the slide) and computed style.
_MEASURE_JS = r"""
() => Array.from(document.querySelectorAll('.slide')).map(slide => {
  const sr = slide.getBoundingClientRect();
  const texts = Array.from(slide.querySelectorAll('.pptx-text')).map(el => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return {
      x: r.x - sr.x, y: r.y - sr.y, w: r.width, h: r.height,
      text: (el.innerText || '').replace(/ /g, ' ').trim(),
      size: parseFloat(cs.fontSize) || 16,
      weight: parseInt(cs.fontWeight, 10) || 400,
      italic: cs.fontStyle === 'italic',
      color: cs.color || 'rgb(26,35,48)',
      align: cs.textAlign || 'left',
      nowrap: cs.whiteSpace === 'nowrap' || cs.whiteSpace === 'pre'
    };
  }).filter(t => t.text.length > 0);
  return { notes: slide.getAttribute('data-notes') || '', texts };
});
"""

# Injected before screenshotting: make the editable text invisible in the background so
# it isn't baked in twice, WITHOUT disturbing layout or decoration. `color: transparent`
# (not visibility:hidden) is deliberate — visibility:hidden would also drop the element's
# own background/border, which would erase table-header fills and card backgrounds that
# live on the same element as the text. The `*` clause also neutralizes the navy figure
# runs so they don't survive as baked color under the overlaid text.
_EXPORT_CSS = """
.pptx-text, .pptx-text * { color: transparent !important; text-shadow: none !important; }
.slide { box-shadow: none !important; border-radius: 0 !important; }
.nav { display: none !important; }
"""


def render_deck(spec: dict, *, kind: str, slug: str, lang: str = "ja") -> dict[str, "Path"]:
    """Render a deck spec to HTML + PDF + editable PPTX and return the produced files
    as {"pptx": Path, "html": Path, "pdf": Path?}. This is the one HTML-first path shared
    by every deck generator (generate_pptx, generate_proposal, the planner). The PPTX is
    always produced: if headless Chromium is unavailable the browser exports are skipped
    and it falls back to the native python-pptx renderer, so a deck is never lost.

    `kind` names the file family (e.g. 'pptx', 'proposal'); `slug` is the human filename
    stem (deal id or title)."""
    from senpai.documents import html_render
    from senpai.documents.render import output_path, render_pptx

    html = html_render.render_html(spec, lang=lang)
    html_path = output_path(kind, slug, "html")
    html_path.write_text(html, encoding="utf-8")
    pptx_path = output_path(kind, slug, "pptx")
    pdf_path = output_path(kind, slug, "pdf")

    produced = export_html_deck(html, pptx_path=pptx_path, pdf_path=pdf_path)
    if not produced.get("pptx"):
        render_pptx(spec, pptx_path)  # browser unavailable → native fallback

    files: dict[str, Path] = {"pptx": pptx_path, "html": html_path}
    if produced.get("pdf"):
        files["pdf"] = pdf_path
    return files


def export_html_deck(html: str, *, pptx_path: Path | None = None,
                     pdf_path: Path | None = None) -> dict[str, bool]:
    """Produce the requested artifacts from `html`. Returns e.g. {"pptx": True,
    "pdf": True}. On any browser failure returns {} so the caller can fall back."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        return {}

    done: dict[str, bool] = {}
    pw = browser = None
    try:
        import sys, asyncio
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": SLIDE_W, "height": SLIDE_H}, device_scale_factor=2)
        page = ctx.new_page()
        page.set_content(html, wait_until="load")
        try:
            page.evaluate("() => document.fonts && document.fonts.ready")
        except Exception:
            pass
        page.wait_for_timeout(180)  # let fonts/layout settle

        if pdf_path is not None:
            try:
                page.emulate_media(media="print")
                page.pdf(path=str(pdf_path), width=f"{SLIDE_W}px", height=f"{SLIDE_H}px",
                         print_background=True, margin={"top": "0", "right": "0",
                                                        "bottom": "0", "left": "0"})
                page.emulate_media(media="screen")
                done["pdf"] = True
            except Exception:
                done["pdf"] = False

        if pptx_path is not None:
            try:
                _render_pptx_from_page(page, pptx_path)
                done["pptx"] = True
            except Exception:
                done["pptx"] = False
    except Exception:
        return done
    finally:
        for obj, meth in ((browser, "close"), (pw, "stop")):
            try:
                if obj is not None:
                    getattr(obj, meth)()
            except Exception:
                pass
    return done


def _render_pptx_from_page(page, pptx_path: Path) -> None:
    """Measure text, screenshot text-hidden slide backgrounds, assemble the PPTX."""
    from pptx import Presentation
    from pptx.util import Emu, Pt
    from pptx.enum.text import PP_ALIGN, MSO_AUTO_SIZE

    metas = page.evaluate(_MEASURE_JS)
    handles = page.query_selector_all(".slide")
    page.add_style_tag(content=_EXPORT_CSS)  # hide text + flatten AFTER measuring
    backgrounds = [h.screenshot(type="png") for h in handles]

    align_map = {"center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT,
                 "justify": PP_ALIGN.JUSTIFY, "left": PP_ALIGN.LEFT, "start": PP_ALIGN.LEFT}

    prs = Presentation()
    prs.slide_width = Emu(_SLIDE_W_EMU)
    prs.slide_height = Emu(_SLIDE_H_EMU)
    blank = prs.slide_layouts[6]

    for meta, bg in zip(metas, backgrounds):
        slide = prs.slides.add_slide(blank)
        slide.shapes.add_picture(io.BytesIO(bg), 0, 0,
                                 width=Emu(_SLIDE_W_EMU), height=Emu(_SLIDE_H_EMU))
        for t in meta.get("texts", []):
            # Give each box a little horizontal slack so PowerPoint/LibreOffice metrics
            # (Yu Gothic) — slightly wider than Chromium's Noto — don't wrap a line that
            # fit in the HTML. Extend symmetrically so centered text stays centered, and
            # clamp x so we never push off the left edge.
            slack = max(14, round(t["w"] * 0.06))
            x = max(0, int((t["x"] - slack / 2) * _EMU_PER_PX))
            box = slide.shapes.add_textbox(
                Emu(x), Emu(int(t["y"] * _EMU_PER_PX)),
                Emu(int((t["w"] + slack) * _EMU_PER_PX)), Emu(int(max(t["h"], 8) * _EMU_PER_PX)))
            tf = box.text_frame
            # Honor the HTML's white-space: a nowrap element (e.g. a big stat figure) must
            # not wrap in PowerPoint — it overflows its box symmetrically instead, which for
            # centered text keeps it centered rather than breaking onto a second line.
            tf.word_wrap = not t.get("nowrap")
            for side in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
                setattr(tf, side, Emu(0))
            try:
                tf.auto_size = MSO_AUTO_SIZE.NONE
            except Exception:
                pass
            align = align_map.get((t.get("align") or "left").lower(), PP_ALIGN.LEFT)
            size = Pt(t["size"] * _PT_PER_PX)
            color = _parse_rgb(t["color"])
            bold = t.get("weight", 400) >= 600
            italic = bool(t.get("italic"))
            # A single element may hold several visual lines (e.g. a cover subtitle with
            # line breaks) — one PPTX paragraph per line so they stay editable and stacked.
            for li, line in enumerate(t["text"].split("\n")):
                para = tf.paragraphs[0] if li == 0 else tf.add_paragraph()
                para.alignment = align
                _add_runs(para, line, size, color, bold=bold, italic=italic)
        notes = (meta.get("notes") or "").strip()
        if notes:
            slide.notes_slide.notes_text_frame.text = notes

    prs.save(str(pptx_path))


def _add_runs(paragraph, text: str, size, base_color, *, bold: bool, italic: bool) -> None:
    """Emit runs for `text`, bolding grounded figure tokens in navy (same rule as
    render._add_styled_runs) while keeping the element's base weight/italic/color."""
    from pptx.dml.color import RGBColor
    from pptx.oxml.ns import qn

    _STAT_NAVY = RGBColor(0x00, 0x20, 0x60)
    parts = _STAT_RE.split(text or "")
    for i, part in enumerate(parts):
        if not part:
            continue
        run = paragraph.add_run()
        run.text = part
        run.font.size = size
        run.font.italic = italic
        is_fig = i % 2 == 1
        run.font.bold = True if is_fig else bold
        run.font.color.rgb = _STAT_NAVY if is_fig else base_color
        # Set the typeface for Latin, East-Asian and complex scripts so Japanese renders
        # in the intended font rather than the theme default.
        run.font.name = _PPTX_FONT
        rpr = run._r.get_or_add_rPr()
        for tag in ("a:latin", "a:ea", "a:cs"):
            el = rpr.find(qn(tag))
            if el is None:
                el = rpr.makeelement(qn(tag), {})
                rpr.append(el)
            el.set("typeface", _PPTX_FONT)


_RGB_RE = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")


def _parse_rgb(css: str):
    from pptx.dml.color import RGBColor
    m = _RGB_RE.match(css or "")
    if m:
        return RGBColor(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return RGBColor(0x1A, 0x23, 0x30)


_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
_RULE_RE = re.compile(r"^-{3,}$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")


def _text_to_doc_spec(text: str, title: str) -> dict:
    sections: list[dict] = []
    current = {"heading": "", "body": []}

    def flush() -> None:
        if current["body"] or current["heading"]:
            sections.append({"heading": current["heading"], "body": list(current["body"])})

    for raw_line in (text or "").replace("\r", "").split("\n"):
        line = raw_line.strip()
        if not line or _RULE_RE.match(line):
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            current = {"heading": heading.group(1).strip(), "body": []}
            continue
        bullet = _BULLET_RE.match(line)
        current["body"].append(f"- {bullet.group(1).strip()}" if bullet else line)
    flush()

    if not sections:
        sections = [{"heading": "", "body": [(text or "").strip() or "(no content)"]}]

    return {"title": title or "Export", "subtitle": "", "sections": sections}


def export_text_as_docx(text: str, title: str = "", slug: str = "") -> dict:
    """Render `text` verbatim (parsed, not LLM-rewritten) to a .docx and register
    it for download. Returns the registry record (doc_id, filename, download_url)."""
    from senpai.documents import registry, render
    spec = _text_to_doc_spec(text, title)
    path = render.output_path("export", slug or title or "chat", "docx")
    render.render_docx(spec, path)
    return registry.register("export", path)
````

## File: senpai/orchestration/metadata.py
````python
from enum import Enum
from dataclasses import dataclass

class OperationKind(Enum):
    READ = "read"         # Safe, deterministic data fetching
    SEARCH = "search"     # Safe, non-deterministic queries (e.g., web_search)
    COMPUTE = "compute"   # CPU-bound data transformation
    WRITE = "write"       # State-mutating internal actions
    EXTERNAL = "external" # State-mutating external actions (e.g., send_email)

@dataclass
class CapabilityMetadata:
    kind: OperationKind
    parallel_safe: bool = True
    idempotent: bool = True
    cacheable: bool = False
    requires_confirmation: bool = False
    max_concurrency: int = 8
    timeout: int = 30
    retries: int = 2

# Global registry of metadata for all tools exposed to the LLM.
# Read/Search tools are generally parallel_safe.
# Write/External tools are strictly serialized and may require confirmation.
TOOL_METADATA: dict[str, CapabilityMetadata] = {
    "query_spr": CapabilityMetadata(OperationKind.READ, cacheable=True),
    "find_deals": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "find_similar_deals": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "retrieve_playbook": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "search_notes": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "lookup_customer_environment": CapabilityMetadata(OperationKind.READ, cacheable=True),
    "get_product_info": CapabilityMetadata(OperationKind.READ, cacheable=True),
    "score_deal_health": CapabilityMetadata(OperationKind.COMPUTE),
    "review_sales_note": CapabilityMetadata(OperationKind.COMPUTE),
    "draft_daily_report": CapabilityMetadata(OperationKind.COMPUTE),
    "route_to_expert": CapabilityMetadata(OperationKind.COMPUTE),
    "summarize_reports": CapabilityMetadata(OperationKind.COMPUTE),
    "get_seasonal_context": CapabilityMetadata(OperationKind.READ, cacheable=True),
    "morning_briefing": CapabilityMetadata(OperationKind.COMPUTE),
    "list_at_risk_deals": CapabilityMetadata(OperationKind.READ),
    "team_pipeline_overview": CapabilityMetadata(OperationKind.COMPUTE),
    "team_report_digest": CapabilityMetadata(OperationKind.COMPUTE),
    "rep_coaching_focus": CapabilityMetadata(OperationKind.COMPUTE),
    "draft_message": CapabilityMetadata(OperationKind.COMPUTE),
    "web_search": CapabilityMetadata(OperationKind.SEARCH, max_concurrency=4, retries=3),
    "search_knowledge": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "search_products": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "create_quote": CapabilityMetadata(OperationKind.COMPUTE),
    "schedule_meeting": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=False),
    "send_email": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=True),
    "get_calendar": CapabilityMetadata(OperationKind.READ, cacheable=True),
    "query_graph": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "segment_intelligence": CapabilityMetadata(OperationKind.SEARCH, cacheable=True),
    "search_workspace_documents": CapabilityMetadata(OperationKind.SEARCH, max_concurrency=4),
    "edit_workspace_document": CapabilityMetadata(OperationKind.WRITE, parallel_safe=False, idempotent=False, requires_confirmation=False),
    "generate_proposal": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=False),
    "generate_ringisho": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=False),
    "generate_pptx": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=False),
    "generate_docx": CapabilityMetadata(OperationKind.EXTERNAL, parallel_safe=False, idempotent=False, requires_confirmation=False),
}
````

## File: senpai/planner/plan.py
````python
"""`document_plan(selection)` — turn a capability Selection into an ExecutionPlan.

The graph is deliberately shallow (two levels), which is all document generation
needs and keeps the first planner minimal:

    Level 0 (parallel gather):  conversation / workspace / crm / knowledge / solutions / web
    Level 1 (terminal):         documents  ── depends on every gather task

Every gather task runs in parallel (they're independent READ/SEARCH); the single
`documents` task depends on all of them, so the engine runs it only after the
grounding is in the bundle. The edges ARE the dependency: no ordering logic lives
in the engine or the capabilities — it's entirely expressed by `depends_on`.
"""
from __future__ import annotations

from senpai.orchestration import ExecutionPlan, Task, TaskPolicy
from senpai.planner.selection import Selection

_GATHER = "gather"
_DOCS = "documents"


def document_plan(sel: Selection) -> ExecutionPlan:
    query = sel.goal

    # Organize is a self-contained WRITE over the workspace — no gather graph.
    if sel.doc_kind == "organize":
        return ExecutionPlan(tasks=(Task(
            id="workspace_organize", capability="workspace_organize",
            op="apply" if sel.confirm else "plan", inputs={"confirm": sel.confirm},
            policy=TaskPolicy(retries=0, on_failure="skip"),
            group=_DOCS, summary="ワークスペースを整理"),))

    gather: list[Task] = []

    if "conversation" in sel.capabilities:
        gather.append(Task(id="conversation", capability="conversation",
                           inputs={"query": query}, group=_GATHER,
                           summary="会話の文脈を収集"))
    if "workspace" in sel.capabilities:
        gather.append(Task(id="workspace", capability="workspace",
                           inputs={"query": query}, group=_GATHER,
                           summary="ローカル文書を検索・抽出"))
    if "crm" in sel.capabilities:
        gather.append(Task(id="crm", capability="crm",
                           inputs={"deal_id": sel.deal_id or "",
                                   "customer_id": sel.customer_id or ""},
                           group=_GATHER, summary="社内記録を取得"))
    if "knowledge" in sel.capabilities:
        gather.append(Task(id="knowledge", capability="knowledge",
                           inputs={"query": query}, group=_GATHER,
                           summary="社内ナレッジを照合"))
    if "solutions" in sel.capabilities:
        gather.append(Task(id="solutions", capability="solutions",
                           inputs={"query": query, "deal_id": sel.deal_id or "",
                                   "customer_id": sel.customer_id or ""},
                           group=_GATHER, summary="関連するソリューション・製品情報を検索"))
    if "web" in sel.capabilities:
        gather.append(Task(id="web", capability="web",
                           inputs={"query": query}, group=_GATHER,
                           summary="Web検索でカバー"))

    deps = frozenset(t.id for t in gather)
    # A note WRITEs into the workspace; proposal/pptx/docx GENERATE a downloadable file.
    if sel.doc_kind == "note":
        terminal = Task(
            id="workspace_write", capability="workspace_write", op="note",
            inputs={"goal": query, "prompt": query, "path": sel.path, "lang": sel.lang},
            depends_on=deps, policy=TaskPolicy(retries=0, on_failure="skip"),
            group=_DOCS, summary="ノートを保存")
    else:
        # "cover all of this customer's deals" (proposal only) — the deterministic
        # generator merges every deal on file instead of silently grounding on
        # just the biggest one.
        deal_ids: list[str] = []
        if sel.doc_kind == "proposal" and sel.all_deals and sel.customer_id:
            from senpai.data import store as _store
            deal_ids = [d["deal_id"] for d in _store.deals_for_customer(sel.customer_id)]

        terminal = Task(
            id="documents", capability="documents", op=sel.doc_kind,
            inputs={"goal": query, "prompt": query, "deal_id": sel.deal_id or "",
                    "customer_id": sel.customer_id or "", "deal_ids": deal_ids,
                    "target": sel.target, "lang": sel.lang, "title": sel.title},
            depends_on=deps,
            # A WRITE deliverable: never auto-repeat, run after the grounding is in.
            policy=TaskPolicy(retries=0, on_failure="skip"),
            group=_DOCS, summary=f"{sel.doc_kind} を生成")

    return ExecutionPlan(tasks=(*gather, terminal))
````

## File: web/components/workspace/context-pane.tsx
````typescript
"use client";

import { useMemo, useState } from "react";
import { Building2, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { useWorkspaceFocus } from "@/lib/chat-store";
import { customerText } from "@/lib/content-i18n";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { BandPill } from "@/components/band";
import { AccountView } from "@/components/account/account-view";
import type { Role } from "@/lib/session";
import type { Band, DealRow, GrowthData } from "@/lib/types";

// Surface the most urgent work first: at-risk deals before watch before healthy.
const BAND_ORDER: Record<Band, number> = { red: 0, yellow: 1, green: 2 };

/**
 * The left pane of the Command Center: the rep's live deal/account context.
 * Clicking a deal sets the shared workspace focus, which the Copilot (right
 * pane) reads to ground its next answer — no slash commands, no retyping a
 * customer name. "Open account" reuses the existing AccountView in a drawer, so
 * the full account read sits beside the conversation instead of on its own page.
 */
export function ContextPane({
  deals,
  role,
  profile,
}: {
  deals: DealRow[];
  role: Role;
  // Junior passes its growth profile; the manager surface has no single-rep
  // profile, so this is optional. Currently informational only.
  profile?: GrowthData;
}) {
  const { t, lang } = useT();
  const { focus, setFocus } = useWorkspaceFocus(role);
  const [q, setQ] = useState("");
  const [bandFilter, setBandFilter] = useState<Band | "all">("all");
  const [openAccount, setOpenAccount] = useState<{ id: string; name: string } | null>(null);

  const myDeals = useMemo(() => {
    const query = q.trim().toLowerCase();
    return deals
      .filter((d) => {
        if (bandFilter !== "all" && d.band !== bandFilter) return false;
        if (!query) return true;
        const name = customerText(lang, d.customer).text.toLowerCase();
        return name.includes(query) || d.customer.toLowerCase().includes(query);
      })
      .slice()
      .sort((a, b) => BAND_ORDER[a.band] - BAND_ORDER[b.band] || b.amount - a.amount);
  }, [deals, q, bandFilter, lang]);

  return (
    <div className="space-y-4">

      <div>
        <div className="eyebrow">{t("cc.todayWork")}</div>
        <p className="mt-1 text-[12px] text-muted-foreground">{t("cc.todayWorkLead")}</p>
      </div>

      <label className="flex items-center gap-2 rounded-lg border border-input bg-muted/40 px-3 py-2">
        <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("cc.searchAccounts")}
          className="w-full bg-transparent text-[13px] outline-none placeholder:text-muted-foreground"
        />
      </label>

      <div className="flex flex-wrap gap-1.5 pb-1">
        <button
          onClick={() => setBandFilter("all")}
          className={cn(
            "rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ring-1 ring-inset",
            bandFilter === "all" 
              ? "bg-primary text-primary-foreground ring-primary" 
              : "bg-muted/50 text-muted-foreground ring-border hover:bg-muted"
          )}
        >
          {lang === "ja" ? "すべて" : "All"}
        </button>
        {(["red", "yellow", "green"] as Band[]).map((b) => (
          <button
            key={b}
            onClick={() => setBandFilter(b)}
            className={cn(
              "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors ring-1 ring-inset",
              bandFilter === b
                ? (b === "red" ? "bg-band-red text-white ring-band-red" : b === "yellow" ? "bg-band-yellow text-white ring-band-yellow" : "bg-band-green text-white ring-band-green")
                : (b === "red" ? "bg-band-red/10 text-band-red ring-band-red/25 hover:bg-band-red/20" : b === "yellow" ? "bg-band-yellow/10 text-band-yellow ring-band-yellow/25 hover:bg-band-yellow/20" : "bg-band-green/10 text-band-green ring-band-green/25 hover:bg-band-green/20")
            )}
          >
            <div className={cn("h-1.5 w-1.5 rounded-full", bandFilter === b ? "bg-white" : (b === "red" ? "bg-band-red" : b === "yellow" ? "bg-band-yellow" : "bg-band-green"))} />
            {t(b === "red" ? "dash.atRisk" : b === "yellow" ? "dash.watch" : "dash.healthy")}
          </button>
        ))}
      </div>

      <div className="space-y-2">
        {myDeals.length === 0 && (
          <p className="px-1 py-6 text-center text-[12.5px] text-muted-foreground">{t("cc.noDeals")}</p>
        )}
        {myDeals.map((d) => {
          const name = customerText(lang, d.customer).text;
          const active = focus.dealId === d.deal_id;
          return (
            <Card
              key={d.deal_id}
              role="button"
              tabIndex={0}
              onClick={() => setFocus({ dealId: d.deal_id, customerId: d.customer_id, customerName: name })}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setFocus({ dealId: d.deal_id, customerId: d.customer_id, customerName: name });
                }
              }}
              className={cn(
                "cursor-pointer transition-colors",
                active ? "border-primary ring-1 ring-inset ring-primary" : "hover:border-primary/40",
              )}
            >
              <CardContent className="flex items-center justify-between gap-3 p-3">
                <div className="min-w-0">
                  <div className="truncate text-[13.5px] font-medium">{name}</div>
                  <div className="truncate text-[11.5px] text-muted-foreground">
                    {d.stage} · ¥{d.amount.toLocaleString("ja-JP")}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <BandPill band={d.band} />
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpenAccount({ id: d.customer_id, name });
                    }}
                    className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-primary hover:bg-primary/5"
                  >
                    <Building2 className="h-3 w-3" />
                    {t("cc.openAccount")}
                  </button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Full account read — the existing AccountView, now in a drawer beside the
          Copilot rather than on its own route. */}
      <Dialog open={!!openAccount} onOpenChange={(o) => !o && setOpenAccount(null)}>
        <DialogContent className="p-5">
          <DialogTitle className="sr-only">{openAccount?.name ?? t("cc.openAccount")}</DialogTitle>
          {openAccount && (
            <AccountView
              customerId={openAccount.id}
              role={role}
              compact
              onAskCopilot={() => {
                // Hand off to the Copilot grounded on this account's most urgent
                // open deal (falling back to the account itself), then close.
                const top = deals
                  .filter((d) => d.customer_id === openAccount.id)
                  .sort((a, b) => BAND_ORDER[a.band] - BAND_ORDER[b.band] || b.amount - a.amount)[0];
                setFocus(
                  top
                    ? { dealId: top.deal_id, customerId: openAccount.id, customerName: openAccount.name }
                    : { customerId: openAccount.id, customerName: openAccount.name },
                );
                setOpenAccount(null);
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
````

## File: .gitignore
````
# Byte-compiled / optimized / DLL files
__pycache__/
*.py[codz]
*$py.class

# C extensions
*.so

# Distribution / packaging
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
*.jsonl
lib/
lib64/
parts/
sdist/
var/
wheels/
share/python-wheels/
*.egg-info/
.installed.cfg
*.egg
MANIFEST

# PyInstaller
#   Usually these files are written by a python script from a template
#   before PyInstaller builds the exe, so as to inject date/other infos into it.
*.manifest
*.spec

# Installer logs
pip-log.txt
pip-delete-this-directory.txt

# Unit test / coverage reports
htmlcov/
.tox/
.nox/
.coverage
.coverage.*
.cache
nosetests.xml
coverage.xml
*.cover
*.py.cover
.hypothesis/
.pytest_cache/
cover/

# Translations
*.mo
*.pot

# Django stuff:
*.log
local_settings.py
db.sqlite3
db.sqlite3-journal

# Flask stuff:
instance/
.webassets-cache

# Scrapy stuff:
.scrapy

# Sphinx documentation
docs/_build/

# PyBuilder
.pybuilder/
target/

# Jupyter Notebook
.ipynb_checkpoints

# IPython
profile_default/
ipython_config.py

# pyenv
#   For a library or package, you might want to ignore these files since the code is
#   intended to run in multiple environments; otherwise, check them in:
# .python-version

# pipenv
#   According to pypa/pipenv#598, it is recommended to include Pipfile.lock in version control.
#   However, in case of collaboration, if having platform-specific dependencies or dependencies
#   having no cross-platform support, pipenv may install dependencies that don't work, or not
#   install all needed dependencies.
# Pipfile.lock

# UV
#   Similar to Pipfile.lock, it is generally recommended to include uv.lock in version control.
#   This is especially recommended for binary packages to ensure reproducibility, and is more
#   commonly ignored for libraries.
# uv.lock

# poetry
#   Similar to Pipfile.lock, it is generally recommended to include poetry.lock in version control.
#   https://python-poetry.org/docs/basic-usage/#commit-your-poetrylock-file-to-version-control
# poetry.lock
# poetry.toml

# pdm
#   Similar to Pipfile.lock, it is generally recommended to include pdm.lock in version control.
#   pdm recommends including project-wide configuration in pdm.toml, but excluding .pdm-python.
#   https://pdm-project.org/en/latest/usage/project/#working-with-version-control
# pdm.lock
# pdm.toml
.pdm-python
.pdm-build/

# pixi
#   Similar to Pipfile.lock, it is generally recommended to include pixi.lock in version control.
# pixi.lock
#   Pixi creates a virtual environment in the .pixi directory, just like venv module creates one
#   in the .venv directory. It is recommended not to include this directory in version control.
.pixi

# PEP 582; used by e.g. github.com/David-OConnor/pyflow and github.com/pdm-project/pdm
__pypackages__/

# Celery stuff
celerybeat-schedule
celerybeat.pid

# Redis
*.rdb
*.aof
*.pid

# RabbitMQ
mnesia/
rabbitmq/
rabbitmq-data/

# ActiveMQ
activemq-data/

# SageMath parsed files
*.sage.py

# Environments
.env
.envrc
.node_modules/
.venv
env/
venv/
ENV/
env.bak/
venv.bak/
# Freeze cache
scripts/.freeze_cache/

# Spyder project settings
.spyderproject
.spyproject

# Rope project settings
.ropeproject

# mkdocs documentation
/site

# mypy
.mypy_cache/
.dmypy.json
dmypy.json

# Pyre type checker
.pyre/

# pytype static type analyzer
.pytype/

# Cython debug symbols
cython_debug/

# PyCharm
#   JetBrains specific template is maintained in a separate JetBrains.gitignore that can
#   be found at https://github.com/github/gitignore/blob/main/Global/JetBrains.gitignore
#   and can be added to the global gitignore or merged into this file.  For a more nuclear
#   option (not recommended) you can uncomment the following to ignore the entire idea folder.
# .idea/

# Abstra
#   Abstra is an AI-powered process automation framework.
#   Ignore directories containing user credentials, local state, and settings.
#   Learn more at https://abstra.io/docs
.abstra/

# Visual Studio Code
#   Visual Studio Code specific template is maintained in a separate VisualStudioCode.gitignore 
#   that can be found at https://github.com/github/gitignore/blob/main/Global/VisualStudioCode.gitignore
#   and can be added to the global gitignore or merged into this file. However, if you prefer, 
#   you could uncomment the following to ignore the entire vscode folder
# .vscode/
# Temporary file for partial code execution
tempCodeRunnerFile.py

# ---------------------------------------------------------------------------
# Demo: secrets and runtime artifacts (never commit these)
# ---------------------------------------------------------------------------
# Google OAuth client secret and the live token (refresh/access). Use the
# committed demo/credentials.json.example as a template instead.
demo/credentials.json
demo/token.json
# Files written at runtime by the create_file tool.
demo/output/
# Root-level Google OAuth secret + live token used by senpai's schedule_meeting.
/credentials.json
/token.json

# Ruff stuff:
.ruff_cache/

# PyPI configuration file
.pypirc

# Marimo
marimo/_static/
marimo/_lsp/
__marimo__/

# Streamlit
.streamlit/secrets.toml


# Documents the chatbot generates (PPTX/DOCX); demo-only output, not committed
senpai/data/generated/

# Raw source deck used to derive the brand template — large, not needed at runtime.
# Only the slimmed-down derived template (otsuka_template.pptx) is committed.
# senpai/data/templates/otsuka_source.pptx

# Node.js dependencies
node_modules/

# Ingested chat history database (written at runtime)
senpai/data/ingested/chat_history.db
````

## File: tests/test_documents.py
````python
"""Tests for the document-generation tools (generate_proposal/ringisho/pptx/docx).

The deterministic path (proposal/ringisho) is exercised fully — no GPU/LLM, since
conftest leaves SENPAI_USE_LLM off. The general tools (pptx/docx) require a model, so
here we only assert they degrade gracefully (a clear message, no file) when it's off.
All output is redirected to a tmp dir so the committed seed is never touched.
"""
from __future__ import annotations

import pytest
from docx import Document
from pptx import Presentation

from senpai import config
from senpai.data import store
from senpai.documents import proposal, registry, ringisho
from senpai.documents.context import build_document_context
from senpai.documents.render import render_docx, render_pptx
from senpai.tools.impl import dispatch

DEAL = "D001"  # seeded dead-but-optimistic deal with real pain points + financials


@pytest.fixture(autouse=True)
def _tmp_generated(tmp_path, monkeypatch):
    """Redirect generated files to a tmp dir for every test."""
    monkeypatch.setattr(config, "GENERATED_DIR", tmp_path / "generated")
    return tmp_path / "generated"


def _pptx_text(path) -> str:
    out = []
    for slide in Presentation(str(path)).slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                out.append(shape.text_frame.text)
            if shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        if cell.text_frame:
                            out.append(cell.text_frame.text)
            if shape.has_chart:
                try:
                    chart = shape.chart
                    for plot in chart.plots:
                        for series in plot.series:
                            if series.name:
                                out.append(series.name)
                            for val in series.values:
                                out.append(str(val))
                except Exception:
                    pass
    return "\n".join(out)


def _docx_text(path) -> str:
    return "\n".join(p.text for p in Document(str(path)).paragraphs)


# --- render.py (pure, LLM-free) ------------------------------------------------
def test_render_pptx_slide_count(tmp_path):
    spec = {"slides": [
        {"layout": "title", "title": "T", "subtitle": "sub"},
        {"layout": "content", "title": "A", "bullets": ["x", "y"]},
        {"layout": "content", "title": "B", "bullets": ["z"]},
    ]}
    p = render_pptx(spec, tmp_path / "d.pptx")
    prs = Presentation(str(p))
    assert len(prs.slides) == 3


def test_render_docx_headings(tmp_path):
    spec = {"title": "Doc", "sections": [
        {"heading": "One", "body": ["para a", "- bullet"]},
        {"heading": "Two", "body": ["para b"]},
    ]}
    p = render_docx(spec, tmp_path / "d.docx")
    text = _docx_text(p)
    assert "One" in text and "Two" in text and "bullet" in text


# --- context grounding ---------------------------------------------------------
def test_context_numbers_match_store():
    ctx = build_document_context(DEAL)
    d = store.get_deal(DEAL)
    assert ctx is not None
    assert ctx.financials["investment"] == d["total_order_amount"]
    assert ctx.customer == store.customer_name(d["customer_id"])
    assert ctx.pain_points  # real customer_challenge values exist for this deal


def test_context_unknown_deal_is_none():
    assert build_document_context("ZZZ") is None


# --- proposal (PPTX) -----------------------------------------------------------
def test_proposal_arc_and_grounded():
    res = proposal.generate(DEAL)
    assert res is not None
    path, ctx, spec = res
    prs = Presentation(str(path))
    # Full proposal arc: 表紙 → 背景 → 課題 → ソリューション → 投資対効果 → 次のステップ.
    assert len(prs.slides) == 9
    assert len(spec["slides"]) == 9
    text = _pptx_text(path)
    assert ctx.customer in text                       # title slide names the customer
    assert (f"{ctx.financials['investment']:,}" in text or str(float(ctx.financials['investment'])) in text)  # ROI slide carries the real ¥ (D001 has no quote)


# --- ringisho (DOCX) -----------------------------------------------------------
def test_ringisho_headings_and_amount():
    res = ringisho.generate(DEAL)
    assert res is not None
    path, ctx = res
    text = _docx_text(path)
    for heading in ("稟議書", "背景・課題", "提案内容", "投資額と効果", "結論・承認依頼"):
        assert heading in text
    assert f"{ctx.financials['investment']:,}" in text


# --- pptx generates directly (no confirm gate) ---------------------------------
def test_proposal_tool_generates_directly(_tmp_generated):
    gen = _tmp_generated
    # PPTX proposals build in one round — no preview/confirm step.
    out = dispatch("generate_proposal", {"deal_id": DEAL})
    assert "生成しました" in out
    assert "プレビュー" not in out
    assert len(list(gen.glob("*.pptx"))) == 1                 # file written on the first call


def test_ringisho_tool_writes_docx(_tmp_generated):
    dispatch("generate_ringisho", {"deal_id": DEAL, "confirm": True})
    assert len(list(_tmp_generated.glob("*.docx"))) == 1


# --- general tools need the model ----------------------------------------------
def test_general_tools_need_model(_tmp_generated):
    msg = dispatch("generate_pptx", {"prompt": "GTA 6", "confirm": True})
    assert "モデル" in msg                                     # "needs the model"
    msg2 = dispatch("generate_docx", {"prompt": "security training"})
    assert "モデル" in msg2
    assert not _tmp_generated.exists() or not list(_tmp_generated.iterdir())  # no file


# --- grounding: general tools ground on conversation + workspace, not just CRM --
def test_gather_grounding_uses_conversation_and_workspace(tmp_path, monkeypatch):
    """A 'proposal for <company>' where the company lives in the rep's local files
    (and was discussed earlier) must ground on that file/conversation — and must NOT
    inject an unrelated fuzzy CRM customer (the wrong-company-name hallucination).
    Uses a hermetic workspace so it never depends on the configured WORKSPACE_ROOT."""
    from senpai import config
    from senpai.tools import conversation as conv
    from senpai.tools import impl

    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "murata_printing_display_quote.txt").write_text(
        "有限会社村田印刷 様\n27インチモニター × 4台: ¥204,000\n", encoding="utf-8")
    monkeypatch.setattr(config, "WORKSPACE_ROOT", ws)

    conv.set_conversation([
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "村田印刷にいくら見積もった？"},
        {"role": "tool", "content": "ワークスペース文書: 有限会社村田印刷 ¥204,000"},
        {"role": "assistant", "content": "村田印刷への見積もりは¥204,000です。"},
        {"role": "user", "content": "make a proposal ppt for Murata Printing"},
    ])
    try:
        g = impl._gather_grounding("make a proposal ppt for Murata Printing 村田印刷",
                                   customer="", use_web=False)
    finally:
        conv.set_conversation(None)
    assert "村田印刷" in g                       # the referenced entity is grounded
    assert "204,000" in g                        # its real figure, from file/conversation
    assert "松田" not in g                        # no unrelated fuzzy CRM customer
    assert "【社内データ】" not in g              # CRM suppressed when workspace matched


def test_gather_grounding_junk_gated_and_crm_fallback(tmp_path, monkeypatch):
    """An unrelated topic pulls no workspace junk; a real CRM customer still grounds.
    The workspace root is pointed at an empty dir so the assertion is deterministic
    regardless of what real files exist under the configured WORKSPACE_ROOT."""
    from senpai import config
    from senpai.tools import conversation as conv
    from senpai.tools import impl

    empty = tmp_path / "empty_workspace"
    empty.mkdir()
    monkeypatch.setattr(config, "WORKSPACE_ROOT", empty)  # sandbox re-reads config each call

    conv.set_conversation(None)
    assert impl._workspace_grounding("best gaming laptops under 1000000 yen") == ""
    # A named CRM customer with no local file still injects internal records.
    g = impl._gather_grounding("藤本食品の提案書", customer="", use_web=False)
    assert "【社内データ】" in g


def test_gather_grounding_uses_session_focus(tmp_path, monkeypatch):
    """'make a proposal' with no customer named, but a deal was looked up earlier this
    session → grounding pulls that deal's CRM record via SessionFocus (a lookup off the
    resolved id), not a fuzzy re-match. Hermetic empty workspace so ws never interferes."""
    from senpai import config
    from senpai.data import store
    from senpai.tools import conversation as conv
    from senpai.tools import impl

    empty = tmp_path / "empty_ws"
    empty.mkdir()
    monkeypatch.setattr(config, "WORKSPACE_ROOT", empty)

    deal = "D001"
    cid = store.get_deal(deal)["customer_id"]
    conv.set_conversation([
        {"role": "user", "content": "この案件の状況は？"},
        {"role": "tool", "content": f"{deal} 案件 / 受注ランクA / ¥204,000"},
        {"role": "assistant", "content": "進行中です。"},
        {"role": "user", "content": "提案書を作って"},
    ])
    try:
        g = impl._gather_grounding("提案書を作って", customer="", use_web=False)
    finally:
        conv.set_conversation(None)
    assert "【社内データ】" in g                     # CRM grounded off the deal in focus
    assert store.customer_name(cid) in g            # the RIGHT customer, from the id


def test_conversation_grounding_relevance_beats_recency():
    """The entity in focus must survive even after several unrelated turns push it out
    of the plain last-N window: relevance ranking pulls the older Murata fact back in,
    while the recent off-topic chatter that a tail-only slice would have kept is
    dropped as irrelevant to the current request."""
    from senpai.tools import conversation as conv
    from senpai.tools import impl

    convo = [
        {"role": "user", "content": "村田印刷にいくら見積もった？"},
        {"role": "tool", "content": "ワークスペース文書: 有限会社村田印刷 27インチ×4 ¥204,000"},
        {"role": "assistant", "content": "村田印刷への見積もりは¥204,000です。"},
    ]
    # Several intervening, unrelated turns — enough to push Murata past RECENT_FLOOR.
    for q, a in [("今日の天気は？", "晴れです。"),
                 ("会議は何時？", "15時からです。"),
                 ("昼食のおすすめは？", "近くの蕎麦屋です。"),
                 ("電車は動いてる？", "平常運転です。")]:
        convo += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    convo.append({"role": "user", "content": "村田印刷の提案書を作って"})

    conv.set_conversation(convo)
    try:
        g = impl._conversation_grounding("村田印刷の提案書を作って 村田印刷")
    finally:
        conv.set_conversation(None)
    assert "204,000" in g          # the older on-topic fact was rescued by relevance
    assert "蕎麦屋" not in g        # recent-but-irrelevant chatter was NOT padded in


def test_truncate_on_boundary_does_not_sever_facts():
    from senpai.tools import impl

    text = "村田印刷への見積もり金額は¥204,000です。" + "あ" * 5000 + "末尾の重要な数値¥999"
    out = impl._truncate_on_boundary(text, 1500)
    assert len(out) <= 1500 + 2          # budget respected (+ elision marker)
    assert out.endswith("…")             # marked as elided
    assert "¥204,000" in out             # the leading fact is intact, not half-cut
    # A string already within budget is returned unchanged (no marker).
    assert impl._truncate_on_boundary("短い文。", 1500) == "短い文。"


# --- registry + isolation ------------------------------------------------------
def test_registry_records_for_download(_tmp_generated):
    dispatch("generate_proposal", {"deal_id": DEAL, "confirm": True})
    # _DOCS is a process-global registry; take the most recent proposal record.
    rec = next(r for r in reversed(list(registry._DOCS.values())) if r["kind"] == "proposal")
    assert registry.get(rec["doc_id"]) is rec
    assert str(_tmp_generated) in rec["path"]                  # under tmp, not the seed


def test_seed_dir_not_written():
    proposal.generate(DEAL)
    ringisho.generate(DEAL)
    # generated files land under the (tmp) GENERATED_DIR, never the committed seed
    assert not list(config.SEED_DIR.glob("*.pptx"))
    assert not list(config.SEED_DIR.glob("*.docx"))
````

## File: web/app/login/page.tsx
````typescript
"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, LayoutDashboard, UserRound } from "lucide-react";
import { useT } from "@/lib/i18n";
import { useSession, demoCreds, type Role } from "@/lib/session";
import { Brand } from "@/components/site/brand";
import { ClientBadge } from "@/components/site/client-badge";
import { LangToggle } from "@/components/site/lang-toggle";
import { Button } from "@/components/ui/button";

function LoginForm() {
  const { t } = useT();
  const router = useRouter();
  const { login } = useSession();
  const params = useSearchParams();
  const role: Role = params.get("role") === "manager" ? "manager" : "junior";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(false);

  const Icon = role === "manager" ? LayoutDashboard : UserRound;
  const accent = role === "manager" ? "text-navy" : "text-primary";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const resolved = await login(role, username, password);
    if (resolved) {
      router.replace(resolved === "manager" ? "/manager" : "/junior");
    } else {
      setError(true);
    }
  }

  return (
    <div className="hero-wash flex min-h-screen flex-col">
      <header className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-5">
        <Brand fullMark tagline={t("app.tagline")} />
        <div className="flex items-center gap-3 sm:gap-4">
          <ClientBadge />
          <div className="hidden h-5 w-px bg-border sm:block" />
          <LangToggle />
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center px-6 pb-16">
        <div className="w-full max-w-sm">
          <Link href="/" className="mb-6 inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground">
            <ArrowLeft className="h-3.5 w-3.5" /> {t("login.switchRole")}
          </Link>

          <div className="rounded-2xl border border-border bg-card p-7 shadow-[0_8px_40px_-24px_rgba(16,24,40,0.4)]">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted">
                <Icon className={`h-5 w-5 ${accent}`} />
              </div>
              <div>
                <h1 className="text-lg font-semibold tracking-tight">
                  {t("login.title", { role: t(role === "manager" ? "role.manager" : "role.junior") })}
                </h1>
                <p className="text-[12px] text-muted-foreground">{t("login.subtitle")}</p>
              </div>
            </div>

            <form onSubmit={submit} className="mt-6 space-y-3">
              <div className="space-y-1.5">
                <label className="eyebrow">{t("login.username")}</label>
                <input
                  value={username}
                  onChange={(e) => { setUsername(e.target.value); setError(false); }}
                  className="h-10 w-full rounded-lg border border-input bg-card px-3 text-[14px] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  autoComplete="off"
                />
              </div>
              <div className="space-y-1.5">
                <label className="eyebrow">{t("login.password")}</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); setError(false); }}
                  className="h-10 w-full rounded-lg border border-input bg-card px-3 text-[14px] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  autoComplete="off"
                />
              </div>
              {error && <p className="text-[12px] text-band-red">{t("login.error")}</p>}
              <Button type="submit" variant="seal" className="w-full">{t("login.submit")}</Button>
            </form>

            <div className="mt-6 rounded-xl border border-primary/20 bg-primary/5 p-4">
              <div className="flex items-center justify-between">
                <div className="space-y-1">
                  <p className="text-[12px] font-semibold text-primary">{t("login.demo")}</p>
                  <p className="font-mono text-[11px] text-muted-foreground">{demoCreds(role).username} / {demoCreds(role).password}</p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 text-[11px] bg-background"
                  onClick={() => {
                    setUsername(demoCreds(role).username);
                    setPassword(demoCreds(role).password);
                    setError(false);
                  }}
                >
                  {t("login.useThese")}
                </Button>
              </div>
            </div>


            {role === "junior" && (
              <p className="mt-5 text-center text-[12px] text-muted-foreground">
                {t("login.noAccount")}{" "}
                <Link href="/signup" className="font-medium text-primary hover:underline">
                  {t("login.createAccount")}
                </Link>
              </p>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
````

## File: README.md
````markdown
# Senpai — Sales Knowledge & Onboarding Copilot (Otsuka, Phase 2)

Senpai makes the knowledge that lives in Otsuka's best salespeople available to every rep —
on demand and in context — while giving managers one place to read deal health and catch
dying deals early. It is a **fine-tuned, tool-calling assistant (exp3)** anchored to Otsuka's
real SPR data, not a generic sales chatbot.

The pitch in one line: **onboarding is the relatable face; pipeline reliability — "nobody
knows if a deal is real" — is the engine underneath.** The same deterministic deal-health
read that briefs a junior before a call also flags a manager's dying deal.

---

## Repository map

| Path | What it is | Owner |
|---|---|---|
| **`senpai/`** | **Our pipeline** — the deterministic deal-health engine on Otsuka's real SPR schema, plus the junior chat, manager chat, and manager dashboard. **Start here.** | this team |
| `Schema.md` | The real Otsuka SPR schema (4 tables) + how our pipeline maps to it | this team |
| `senpai/api/`, `web/`, `senpai/coach/`, `senpai/knowledge/` | A separate, in-progress **web-app experiment** (FastAPI + Next.js frontend, Sales Review Coach, Knowledge Explorer) | another team member |
| `demo/` | Phase-1 tool-calling demo (the exp3 Gradio showcase that proved the model) | this team |

> Our pipeline does **not** import or depend on the web-app experiment; the two are
> decoupled and can run independently. See `senpai/README.md` → *Isolation* for details.

---

## Quickstart (web app)

Run the **backend** and **frontend** in two separate terminals. `SENPAI_USE_LLM=1` switches
live Coach commentary ON (default off = deterministic only).

### Windows (PowerShell)

```powershell
# install deps (Python bridge + frontend)
.\.venv\Scripts\pip.exe install -r requirements.txt
cd web; npm install; cd ..
```

# Terminal 1 — Backend bridge (FastAPI) → <http://localhost:8000>

$env:SENPAI_USE_LLM = '1'
$env:SENPAI_TODAY   = '2026-07-07'        # pin scoring's "today" to the seed anchor
.\.venv\Scripts\python.exe -m uvicorn senpai.api.server:app --port 8000 --host 127.0.0.1 --reload

# Terminal 2 — Frontend (Next.js) → <http://localhost:3000>   (defaults to the :8000 backend)

cd web; npm run dev

```

### Linux / macOS (bash)

```bash
# install deps (Python bridge + frontend)
.venv/bin/pip install -r requirements.txt
( cd web && npm install )

# Terminal 1 — Backend bridge (FastAPI) → http://localhost:8000
export SENPAI_USE_LLM=1
export SENPAI_TODAY=2026-06-16            # pin scoring's "today" to the seed anchor
.venv/bin/python -m uvicorn senpai.api.server:app --port 8000 --host 127.0.0.1 --reload

# Terminal 2 — Frontend (Next.js) → http://localhost:3000   (defaults to the :8000 backend)
cd web && npm run dev
```

The deal-health engine and unit tests are **pure Python (no GPU)**. Live Senior Commentary
additionally needs a GPU-served model on `:8765` — see **[Web app: switching on live Coach
commentary](#web-app-frontend--backend--switching-on-live-coach-commentary)** below for the
model server, the `SENPAI_USE_LLM` switch, and the `.env` wiring.

**→ Full engineering reference, tool list, env vars, and verify steps:
[`senpai/README.md`](senpai/README.md).**
**→ The data shape we build against: [`Schema.md`](Schema.md).**

---

## Web app (frontend + backend) — switching on live Coach commentary

The Next.js web app (`web/`) talks to the FastAPI bridge (`senpai/api/server.py`), which in
turn streams the optional **Senior Commentary** from a GPU-served, OpenAI-compatible model
(llama.cpp `llama-server`). The deterministic Review Coach always works without a model; the
LLM only *rephrases* the same findings. Live commentary is **gated OFF by default** — you turn
it on with one backend env var.

> The web↔engine boundary, the "endpoint first, then types/api/fixture" rule, and the drift
> check (`scripts/check_contract.py`) are documented in [`docs/web-integration.md`](docs/web-integration.md).

Start three things, in order:

### 1. Model server (GPU box) — `:8765`

The model is served by `llama-server` on the GPU box and reached over an OpenAI-compatible
endpoint. The bridge reads the endpoint + model name from the **repo-root `.env`** (loaded
automatically by `senpai/config.py`):

```bash
# E:\my_stuff\OtsukaPhase2\.env
BASE_URL="http://127.0.0.1:8765/v1"                          # via SSH tunnel (see below)
MODEL="Qwen3.6-27B-Claude-Opus-Reasoning-Distilled"          # llama-server ignores this field; label only
```

**Connectivity (from this Windows box):** the direct Tailscale URL
`http://100.101.186.29:8765/v1` is **firewalled** — the host pings but the port refuses. Reach
the server through an SSH tunnel instead, then point `BASE_URL` at `127.0.0.1:8765` (as above):

```bash
ssh -N -L 8765:127.0.0.1:8765 team-a@100.101.186.29     # leave running in its own terminal
```

**Starting / restarting the model** (the 27B GGUF is periodically **OOM-killed** on the shared
GB10 — when the Assistant shows "Couldn't reach the server", relaunch it):

```bash
# from anywhere — launches detached on the GPU box
ssh team-a@100.101.186.29 'cd ~/Desktop/toolcallLM/qwen3 && \
  setsid bash -c "./serve_gguf.sh > llama-server.log 2>&1" </dev/null &'
```

Sanity check it's up (needs the tunnel): `curl http://127.0.0.1:8765/v1/models`.
Check it's alive on the box: `ssh team-a@100.101.186.29 'pgrep -af llama-server'`.
> A `couldn't bind … 0.0.0.0:8765` line in the llama-server log just means a **second** launch
> hit an already-running instance — the first one is fine.

### 2. Backend bridge (FastAPI) — `:8000`  ← **this is the switch**

```bash
# PowerShell (Windows)
$env:SENPAI_USE_LLM = '1'        # ← switches live commentary ON (default '0' = deterministic only)
$env:SENPAI_TODAY   = '2026-07-07'   # pin scoring's "today" to the seed anchor
python -m uvicorn senpai.api.server:app --port 8000 --host 127.0.0.1 --reload
```

```bash
# bash / macOS / Linux
export SENPAI_USE_LLM=1
export SENPAI_TODAY=2026-06-16
.venv/bin/python -m uvicorn senpai.api.server:app --port 8000 --host 127.0.0.1 --reload
```

- **`SENPAI_USE_LLM=1` is the on/off switch.** Without it, `/api/coach/narrate` returns
  `unavailable: llm_disabled` and the UI shows *"Couldn't reach the explanation model…"*.
- The bridge **uses `--reload`**: after editing Python files, the server will restart automatically. (For `.env` changes, you may still need to restart it manually.)
- Verify: `curl http://localhost:8000/api/health` → `{"status":"ok", …}`.

### 3. Frontend (Next.js) — `:3000`

```bash
cd web
npm install            # first time only
npm run dev            # → http://localhost:3000
```

The frontend points at the backend via `NEXT_PUBLIC_API_BASE`, which **defaults to
`http://localhost:8000`** — so if the bridge runs on :8000 you need no config. To target a
different host, create `web/.env.local`:

```bash
# web/.env.local
NEXT_PUBLIC_API_BASE="http://localhost:8000"
```

Then open **Review Coach → Get the senior's read**: with the backend switch on and the model
reachable, the commentary streams in live. With either off, the page falls back cleanly to the
deterministic coaching.

### Senior Commentary — what it does, and its contract

The commentary is an **experienced rep's interpretation** layered on the deterministic coach —
not a restatement of the six lenses. Before calling the model, the bridge builds a grounded
**context package** (`senpai/coach/context.py`): it resolves the customer named in the note to a
real deal, then assembles that deal's health, recent activity, quote/order history, prior
deals, and a similar past case. The model reasons over that context and answers in four short
sections (Situation Summary / What an Experienced Rep Would Focus On / Likely Customer Dynamics
/ Practical Advice).

| Property | Value |
|---|---|
| **Active model** | `Qwen3.6-27B-Claude-Opus-Reasoning-Distilled` (GGUF Q4_K_M, llama-server) — shown in the UI's `start`/`Generated by` badge |
| **Endpoint** | pinned to `BASE_URL` from `.env` (`http://100.101.186.29:8765/v1`). The request sets `allow_fallback=False` — it **never** silently switches to another model. |
| **Latency** | Reasoning is **disabled** (empty-`<think>` prefill) and output is capped at `LLM_NARRATE_MAX_TOKENS` (default 260) → ~15–22s, vs ~60–90s with reasoning on. |
| **Fallback behaviour** | If the endpoint is down/empty, the stream emits `unavailable` and the UI shows **"Senior commentary unavailable — the deterministic coaching above still stands."** No second model is used. |
| **Grounding** | Only real store records are used. If the note names no known customer, the UI shows no "Grounded in …" badge and the model is told to read from the note alone and invent nothing. |

Tunables (env): `LLM_NARRATE_MAX_TOKENS` (length/latency trade-off), `LLM_TIMEOUT` (per-read
stream timeout). The model name is a label only — llama-server serves whatever GGUF is loaded.

---

## What's inside the pipeline (at a glance)

- **Real SPR schema.** `senpai/data/gen_seed.py` generates byte-stable synthetic data in
  Otsuka's production shape (`deals`, `orders`, `quotes`, `sales_activities`), so the real
  data is a drop-in when we get access. `order_rank` (`1_Confirmed … 8_Cancelled`) is the spine.
- **Deterministic deal-health engine.** Seven rank-aware signals (staleness, rank stagnation,
  order-date passed, rank regression, missing decision-maker, stall language, low activity) →
  a 🔴🟡🟢 score with a Japanese reason for every signal. No number is ever invented by a model.
- **Report-reliability flags.** Surfaces deals whose recorded rank contradicts their activity
  signals (`optimism_mismatch`, `stale_active`, `close_date_passed`, …).
- **Web app over one shared engine.** A Next.js frontend (Review Coach, Knowledge Explorer,
  manager workspace, growth) on a FastAPI bridge — junior briefs/playbook/report drafting and
  manager at-risk deals, report digests, and coaching focus, all reading the same deterministic
  engine, with optional GPU-served Senior Commentary.

## Verify (no GPU)

```bash
export SENPAI_TODAY=2026-06-16
.venv/bin/pytest tests/test_scoring.py tests/test_flags.py tests/test_manager_tools.py
.venv/bin/python -m senpai.tools.impl        # one canned call per tool
```

## Phase-1 demo

The original tool-calling showcase (exp3 answering in natural language while calling real
tools) lives in [`demo/`](demo/) with its own run sheet at `demo/demo_script.md`.
````

## File: senpai/planner/capabilities.py
````python
"""The planner's capabilities: one per grounding source, plus the terminal document
producer. Every one is a THIN adapter over logic that already exists — no retrieval,
scoring, or rendering is reimplemented here. This is the whole point of the
capability graph: the planner selects *which* of these run; the engine runs them;
their Evidence lands in one bundle; the Documents capability consumes that bundle.

    conversation ─┐
    workspace ────┤
    crm ──────────┼──►  documents   (depends on all gathered; authors the artifact)
    knowledge ────┤
    solutions ────┤
    web ──────────┘

Gather capabilities emit a uniform `{"text": <grounding>, "label": <section>}` so the
Documents capability can concatenate them into one grounding block regardless of
which were selected. All are READ/SEARCH and degrade to empty — never raise.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from senpai.orchestration import ExecContext
from senpai.orchestration.evidence import Evidence
from senpai.orchestration.metadata import CapabilityMetadata, OperationKind

# Section-header labels mirror the doc tools' inline grounding blocks, so a deck
# authored via the planner reads identically to one authored via generate_pptx.
_LABELS = {
    "conversation": "これまでの会話・確定済みの文脈",
    "workspace": "ローカル文書（あなたのファイル）",
    "crm": "社内データ",
    "knowledge": "社内ナレッジ",
    "solutions": "大塚商会ソリューション・製品情報",
    "web": "Web検索",
}


# workspace/knowledge/solutions already embed real provenance inline
# ("出典: file://…", "出典: Playbook 123", "根拠: 先輩2名 / int001") but only CRM
# passes an explicit `citations` list — without this, the evidence-count receipt
# line always read 0 for them even when real grounding was retrieved.
_CITATION_RE = re.compile(r"(?:出典|根拠):\s*([^\n）)]+)")


def _extract_citations(text: str) -> list[str]:
    return [m.strip() for m in _CITATION_RE.findall(text)]


def _text_evidence(name: str, text: str, citations=()) -> Evidence:
    text = (text or "").strip()
    if not text:
        return Evidence.empty(provenance={"capability": name})
    citations = tuple(citations) or tuple(_extract_citations(text))
    return Evidence.ok({"text": text, "label": _LABELS.get(name, name)},
                       citations=citations, status="ok")


def _register_deck(registry, files: dict, *, primary_kind: str,
                   deal_id: str | None = None) -> list[dict]:
    """Register a deck's export set (from export.render_deck) for download — the editable
    office file first (primary), then PDF, then source HTML — and return the records, with
    the primary at index 0. Mirrors impl._register_deck_files for the planner path."""
    recs = [registry.register(primary_kind, files["pptx"], deal_id=deal_id)]
    if files.get("pdf"):
        recs.append(registry.register("pdf", files["pdf"], deal_id=deal_id))
    if files.get("html"):
        recs.append(registry.register("html", files["html"], deal_id=deal_id))
    return recs


class ConversationCapability:
    """Grounding from the live session — a company/quote/deal already discussed.
    Reuses the doc tools' own `_conversation_grounding` over the published convo."""
    name = "conversation"
    metadata = CapabilityMetadata(OperationKind.READ)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.tools.impl import _conversation_grounding
        text = _conversation_grounding(str(inputs.get("query", "")))
        ctx.emit("会話文脈あり" if text else "会話文脈なし")
        return _text_evidence("conversation", text)


class WorkspaceCapability:
    """Relevant LOCAL documents (sandboxed, read-only). Reuses the doc tools'
    relevance-gated `_workspace_grounding`, which runs the real find→extract."""
    name = "workspace"
    metadata = CapabilityMetadata(OperationKind.SEARCH, max_concurrency=4)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.tools.impl import _workspace_grounding
        text = _workspace_grounding(str(inputs.get("query", "")))
        ctx.emit("該当文書あり" if text else "該当文書なし")
        # Citations are the file provenance already embedded in the text ("出典: file://…").
        return _text_evidence("workspace", text)


class CRMCapability:
    """Internal SPR records for the resolved deal/customer. Reuses `impl.query_spr`."""
    name = "crm"
    metadata = CapabilityMetadata(OperationKind.READ, cacheable=True)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.data import store
        from senpai.tools.impl import query_spr
        deal_id = str(inputs.get("deal_id") or "")
        customer_id = str(inputs.get("customer_id") or "")
        if deal_id:
            text, cite = query_spr(deal_id=deal_id), f"SPR {deal_id}"
        elif customer_id:
            text, cite = query_spr(customer=customer_id), f"SPR {customer_id}"
            # query_spr's customer branch is a summary line per deal only — unlike
            # its deal_id branch, it never includes activity/daily-report history.
            # Without an open deal_id (the common case for a closed-won/lost
            # account), that history is the only place a real win/loss reason
            # ("competitor comparison", "budget on hold") lives — pull it directly
            # so authoring doesn't have to guess a cause.
            acts = store.activities_for_customer(customer_id)[:5]
            if acts:
                text += "\n直近の活動:\n" + "\n".join(
                    f"  ・{a['activity_date']} {a['deal_id']} [{a['activity_type']}] {a['daily_report']}"
                    for a in acts)
        else:
            return Evidence.empty(provenance={"capability": "crm"})
        ctx.emit("社内記録を取得")
        return _text_evidence("crm", text, citations=[cite])


class KnowledgeCapability:
    """Validated playbook / approved coaching knowledge for the goal. Reuses
    `impl.search_knowledge` (attributed, cited snippets)."""
    name = "knowledge"
    metadata = CapabilityMetadata(OperationKind.SEARCH, cacheable=True)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.tools.impl import search_knowledge
        text = search_knowledge(query=str(inputs.get("query", "")), limit=3)
        if "見つかりません" in text:
            return Evidence.empty(provenance={"capability": "knowledge"})
        ctx.emit("社内ナレッジを取得")
        return _text_evidence("knowledge", text)


class SolutionsCapability:
    """Real Otsuka Shokai product/solution pages for the goal — named products/
    services to ground a pitch, not just an internal category label. Reuses
    `impl.search_solutions` (attributed, cited snippets).

    The raw goal text is usually an imperative ("make a proposal for D001"), not
    a description of the customer's need — a bad query for the product corpus.
    When a deal/customer resolved, its product_category/industry describe the
    actual need and are folded into the query; the raw goal is kept too so a
    free-form ask ("...for a paperless office push") still contributes signal."""
    name = "solutions"
    metadata = CapabilityMetadata(OperationKind.SEARCH, cacheable=True)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.data import store
        from senpai.tools.impl import search_solutions

        goal = str(inputs.get("query", ""))
        deal_id = str(inputs.get("deal_id") or "")
        customer_id = str(inputs.get("customer_id") or "")
        deal = store.get_deal(deal_id) if deal_id else None
        category = (deal or {}).get("product_category", "")
        if not customer_id and deal:
            customer_id = deal.get("customer_id", "")
        customer = store.get_customer(customer_id) if customer_id else None
        industry = (customer or {}).get("industry", "")

        query = " ".join(p for p in (category, industry, goal) if p)
        if not query:
            return Evidence.empty(provenance={"capability": "solutions"})

        text = search_solutions(query=query, limit=3)
        if "見つかりません" in text:
            return Evidence.empty(provenance={"capability": "solutions"})
        ctx.emit("ソリューション・製品情報を取得")
        return _text_evidence("solutions", text)


class WebCapability:
    """External web search for factual/current topics. Reuses `impl.web_search`."""
    name = "web"
    metadata = CapabilityMetadata(OperationKind.SEARCH, max_concurrency=4, retries=1)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.tools.impl import web_search
        try:
            text = web_search(query=str(inputs.get("query", "")))
        except Exception as e:  # noqa: BLE001 — web is best-effort grounding
            return Evidence.empty(provenance={"capability": "web", "error": str(e)})
        ctx.emit("Web検索を実施")
        return _text_evidence("web", text)


# Order gathered grounding lands in the document, most-specific first.
_GATHER_ORDER = ("conversation", "workspace", "crm", "knowledge", "solutions", "web")


class DocumentsCapability:
    """The terminal producer: consume the gathered EvidenceBundle (via ctx.deps),
    assemble one grounding block, and author + render + register the artifact —
    reusing the existing author/proposal/render/registry logic. `op` is the doc kind
    (proposal | pptx | docx). This capability does NOT re-gather: its grounding is
    exactly what the selected capabilities put in the bundle."""
    name = "documents"
    metadata = CapabilityMetadata(OperationKind.WRITE, parallel_safe=False,
                                  idempotent=False, retries=0)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        kind = op or "pptx"
        if kind == "proposal":
            return self._proposal(inputs, ctx)
        return self._authored(kind, inputs, ctx)

    # -- grounding assembled from the bundle (not re-gathered) -------------------
    def _grounding(self, ctx: ExecContext) -> str:
        by_cap = {ev.capability: ev for ev in ctx.deps.values()}
        blocks = []
        for cap in _GATHER_ORDER:
            ev = by_cap.get(cap)
            if ev and ev.status in ("ok", "partial") and ev.data.get("text"):
                blocks.append(f"【{ev.data.get('label', cap)}】\n{ev.data['text']}")
        return "\n\n".join(blocks)

    def _citations(self, ctx: ExecContext) -> list[str]:
        cites: list[str] = []
        for ev in ctx.deps.values():
            cites.extend(ev.citations)
        return cites

    # -- proposal: deal-scoped, deterministic (GPU-free) ------------------------
    def _proposal(self, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.documents import proposal, registry
        deal_id = str(inputs.get("deal_id") or "")
        if not deal_id:
            return Evidence.error("proposal requires a deal_id",
                                  provenance={"capability": "documents"})
        deal_ids = [str(d) for d in (inputs.get("deal_ids") or [])]
        res = proposal.generate(deal_id, lang=str(inputs.get("lang", "ja")),
                                deal_ids=deal_ids or None)
        if res is None:
            return Evidence.error(f"deal {deal_id} not found",
                                  provenance={"capability": "documents"})
        files, doc_ctx, spec = res
        recs = _register_deck(registry, files, primary_kind="proposal", deal_id=deal_id)
        rec = recs[0]
        ctx.emit(f"提案書を生成: {rec['filename']}")
        outline = [{"title": s.get("title", "")} for s in spec.get("slides", [])]
        n = len(doc_ctx.deals)
        msg = (f"提案書(PPTX)を生成しました: {rec['filename']}（{n}件の案件を統合）"
              if n > 1 else f"提案書(PPTX)を生成しました: {rec['filename']}")
        return self._artifact_evidence(rec, ctx, msg, outline=outline, recs=recs)

    # -- pptx/docx: free-prompt, authored over the gathered grounding -----------
    def _authored(self, kind: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.documents import author, registry
        from senpai.documents.render import output_path, render_docx
        goal = str(inputs.get("goal") or inputs.get("prompt") or "")
        lang = str(inputs.get("lang", "ja"))
        # Whether a CRM customer resolved — independent of deal status, this alone
        # decides the sales-pitch voice (see playbook.deck_style_guide).
        customer_scoped = bool(inputs.get("customer_id"))
        grounding = self._grounding(ctx)
        if not author._use_llm():
            return Evidence.error("model required for pptx/docx authoring",
                                  provenance={"capability": "documents", "kind": kind})
        if kind == "docx":
            spec = author.author_doc(goal, grounding=grounding, lang=lang)
            if spec is None:
                return Evidence.error("author unavailable",
                                      provenance={"capability": "documents"})
            sections = spec.get("sections", [])
            ctx.emit(f"アウトライン生成: {len(sections)}セクション")
            for i, s in enumerate(sections, 1):
                ctx.emit(f"セクション{i}: {s.get('heading', '')}")
            ctx.emit("レンダリング中")
            path = output_path("docx", spec.get("_title") or goal[:30], "docx")
            render_docx(spec, path)
            rec = registry.register("docx", path)
            n = len(sections)
            msg = f"文書(DOCX)を生成しました: {rec['filename']}（{n}セクション）。"
            outline = [{"title": s.get("heading", "")} for s in sections]
        else:
            spec = author.author_deck(goal, grounding=grounding, lang=lang,
                                      customer_scoped=customer_scoped)
            if spec is None:
                return Evidence.error("author unavailable",
                                      provenance={"capability": "documents"})
            content_slides = [s for s in spec.get("slides", []) if s.get("layout") != "title"]
            ctx.emit(f"アウトライン生成: {len(content_slides)}スライド")
            for i, s in enumerate(content_slides, 1):
                ctx.emit(f"スライド{i}: {s.get('title', '')}")
            ctx.emit("レンダリング中")
            # HTML-first pipeline (editable PPTX + PDF + HTML); native fallback if no browser.
            from senpai.documents import export
            files = export.render_deck(spec, kind="pptx",
                                       slug=spec.get("_title") or goal[:30], lang=lang)
            recs = _register_deck(registry, files, primary_kind="pptx")
            rec = recs[0]
            n = len(content_slides)
            msg = f"プレゼン(PPTX)を生成しました: {rec['filename']}（{n}スライド）。"
            outline = [{"title": s.get("title", "")} for s in content_slides]
            ctx.emit(f"資料を生成: {rec['filename']}")
            return self._artifact_evidence(rec, ctx, msg, outline=outline, recs=recs)
        ctx.emit(f"資料を生成: {rec['filename']}")
        return self._artifact_evidence(rec, ctx, msg, outline=outline)

    def _artifact_evidence(self, rec: dict, ctx: ExecContext, msg: str,
                           outline: list | None = None,
                           recs: list[dict] | None = None) -> Evidence:
        def _doc(r: dict) -> dict:
            return {"doc_id": r["doc_id"], "kind": r["kind"],
                    "filename": r["filename"], "download_url": r["download_url"]}
        # `document` (singular) stays the primary editable file; `documents` carries the
        # whole export set (PPTX + PDF + HTML) so all surface as download chips.
        data = {"text": msg, "document": _doc(rec),
                "documents": [_doc(r) for r in (recs or [rec])],
                "grounded_on": sorted(
                    ev.capability for ev in ctx.deps.values()
                    if ev.status in ("ok", "partial") and ev.data.get("text"))}
        if outline:
            data["outline"] = outline
        return Evidence.ok(
            data, citations=[*self._citations(ctx), f"doc://{rec['doc_id']}"], status="ok")


# --- workspace WRITE terminals: note (create a text file) + organize (tidy) --------
import re as _re


def _slugify(text: str, default: str = "note") -> str:
    base = _re.sub(r"[^\w]+", "-", (text or "").strip().lower()).strip("-")
    base = _re.sub(r"-{2,}", "-", base)
    return (base[:48] or default)


# Deterministic filename → destination folder classifier for organize. Keyword-based,
# GPU-free; a file that matches nothing lands in "other/". Order = priority.
_ORGANIZE_RULES = (
    ("quotes",        ("見積", "quote", "estimate", "quotation", "お見積")),
    ("proposals",     ("提案", "proposal")),
    ("meeting-notes", ("議事", "meeting", "kickoff", "minutes", "打合", "面談", "notes", "memo", "メモ")),
    ("reports",       ("報告", "report", "レポート")),
    ("contracts",     ("契約", "contract", "nda", "agreement", "覚書")),
)


def _organize_bucket(name: str) -> str:
    low = name.lower()
    for folder, keys in _ORGANIZE_RULES:
        if any(k.lower() in low for k in keys):
            return folder
    return "other"


class WorkspaceWriteCapability:
    """Terminal that WRITES a short text note INTO the workspace (a real file the rep
    keeps), authored from the gathered grounding + the goal. Reuses the existing,
    sandbox-checked, confirm-gated `impl.edit_workspace_document` — this capability
    does not open a path itself. Read-gather → write is how the planner produces a
    persisted note instead of a downloadable artifact."""
    name = "workspace_write"
    metadata = CapabilityMetadata(OperationKind.WRITE, parallel_safe=False,
                                  idempotent=False, retries=0)

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.tools.impl import edit_workspace_document
        goal = str(inputs.get("goal") or inputs.get("prompt") or "")
        grounding = _grounding_from_deps(ctx)
        content = self._authored(goal, grounding, str(inputs.get("lang", "ja")))
        path = str(inputs.get("path") or "").strip() or self._pick_path(goal)
        result = edit_workspace_document(path, content, confirm=True)
        if result.startswith("エラー") or "エラーが発生" in result:
            return Evidence.error(result, provenance={"capability": "workspace_write"})
        ctx.emit(f"ノートを保存: {path}")
        grounded_on = sorted(ev.capability for ev in ctx.deps.values()
                             if ev.status in ("ok", "partial") and ev.data.get("text"))
        return Evidence.ok({"text": result, "saved_path": path, "kind": "note",
                            "grounded_on": grounded_on},
                           citations=[f"file://{path}"], status="ok")

    def _pick_path(self, goal: str) -> str:
        # A filename named in the goal wins; otherwise a slug under notes/.
        m = _re.search(r"([\w./-]+\.(?:md|txt|json|csv))", goal, _re.IGNORECASE)
        if m:
            return m.group(1)
        return f"notes/{_slugify(goal)}.md"

    def _authored(self, goal: str, grounding: str, lang: str) -> str:
        from senpai.documents import author
        if author._use_llm():
            instr = (
                "You are writing a concise MARKDOWN note to save into the user's files. "
                "Return ONLY the note body (no code fence). "
                f"Write in {'Japanese' if lang == 'ja' else 'English'}.\n"
                f"Use the reference context as the source of facts; do not invent figures.\n"
                f"Request: {goal}\n\n"
                f"{('参考情報:\n' + grounding) if grounding else '(参考情報なし)'}")
            out = author._complete(instr)
            if out:
                return out.strip()
        # Deterministic fallback: the grounding itself, titled.
        title = goal.strip() or "メモ"
        body = grounding or "(参考情報なし)"
        return f"# {title}\n\n{body}\n"


class WorkspaceOrganizeCapability:
    """Terminal that TIDIES the workspace: buckets loose documents into topic folders
    (quotes / proposals / meeting-notes / …) by a deterministic filename classifier.
    `op='plan'` previews the moves (read-only, the default — organizing real files is
    destructive); `op='apply'` performs them via the sandbox's no-overwrite
    `move_within`. Files already inside a subfolder are left alone."""
    name = "workspace_organize"
    metadata = CapabilityMetadata(OperationKind.WRITE, parallel_safe=False,
                                  idempotent=False, retries=0)

    def _llm_organize_bucket(self, names: list[str]) -> dict[str, str]:
        from senpai.documents import author
        import json, re
        
        if not author._use_llm() or not names:
            return {n: _organize_bucket(n) for n in names}
            
        prompt = (
            "You are an assistant organizing a user's files. "
            "Given the list of filenames below, assign a single short folder name to each file based on its likely content. "
            "Use standard categories like 'quotes', 'proposals', 'meeting-notes', 'reports', 'contracts', "
            "or create custom descriptive ones like 'invoices', 'research', 'specs'. "
            "Return strictly a JSON object mapping the exact filename to the folder name. No prose.\n\n"
            "Files:\n" + "\n".join(f"- {n}" for n in names)
        )
        
        try:
            out = author._complete(prompt)
            if out:
                m = re.search(r"\{.*\}", out, re.DOTALL)
                if m:
                    mapping = json.loads(m.group(0))
                    return {n: str(mapping.get(n, _organize_bucket(n))).strip("/") for n in names}
        except Exception:
            pass
            
        return {n: _organize_bucket(n) for n in names}

    def run(self, op: str, inputs: Mapping[str, Any], ctx: ExecContext) -> Evidence:
        from senpai.workspace import sandbox
        docs = sandbox.list_documents()
        root = sandbox.workspace_root()
        
        # Only reorganize files sitting at the ROOT (don't churn already-filed docs).
        root_files = [p for p in docs if "/" not in sandbox.rel(p) and "\\" not in sandbox.rel(p)]
        
        if root_files:
            file_to_folder = self._llm_organize_bucket([p.name for p in root_files])
        else:
            file_to_folder = {}

        moves: list[tuple[str, str]] = []
        for p in root_files:
            rel = sandbox.rel(p)
            folder = file_to_folder.get(p.name, _organize_bucket(p.name))
            dest = f"{folder}/{p.name}"
            if dest != rel:
                moves.append((rel, dest))

        if not moves:
            return Evidence.ok({"text": "整理対象のファイルはありません（すべて分類済み）。",
                                "kind": "organize", "moves": []}, status="ok")

        preview = "\n".join(f"  {s} → {d}" for s, d in moves)
        if op != "apply":
            body = (f"【整理プレビュー（未実行・{len(moves)}件）】\n{preview}\n\n"
                    "実行するには「整理して実行」/「apply」と指示してください。")
            ctx.emit(f"{len(moves)}件の移動を提案")
            return Evidence.ok({"text": body, "kind": "organize", "applied": False,
                                "moves": [{"from": s, "to": d} for s, d in moves]},
                               status="ok")

        done, failed = [], []
        for s, d in moves:
            try:
                sandbox.move_within(s, d)
                done.append((s, d))
            except Exception as e:  # noqa: BLE001 — one bad move must not abort the rest
                failed.append((s, str(e)))
        ctx.emit(f"{len(done)}件を整理")
        lines = [f"【整理を実行しました（{len(done)}件）】",
                 *(f"  {s} → {d}" for s, d in done)]
        if failed:
            lines.append(f"スキップ {len(failed)}件: " + "、".join(f"{s}({e})" for s, e in failed))
        return Evidence.ok({"text": "\n".join(lines), "kind": "organize", "applied": True,
                            "moves": [{"from": s, "to": d} for s, d in done]}, status="ok")


def _grounding_from_deps(ctx: ExecContext) -> str:
    """Assemble gathered grounding from ctx.deps, most-specific-first (shared by the
    Documents and WorkspaceWrite terminals)."""
    by_cap = {ev.capability: ev for ev in ctx.deps.values()}
    blocks = []
    for cap in _GATHER_ORDER:
        ev = by_cap.get(cap)
        if ev and ev.status in ("ok", "partial") and ev.data.get("text"):
            blocks.append(f"【{ev.data.get('label', cap)}】\n{ev.data['text']}")
    return "\n\n".join(blocks)


def build_registry():
    """A registry with all planner capabilities, ready for the ExecutionEngine."""
    from senpai.orchestration import CapabilityRegistry
    reg = CapabilityRegistry()
    for cap in (ConversationCapability(), WorkspaceCapability(), CRMCapability(),
                KnowledgeCapability(), SolutionsCapability(), WebCapability(),
                DocumentsCapability(), WorkspaceWriteCapability(),
                WorkspaceOrganizeCapability()):
        reg.register(cap)
    return reg
````

## File: senpai/planner/selection.py
````python
"""What the planner decides: a `Selection` — which capabilities to gather from and
what document to produce — plus the deterministic resolver that grounds it.

The LLM's job (in llm_planner.py) is to pick *which capabilities* are worth
gathering. IDs are never trusted to the model: the customer/deal a document is
grounded in is resolved here, deterministically, from the store (the project's
"never invent an ID" rule). So even a hallucinated capability list can only widen
or narrow the gather — it can never point the document at the wrong deal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from senpai import config
from senpai.data import store

# The gather capabilities the planner may select from (documents is always the
# terminal, so it is not part of the selectable gather set).
GATHER_CAPABILITIES = ("conversation", "workspace", "crm", "knowledge", "solutions", "web")
# What the terminal produces. proposal/pptx/docx = generate an artifact file; note =
# write a text file into the workspace; organize = tidy the workspace on disk.
DOC_KINDS = ("proposal", "pptx", "docx", "note", "organize")

_DEAL_ID_RE = re.compile(r"\bD\d{3}\b", re.IGNORECASE)
_PROPOSAL_CUES = ("提案", "proposal", "提案書")
# "cover every deal for this customer" — a proposal grounded in ALL of a resolved
# customer's deals (merged financials/products/comparables), not just the biggest
# one. Independent of doc_kind/deal-status routing; see _wants_all_deals.
_ALL_DEALS_RE = re.compile(
    r"\ball\s+(?:the\s+)?deals\b|\bevery\s+deal\b|\beach\s+deal\b|"
    r"全て?の案件|全案件|各案件", re.IGNORECASE)
# 稟議 (ringisho) is intentionally NOT here: it has its own dedicated template/tool
# (generate_ringisho) and is routed to the ReAct loop, not the planner.
_DOCX_CUES = ("文書", "報告書", "レポート", "docx", "document", "report")
# External/factual cue (stale-in-weights topics) — reuse the doc tools' own heuristic.
from senpai.tools.impl import _auto_web  # noqa: E402


# --- planner intent detection (the router's source of truth) ----------------
# Document GENERATION: a create verb + a document noun. 稟議 excluded (own tool).
_DOC_VERB = (r"(?:make|create|generate|build|draft|write|produce|prepare|"
             r"put\s+together|作って|作成|作る|生成|書いて|まとめて|用意|つくって)")
_DOC_NOUN = (r"(?:proposal|deck|slides?|slide\s?deck|presentation|power\s?point|"
             r"pptx?|ppt|docx?|word\s+doc(?:ument)?|document|report|"
             r"提案書|提案|スライド|資料|プレゼン(?:テーション)?|文書|報告書|レポート)")
_DOC_GOAL_RE = re.compile(
    _DOC_VERB + r"\b.{0,40}?" + _DOC_NOUN + r"|" + _DOC_NOUN + r".{0,20}?(?:を|の)?\s*" + _DOC_VERB,
    re.IGNORECASE)
_RINGISHO_RE = re.compile(r"稟議|ringisho", re.IGNORECASE)

# ORGANIZE: tidy/sort/reorganize the workspace on disk (a WRITE that moves files).
_ORGANIZE_RE = re.compile(
    r"\b(?:organi[sz]e|reorgani[sz]e|rearrange|tidy(?:\s?up)?|clean\s?up|sort|file\s+away|declutter)\b"
    r".{0,30}?(?:files?|documents?|docs?|folder|workspace)|"
    r"\b(?:put|move|place)\b.{1,40}?\b(?:in|into|under|to|inside)\b.{1,30}?(?:folder|directory)?|"
    r"(?:ファイル|資料|ドキュメント|文書|フォルダ|ワークスペース).{0,10}?"
    r"(?:整理|片付け|仕分け|フォルダ分け|分類|移動)|"
    r"(?:整理|片付け|仕分け|フォルダ分け|分類|移動)(?:して|する)?", re.IGNORECASE)

# NOTE: save/write a short text file INTO the workspace (not a generated artifact).
_NOTE_RE = re.compile(
    r"\b(?:save|jot(?:\s+down)?|record|note\s+down|write\s+(?:a\s+|this\s+)?(?:note|down))\b"
    r".{0,40}?(?:my\s+)?(?:files?|documents?|docs?|workspace|note|\.md|\.txt)|"
    r"(?:save|write|append).{0,20}?(?:to|into)\s+[\w./-]+\.(?:md|txt|json|csv)|"
    r"(?:メモ|ノート|記録)(?:を|に)?.{0,10}?(?:保存|作成|残|書|追記)|"
    r"(?:ファイル|資料|文書)(?:に|へ).{0,10}?(?:保存|書き込|追記|記録)", re.IGNORECASE)

# Explicit "actually do it" for the destructive organize (otherwise preview only).
_APPLY_RE = re.compile(r"\b(?:apply|do\s+it|go\s+ahead|confirm|execute)\b|実行|適用|やって",
                       re.IGNORECASE)
# A broader affirmation, only ever consulted right after an organize PREVIEW (so a
# bare "yes"/"go ahead"/"はい" continues and applies the pending reorganize).
_AFFIRM_RE = re.compile(
    r"\b(?:yes|yeah|yep|ok|okay|sure|go\s+ahead|do\s+it|apply|proceed|confirm|"
    r"execute|please\s+do|go\s+for\s+it)\b|はい|お願い|やって|実行|適用|進めて|それで",
    re.IGNORECASE)
# The marker the organize PREVIEW writes into its assistant reply (see
# WorkspaceOrganizeCapability); its presence in the last assistant turn is what makes
# a following affirmation mean "apply the reorganize".
_ORGANIZE_PREVIEW_MARK = "【整理プレビュー"


def _recent_assistant_texts(history: list | None, limit: int = 3) -> list[str]:
    """The most recent assistant messages' texts, so continuation detection works
    even if the model hallucinated a turn in between."""
    if not history:
        return []
    texts = []
    for item in reversed(history):
        role = getattr(item, "role", None)
        content = getattr(item, "content", None)
        if role is None and isinstance(item, dict):
            role, content = item.get("role"), item.get("content")
        if role == "assistant":
            texts.append(content or "")
            if len(texts) >= limit:
                break
    return texts


def _organize_apply_continuation(message: str, history: list | None) -> bool:
    """True when the user is confirming a pending organize preview (an affirmation
    immediately after the preview was shown, checking up to 3 turns back)."""
    if not bool(_AFFIRM_RE.search(message or "")):
        return False
    recent = _recent_assistant_texts(history, limit=3)
    return any(_ORGANIZE_PREVIEW_MARK in text for text in recent)


def is_organize_goal(message: str, history: list | None = None) -> bool:
    return (bool(_ORGANIZE_RE.search(message or ""))
            or _organize_apply_continuation(message, history))


def is_note_goal(message: str) -> bool:
    return bool(_NOTE_RE.search(message or ""))


def is_document_goal(message: str) -> bool:
    m = message or ""
    if _RINGISHO_RE.search(m):
        return False
    return bool(_DOC_GOAL_RE.search(m))


def is_planner_goal(message: str, history: list | None = None) -> bool:
    """Any goal the LLMPlanner owns: organize / note-write / document generation.
    Order matters — organize and note are checked first because their phrasings can
    also contain a document noun ('organize my documents')."""
    return (is_organize_goal(message, history) or is_note_goal(message)
            or is_document_goal(message))


# --- hybrid router: regex fast-path + LLM confirmation for complex prompts ---
# The regex triggers above are a keyword match ANYWHERE in the message — correct
# for the common case ("make me a pptx about X"), but a document noun/verb near
# the END of a long, multi-step research message (numbered lookups, faceted
# searches, etc.) hijacks the ENTIRE turn into the planner's one-shot capability
# graph, which cannot run N arbitrary tool calls — it silently drops everything
# but a hollow single-section doc. Only worth a second opinion when the regex
# says "planner" AND the message actually looks like that shape; a short,
# single-intent ask never pays the extra round-trip.
# "・" (nakaguro) is the standard Japanese bullet in business writing — a plain
# `-`/`*`/digit check misses it entirely, which matters here: Japanese has no
# spaces, so the word-count fallback below is blind on CJK text, leaving the
# step-bullet check as the ONLY signal for a Japanese multi-step prompt.
_NUMBERED_STEP_RE = re.compile(r"(?:^|\n)\s*\d+[.)]\s|(?:^|\n)\s*[-*・]\s?", re.MULTILINE)
_COMPLEXITY_WORD_THRESHOLD = 60
_COMPLEXITY_STEP_THRESHOLD = 3
_CJK_RE = re.compile(r"[぀-ヿ一-鿿]")
# Japanese has no word-separating spaces, so `len(message.split())` counts the
# whole line as ~1 "word" and never trips the English word-count threshold —
# use a character-count threshold on CJK text instead.
_COMPLEXITY_CJK_CHAR_THRESHOLD = 120


def _looks_complex(message: str) -> bool:
    m = message or ""
    if len(_NUMBERED_STEP_RE.findall(m)) >= _COMPLEXITY_STEP_THRESHOLD:
        return True
    if _CJK_RE.search(m):
        return len(re.sub(r"\s+", "", m)) > _COMPLEXITY_CJK_CHAR_THRESHOLD
    return len(m.split()) > _COMPLEXITY_WORD_THRESHOLD


def _extract_route_json(text: str) -> dict | None:
    if not text:
        return None
    t = re.sub(r"```(?:json)?", "", text).strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        import json
        obj = json.loads(t[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except ValueError:
        return None


def _llm_classify_route(message: str) -> bool | None:
    """Ask a small, fast model for the DOMINANT intent of a long/complex message.
    Returns True (planner) / False (chat/ReAct loop) / None on any failure — the
    caller falls back to the regex verdict on None (fail-open, same pattern as
    the planner's own capability-selector LLM call)."""
    from senpai.documents.author import _use_llm
    if not _use_llm():
        return None
    prompt = (
        "You are a routing classifier for a sales assistant with two surfaces:\n"
        "  \"planner\" — a one-shot document/note generator or workspace-organizer. "
        "Good when the message's DOMINANT ask is to produce ONE document/deck/note "
        "or tidy files.\n"
        "  \"chat\" — a tool-calling research assistant that can look things up "
        "(pipelines, deals, notes, playbook, web) an arbitrary number of times, one "
        "call at a time, and can ALSO generate a document as its last step.\n"
        "Pick \"chat\" whenever the message is primarily a multi-step research/lookup "
        "task (many distinct queries, numbered steps, several named entities) — even "
        "if it also asks for a document at the end, since \"chat\" can produce that "
        "document once the research is actually done. Pick \"planner\" only when the "
        "message has no real multi-step research to do first.\n"
        "Return strict JSON only, no prose, no code fence: {\"route\": \"planner\"|\"chat\"}\n\n"
        f"Message:\n{(message or '')[:4000]}"
    )
    try:
        from senpai.llm.client import simple_complete
        raw = simple_complete([{"role": "user", "content": prompt}],
                              temperature=0.0, max_tokens=30,
                              no_think=True, allow_fallback=False)
    except Exception:  # noqa: BLE001 — model down/timeout → regex verdict stands
        return None
    obj = _extract_route_json(raw)
    if not isinstance(obj, dict):
        return None
    route = obj.get("route")
    if not isinstance(route, str):
        return None
    if route.lower() not in ("planner", "chat"):
        return None
    return route.lower() == "planner"


def _wants_multiple_deliverable_kinds(message: str, history: list | None = None) -> bool:
    """True when the message asks for more than one DISTINCT kind of planner
    deliverable (organize + note + document, in any combination), OR multiple
    distinct documents (e.g., both a PPTX and a DOCX). The planner's ExecutionPlan
    has exactly one terminal task (see plan.py's module docstring) — it physically
    cannot save a note AND organize files AND generate a proposal in the same turn.
    `_pick_doc_kind`'s priority order silently picks one and the other asks vanish.
    The ReAct loop has no such ceiling, so route there instead whenever multiple
    deliverables are being asked for."""
    kinds = sum((
        is_organize_goal(message, history),
        is_note_goal(message),
        is_document_goal(message),
    ))
    if kinds > 1:
        return True
        
    # If it's a document goal, check if there are multiple document creation verbs
    # which usually implies multiple distinct documents (e.g. "make a pptx and draft a docx")
    if is_document_goal(message):
        if len(_DOC_GOAL_RE.findall(message or "")) > 1:
            return True
            
    return False


def resolve_route(message: str, history: list | None = None) -> bool:
    """True → route this turn through the LLMPlanner; False → the ReAct tool loop.
    Fast path (the overwhelming majority of turns): trust the regex heuristic
    directly, zero added latency. Two escapes from the fast path, both deterministic
    or fail-open, never trusting a single ambiguous signal: (1) more than one
    DISTINCT deliverable kind is being asked for in one message — the planner can
    only ever produce one, so this always goes to chat; (2) the regex says
    "planner" and the message reads as a long, multi-step task — confirm the
    dominant intent with a small LLM classifier before committing to the
    planner's one-shot graph."""
    if _wants_multiple_deliverable_kinds(message, history):
        return False
    regex_says_planner = is_planner_goal(message, history)
    if not regex_says_planner or not _looks_complex(message):
        return regex_says_planner
    verdict = _llm_classify_route(message)
    return regex_says_planner if verdict is None else verdict


@dataclass(frozen=True)
class Selection:
    """The plan the LLMPlanner emits: the capability set to gather from + the
    document to build (kind + the deterministically-resolved entity it grounds in)."""
    goal: str
    capabilities: tuple[str, ...]          # subset of GATHER_CAPABILITIES
    doc_kind: str                          # one of DOC_KINDS
    deal_id: str | None = None
    customer_id: str | None = None
    target: str = ""                       # display name of the entity in focus
    lang: str = "ja"
    title: str = ""
    reason: str = ""                       # why these capabilities (observability)
    confirm: bool = False                  # apply a destructive op (organize); else preview
    path: str = ""                         # target file for a note write (optional)
    all_deals: bool = False                # proposal: merge ALL of the customer's deals

    def with_capabilities(self, caps) -> "Selection":
        ordered = tuple(c for c in GATHER_CAPABILITIES if c in set(caps))
        return replace(self, capabilities=ordered)


def _wants_all_deals(goal: str) -> bool:
    return bool(_ALL_DEALS_RE.search(goal or ""))


def _resolve_entity(goal: str, deal_hint: str | None = None) -> tuple[str | None, str | None, str]:
    """(deal_id, customer_id, display_target) for the document, from the store.
    A `deal_hint` (e.g. the deal the rep picked in the selector) is authoritative;
    then an explicit D### in the goal; otherwise a customer name resolves to its
    primary open deal (largest amount) so a proposal can be grounded. None/None when
    the entity isn't in the CRM (e.g. a workspace-only company) — then a free deck
    grounds on the workspace/conversation instead."""
    if deal_hint:
        d = store.get_deal(deal_hint.strip().upper())
        if d:
            did = d["deal_id"]
            return did, d["customer_id"], store.customer_name(d["customer_id"])
    m = _DEAL_ID_RE.search(goal or "")
    if m:
        did = m.group(0).upper()
        d = store.get_deal(did)
        if d:
            return did, d["customer_id"], store.customer_name(d["customer_id"])
    cust = store.match_customer_in_text(goal or "")
    if not cust:
        return None, None, ""
    cid = cust["customer_id"]
    deals = store.deals_for_customer(cid)
    open_deals = [d for d in deals if config.is_open_rank(d.get("order_rank"))]
    # Prefer an open deal (the live pipeline); but a customer whose deals are all
    # Confirmed/Lost is still a real account with real history to ground a proposal
    # on — falling all the way to None here is what silently degraded these to
    # ungrounded free decks. Ground on the best deal on file either way.
    pool = open_deals or deals
    pool = sorted(pool, key=lambda d: d.get("total_order_amount", 0), reverse=True)
    deal_id = pool[0]["deal_id"] if pool else None
    return deal_id, cid, cust.get("name", "")


def _pick_doc_kind(goal: str, deal_id: str | None, history: list | None = None) -> str:
    g = (goal or "")
    # Workspace ops win over document generation (their phrasing overlaps).
    if is_organize_goal(g, history):
        return "organize"
    if is_note_goal(g):
        return "note"
    if deal_id or any(c in g.lower() or c in g for c in _PROPOSAL_CUES):
        # A grounded proposal needs a deal; without one it degrades to a free deck.
        return "proposal" if deal_id else "pptx"
    if any(c in g.lower() or c in g for c in _DOCX_CUES):
        return "docx"
    return "pptx"


def _lang_of(goal: str) -> str:
    """JA unless the goal has no CJK at all (then EN)."""
    return "ja" if re.search(r"[぀-ヿ一-鿿]", goal or "") else "ja"


def heuristic_selection(goal: str, deal_hint: str | None = None, history: list | None = None) -> Selection:
    """Deterministic capability selection — the default, and the fallback whenever
    the LLM is off or returns junk. Always gathers conversation (session context);
    adds workspace (self-gated on a real file match), CRM when an entity resolved,
    knowledge for proposals (playbook grounding), and web for external/factual
    topics with no internal entity."""
    deal_id, customer_id, target = _resolve_entity(goal, deal_hint)
    doc_kind = _pick_doc_kind(goal, deal_id, history)

    # Organize is self-contained (it inspects the workspace itself) — no gather.
    # Apply when the goal itself says so ("...and apply") OR when it's an affirmation
    # confirming a pending preview ("go ahead"); otherwise preview (never move silently).
    if doc_kind == "organize":
        confirm = (bool(_APPLY_RE.search(goal or ""))
                   or _organize_apply_continuation(goal, history))
        return Selection(goal=goal, capabilities=(), doc_kind="organize",
                         lang=_lang_of(goal), confirm=confirm,
                         reason="heuristic: organize workspace ("
                                + ("apply" if confirm else "preview") + ")")

    caps = ["conversation", "workspace"]
    if customer_id or deal_id:
        caps.append("crm")
    if doc_kind == "proposal":
        caps.append("knowledge")
        caps.append("solutions")
    if _auto_web(goal) and not (customer_id or deal_id):
        caps.append("web")

    return Selection(
        goal=goal, capabilities=tuple(caps), doc_kind=doc_kind,
        deal_id=deal_id, customer_id=customer_id, target=target,
        lang=_lang_of(goal), all_deals=_wants_all_deals(goal),
        reason="heuristic: " + ("entity in CRM" if (customer_id or deal_id)
                                else "no CRM entity — workspace/conversation grounded"))


def ground_selection(goal: str, caps, doc_kind: str, reason: str = "",
                     deal_hint: str | None = None, history: list | None = None) -> Selection:
    """Build a Selection from an LLM-chosen capability set + doc_kind, but re-ground
    the entity/IDs deterministically and enforce invariants: conversation is always
    gathered; a `proposal` with no resolvable deal degrades to a free `pptx`; CRM is
    only kept when an entity actually resolved."""
    deal_id, customer_id, target = _resolve_entity(goal, deal_hint)
    if doc_kind not in DOC_KINDS:
        doc_kind = _pick_doc_kind(goal, deal_id, history)
    # IDs/routing are never trusted to the model (see module docstring) — a
    # deterministically resolved deal always grounds a proposal, regardless of
    # what the LLM guessed for doc_kind. Only an explicit docx/note ask is left as
    # the model chose it (those aren't deal-shaped documents).
    if deal_id and doc_kind not in ("docx", "note"):
        doc_kind = "proposal"
    if doc_kind == "proposal" and not deal_id:
        doc_kind = "pptx"  # can't ground a proposal without a deal

    chosen = {c for c in caps if c in set(GATHER_CAPABILITIES)}
    chosen.add("conversation")             # session context is always worth gathering
    if "crm" in chosen and not (customer_id or deal_id):
        chosen.discard("crm")              # nothing for CRM to ground on
    if doc_kind == "proposal":
        chosen.add("knowledge")
        chosen.add("solutions")

    return Selection(
        goal=goal, capabilities=tuple(c for c in GATHER_CAPABILITIES if c in chosen),
        doc_kind=doc_kind, deal_id=deal_id, customer_id=customer_id, target=target,
        lang=_lang_of(goal), all_deals=_wants_all_deals(goal),
        reason=reason or "llm-selected")
````

## File: senpai/config.py
````python
"""Central configuration for Senpai.

Holds the model-server connection details (shared with the Phase-1 demo), the
filesystem paths to the seed data, and — most importantly — the *tunable* deal-
health scoring parameters. Everything the scoring engine treats as a threshold
lives here so the rules stay auditable and adjustable in one place (no magic
numbers buried in the engine).

Env:
  BASE_URL      default http://127.0.0.1:8765/v1   (vLLM OpenAI endpoint)
  MODEL         default exp3
  LLM_TIMEOUT   default 120 (seconds) — per-request inference timeout
  LLM_STREAM    default 1 — stream tokens from the server when supported
  LLM_MAX_TOKENS default 1024 — cap on generated tokens for narration
  SENPAI_TODAY  default unset → date.today(); set YYYY-MM-DD to pin the
                "current date" used by scoring (handy for a reproducible demo
                against the committed seed data, whose reference is 2026-06-16).
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

def _load_dotenv() -> None:
    """Load .env files into os.environ (stdlib only; never overrides an already-set
    var). config is the first senpai import in every entrypoint, so doing this here
    means BASE_URL/MODEL/etc. take effect everywhere — including the FastAPI bridge.
    Loads the repo-root `.env` first, then `senpai/.env` (handy for keeping
    ingestion keys like OPENAI_BASE_URL/OPENAI_API_KEY next to the package);
    repo-root wins on conflicts because setdefault keeps the first value seen."""
    here = Path(__file__).resolve().parent
    for env in (here.parent / ".env", here / ".env"):
        if not env.exists():
            continue
        for raw in env.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()

# --- Model server -----------------------------------------------------------
# Any OpenAI-compatible endpoint works here: vLLM (`vllm serve … --port 8765`),
# llama.cpp's `llama-server`, and ollama's `/v1` are all drop-in compatible.
# Only this URL + MODEL change between backends; both come from the repo-root
# .env (loaded above) or process env.
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8765/v1")
FALLBACK_BASE_URL = os.environ.get("FALLBACK_BASE_URL", "http://100.101.186.29:8766/v1")
MODEL = os.environ.get("MODEL", "exp3")
FALLBACK_MODEL = os.environ.get("FALLBACK_MODEL", "toolmind_exp3_final")
MAX_TOOL_ROUNDS = int(os.environ.get("MAX_TOOL_ROUNDS", 30))


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- Inference tunables -----------------------------------------------------
LLM_TIMEOUT = _env_float("LLM_TIMEOUT", 120.0)        # seconds, per request
LLM_MAX_TOKENS = _env_int("LLM_MAX_TOKENS", 4096)
# Senior Commentary budget. Default sized for the fast live path (thinking OFF):
# enough for a flowing conversational read, not long-form. If NARRATE_THINK is
# enabled (reasoning ON, for a pre-warmed cache when the GPU is free), raise this
# to ~2400 so the hidden <think> block plus the answer both fit without truncation.
LLM_NARRATE_MAX_TOKENS = _env_int("LLM_NARRATE_MAX_TOKENS", 600)
# Reasoning on Senior Commentary. OFF by default: on the shared ~11 tok/s box a
# <think> block adds ~2 min/call, too slow for a live demo. Flip on (with a higher
# LLM_NARRATE_MAX_TOKENS) for offline/pre-warmed generation where quality wins.
NARRATE_THINK = os.environ.get("SENPAI_NARRATE_THINK", "0").lower() not in ("0", "false", "no", "")
LLM_STREAM = os.environ.get("LLM_STREAM", "1").lower() not in ("0", "false", "no", "")
# Assistant tool-loop reasoning. Both the tool-selection rounds and the final
# synthesis run the reasoning distill's <think> phase, which dominates Assistant
# latency on the shared ~11 tok/s box. ON skips it (empty-think prefill) across
# the whole loop — same lever the narrate path uses. Measured ~1.9x faster
# overall (up to ~3x on tool + short-answer turns), with tool selection and
# provenance preserved; the only cost seen was an occasional numeric paraphrase
# slip in long answers. Default ON; set SENPAI_TOOLLOOP_NOTHINK=0 to restore the
# slower, fully-reasoned loop.
TOOLLOOP_NO_THINK = os.environ.get("SENPAI_TOOLLOOP_NOTHINK", "1").lower() not in ("0", "false", "no", "")
# Dynamic reasoning router for the Assistant synthesis round (senpai/llm/routing.py).
# "deterministic" (default) routes FAST vs REASONING by the tools used + query
# intent — reasoning is added back only where it helps (numeric/synthesis), while
# retrieval stays fast. "off" reverts to the static TOOLLOOP_NO_THINK behaviour.
# Later: "atlas" / "classifier" / "llm" — swap in get_reasoning_router(), no
# change to the execution loop. Tool-selection rounds are always fast regardless.
REASONING_ROUTER = os.environ.get("SENPAI_REASONING_ROUTER", "deterministic").strip().lower()
# Model decomposition: serve the FAST (no_think) final synthesis from the smaller
# FALLBACK model (8B Q4) instead of the primary 27B — validated ~2.7x faster at
# grounding parity (docs/phase25_session_log.md). THINK synthesis stays on the 27B
# for its mentorship narrative. OFF by default; SENPAI_FAST_SYNTH_FALLBACK=1 routes
# FAST synthesis to the 8B. (Tool selection always stays on the primary 27B.)
FAST_SYNTH_FALLBACK = os.environ.get("SENPAI_FAST_SYNTH_FALLBACK", "0").lower() not in ("0", "false", "no", "")
# Latency-first override: route ALL synthesis (FAST + THINK) to the 8B, not just
# FAST. The 27B THINK synthesis was the slow path (~150s); the 8B does it far
# faster at a quality cost. Implies the fallback endpoint is the 8B.
SYNTH_ALL_FALLBACK = os.environ.get("SENPAI_SYNTH_ALL_8B", "0").lower() not in ("0", "false", "no", "")

# --- Atlas (spark) serving knobs --------------------------------------------
# The served model is now the atlas 35B (Qwen3.6-35B-A3B-NVFP4, spark/atlas on
# :8888). Two atlas-specific behaviours feed every create() call (see
# senpai/llm/client.py::_gen_kwargs):
#   1. Reasoning is toggled via the chat template's `enable_thinking` kwarg
#      (passed through extra_body→chat_template_kwargs), NOT the old empty
#      <think> prefill — atlas ignores the prefill.
#   2. Sampling MUST be set explicitly. With no sampling params atlas decodes
#      greedily and degenerates into repetition loops ("3. 3. 3.") on long
#      output; the recommended Qwen3 non-thinking sampling fixes it.
LLM_TOP_P = _env_float("SENPAI_LLM_TOP_P", 0.95)
LLM_TOP_K = _env_int("SENPAI_LLM_TOP_K", 20)
# Final-answer (synthesis) temperature. Non-zero on purpose: greedy (0.0) long
# generation degenerates on this NVFP4 model. Tool-selection rounds stay greedy
# (short, structured output — no degeneration, more deterministic tool picks).
SYNTH_TEMPERATURE = _env_float("SENPAI_SYNTH_TEMPERATURE", 0.7)

# --- Review Coach grounding controls ----------------------------------------
# Grounding-audit P0: similar past cases are CROSS-CUSTOMER by construction
# (find_similar_cases injects another customer's closed deal ~99% of the time),
# which risks narrative contamination — the model reasoning from analogy rather
# than this customer's own evidence. Disabled by default while we verify grounding.
# Corpus principles (playbooks) are kept; they are a separate, evaluated axis.
COACH_USE_SIMILAR_CASES = os.environ.get("SENPAI_COACH_SIMILAR_CASES", "0").lower() not in ("0", "false", "no", "")
COACH_USE_CORPUS = os.environ.get("SENPAI_COACH_CORPUS", "1").lower() not in ("0", "false", "no", "")

# --- Paths ------------------------------------------------------------------
PKG_DIR = Path(__file__).resolve().parent
SEED_DIR = PKG_DIR / "data" / "seed"
INDEX_DIR = PKG_DIR / "data" / "index"   # committed dense-embedding vectors (build_index.py)
# Committed Segment-Intelligence community reports (build_communities.py). Like the
# dense index, this is a committed build artifact so the runtime is GPU-free — the
# deterministic stats can always be recomputed, and the optional LLM narratives ride
# along. Missing file → senpai.graph.communities rebuilds deterministically in-memory.
COMMUNITIES_PATH = INDEX_DIR / "communities.json"
# A category×industry leaf segment is only emitted as its own report when it has at
# least this many CLOSED deals (won+lost); thinner leaves are represented by their
# parent category rollup, which always aggregates every deal in the category.
SEGMENT_MIN_DEALS = _env_int("SENPAI_SEGMENT_MIN_DEALS", 5)
# Sidecar dir for runtime-ingested rows (daily reports, etc.). Gitignored and
# loaded as an OVERLAY on top of SEED_DIR by senpai.data.store — the committed
# seed stays canonical/byte-stable; ingested data is demo-only and never merged.
INGESTED_DIR = PKG_DIR / "data" / "ingested"
# Output dir for documents the chatbot generates (PPTX proposals, DOCX 稟議書, and
# the general-purpose pptx/docx tools). Gitignored and demo-only, like INGESTED_DIR;
# created on first write. The committed seed is never touched by document generation.
GENERATED_DIR = PKG_DIR / "data" / "generated"

# Cross-chat memory: durable, entity-anchored Observations (the judgments a chat
# reached, NOT transcripts), keyed by Subject so a later chat about the same deal can
# reason from them. Gitignored and demo-only. The JSONL file is a storage STUB behind
# the ObservationStore seam (senpai.orchestration.memory); the persistence layer's DB
# is just another implementation of that interface and replaces this file wholesale.
MEMORY_DIR = PKG_DIR / "data" / "memory"
OBSERVATIONS_PATH = MEMORY_DIR / "observations.jsonl"

# Persistent copilot chat history: durable, per-user conversation transcripts so a
# rep can close the tab and resume a past chat exactly where it left off. A single
# SQLite file (stdlib sqlite3, WAL mode) keyed by conversation_id — deliberately
# SEPARATE from senpai.data.store's seed/overlay tables so chat writes never drop
# store's lru_cache. Gitignored and demo-only, like INGESTED_DIR; created on first
# use. The stored blob is an opaque client-owned transcript the server never parses.
CHAT_DB_PATH = INGESTED_DIR / "chat_history.db"

# --- Workspace (sandboxed local document access) ----------------------------
# The Workspace capability reaches OUTSIDE the seed DB — it finds and reads real
# local documents (PDF/DOCX/PPTX/XLSX/TXT/MD) and returns structured evidence into
# the orchestration EvidenceBundle. It is strictly READ-ONLY and confined to
# WORKSPACE_ROOT: every path is resolved and must stay inside that root (no
# traversal, no symlink escape). Points at a real local docs folder; override with
# SENPAI_WORKSPACE_ROOT. list_documents() prunes VCS/build dirs and our own
# `generated` output so machine artifacts don't feed back in as grounding.
WORKSPACE_ROOT = Path(
    os.environ.get("SENPAI_WORKSPACE_ROOT", r"E:\my_stuff\Otsuka_backup")
).resolve()
# Extensions the Workspace will find/extract (read-only). Lowercase, with dot.
WORKSPACE_EXTS = tuple(
    e.strip().lower() for e in os.environ.get(
        "SENPAI_WORKSPACE_EXTS", ".pdf,.docx,.pptx,.xlsx,.txt,.md,.png,.jpg,.jpeg,.gif").split(",") if e.strip())
# Runtime fan-out cap: a `find` never expands into more than this many parallel
# `extract` tasks, so one query can't read an unbounded tree.
WORKSPACE_MAX_FILES = _env_int("SENPAI_WORKSPACE_MAX_FILES", 12)
# Per-document extracted-text cap (chars) — keeps the evidence bundle bounded and
# the reasoner context safe, mirroring the chat loop's 1500-char tool truncation.
WORKSPACE_MAX_CHARS = _env_int("SENPAI_WORKSPACE_MAX_CHARS", 4000)
# Skip absurdly large files before we even open them (bytes).
WORKSPACE_MAX_BYTES = _env_int("SENPAI_WORKSPACE_MAX_BYTES", 25_000_000)

# Committed brand template for generated PPTX decks: an Otsuka proposal deck with
# all content slides stripped, leaving only its slide masters/layouts/theme (the
# Meiryo UI font + corporate styling). render.render_pptx opens this as the base
# so generated decks inherit Otsuka branding. If absent, rendering falls back to
# python-pptx's blank default (keeps tests/CI green without the committed asset).
PPTX_TEMPLATE_PATH = PKG_DIR / "data" / "templates" / "otsuka_template.pptx"


def fiscal_year_quarter(d_iso: str) -> tuple[int, int]:
    """Japanese fiscal year/quarter for a YYYY-MM-DD date (FY starts in April).
    Single source of truth shared by gen_seed (seed authoring) and ingestion
    (runtime activity records) so both stay in the same fiscal calendar."""
    y, m, _ = (int(x) for x in d_iso.split("-"))
    fy = y if m >= 4 else y - 1
    q = {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3,
         1: 4, 2: 4, 3: 4}[m]
    return fy, q


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "")


# --- Retrieval (hybrid semantic search) -------------------------------------
# Dense embeddings run on CPU via fastembed (ONNX); corpus vectors are precomputed
# and committed under INDEX_DIR, so only the query is embedded at runtime. Hybrid
# search fuses BM25 + dense via Reciprocal Rank Fusion. Everything degrades to
# BM25 (then keyword) when the libs/vectors are missing — mirrors SENPAI_USE_LLM.
EMBED_MODEL = os.environ.get(
    "SENPAI_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
# Dense layer on by default; set SENPAI_USE_EMBEDDINGS=0 for a hermetic BM25-only run
# (tests / no-network CI). semantic.py still no-ops dense if fastembed/vectors absent.
USE_EMBEDDINGS = _env_bool("SENPAI_USE_EMBEDDINGS", True)
USE_RERANKER = _env_bool("SENPAI_USE_RERANKER", False)   # optional cross-encoder, off by default
RRF_K = _env_int("SENPAI_RRF_K", 60)                     # Reciprocal Rank Fusion constant
# Fusion weights — dense carries more weight than lexical BM25 because, on these
# short Japanese notes, the embedding model is the stronger signal for paraphrases.
BM25_WEIGHT = _env_float("SENPAI_BM25_WEIGHT", 1.0)
DENSE_WEIGHT = _env_float("SENPAI_DENSE_WEIGHT", 3.0)

# --- Multimodal ingestion (senpai/ingestion) --------------------------------
# Audio (STT) and image (vision/OCR) run via an OpenAI-compatible *multimodal*
# endpoint — OPENAI_BASE_URL + OPENAI_API_KEY (e.g. Groq's free tier; the local
# exp3 is text-only). Model ids default to Groq's free models; override per env.
INGEST_BASE_URL = os.environ.get("OPENAI_BASE_URL")            # None → api.openai.com
INGEST_API_KEY = os.environ.get("OPENAI_API_KEY")
INGEST_AUDIO_MODEL = os.environ.get("INGEST_AUDIO_MODEL", "whisper-large-v3")
INGEST_VISION_MODEL = os.environ.get(
    "INGEST_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
INGEST_STRUCT_MODEL = os.environ.get(
    "INGEST_STRUCT_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")


def have_multimodal() -> bool:
    """True when a usable multimodal key is configured (not missing/placeholder)."""
    return bool(INGEST_API_KEY) and INGEST_API_KEY not in ("dummy", "")

# Fixed anchor used by data/gen_seed.py so the committed seed JSON is byte-stable
# no matter what day it is regenerated. Scoring uses today() (below), which on the
# authoring date equals this anchor.
REFERENCE_DATE = date(2026, 6, 16)


def today() -> date:
    """The 'current date' scoring reasons against. Override with SENPAI_TODAY
    for a perfectly reproducible demo against the committed seed."""
    raw = os.environ.get("SENPAI_TODAY")
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return date.today()


# --- Order-rank model (mirrors the production `deals.order_rank` values) -----
# The real SPR schema ranks every deal on this 8-point scale. We treat ranks 2–6
# as the live pipeline, 1 as won, and 7–8 as dead. Lower prefix number = stronger
# (closer to a confirmed order).
ORDER_RANKS = ["1_Confirmed", "2_A+", "3_A", "4_B", "5_C", "6_P", "7_Lost", "8_Cancelled"]
OPEN_RANKS = {"2_A+", "3_A", "4_B", "5_C", "6_P"}   # live pipeline
WON_RANKS = {"1_Confirmed"}
DEAD_RANKS = {"7_Lost", "8_Cancelled"}


def rank_num(order_rank: str | None) -> int:
    """Numeric prefix of an order_rank ('3_A' → 3); unknown/NULL → 99."""
    try:
        return int(str(order_rank).split("_", 1)[0])
    except (ValueError, AttributeError):
        return 99


def is_open_rank(order_rank: str | None) -> bool:
    return order_rank in OPEN_RANKS


# --- Deal-health scoring parameters (all tunable) ---------------------------
# Per-rank health benchmarks: (max healthy days at this rank, expected contact
# cadence in days). A deal sitting longer than the benchmark accrues risk points.
RANK_BENCHMARKS: dict[str, tuple[int, int]] = {
    "2_A+": (21, 7),
    "3_A":  (30, 10),
    "4_B":  (45, 14),
    "5_C":  (60, 21),
    "6_P":  (60, 21),
}

# Ranks strong enough that a decision-maker really should be identified by now.
DECISION_MAKER_RANKS = {"2_A+", "3_A", "4_B"}

# Titles in sales_activities.business_card_info that count as a decision-maker contact.
DECISION_MAKER_TITLES = ["社長", "代表", "取締役", "役員", "本部長", "部長", "課長",
                         "責任者", "マネージャー", "CIO", "情シス長"]

# Ranks the rep is signalling as likely to close — used for the optimism-mismatch
# reliability flag (strong rank but red health = report doesn't match reality).
OPTIMISTIC_RANKS = {"2_A+", "3_A"}

# Japanese stall lexicon — phrases that, in the latest daily_report, signal a stall.
STALL_LEXICON = ["検討します", "予算が", "時期を見て", "上と相談", "持ち帰り", "また連絡", "見送り", "様子見"]

# Words that, when present in a note, mean a competitor is in play (a *factor* the
# rep should reason about, not a gap). Used by the Sales Review Coach.
COMPETITION_LEXICON = ["競合", "他社", "相見積", "コンペ", "比較中", "比較検討", "リプレイス", "切り替え"]

# Risk-score band thresholds (score is 0–100, higher = worse).
RED_THRESHOLD = 55      # score >= 55  → red
YELLOW_THRESHOLD = 25   # 25 <= score < 55 → yellow ; < 25 → green


def band_for_score(score: int) -> str:
    """Map a 0–100 risk score to a traffic-light band."""
    if score >= RED_THRESHOLD:
        return "red"
    if score >= YELLOW_THRESHOLD:
        return "yellow"
    return "green"
````

## File: senpai/tools/schemas.py
````python
"""OpenAI function-calling schemas for Senpai's sales tools.

Same shape as demo/tools.py's TOOLS. These are the capabilities the junior
assistant (exp3) can call; every one is backed by the deterministic store /
scoring engine in senpai.tools.impl.
"""
from __future__ import annotations

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_spr",
            "description": "Look up deals and recent notes from the sales pipeline (SPR) "
                           "by customer name/ID or rep ID. Use this to prepare for a visit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Customer name or ID (e.g. 'アクメ商事' or 'C01')"},
                    "rep_id": {"type": "string", "description": "Rep ID, e.g. 'R05'"},
                    "deal_id": {"type": "string", "description": "Specific deal ID, e.g. 'D012'"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_deals",
            "description": "Grounded faceted search over real past/current deals. Filters by any "
                           "combination of: product_category, customer industry, customer size, "
                           "outcome (won/lost/open), order_rank, amount band, or a product code — "
                           "and reports the win/lost/open breakdown of the matches. Use this to "
                           "answer 'show me past <category> deals at <size>/<industry> companies "
                           "and how they went' BEFORE giving advice, so the answer is from data. "
                           "Filter values must be real values present in the data; if a filter "
                           "matches nothing, the tool lists the valid values to use.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_category": {"type": "string", "description": "Deal product category, e.g. 'サーバー', 'ソフトウェア', 'ネットワーク機器' (substring ok)"},
                    "industry": {"type": "string", "description": "Customer industry, e.g. '製造', '医療' (substring ok)"},
                    "size": {"type": "string", "description": "Customer size band, e.g. '中規模', '小規模'"},
                    "outcome": {"type": "string", "description": "'won', 'lost', or 'open' (derived from order_rank)"},
                    "order_rank": {"type": "string", "description": "Exact/substring order_rank, e.g. '3_A'"},
                    "min_amount": {"type": "number", "description": "Minimum total_order_amount (¥)"},
                    "max_amount": {"type": "number", "description": "Maximum total_order_amount (¥)"},
                    "product_code": {"type": "string", "description": "A specific product code the deal includes, e.g. 'MON27'"},
                    "limit": {"type": "integer", "description": "Max deals to list (default 10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_similar_deals",
            "description": "Find comparable past deals for a new or thin customer, matched on "
                           "industry, size and profile tags. Useful when the customer has little history.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Customer name or ID"},
                    "industry": {"type": "string", "description": "Industry (e.g. '製造', '医療')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_playbook",
            "description": "Retrieve senior reps' tactical advice for a situation, by keywords or "
                           "tags (e.g. '決定先延ばし', '値引き'). Returns attributed snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The situation in natural language"},
                    "tags": {"type": "array", "items": {"type": "string"},
                             "description": "Optional situation tags to match"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "Semantic search across CRM daily reports (日報) ONLY — not the "
                           "user's local files. Finds notes that mean the same thing as the "
                           "query even when worded differently (e.g. '予算が理由で停滞' also "
                           "surfaces 'コスト面で渋い'). ALWAYS pass `customer` (the account in "
                           "focus) for any account-specific question — this restricts the "
                           "search to that customer's own notes. Omit `customer` ONLY for "
                           "deliberate cross-account research; results then span all customers "
                           "and are labelled as such. If this comes back thin/generic, or the "
                           "user's phrasing could mean an actual document (e.g. names a file, "
                           "says 'the notes', 'the doc', or asks to add/edit/apply something "
                           "INTO them), also call search_workspace_documents — the real notes "
                           "may live in a local file, not a daily report.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for, in natural language"},
                    "customer": {"type": "string", "description": "The account in focus (name or ID). "
                                 "Scopes the search to this customer's notes. Pass it whenever the "
                                 "question is about a specific account."},
                    "limit": {"type": "integer", "description": "Max notes to return (default 5)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_customer_environment",
            "description": "Get the customer's IT environment record (PCs, OS, network) — the "
                           "handoff information a rep needs before a technical visit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Customer name or ID"},
                },
                "required": ["customer"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product_info",
            "description": "Get specs, price and a manual excerpt for a product by SKU or name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product": {"type": "string", "description": "Product SKU (e.g. 'MFP30') or name"},
                },
                "required": ["product"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "score_deal_health",
            "description": "Assess a deal's health: returns a red/yellow/green band, a risk score "
                           "and the concrete reasons behind it. Use to judge if a deal is really on track.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string", "description": "Deal ID, e.g. 'D012'"},
                },
                "required": ["deal_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "review_sales_note",
            "description": "Coach a junior on a raw meeting note or daily report. Returns what an "
                           "experienced rep would notice, missing info, risk signals, questions to ask "
                           "next, several possible next moves, and decision factors — it teaches "
                           "reasoning and never gives a single 'correct answer'. Pass the note text; "
                           "add deal_id to fold in that deal's structured signals.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "The meeting note / daily report text to review"},
                    "deal_id": {"type": "string", "description": "Optional related deal ID, e.g. 'D012'"},
                },
                "required": ["note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_daily_report",
            "description": "Draft an SPR-ready daily sales report (日報) in Japanese from a short "
                           "activity description and optional deal ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "activity": {"type": "string", "description": "What happened today, in natural language"},
                    "deal_id": {"type": "string", "description": "Related deal ID, if any"},
                },
                "required": ["activity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "route_to_expert",
            "description": "Find the right senior/expert rep to escalate a question to, matched on "
                           "their specialty tags, and draft a short intro message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to escalate"},
                    "tags": {"type": "array", "items": {"type": "string"},
                             "description": "Topic tags (e.g. 'ネットワーク', 'サーバー')"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_reports",
            "description": "Summarize a rep's recent reports and surface report-reliability flags "
                           "(stale/optimistic/missing-field deals). Manager-facing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rep_id": {"type": "string", "description": "Rep ID, e.g. 'R05'"},
                },
                "required": ["rep_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_seasonal_context",
            "description": "Get Japanese fiscal-year budget-timing context (the year ends in March) "
                           "to advise on close-timing and budget conversations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "month": {"type": "integer", "description": "Month number 1-12 (default: current)"},
                },
                "required": [],
            },
        },
    },
    # --- Manager + shared tools ---------------------------------------------
    {
        "type": "function",
        "function": {
            "name": "morning_briefing",
            "description": "The rep's prioritized to-do for today: their open deals ranked by "
                           "urgency × value, each with ONE concrete next action (e.g. follow up, "
                           "identify the decision-maker, re-confirm the close date). Includes a "
                           "predictive nudge for deals about to breach their contact cadence. "
                           "Omit rep_id for a whole-team view. Use this to answer 'what should I "
                           "do today?' / '今日やるべきことは?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rep_id": {"type": "string", "description": "Rep ID to brief, e.g. 'R12'. Omit for the whole team."},
                    "limit": {"type": "integer", "description": "Max actions to return (default 10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_at_risk_deals",
            "description": "List at-risk open deals across the whole team (or one rep), worst first. "
                           "Each line shows the owner, customer, risk score and the top reason. "
                           "Defaults to red deals; pass band='yellow' to include yellow too.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rep_id": {"type": "string", "description": "Optional rep ID to limit to one rep, e.g. 'R05'"},
                    "band": {"type": "string", "description": "'red' (default), 'yellow' (red+yellow), or 'green'"},
                    "limit": {"type": "integer", "description": "Max deals to return (default 10)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "team_pipeline_overview",
            "description": "Team pipeline at a glance: open-deal count, total ¥ value, breakdown by "
                           "stage, red/yellow/green health split, and number of flagged reports.",
            "parameters": {
                "type": "object",
                "properties": {
                    "rep_id": {"type": "string", "description": "Optional rep ID to scope to one rep"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "team_report_digest",
            "description": "Digest every rep's open deals into one manager view: the flagged/stale/"
                           "optimistic deals grouped by rep, worst first. Use to review the whole team at once.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rep_coaching_focus",
            "description": "Per-rep rollup (deal count, at-risk count, flagged count, average risk), sorted "
                           "so the reps who need coaching attention come first.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "draft_message",
            "description": "Draft a short, editable Japanese message (a nudge to a rep or a client "
                           "follow-up). Pulls deal context when a deal_id is given. Never sends — the human edits and sends.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient name, e.g. '伊藤さん' or a client"},
                    "about": {"type": "string", "description": "What the message is about"},
                    "deal_id": {"type": "string", "description": "Optional related deal ID for context"},
                    "purpose": {"type": "string", "description": "Optional purpose, e.g. '進捗確認'"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for external information (industry trends, company/customer news, "
                           "competitor info). Use for facts not in the internal data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "A short keyword search query (a few words, "
                                                                "like a search-engine query) — NOT the user's "
                                                                "full question or instructions verbatim."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_research",
            "description": "Research the open web by ACTUALLY VISITING pages (a real crawler), then "
                           "answer grounded in what was on them. Auto-routes on the input: (a) a "
                           "website URL or bare domain → crawls that site and returns a pre-call "
                           "intel brief (company overview, products, recent news, IR/財務 docs, "
                           "talking points); (b) a question with no URL (e.g. '築地の営業会社トップ5') "
                           "→ web-searches it, crawls the top result sites, and answers with source "
                           "URLs. Every claim carries a source link. Prefer this over web_search "
                           "when the user pastes a URL or wants real page content, not just snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "input": {"type": "string",
                              "description": "A website URL (e.g. 'https://www.example.co.jp') OR a "
                                             "research question (e.g. '築地の営業支援会社を教えて')"},
                    "max_pages": {"type": "integer",
                                  "description": "Max pages per site to visit (default 6, capped at 12)"},
                    "max_sites": {"type": "integer",
                                  "description": "For a question: how many distinct sites to crawl (default 3, max 5)"},
                },
                "required": ["input"],
            },
        },
    },
    # --- Knowledge RAG + sales-action tools (ported from demo/tools.py) -------
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search the validated internal knowledge corpus — senior-rep "
                           "principles, approved coaching cases and the playbook — for advice "
                           "grounded in real interviews. Returns short attributed/cited snippets. "
                           "Prefer this over web_search for 'how should I handle…' questions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The situation in natural language"},
                    "tags": {"type": "array", "items": {"type": "string"},
                             "description": "Optional situation tags (e.g. '値引き', '決定先延ばし')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_solutions",
            "description": "Search Otsuka Shokai's real product/solution pages for what to offer "
                           "a customer — named products/services with a short description, each "
                           "cited by source URL. Use this for 'what should we propose/recommend' "
                           "questions; prefer search_products instead when the rep needs a SKU "
                           "price lookup, not a solution pitch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "The customer's need/problem or product category, in natural language"},
                    "category": {"type": "string",
                                 "description": "Optional: restrict to a URL-derived category substring (e.g. 'security', 'cad')"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search the Otsuka product catalog by category, price range, or keyword. "
                           "Returns matching products with code, name and unit price (JPY). "
                           "IMPORTANT: If the first 1-2 attempts return no results, STOP retrying with "
                           "synonym keywords — the catalog is limited. Instead call get_product_info "
                           "or find_deals to find relevant products. Do NOT spray dozens of keyword variants.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string",
                                 "description": "Category term to match (e.g. '複合機', 'サーバー', 'PC')"},
                    "max_price": {"type": "number", "description": "Maximum unit price in JPY"},
                    "min_price": {"type": "number", "description": "Minimum unit price in JPY"},
                    "keyword": {"type": "string", "description": "Free-text term to match in name/specs"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_quote",
            "description": "Build a price quote (estimate) for one or more catalog products: line "
                           "totals, optional discount, tax and grand total. A draft — never sent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Products to quote.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sku": {"type": "string", "description": "Product code or name"},
                                "qty": {"type": "integer", "description": "Quantity"},
                            },
                            "required": ["sku", "qty"],
                        },
                    },
                    "discount_pct": {"type": "number", "description": "Discount percent on the subtotal (0-100)"},
                    "customer": {"type": "string", "description": "Customer/company name for the header"},
                    "tax_pct": {"type": "number", "description": "Sales-tax percent (default 10)"},
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_meeting",
            "description": "Book a meeting on the calendar directly in one step. "
                           "Call with confirm=true; do not ask the rep for a second confirmation turn. Resolve "
                           "relative dates to YYYY-MM-DD first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Meeting title"},
                    "date": {"type": "string", "description": "Date as YYYY-MM-DD"},
                    "start_time": {"type": "string", "description": "Start time as 24h HH:MM (JST)"},
                    "duration_hours": {"type": "number", "description": "Length in hours (default 1)"},
                    "attendees": {"type": "array", "items": {"type": "string"},
                                  "description": "Attendee names or emails"},
                    "description": {"type": "string", "description": "Optional agenda/notes"},
                    "confirm": {"type": "boolean",
                                "description": "Always set true; actually books the event in this turn."},
                },
                "required": ["title", "date", "start_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Prepare an email draft to a recipient. Never actually sends — the human "
                           "edits and sends. Use for follow-ups / quote delivery messages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient name or email address"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_calendar",
            "description": "Get the schedule for a given day (YYYY-MM-DD or 'today') from the real Google Calendar (falls back to simulated data if calendar auth is unavailable).",
            "parameters": {
                "type": "object",
                "properties": {
                    "day": {"type": "string", "description": "Date as YYYY-MM-DD or 'today'"},
                },
                "required": ["day"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_graph",
            "description": "Answer relational, multi-hop questions over the sales knowledge graph "
                           "(customer→deal→activity→rep→product) that simple lookups can't. Intents: "
                           "'reps_who_win' (who has the best win-rate on deals filtered by category / "
                           "industry / activity type — e.g. 'reps who win サーバー deals in 製造業 after "
                           "a site survey'); 'account' (one customer's whole deal/rep/product network); "
                           "'connections' (how two entities are linked); 'similar' (deals related to a "
                           "deal_id by shared rep/product/industry).",
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string",
                               "description": "'reps_who_win' | 'account' | 'connections' | 'similar'"},
                    "category": {"type": "string", "description": "Product category filter, e.g. 'サーバー'"},
                    "industry": {"type": "string", "description": "Customer industry filter, e.g. '製造'"},
                    "after_activity_type": {"type": "string",
                                            "description": "Require deals that had this activity type, e.g. '001_Scheduled'"},
                    "customer": {"type": "string", "description": "Customer name/ID (intent='account')"},
                    "deal_id": {"type": "string", "description": "Deal ID (intent='similar'), e.g. 'D012'"},
                    "entity_a": {"type": "string", "description": "First entity (intent='connections')"},
                    "entity_b": {"type": "string", "description": "Second entity (intent='connections')"},
                    "limit": {"type": "integer", "description": "Max rows (default 8)"},
                },
                "required": ["intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "segment_intelligence",
            "description": "Answer AGGREGATE / thematic / portfolio questions across market "
                           "segments (product category × customer industry) that per-deal or "
                           "per-account lookups can't: win rates, the common FAILURE MODES "
                           "behind lost deals, and the recommended play per segment. Use for "
                           "questions like 'なぜ製造業のサーバー案件は負ける？', 'common failure "
                           "modes across our lost deals', 'which segment loses most and why', "
                           "'どのカテゴリの勝率が低い？'. Each segment answer is grounded in real "
                           "tallies from the deal-health engine and cites the evidence deal ids. "
                           "Pass category and/or industry to focus; omit both for a portfolio "
                           "overview.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "The manager's thematic question (used to pick relevant segments)"},
                    "category": {"type": "string", "description": "Product category filter, e.g. 'サーバー'"},
                    "industry": {"type": "string", "description": "Customer industry filter, e.g. '製造業'"},
                    "outcome": {"type": "string", "description": "'won' | 'lost' | 'all' (default 'all') — nudges ranking"},
                    "limit": {"type": "integer", "description": "Max segments to return (default 6)"},
                },
                "required": ["query"],
            },
        },
    },
    # --- Document generation: the chatbot's "do stuff" tools ------------------
    {
        "type": "function",
        "function": {
            "name": "generate_proposal",
            "description": "Generate a persuasive PowerPoint (.pptx) SALES PROPOSAL for a "
                           "specific deal, grounded in its SPR data. It follows a full "
                           "proposal arc (background → challenges → solution → ROI → next "
                           "steps), mapping the customer's real pain points against the "
                           "deal's real financials, quote, and same-category comparable "
                           "deals — persuasive framing, grounded numbers. Builds the file "
                           "directly in one call (no confirmation step). Use when the rep "
                           "asks to make a proposal/提案書 deck for a deal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string", "description": "The deal to build the proposal for, e.g. 'D012'"},
                    "lang": {"type": "string", "description": "'ja' (default) or 'en'"},
                    "confirm": {"type": "boolean",
                                "description": "Always set true; creates the file immediately in this turn."},
                },
                "required": ["deal_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_ringisho",
            "description": "Generate a formal Japanese internal-approval document (稟議書) as "
                           "a Word file (.docx) for a specific deal, written from the "
                           "customer's IT-manager persona pitching their own CEO, using the "
                           "deal's real financials to justify solving the SPR-logged pain "
                           "points. Builds and saves the file directly in one call with "
                           "confirm=true. Use when the rep asks "
                           "for a 稟議書 / approval document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string", "description": "The deal to build the 稟議書 for, e.g. 'D012'"},
                    "confirm": {"type": "boolean",
                                "description": "Always set true; creates the file immediately in this turn."},
                },
                "required": ["deal_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_pptx",
            "description": "Generate a general-purpose PowerPoint (.pptx) on ANY topic from a "
                           "natural-language prompt — not tied to a deal. The deck is authored "
                           "by the model and can be about anything (e.g. 'make a deck about "
                           "GTA 6'); no fixed slide count. Grounding is automatic: external/"
                           "factual topics (products, prices, 'best-of', comparisons, current "
                           "models) are web-grounded by default, and a customer grounds it in "
                           "internal records — you normally do NOT set use_web. Builds the file "
                           "directly in one call (no confirmation step). Use generate_proposal "
                           "instead for a deal-specific sales proposal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "What the presentation should be about"},
                    "title": {"type": "string", "description": "Optional title override"},
                    "use_web": {"type": "boolean", "description": "Override web grounding. Omit to auto-decide (external/factual topics are web-grounded automatically). Set false to force the model's own knowledge; true to force a web search."},
                    "customer": {"type": "string", "description": "Optional customer name/ID to ground the deck in internal records"},
                    "lang": {"type": "string", "description": "'ja' (default) or 'en'"},
                    "confirm": {"type": "boolean",
                                "description": "Always set true; creates the file immediately in this turn."},
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_docx",
            "description": "Generate a general-purpose Word document (.docx) on ANY topic from "
                           "a natural-language prompt — not tied to a deal. Authored by the "
                           "model; can be about anything. Grounding is automatic: external/"
                           "factual topics are web-grounded by default, and a customer grounds "
                           "it in internal records — you normally do NOT set use_web. Builds the "
                           "file directly in one call (no confirmation step). Use "
                           "generate_ringisho instead for a deal-specific 稟議書.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "What the document should be about"},
                    "title": {"type": "string", "description": "Optional title override"},
                    "use_web": {"type": "boolean", "description": "Override web grounding. Omit to auto-decide (external/factual topics are web-grounded automatically). Set false to force the model's own knowledge; true to force a web search."},
                    "customer": {"type": "string", "description": "Optional customer name/ID to ground the document in internal records"},
                    "lang": {"type": "string", "description": "'ja' (default) or 'en'"},
                    "confirm": {"type": "boolean",
                                "description": "Always set true; creates the file immediately in this turn."},
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_workspace_documents",
            "description": "Find and READ relevant local documents (PDF, DOCX, PPTX, "
                           "XLSX, TXT, Markdown) from the user's sandboxed workspace "
                           "folder, and return their text with per-file citations. Use "
                           "when the answer may live in the user's own files (a proposal "
                           "deck, meeting notes, a spreadsheet, a PDF) rather than the CRM "
                           "or the web — e.g. 'what did we send Endo Kogyo?', 'summarize my "
                           "notes on this account'. Read-only; never edits or deletes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "What to look for; matched against file names/paths. Empty returns the most recent documents."},
                    "limit": {"type": "integer",
                              "description": "Max documents to read (default/cap set by the server)."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_workspace_document",
            "description": "Create or modify a local text document (e.g. .txt, .md, .csv, .json) in the user's workspace. "
                           "This is the ONLY way to actually persist something into a local file — if the user asks to "
                           "add/append/apply/update/edit/save/反映/追加/適用/編集 information INTO a file or notes you "
                           "already found (e.g. via search_workspace_documents), you MUST call this tool with the full "
                           "merged content, not just describe the merge in your chat answer — never claim something was "
                           "saved or applied unless this tool actually ran. "
                           "Pass confirm=True and commit the write immediately; do not ask for a second confirmation turn.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The absolute path or relative path from the workspace to save the file."},
                    "content": {"type": "string", "description": "The text content to write into the file."},
                    "confirm": {"type": "boolean", "description": "Always set true; writes the file immediately."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_workspace_document",
            "description": "Move or rename a local document in the user's workspace. "
                           "Pass confirm=True and commit the move immediately; do not ask for a second confirmation turn. "
                           "Can be used to organize all types of files, including PDFs and PPTXs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string", "description": "The current path of the file."},
                    "dst": {"type": "string", "description": "The new path for the file."},
                    "confirm": {"type": "boolean", "description": "Always set true; moves the file immediately."},
                },
                "required": ["src", "dst"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "advise_solutions",
            "description": "Recommend appropriate Otsuka solutions for a customer based on their context (expansion signals, environment gaps, and category). Use this when asked 'what should I propose?' or to generate a list of targeted solution recommendations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string", "description": "Customer name or ID to get recommendations for"},
                    "deal_id": {"type": "string", "description": "Optional specific deal ID to focus recommendations around"},
                },
                "required": ["customer"],
            },
        },
    },
]


# --- Role-scoped tool subsets ----------------------------------------------
# Each front end passes its own list to stream_turn(). Built by name from TOOLS
# so a schema is defined exactly once.
_BY_NAME = {t["function"]["name"]: t for t in TOOLS}


def _pick(*names: str) -> list[dict]:
    return [_BY_NAME[n] for n in names]


# Junior assistant: the in-context coaching tools + web_search.
# (review_sales_note is intentionally excluded — it bridges to the friend-owned
#  coach experiment and is kept out of our chat surface for isolation.)
JUNIOR_TOOLS = _pick(
    "query_spr", "find_deals", "find_similar_deals", "retrieve_playbook", "search_knowledge",
    "search_solutions",
    "search_notes", "lookup_customer_environment", "get_product_info", "search_products",
    "create_quote", "score_deal_health", "draft_daily_report", "schedule_meeting",
    "send_email", "get_calendar", "route_to_expert", "morning_briefing",
    "get_seasonal_context", "web_search", "web_research", "search_workspace_documents", "edit_workspace_document", "move_workspace_document",
    "generate_proposal", "generate_ringisho", "generate_pptx", "generate_docx", "advise_solutions",
)

# Manager: team analytics + drill-down + drafting + semantic/graph search + web.
MANAGER_TOOLS = _pick(
    "query_spr", "find_deals", "score_deal_health", "morning_briefing", "list_at_risk_deals",
    "team_pipeline_overview", "team_report_digest", "rep_coaching_focus",
    "search_knowledge", "search_solutions", "search_notes", "query_graph", "segment_intelligence", "search_products",
    "create_quote", "schedule_meeting",
    "send_email", "get_calendar", "draft_message", "web_search", "web_research", "search_workspace_documents", "edit_workspace_document", "move_workspace_document",
    "generate_proposal", "generate_ringisho", "generate_pptx", "generate_docx", "advise_solutions",
)

# Research assistant ("tell me about this customer"): read-only lookups, internal
# first, with web_search to fill external gaps. No drafting/coaching tools — this
# is a grounded research surface, not a generic chat. Order mirrors the intended
# source priority (internal records → deal signals → web).
RESEARCH_TOOLS = _pick(
    "query_spr", "find_deals", "find_similar_deals", "score_deal_health", "search_notes",
    "lookup_customer_environment", "get_product_info", "search_solutions", "segment_intelligence",
    "get_seasonal_context", "web_search", "web_research", "search_workspace_documents", "edit_workspace_document", "move_workspace_document",
)
````

## File: senpai/tools/impl.py
````python
"""Tool implementations + dispatch — mirrors demo/tools.py's contract.

Every executor returns a SHORT string (what the model sees as the tool result)
and `dispatch` never raises, so the chat loop can't crash. All data comes from
the deterministic store / scoring engine, so these run GPU-free.

`python -m senpai.tools.impl` runs a canned call per tool (smoke test).
"""
from __future__ import annotations

import json
import re

from senpai import config
from senpai.data import store
from senpai.health.flags import deal_flags
from senpai.health.scoring import score_deal
from senpai.retrieval.knowledge import search_knowledge as _search_knowledge
from senpai.retrieval.playbook import find_similar_deals, retrieve_playbook
from senpai.tools.focus import session_focus
from senpai.tools.web import web_search
from senpai.tools.crawl import web_research


def _score_open_deals(rep_id: str = ""):
    """Score every open deal once (optionally limited to one rep). Returns a list
    of (deal, HealthResult, flags) — the shared backbone for the manager
    analytics tools and summarize_reports, so the scoring loop lives in one place."""
    deals = store.deals_for_rep(rep_id) if rep_id else store.open_deals()
    out = []
    for d in deals:
        if not config.is_open_rank(d.get("order_rank")):
            continue
        acts = store.activities_for_deal(d["deal_id"])
        res = score_deal(d, acts)
        flags = deal_flags(d, acts, health_band=res.band)
        out.append((d, res, flags))
    return out


def _resolve_customer(customer: str) -> dict | None:
    """Alias-aware: resolves JA / English / romaji / known-alias forms (e.g.
    'Aozora Services' -> あおぞらサービス) before any retrieval."""
    if not customer:
        return None
    return store.resolve_customer(customer)


def _deal_line(d: dict) -> str:
    # The deal_name (e.g. "藤本食品 複合機案件") and product_category are what let the
    # model pick the deal the rep actually named — a request for "複合機案件" must not
    # silently resolve to the biggest open deal. The name already carries the customer.
    cust = store.customer_name(d["customer_id"])
    label = (d.get("deal_name") or "").strip() or cust
    cat = (d.get("product_category") or "").strip()
    if cat:
        label = f"{label}（{cat}）"
    return (f"{d['deal_id']} {label} / 担当{store.rep_name(store.deal_rep_id(d))} / "
            f"{d['order_rank']} / ¥{d['total_order_amount']:,} / "
            f"完了予定{d['expected_order_date']}")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
def query_spr(customer: str = "", rep_id: str = "", deal_id: str = "") -> str:
    if deal_id:
        d = store.get_deal(deal_id)
        if not d:
            return f"案件 {deal_id} は見つかりません。"
        acts = store.activities_for_deal(deal_id)
        head = _deal_line(d)
        act_lines = [f"  ・{a['activity_date']} [{a['activity_type']}] {a['daily_report']}"
                     for a in acts[:3]]
        return head + ("\n直近の活動:\n" + "\n".join(act_lines) if act_lines else "")

    if customer:
        c = _resolve_customer(customer)
        if not c:
            return f"顧客「{customer}」は見つかりません。"
        deals = store.deals_for_customer(c["customer_id"])
        if not deals:
            return f"{c['name']} の案件はありません。"
        lines = [_deal_line(d) for d in deals]
        return f"{c['name']} の案件 {len(deals)}件:\n- " + "\n- ".join(lines)

    if rep_id:
        deals = store.deals_for_rep(rep_id)
        if not deals:
            return f"担当 {rep_id} の案件はありません。"
        lines = [_deal_line(d) for d in deals]
        return f"{store.rep_name(rep_id)} の案件 {len(deals)}件:\n- " + "\n- ".join(lines)

    return "customer / rep_id / deal_id のいずれかを指定してください。"


def find_deals(product_category: str = "", industry: str = "", size: str = "",
               outcome: str = "", order_rank: str = "", min_amount=None,
               max_amount=None, product_code: str = "", limit: int = 10) -> str:
    """Grounded faceted search over real past/current deals. Filters the actual SPR
    fields (deal product_category / order_rank / amount / product code, customer
    industry / size) and reports the win/lost/open breakdown of the matches, so the
    model answers 'show me past <category> deals at <size>/<industry> companies and
    how they went' from data — never from invention."""
    from senpai.retrieval.deals import deal_facets, find_deals as _find, outcome_breakdown
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    all_hits = _find(product_category=product_category, industry=industry, size=size,
                     outcome=outcome, order_rank=order_rank, min_amount=min_amount,
                     max_amount=max_amount, product_code=product_code, limit=0)
    cond = "／".join(str(x) for x in [product_category, industry, size, outcome,
                                      order_rank, product_code] if x) or "全条件"
    if not all_hits:
        f = deal_facets()
        return ("条件に合う案件は見つかりませんでした。指定可能な値:\n"
                f"- 商品カテゴリ: {'、'.join(f['product_category'])}\n"
                f"- 業種: {'、'.join(f['industry'])}\n"
                f"- 規模: {'、'.join(f['size'])}\n"
                f"- 受注ランク: {'、'.join(f['order_rank'])}\n"
                "- 結果(outcome): won / lost / open")
    bd = outcome_breakdown(all_hits)
    head = (f"該当案件【{cond}】{len(all_hits)}件 "
            f"(受注{bd['won']}／失注{bd['lost']}／進行中{bd['open']}):")
    lines = []
    for d in all_hits[:limit]:
        cust = store.get_customer(d["customer_id"]) or {}
        lines.append(f"{d['deal_id']} {store.customer_name(d['customer_id'])}"
                     f"（{cust.get('industry', '-')}/{cust.get('size', '-')}）"
                     f" {d.get('product_category', '-')} / {d.get('order_rank', '-')}"
                     f" / ¥{d.get('total_order_amount', 0):,}")
    return head + "\n- " + "\n- ".join(lines)


def find_similar_deals_tool(customer: str = "", industry: str = "") -> str:
    cid = ""
    if customer:
        c = _resolve_customer(customer)
        if c:
            cid = c["customer_id"]
    hits = find_similar_deals(customer_id=cid, industry=industry)
    if not hits:
        return "類似案件は見つかりませんでした。"
    lines = [_deal_line(d) for d in hits]
    return "類似案件:\n- " + "\n- ".join(lines)


def retrieve_playbook_tool(query: str = "", tags=None) -> str:
    if isinstance(tags, str):
        tags = [tags]
    hits = retrieve_playbook(query=query, tags=tags or [])
    if not hits:
        return "該当するプレイブックがありません。route_to_expert の利用を検討してください。"
    lines = []
    for e in hits:
        entry_id = e.get("entry_id", "Unknown")
        lines.append(f"[{'/'.join(e['situation_tags'])}] {e['text']}(出典: Playbook {entry_id})")
    return "プレイブック:\n- " + "\n- ".join(lines)


def lookup_customer_environment(customer: str = "") -> str:
    c = _resolve_customer(customer)
    if not c:
        return f"顧客「{customer}」は見つかりません。"
    env = store.get_environment(c["customer_id"])
    if not env:
        return f"{c['name']} の環境情報は未登録です。"
    return (f"{c['name']} の環境: PC={env['pc']} / OS={env['os']} / "
            f"ネットワーク={env['network']} / 備考: {env['notes']}")


def get_product_info(product: str = "") -> str:
    p = store.get_product(product.upper()) if product else None
    if not p:
        p = next((x for x in store.all_products()
                  if product and product in x["product_name"]), None)
    if not p:
        names = ", ".join(x["product_name"] for x in store.all_products())
        return f"製品「{product}」は見つかりません。取扱: {names}"
    return (f"{p['product_name']} ({p['product_code']} / {p['manufacturer_model_number']}) "
            f"— ¥{p['standard_unit_price']:,}\n"
            f"分類: {p['major']} > {p['mid']} > {p['minor']}\n"
            f"仕様: {p['specs']}\nマニュアル抜粋: {p['manual_ja']}")


def score_deal_health(deal_id: str = "") -> str:
    d = store.get_deal(deal_id)
    if not d:
        return f"案件 {deal_id} は見つかりません。"
    acts = store.activities_for_deal(deal_id)
    res = score_deal(d, acts)
    emoji = {"red": "🔴", "yellow": "🟡", "green": "🟢"}[res.band]
    reasons = res.top_reasons(3)
    body = "／".join(reasons) if reasons else "目立ったリスク信号なし"
    return f"{emoji} {res.band}(リスク{res.score}/100): {body}"


def draft_daily_report(activity: str = "", deal_id: str = "") -> str:
    deal = store.get_deal(deal_id) if deal_id else None
    cust = store.customer_name(deal["customer_id"]) if deal else "(顧客未指定)"
    rank = deal["order_rank"] if deal else "-"
    next_action = "次回アクションを記入してください"
    if deal:
        res = score_deal(deal, store.activities_for_deal(deal_id))
        if res.band == "red":
            next_action = "健全度が赤。上長同席での再提案を打診"
    return ("【日報ドラフト】\n"
            f"顧客: {cust}\n"
            f"案件: {deal_id or '-'} / 受注ランク: {rank}\n"
            f"活動内容: {activity}\n"
            f"次アクション: {next_action}")


def review_sales_note(note: str = "", deal_id: str = "") -> str:
    """Bridge to the Sales Review Coach (a separate, friend-owned experiment under
    senpai.coach). Kept here only so the coach's own tests can reach it; it is NOT
    part of our chat tool surface. The coach is imported lazily so our pipeline's
    import graph never depends on it."""
    if not (note or "").strip():
        return "レビューするメモ・日報の本文を入力してください。"
    from senpai.coach.review import format_review, review_note   # lazy: keep us decoupled
    deal = store.get_deal(deal_id) if deal_id else None
    notes = store.notes_for_deal(deal_id) if deal else None
    report = store.report_for_deal(deal_id) if deal else None
    review = review_note(note, deal=deal, notes=notes, report=report)
    return format_review(review)


def route_to_expert(question: str = "", tags=None) -> str:
    if isinstance(tags, str):
        tags = [tags]
    tags = tags or []
    experts = [r for r in store.all_reps() if r["role"] in ("senior", "expert")]
    best, best_score = None, -1
    for r in experts:
        score = sum(1 for t in tags
                    if any(t in s or s in t for s in r["specialty_tags"]))
        score += sum(1 for s in r["specialty_tags"] if question and s in question)
        if r["is_top_performer"]:
            score += 0.5
        if score > best_score:
            best, best_score = r, score
    if not best:
        return "適切な担当が見つかりませんでした。"
    return (f"エキスパート紹介: {best['name']}({'/'.join(best['specialty_tags'])})\n"
            f"紹介メッセージ案: 「{best['name']}さん、{question} の件でご相談です。"
            "お手すきの際にご助言いただけますか。」")


def summarize_reports(rep_id: str = "") -> str:
    if not store.daily_reports_for_rep(rep_id):
        return f"担当 {rep_id} のレポートはありません。"
    scored = _score_open_deals(rep_id)
    lines = [f"{store.rep_name(rep_id)} のオープン案件 {len(scored)}件の要約:"]
    flagged = 0
    for d, _res, flags in scored:
        if flags:
            flagged += 1
            msgs = "／".join(f.message for f in flags[:2])
            lines.append(f"⚠ {d['deal_id']} {store.customer_name(d['customer_id'])}: {msgs}")
    lines.append(f"信頼性フラグの立った案件: {flagged}件")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Manager-facing analytics tools (all grounded in the deterministic engine)
# ---------------------------------------------------------------------------
_BAND_EMOJI = {"red": "🔴", "yellow": "🟡", "green": "🟢"}


def morning_briefing(rep_id: str = "", limit: int = 10) -> str:
    """The rep's prioritized next-best-action worklist for today (or the whole
    team if no rep). Thin wrapper over senpai.briefing."""
    from senpai.briefing import format_briefing
    from senpai.briefing import morning_briefing as _briefing
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    items = _briefing(rep_id=rep_id, limit=limit)
    return format_briefing(items, rep_id=rep_id)


def list_at_risk_deals(rep_id: str = "", band: str = "", limit: int = 10) -> str:
    """At-risk open deals across the team (or one rep), worst first. Defaults to
    red; pass band='yellow' (includes red+yellow) to widen."""
    scored = _score_open_deals(rep_id)
    if band == "yellow":
        keep = {"red", "yellow"}
    elif band in ("red", "green"):
        keep = {band}
    else:
        keep = {"red"}
    rows = sorted((t for t in scored if t[1].band in keep),
                  key=lambda t: t[1].score, reverse=True)
    if not rows:
        return "該当する要注意案件はありません。"
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    lines = []
    for d, res, _flags in rows[:limit]:
        reason = (res.top_reasons(1) or ["—"])[0]
        lines.append(f"{_BAND_EMOJI[res.band]} {d['deal_id']} "
                     f"{store.customer_name(d['customer_id'])} / 担当{store.rep_name(store.deal_rep_id(d))} / "
                     f"リスク{res.score} / {reason}")
    head = f"要注意案件 {len(rows)}件中 上位{min(limit, len(rows))}件:"
    return head + "\n- " + "\n- ".join(lines)


def team_pipeline_overview(rep_id: str = "") -> str:
    """Team pipeline at a glance: counts, ¥, stage spread, health split, flags."""
    scored = _score_open_deals(rep_id)
    if not scored:
        return "オープン案件がありません。"
    total = len(scored)
    pipeline = sum(d.get("total_order_amount", 0) for d, _, _ in scored)
    by_band = {"red": 0, "yellow": 0, "green": 0}
    by_rank: dict[str, int] = {}
    flagged = 0
    for d, res, flags in scored:
        by_band[res.band] += 1
        by_rank[d["order_rank"]] = by_rank.get(d["order_rank"], 0) + 1
        if flags:
            flagged += 1
    rank_str = "、".join(f"{r}:{n}" for r, n in sorted(by_rank.items()))
    scope = f"{store.rep_name(rep_id)} の" if rep_id else "チーム全体の"
    return (f"{scope}パイプライン概況:\n"
            f"- オープン案件: {total}件 / 想定金額: ¥{pipeline:,}\n"
            f"- 健全度: 🔴{by_band['red']} / 🟡{by_band['yellow']} / 🟢{by_band['green']}\n"
            f"- ランク別: {rank_str}\n"
            f"- 信頼性フラグの立った案件: {flagged}件")


def team_report_digest() -> str:
    """All reps' open deals digested into one manager view: flagged deals grouped
    by rep, worst first."""
    scored = _score_open_deals()
    by_rep: dict[str, list] = {}
    for d, res, flags in scored:
        if flags:
            by_rep.setdefault(store.deal_rep_id(d), []).append((d, res, flags))
    if not by_rep:
        return "信頼性フラグの立った案件はありません。チーム全体が健全です。"
    order = sorted(by_rep.items(), key=lambda kv: len(kv[1]), reverse=True)
    lines = [f"全担当の日報ダイジェスト（要注意 {sum(len(v) for v in by_rep.values())}件）:"]
    for rep_id, items in order:
        lines.append(f"\n【{store.rep_name(rep_id)}】フラグ{len(items)}件")
        for d, _res, flags in sorted(items, key=lambda t: t[1].score, reverse=True)[:5]:
            msg = (flags[0].message if flags else "—")
            lines.append(f"  ⚠ {d['deal_id']} {store.customer_name(d['customer_id'])}: {msg}")
    return "\n".join(lines)


def rep_coaching_focus() -> str:
    """Per-rep rollup so a manager sees where to spend coaching time."""
    scored = _score_open_deals()
    agg: dict[str, dict] = {}
    for d, res, flags in scored:
        a = agg.setdefault(store.deal_rep_id(d), {"deals": 0, "risk": 0, "red": 0, "flagged": 0})
        a["deals"] += 1
        a["risk"] += res.score
        if res.band == "red":
            a["red"] += 1
        if flags:
            a["flagged"] += 1
    if not agg:
        return "オープン案件がありません。"
    rows = sorted(agg.items(), key=lambda kv: (kv[1]["red"], kv[1]["flagged"]), reverse=True)
    lines = ["コーチング優先度（要注意の多い担当順）:"]
    for rep_id, a in rows:
        avg = round(a["risk"] / a["deals"]) if a["deals"] else 0
        lines.append(f"- {store.rep_name(rep_id)}: 案件{a['deals']} / "
                     f"🔴{a['red']} / フラグ{a['flagged']} / 平均リスク{avg}")
    return "\n".join(lines)


def draft_message(to: str = "", about: str = "", deal_id: str = "",
                  purpose: str = "") -> str:
    """Draft a short, editable Japanese message (rep nudge or client follow-up).
    Pulls deal context when deal_id is given. Never sends — human stays in the loop."""
    ctx = ""
    if deal_id:
        d = store.get_deal(deal_id)
        if d:
            res = score_deal(d, store.activities_for_deal(deal_id))
            ctx = (f"（{deal_id} {store.customer_name(d['customer_id'])} / {d['order_rank']} / "
                   f"健全度{_BAND_EMOJI[res.band]}{res.band}）")
    topic = about or purpose or "案件の状況確認"
    recipient = to or "担当者"
    body = (f"{recipient} 様\n\n"
            f"お疲れさまです。{topic} の件、現状を共有いただけますか。{ctx}\n"
            "次回の意思決定事項と完了予定日のすり合わせができればと思います。\n"
            "よろしくお願いいたします。")
    return f"【メッセージ下書き（送信はされません・編集してください）】\n{body}"


_FY_CONTEXT = {
    "q4": "1〜3月は年度末。予算消化の最後の好機。クロージングを強く。",
    "q1": "4〜6月は新年度。新規予算が付く時期。早期の種まきを。",
    "q2": "7〜9月は中間期。下期予算の検討が始まる。提案の仕込みを。",
    "q3": "10〜12月は下期序盤。年度末に向け案件を積み上げる時期。",
}


def get_seasonal_context(month: int = 0) -> str:
    m = int(month) if month else config.today().month
    if m in (1, 2, 3):
        key, label = "q4", "第4四半期(年度末)"
    elif m in (4, 5, 6):
        key, label = "q1", "第1四半期"
    elif m in (7, 8, 9):
        key, label = "q2", "第2四半期"
    else:
        key, label = "q3", "第3四半期"
    return f"{m}月 — {label}: {_FY_CONTEXT[key]}"


# ---------------------------------------------------------------------------
# Sales demo tools — ported from demo/tools.py, re-grounded on the real store
# ---------------------------------------------------------------------------
def _resolve_product(product: str) -> dict | None:
    """Resolve a product by code (e.g. 'MFP30') or a (fuzzy) name match."""
    if not product:
        return None
    p = store.get_product(str(product).strip().upper())
    if p:
        return p
    pl = str(product).strip().lower()
    for x in store.all_products():
        if pl == x["product_name"].lower():
            return x
    for x in store.all_products():
        if pl in x["product_name"].lower() or x["product_name"].lower() in pl:
            return x
    return None


def search_products(category: str = "", max_price: float = None,
                    min_price: float = None, keyword: str = "") -> str:
    """Search the real Otsuka product catalog by category / price band / keyword."""
    hits = []
    for p in store.all_products():
        cat = f"{p.get('major', '')} {p.get('mid', '')} {p.get('minor', '')}"
        if category and category.strip() not in cat:
            continue
        price = p.get("standard_unit_price", 0)
        if max_price is not None and price > float(max_price):
            continue
        if min_price is not None and price < float(min_price):
            continue
        if keyword:
            k = keyword.strip()
            if k not in p["product_name"] and k not in p.get("specs", ""):
                continue
        hits.append(p)
    if not hits:
        return "条件に合う製品は見つかりませんでした。"
    hits.sort(key=lambda p: p.get("standard_unit_price", 0))
    lines = [f"{p['product_code']} — {p['product_name']} — ¥{p['standard_unit_price']:,}"
             f"（{p.get('mid', p.get('major', ''))}）" for p in hits]
    return f"該当製品 {len(hits)}件:\n- " + "\n- ".join(lines)


def create_quote(items, discount_pct: float = 0, customer: str = "",
                 tax_pct: float = 10) -> str:
    """Build a price quote (estimate) from real catalog products: line totals,
    optional discount, tax, grand total. Never persisted — the rep edits/sends."""
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except json.JSONDecodeError:
            return "[error] 見積項目を解析できませんでした。"
    if not isinstance(items, list) or not items:
        return "[error] 見積する製品がありません。"
    lines, skipped, subtotal = [], [], 0
    for it in items:
        if not isinstance(it, dict):
            continue
        p = _resolve_product(it.get("sku") or it.get("name") or it.get("product") or "")
        qty = int(it.get("qty", 1) or 1)
        if not p:
            skipped.append(str(it.get("sku") or it.get("name") or it.get("product")))
            continue
        price = p.get("standard_unit_price", 0)
        line_total = price * qty
        subtotal += line_total
        lines.append(f"  {qty} × {p['product_name']} @ ¥{price:,} = ¥{line_total:,}")
    if not lines:
        return f"[error] 指定された製品が見つかりませんでした: {', '.join(skipped)}"
    discount_pct = float(discount_pct or 0)
    tax_pct = float(tax_pct if tax_pct is not None else 10)
    discount = round(subtotal * discount_pct / 100)
    taxed_base = subtotal - discount
    tax = round(taxed_base * tax_pct / 100)
    total = taxed_base + tax
    header = f"見積書（{customer}様）" if customer else "見積書"
    out = [f"【{header}・ドラフト／送信はされません】", "明細:", *lines,
           f"小計: ¥{subtotal:,}"]
    if discount:
        out.append(f"値引 ({discount_pct:g}%): -¥{discount:,}")
    out.append(f"消費税 ({tax_pct:g}%): ¥{tax:,}")
    out.append(f"合計: ¥{total:,}")
    if skipped:
        out.append(f"（未登録のため除外: {', '.join(skipped)}）")
    return "\n".join(out)


def schedule_meeting(title: str = "", date: str = "", start_time: str = "",
                     duration_hours: float = 1, attendees=None,
                     description: str = "", confirm: bool = True) -> str:
    """Book a meeting in one call by default. With confirm=true it books a
    real event via the Google Calendar API; if calendar auth/creds are missing it
    degrades to a simulated confirmation so the workspace never breaks."""
    if not (title and date and start_time):
        return "[error] title / date / start_time を指定してください。"
    if isinstance(attendees, str):
        attendees = [a.strip() for a in attendees.split(",") if a.strip()]
    attendees = attendees or []
    who = f" / 参加者{len(attendees)}名" if attendees else ""
    dur = float(duration_hours or 1)
    agenda = f"\n議題: {description}" if description else ""

    if not confirm:
        return (f"【予定ドラフト（未確定）】「{title}」{date} {start_time} JST "
                f"／{dur:g}時間{who}{agenda}"
                "\n確定する場合は confirm=true で再度依頼してください。")

    try:
        from senpai.tools import gcal  # lazy: a missing google lib must not break import
        ok, link = gcal.create_event(
            title=title, date=date, start_time=start_time, duration_hours=dur,
            attendees=attendees, description=description,
        )
        if ok:
            tail = f"\n{link}" if link else ""
            return (f"【予定を登録しました】「{title}」{date} {start_time} JST "
                    f"／{dur:g}時間{who}{agenda}{tail}")
    except Exception:  # noqa: BLE001 — fall back to a simulated confirmation
        pass
    return (f"【予定を登録しました（シミュレーション）】「{title}」{date} {start_time} JST "
            f"／{dur:g}時間{who}{agenda}")


def send_email(to: str = "", subject: str = "", body: str = "") -> str:
    """Prepare an email draft. Never actually sends — human stays in the loop."""
    if not to:
        return "[error] 宛先 (to) を指定してください。"
    return (f"【メール下書き（送信はされません）】\n宛先: {to}\n件名: {subject}\n\n{body}")


_CALENDAR_CANNED = [
    "10:00 朝礼／案件確認",
    "13:00 顧客訪問（デモ）",
    "16:30 提案資料の作成",
]


def get_calendar(day: str = "today") -> str:
    """Today's (or a given day's) schedule. Reads the real Google Calendar when
    auth/creds are available; otherwise degrades to simulated demo data."""
    d = config.today().isoformat() if str(day).lower() in ("today", "") else day
    try:
        from senpai.tools import gcal  # lazy: a missing google lib must not break import
        ok, events = gcal.list_events(d)
        if ok:
            if not events:
                return f"{d} の予定はありません。"
            return f"{d} の予定:\n- " + "\n- ".join(
                f"{e['start']} {e['summary']}" for e in events)
    except Exception:  # noqa: BLE001 — fall back to simulated data
        pass
    return f"{d} の予定（シミュレーション）:\n- " + "\n- ".join(_CALENDAR_CANNED)


def search_knowledge(query: str = "", tags=None, limit: int = 4) -> str:
    """RAG over the validated knowledge corpus (principles + approved coaching
    items + playbook). Returns short, attributed/cited snippets to ground answers."""
    if isinstance(tags, str):
        tags = [tags]
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 4
    hits = _search_knowledge(query=query, tags=tags or [], limit=limit)
    from senpai.retrieval import trace as _trace
    _trace.record(
        "knowledge_keyword", scope="all", query=query,  # corpus is general, not per-account
        items=[{"id": kind, "customer": None, "score": int(score), "text": text}
               for score, kind, text in hits])
    if not hits:
        return ("該当する社内ナレッジが見つかりませんでした。"
                "route_to_expert の利用を検討してください。")
    lines = [f"[{kind}] {text}" for _score, kind, text in hits]
    return "社内ナレッジ:\n- " + "\n- ".join(lines)


def search_solutions(query: str = "", category: str = "", limit: int = 4) -> str:
    """Search Otsuka Shokai's real product/solution pages for what to offer a
    customer — named products/services (not internal category labels), each
    cited with its source URL. Prefer this over search_products when the rep
    needs a solution pitch/description, not a SKU price lookup."""
    from senpai.retrieval.solution_knowledge import search_solution_knowledge
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 4
    filters = {"category": category} if category else None
    hits = search_solution_knowledge(query, filters=filters, limit=limit)
    from senpai.retrieval import trace as _trace
    _trace.record(
        "solution_knowledge", scope="all", query=query,
        items=[{"id": h["solution"]["category"], "customer": None,
                "score": h["solution"]["relevance"], "text": h["solution"]["summary"]}
               for h in hits])
    if not hits:
        return "該当するソリューション・製品情報が見つかりませんでした。"
    lines = [f"[{h['solution']['category']}] {h['solution']['name']}: "
             f"{h['solution']['summary']}（出典: {h['solution']['source']}）"
             for h in hits]
    return "ソリューション・製品情報:\n- " + "\n- ".join(lines)


def search_notes(query: str = "", limit: int = 5, customer: str = "") -> str:
    """Semantic search over the field's daily reports (日報). Finds activities that
    *mean* the same thing as the query, not just share keywords — e.g. a search for
    『予算が理由で停滞』 surfaces 「コスト面で渋い」notes too. Returns dated, attributed
    snippets with their deal/customer + retrieval score so the rep can drill in.

    Grounding P0 — account scoping: pass `customer` (the account in focus) to
    restrict the search to that customer's own notes (the default for any
    account-specific question). If `customer` is omitted, we still try to detect a
    customer named in the query and scope to it; only when no account can be
    resolved do we fall back to a cross-account search (clearly labelled). A scoped
    search never widens to other customers."""
    from senpai.retrieval.semantic import semantic_search
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 5
    # Clamp the result count: the notes are the bulk of the synthesis prompt AND of
    # what the model then quotes back, so an over-fetch (the model sometimes asks for
    # 10+) dominates Assistant latency at ~9 tok/s. The top semantically-ranked notes
    # carry the signal; the tail just lengthens the answer. Keep it tight.
    limit = max(1, min(limit, 6))

    # Resolve the account in focus: explicit arg first, then a customer named in the
    # query; None ⇒ no account resolved ⇒ cross-account fallback (preserves behavior).
    cust = None
    if customer:
        cust = store.resolve_customer(customer) or store.get_customer(customer)
    if not cust and query:
        cust = store.match_customer_in_text(query)
    cid = cust.get("customer_id") if cust else None

    from senpai.retrieval import semantic as _sem
    from senpai.retrieval import trace as _trace
    hits = semantic_search(query, corpus="activities", limit=limit, customer_id=cid)

    # Observability: record exactly what was retrieved (Retrieval Explorer spine).
    _trace.record(
        "notes_semantic",
        scope=(f"account:{cid}" if cid else "all"),
        query=query, mode=_sem.mode(),
        customer=(cust.get("name") if cust else None),
        items=[{"id": f"{h.get('deal_id', '-')}@{h.get('activity_date', '?')}",
                "customer_id": h.get("customer_id", ""),
                "customer": store.customer_name(h.get("customer_id", "")) or h.get("customer_id", ""),
                "score": round(float(h.get("score", 0)), 4),
                "text": h.get("snippet", "")} for h in hits])

    if not hits:
        if cid:
            return f"{cust.get('name', cid)} の日報で該当するものは見つかりませんでした。"
        return "該当する日報は見つかりませんでした。"

    scope = (f"（{cust.get('name')} に限定）" if cid
             else "（全社横断・特定顧客に絞れず）")
    lines = []
    for h in hits:
        cn = store.customer_name(h.get("customer_id", "")) or h.get("customer_id", "")
        lines.append(f"{h.get('activity_date', '?')}・{h.get('deal_id', '-')}（{cn}）"
                     f"[score {h.get('score', 0):.3f}]: {h.get('snippet', '')}")
    return f"関連する日報{scope}:\n- " + "\n- ".join(lines)


def query_graph(intent: str = "reps_who_win", category: str = "", industry: str = "",
                after_activity_type: str = "", customer: str = "", deal_id: str = "",
                entity_a: str = "", entity_b: str = "", limit: int = 8) -> str:
    """Multi-hop questions over the customer→deal→activity→rep→product graph.
    intent: 'reps_who_win' | 'account' | 'connections' | 'similar'."""
    from senpai.graph import query as gq
    from senpai.retrieval import trace as _trace
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 8
    # account intent is customer-scoped; the relational intents are cross-account
    # by design (and are research/manager-only per the governance table).
    _trace.record("graph", scope=(f"account:{customer}" if intent == "account" and customer else "all"),
                  intent=intent, query=" ".join(x for x in [category, industry, customer, deal_id] if x))

    if intent == "reps_who_win":
        rows = gq.reps_who_win(category=category, industry=industry,
                               after_activity_type=after_activity_type)[:limit]
        if not rows:
            return "条件に合う実績が見つかりませんでした。"
        cond = "／".join(x for x in [category, industry, after_activity_type] if x) or "全体"
        lines = [f"{r['rep_name']}（{r['rep_id']}）勝率{r['win_rate']*100:.0f}% "
                 f"（{r['won']}/{r['closed']}件）例: {', '.join(r['example_deal_ids'][:3])}"
                 for r in rows]
        return f"勝ちパターン分析【{cond}】:\n- " + "\n- ".join(lines)

    if intent == "account":
        g = gq.account_graph(customer)
        if g.get("status") != "found":
            return f"顧客「{customer}」は見つかりません。"
        reps = "、".join(r["name"] for r in g["reps"]) or "—"
        prods = "、".join(p["name"] for p in g["products"]) or "—"
        deals = "\n  ".join(f"{d['deal_id']} {d['name']}（{d['rank']}/{d['outcome']}・"
                            f"¥{d['amount']:,}）" for d in g["deals"][:limit]) or "—"
        return (f"{g['name']}（{g['industry']}/{g['size']}）の関係図:\n"
                f"担当: {reps}\n製品: {prods}\n案件:\n  {deals}")

    if intent == "connections":
        r = gq.connections(entity_a, entity_b)
        if r.get("status") != "found":
            return f"「{entity_a}」と「{entity_b}」を結ぶ経路は見つかりませんでした。"
        path = " → ".join(f"{n['label']}[{n['kind']}]" for n in r["path"])
        return f"{r['hops']}ホップの経路: {path}"

    if intent == "similar":
        rows = gq.similar_by_graph(deal_id, limit=limit)
        if not rows:
            return f"{deal_id} に関連する案件は見つかりませんでした。"
        lines = [f"{r['deal_id']} {r['name']}（{r['outcome']}・関連度{r['score']}）" for r in rows]
        return f"{deal_id} と関係の深い案件:\n- " + "\n- ".join(lines)

    return f"[error] 未知のintent: {intent}（reps_who_win/account/connections/similar）"


# ---------------------------------------------------------------------------
# Document generation — the chatbot's "do stuff" tools (PPTX / DOCX)
# ---------------------------------------------------------------------------
# Document tools build the file under config.GENERATED_DIR in one confirmed call,
# register it for download, and return a short confirmation. senpai.documents is
# imported lazily so a missing python-pptx/docx can never break tool import.
import hashlib as _hashlib

# Authored specs for the general tools, cached by request so repeated calls can reuse
# the same generated structure when the grounding is identical.
_GEN_SPEC_CACHE: dict[str, dict] = {}


def _yen(n) -> str:
    try:
        return f"¥{int(n):,}"
    except (TypeError, ValueError):
        return "¥0"


def _deck_outline(slides: list[dict]) -> str:
    """Render a deck's headings + subheadings for the success message, so the rep
    sees the structure that was built (titles as headings, bullets/subtitle as
    sub-items) even though the file is generated directly."""
    lines: list[str] = []
    for i, s in enumerate(slides):
        lines.append(f"  {i + 1}. {s.get('title', '')}")
        subs = [str(b) for b in (s.get("bullets") or []) if str(b).strip()]
        if not subs and s.get("subtitle"):
            subs = [ln for ln in str(s["subtitle"]).splitlines() if ln.strip()]
        lines.extend(f"     - {b}" for b in subs)
    return "\n".join(lines)


def generate_proposal(deal_id: str = "", lang: str = "ja", confirm: bool = False) -> str:
    """4-slide PPTX sales proposal grounded in a deal's SPR data. Builds directly
    (no confirmation step) — the call commits the file in one round."""
    from senpai.documents import proposal, registry
    from senpai.documents.context import build_document_context
    if not deal_id:
        return "[error] deal_id を指定してください。"
    ctx = build_document_context(deal_id)
    if ctx is None:
        return f"案件 {deal_id} は見つかりません。"
    res = proposal.generate(deal_id, lang=lang)
    if res is None:
        return f"案件 {deal_id} は見つかりません。"
    files, _ctx, spec = res
    # Register the editable proposal PPTX (deal-scoped) plus its PDF and source HTML.
    registry.register("proposal", files["pptx"], deal_id=deal_id)
    formats = ["PPTX"]
    if files.get("pdf"):
        registry.register("pdf", files["pdf"], deal_id=deal_id)
        formats.append("PDF")
    if files.get("html"):
        registry.register("html", files["html"], deal_id=deal_id)
        formats.append("HTML")
    slides = spec.get("slides", [])
    outline = _deck_outline(slides)
    return (f"提案書({len(slides)}スライド、形式: {' / '.join(formats)})を生成しました"
            f"（{ctx.customer}様）。PowerPointで直接編集できます。\n構成:\n{outline}")


def generate_ringisho(deal_id: str = "", confirm: bool = True) -> str:
    """Formal 稟議書 DOCX (customer IT-manager -> CEO) grounded in deal data."""
    from senpai.documents import registry, ringisho
    from senpai.documents.context import build_document_context
    if not deal_id:
        return "[error] deal_id を指定してください。"
    ctx = build_document_context(deal_id)
    if ctx is None:
        return f"案件 {deal_id} は見つかりません。"
    if not confirm:
        pv = ctx.to_preview()
        pains = "、".join(pv["pain_points"]) or "（SPRに課題記録なし）"
        deal_label = (ctx.deal_name or ctx.customer) + (f"（{ctx.product_category}）" if ctx.product_category else "")
        return (f"【プレビュー】{ctx.customer}様 情報システム部の稟議書(DOCX)\n"
                f"- 対象案件: {ctx.deal_id} {deal_label}\n"
                f"- 背景・課題: {pains}\n"
                f"- 投資額: {_yen(pv['investment'])}\n"
                "- 構成: 背景・課題 / 提案内容 / 投資額と効果 / 結論・承認依頼\n"
                "【システム指示】プレビューが生成されました。これ以上ツールを呼び出さず、このプレビュー内容をユーザーに提示し、作成を実行してよいか確認してください。ユーザーが同意した場合のみ、次のターンで confirm=true に設定して再度呼び出してください。")
    res = ringisho.generate(deal_id)
    if res is None:
        return f"案件 {deal_id} は見つかりません。"
    path, _ctx = res
    rec = registry.register("ringisho", path, deal_id=deal_id)
    return f"稟議書(DOCX)を生成しました: {rec['filename']}（{ctx.customer}様）。"


# Conversation-grounding budget. RECENT_FLOOR snippets are always kept (immediate
# context — the current request and the tool result that just landed); the remaining
# slots up to MAX_SNIPPETS are filled by relevance to the request, not recency.
_CONVO_BUDGET = 4000
_CONVO_MAX_SNIPPETS = 8
_CONVO_RECENT_FLOOR = 3


def _truncate_on_boundary(text: str, limit: int) -> str:
    """Trim `text` to <= `limit` chars, cutting at the nearest natural boundary
    (snippet break → paragraph → line → sentence → word) instead of mid-string, so a
    fact — a company name, a quote figure — is never severed in half. A blind
    `text[:limit]` can drop the second half of '村田印刷' or '¥1,200,000'. Only honors
    a boundary that still keeps most of the budget; adds an elision marker."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    for sep in ("\n---\n", "\n\n", "\n", "。", ". ", "、", " "):
        cut = head.rfind(sep)
        if cut >= limit * 0.6:   # a break too early would waste most of the budget
            return head[:cut].rstrip() + " …"
    return head.rstrip() + " …"


# Latin/number words and CJK character bigrams. A script-agnostic stand-in for word
# segmentation so relevance scoring works WITHOUT a morphological analyzer (janome is
# only an optional dep, and its whitespace fallback can't split Japanese, which has no
# spaces). Bigrams give '村田印刷' the shared keys 村田/田印/印刷 across query & snippet.
_LATIN_NUM_RE = re.compile(r"[a-z0-9](?:[a-z0-9,.]*[a-z0-9])?")
_CJK_RUN_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿]+")


def _relevance_tokens(text: str) -> set[str]:
    text = (text or "").lower()
    toks = set(_LATIN_NUM_RE.findall(text))
    for run in _CJK_RUN_RE.findall(text):
        if len(run) == 1:
            toks.add(run)
        else:
            toks.update(run[i:i + 2] for i in range(len(run) - 1))
    return toks


def _snippet_relevance(query_tokens: set[str], text: str) -> float:
    """Relevance of a snippet to the current request: fraction of the request's
    content tokens it covers. 0.0 when there is no query signal or no overlap."""
    if not query_tokens:
        return 0.0
    toks = _relevance_tokens(text)
    if not toks:
        return 0.0
    return len(query_tokens & toks) / len(query_tokens)


def _conversation_grounding(prompt: str) -> str:
    """Context already established in this session — prior tool results (e.g. a
    workspace file we read) and assistant answers — so a doc that references 'the
    company/quote we just discussed' grounds on it instead of being invented. Reads
    the live conversation the chat loop publishes (senpai.tools.conversation).

    Kept compact: the doc author only needs the entity in focus and the facts around
    it, not the whole transcript. System messages and failed/empty tool results are
    dropped; the current request is included so intent is explicit.

    Selection is relevance-ranked, not just the tail — recency alone drops the entity
    in focus once a few turns intervene (a side question, extra tool calls), which is
    exactly the ungrounded-deck regression this grounding exists to prevent. The most
    recent RECENT_FLOOR snippets are always kept (immediate context); the rest of the
    budget goes to the OLDER snippets that best match the request. With no query
    signal it degrades to pure recency (the prior behavior)."""
    from senpai.tools import conversation as _conv
    convo = _conv.conversation()
    if not convo:
        return ""
    # (position, formatted-text), dropping system + failed/empty tool results.
    snippets: list[tuple[int, str]] = []
    for i, m in enumerate(convo):
        role, content = m.get("role"), m.get("content")
        if role == "system" or not isinstance(content, str) or not content.strip():
            continue
        if role == "tool":
            if content.startswith("[error]") or "見つかりません" in content:
                continue
            snippets.append((i, content.strip()))
        elif role == "assistant":
            snippets.append((i, content.strip()))
        elif role == "user":
            snippets.append((i, f"（依頼）{content.strip()}"))
    if not snippets:
        return ""

    query_tokens = _relevance_tokens(prompt)
    recent = {i for i, _ in snippets[-_CONVO_RECENT_FLOOR:]}
    older = [(i, t) for i, t in snippets if i not in recent]
    # Score each older snippet once; rank by relevance, then recency for ties.
    scored = sorted(
        ((_snippet_relevance(query_tokens, t), i, t) for i, t in older),
        key=lambda s: (s[0], s[1]), reverse=True)
    budget_n = max(0, _CONVO_MAX_SNIPPETS - len(recent))
    # Keep only older snippets that actually match the request; with no query signal
    # (query_tokens empty) fall back to recency so we never return nothing.
    keep_older = [(i, t) for score, i, t in scored[:budget_n]
                  if score > 0 or not query_tokens]
    chosen = sorted(
        [(i, t) for i, t in snippets if i in recent] + keep_older,
        key=lambda it: it[0])
    joined = "\n---\n".join(t for _, t in chosen)
    return _truncate_on_boundary(joined, _CONVO_BUDGET)


def _workspace_grounding(query: str) -> str:
    """Relevant LOCAL documents for `query`, or '' when nothing genuinely matched.
    Gated on a real filename/path match (score > 0), not the finder's recency
    fallback, so an unrelated deck ('best gaming laptops') isn't padded with random
    files. Read-only, sandboxed — the entity may live only in the rep's own files."""
    if not (query or "").strip():
        return ""
    try:
        from senpai.workspace import workspace_evidence
        from senpai.workspace.gather import _format
        res = workspace_evidence(query, limit=3)
    except Exception:  # noqa: BLE001 — grounding is best-effort
        return ""
    if not res.get("documents"):
        return ""
    if not any((f.get("score") or 0) > 0 for f in res.get("found", [])):
        return ""
    return _format(res)


def _gather_grounding(prompt: str, customer: str, use_web: bool) -> str:
    """Best-effort context for the general doc tools, gathered in priority order so
    the deck grounds on what the rep is actually referencing:
      1. the live conversation — a company/quote/deal discussed earlier this session
      2. the rep's own local documents (workspace) that match the topic
      3. internal CRM records for a named customer
      4. a live web_search (external/factual topics)
    Any layer may be empty (then the model uses general knowledge). Conversation and
    workspace come first because they carry the specific entity in focus — that is
    what stops a 'proposal for <company we just read from a file>' from being
    hallucinated as a generic deck under the wrong company name."""
    parts: list[str] = []

    convo_ctx = _conversation_grounding(prompt)
    if convo_ctx:
        parts.append(f"【これまでの会話・確定済みの文脈】\n{convo_ctx}")

    ws = _workspace_grounding(prompt or customer)
    if ws:
        parts.append(f"【ローカル文書（あなたのファイル）】\n{ws}")

    # CRM, in order of trust:
    #   1. an explicit customer arg — authoritative.
    #   2. the entity the conversation already RESOLVED (SessionFocus) — also
    #      authoritative: it comes from ids real tool results emitted (a deal we
    #      looked up, a customer we queried), so 'that company we discussed' is a
    #      lookup, not a re-inference. A deal in focus grounds on that specific deal.
    #   3. as a LAST resort, a fuzzy name match on the prompt — but only when the
    #      workspace didn't already pin the entity, since a local-file company must
    #      not pull an unrelated CRM customer (the wrong-company-name bug).
    cust = _resolve_customer(customer) if customer else None
    crm = ""
    if cust:
        crm = query_spr(customer=cust["customer_id"])
    else:
        focus = session_focus()
        if focus.deal_id:
            crm = query_spr(deal_id=focus.deal_id)
        elif focus.customer_id:
            crm = query_spr(customer=focus.customer_id)
        elif not ws:
            fuzzy = store.match_customer_in_text(prompt)
            if fuzzy:
                crm = query_spr(customer=fuzzy["customer_id"])
    if crm:
        parts.append(f"【社内データ】\n{crm}")

    if use_web:
        try:
            parts.append(f"【Web検索】\n{web_search(query=prompt)}")
        except Exception:  # noqa: BLE001 — grounding is best-effort
            pass
    return "\n\n".join(p for p in parts if p)


# External/factual cues in a free-prompt deck/doc — the topics that go stale in a
# model's weights (products, prices, "best-of" picks, current models, comparisons).
# When present, a general deck is grounded in a live web_search unless the caller
# says otherwise. Internal decks (a customer is named) ground in records instead.
_WEB_SIGNAL_RE = re.compile(
    r"best|top|latest|newest|current|cheap|price|budget|under|vs\b|versus|compare|"
    r"comparison|review|ranking|recommend|spec|market|trend|news|deal|20(2[3-9]|[3-9]\d)|"
    r"おすすめ|比較|最新|価格|相場|予算|以内|ランキング|レビュー|選び方|市場|"
    r"トレンド|ニュース|スペック|円",
    re.IGNORECASE,
)


def _auto_web(prompt: str) -> bool:
    """True when a free-prompt deck/doc should be web-grounded by default: the topic
    reads as external/factual/current, so the model's own knowledge is likely stale."""
    return bool(_WEB_SIGNAL_RE.search(prompt or ""))


def _resolve_use_web(use_web, prompt: str, customer: str) -> bool:
    """Decide grounding. Explicit True/False from the caller wins. When unspecified
    (None), auto-enable web for external/factual prompts, but not when the deck is
    scoped to a customer (that grounds in internal records instead)."""
    if use_web is not None:
        return bool(use_web)
    if customer:
        return False
    return _auto_web(prompt)


def _gen_key(kind: str, prompt: str, customer: str, use_web: bool, grounding: str = "") -> str:
    return _hashlib.md5(
        f"{kind}|{prompt}|{customer}|{use_web}|{grounding}".encode()).hexdigest()


def _author_spec(kind: str, prompt: str, customer: str, use_web: bool, lang: str):
    """Author (or reuse cached) a deck/doc spec for the general tools. None if the
    model is unavailable. The cache key includes the gathered grounding so the same
    prompt in a different conversation (different entity in focus) re-authors rather
    than returning a stale, differently-grounded deck."""
    from senpai.documents import author
    grounding = _gather_grounding(prompt, customer, use_web)
    key = _gen_key(kind, prompt, customer, use_web, grounding)
    spec = _GEN_SPEC_CACHE.get(key)
    if spec is not None:
        return spec
    spec = (author.author_deck if kind == "pptx" else author.author_doc)(
        prompt, grounding=grounding, lang=lang)
    if spec is not None:
        _GEN_SPEC_CACHE[key] = spec
    return spec


def generate_pptx(prompt: str = "", title: str = "", use_web=None,
                  customer: str = "", lang: str = "ja", confirm: bool = False) -> str:
    """General-purpose PPTX from a free prompt (LLM-authored). No fixed slide count.
    Builds directly (no confirmation step) — the call commits the file in one round.
    Grounding is automatic: external/factual topics are web-grounded by default; a
    named customer grounds it in internal records. Needs the model."""
    from senpai.documents import author, export, registry
    if not (prompt or "").strip():
        return "[error] プレゼンの主題(prompt)を指定してください。"
    if not author._use_llm():
        return "本機能はモデル(LLM)が必要です（SENPAI_USE_LLM=1 とモデルサーバ）。"
    spec = _author_spec("pptx", prompt, customer, _resolve_use_web(use_web, prompt, customer), lang)
    if spec is None:
        return "本機能はモデル(LLM)が必要です。現在モデルに接続できません。"
    slides = spec.get("slides", [])
    if title and slides:
        slides[0]["title"] = title
    slug = title or spec.get("_title") or prompt[:30]

    # HTML-first pipeline: build the deck as one self-contained HTML file (the visual
    # source of truth), then render a pixel-perfect PDF and an editable-text PPTX from it
    # with headless Chromium (native python-pptx fallback if the browser is unavailable).
    files = export.render_deck(spec, kind="pptx", slug=slug, lang=lang)
    formats = _register_deck_files(registry, files, primary_kind="pptx")

    outline = _deck_outline(slides)
    return (f"プレゼンを生成しました（{len(slides)}スライド、形式: {' / '.join(formats)}）。\n"
            f"PowerPointで直接編集できます。\n構成:\n{outline}")


def _register_deck_files(registry, files: dict, *, primary_kind: str) -> list[str]:
    """Register a deck's export set for download in a stable order — the editable office
    file first (the primary deliverable), then PDF, then the source HTML — so the primary
    is the one legacy single-document consumers pick up. Returns the format labels shown
    to the user (e.g. ['PPTX', 'PDF', 'HTML'])."""
    registry.register(primary_kind, files["pptx"])
    formats = [primary_kind.upper() if primary_kind in ("pptx", "docx") else "PPTX"]
    if files.get("pdf"):
        registry.register("pdf", files["pdf"])
        formats.append("PDF")
    if files.get("html"):
        registry.register("html", files["html"])
        formats.append("HTML")
    return formats


def generate_docx(prompt: str = "", title: str = "", use_web=None,
                  customer: str = "", lang: str = "ja", confirm: bool = True) -> str:
    """General-purpose DOCX from a free prompt (LLM-authored). Grounding is automatic:
    external/factual topics are web-grounded by default; a named customer grounds it
    in internal records. Needs the model."""
    from senpai.documents import author, registry
    from senpai.documents.render import output_path, render_docx
    if not (prompt or "").strip():
        return "[error] 文書の主題(prompt)を指定してください。"
    if not author._use_llm():
        return "本機能はモデル(LLM)が必要です（SENPAI_USE_LLM=1 とモデルサーバ）。"
    spec = _author_spec("docx", prompt, customer, _resolve_use_web(use_web, prompt, customer), lang)
    if spec is None:
        return "本機能はモデル(LLM)が必要です。現在モデルに接続できません。"
    sections = spec.get("sections", [])
    if not confirm:
        outline = "\n".join(f"  - {s.get('heading', '')}" for s in sections)
        return (f"【プレビュー】DOCX「{title or spec.get('_title') or prompt}」{len(sections)}セクション:\n"
                f"{outline}\n【システム指示】プレビューが生成されました。これ以上ツールを呼び出さず、このプレビュー内容をユーザーに提示し、作成を実行してよいか確認してください。ユーザーが同意した場合のみ、次のターンで confirm=true に設定して再度呼び出してください。")
    if title:
        spec["title"] = title
    path = output_path("docx", title or spec.get("_title") or prompt[:30], "docx")
    render_docx(spec, path)
    rec = registry.register("docx", path)
    return f"文書(DOCX)を生成しました: {rec['filename']}（{len(sections)}セクション）。"


# ---------------------------------------------------------------------------
# Dispatch (mirrors demo/tools.py)
# ---------------------------------------------------------------------------
def segment_intelligence(query: str = "", category: str = "", industry: str = "",
                         outcome: str = "all", limit: int = 6) -> str:
    """Aggregate/thematic answers across category×industry market segments — win
    rates, common failure modes, recommended plays — grounded in the deal-health
    engine and citing evidence deal ids. GPU-free (committed reports or in-memory
    deterministic build)."""
    from senpai.graph import communities
    from senpai.retrieval import trace as _trace
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 6
    reports = communities.select(query=query, category=category, industry=industry,
                                 outcome=outcome, limit=limit)
    _trace.record("segment_intelligence", scope="all",
                  items=[{"id": r["id"], "score": r.get("win_rate")} for r in reports],
                  query=" ".join(x for x in [query, category, industry] if x), n=len(reports))
    if not reports:
        return "該当するセグメント（カテゴリ×業界）が見つかりませんでした。"
    return "\n\n".join(communities.format_report(r) for r in reports)


def search_workspace_documents(query: str = "", limit: int = 0) -> str:
    """Find and read relevant LOCAL documents (PDF/DOCX/PPTX/XLSX/TXT/MD) from the
    sandboxed workspace, returning their text with per-file citations. Runs on the
    orchestration engine: one `find` fans out into parallel `extract` tasks. READ-ONLY.
    The chat loop's synthesis round reduces the returned documents into the answer."""
    from senpai.retrieval import trace as _trace
    from senpai.workspace import workspace_evidence
    lim = None
    try:
        lim = int(limit) if limit else None
    except (TypeError, ValueError):
        lim = None
    res = workspace_evidence(query, limit=lim)
    _trace.record("workspace", scope="local_files",
                  items=[{"id": d["rel"], "score": d.get("chars")} for d in res["documents"]],
                  query=query, n=len(res["documents"]))
    from senpai.workspace.gather import _format
    return _format(res)


def edit_workspace_document(path: str, content: str, confirm: bool = True) -> str:
    """Modifies or creates a local text document in the workspace.
    Commits by default; callers may pass confirm=False only for an explicit preview.
    """
    from senpai.workspace import sandbox
    try:
        safe_p = sandbox.safe_path(path)
    except sandbox.SandboxError as e:
        return f"エラー: パスが無効または境界外です ({e})"
    
    if safe_p.suffix.lower() not in (".txt", ".md", ".json", ".csv"):
        return f"エラー: テキストファイル（.txt, .md, .json, .csv等）のみ編集可能です。指定された拡張子: {safe_p.suffix}"
    
    if not confirm:
        return (f"【ファイル編集プレビュー（保存されていません）】\n"
                f"対象: {sandbox.rel(safe_p)}\n"
                f"新しい内容:\n{content}\n\n"
                f"よろしければ確認して「保存して」と指示してください（confirm=True を指定して再実行します）。")
    
    try:
        safe_p.parent.mkdir(parents=True, exist_ok=True)
        safe_p.write_text(content, encoding="utf-8")
        from senpai.retrieval import trace as _trace
        _trace.record("workspace_edit", scope="local_files",
                      items=[{"id": sandbox.rel(safe_p), "score": len(content)}],
                      query=path, n=1)
        return f"ファイル {sandbox.rel(safe_p)} を保存しました。"
    except Exception as e:
        return f"ファイルの保存中にエラーが発生しました: {e}"


def move_workspace_document(src: str, dst: str, confirm: bool = True) -> str:
    """Move or rename a local document in the workspace.
    Commits by default; callers may pass confirm=False only for an explicit preview.
    """
    from senpai.workspace import sandbox
    try:
        s = sandbox.safe_path(src)
        d = sandbox.safe_path(dst)
    except sandbox.SandboxError as e:
        return f"エラー: パスが無効または境界外です ({e})"
    
    if not s.exists():
        return f"エラー: 移動元のファイルが存在しません: {src}"
    
    if not confirm:
        return (f"【ファイル移動プレビュー（実行されていません）】\n"
                f"移動元: {sandbox.rel(s)}\n"
                f"移動先: {sandbox.rel(d)}\n\n"
                f"よろしければ確認して「移動して」と指示してください（confirm=True を指定して再実行します）。")
    
    try:
        new_path = sandbox.move_within(src, dst)
        from senpai.retrieval import trace as _trace
        _trace.record("workspace_move", scope="local_files",
                      items=[{"id": new_path, "score": 1}],
                      query=f"{src} -> {dst}", n=1)
        return f"ファイルを移動しました: {sandbox.rel(s)} -> {new_path}"
    except Exception as e:
        return f"ファイルの移動中にエラーが発生しました: {e}"


def advise_solutions(customer: str = "", deal_id: str = "") -> str:
    """Recommend appropriate Otsuka solutions for a customer based on their context.
    Uses expansion signals, environment gaps, and category matching to generate
    deterministic candidates, then explains why they fit."""
    from senpai.recommendation.run import run_solution_advisor
    cid = ""
    if customer:
        c = _resolve_customer(customer)
        if c:
            cid = c["customer_id"]
        else:
            cid = customer
            
    recs = run_solution_advisor(cid, deal_id)
    if not recs:
        return "提案できるソリューションが見つかりませんでした。"
        
    lines = []
    for r in recs:
        lines.append(f"■ {r.solution_name} ({r.category}) - 適合度: {r.match_score:.2f}, 確信度: {r.confidence:.2f}")
        lines.append(f"  理由: {r.why}")
        if r.business_value:
            lines.append(f"  価値: {r.business_value}")
        if r.risks:
            lines.append(f"  リスク: {', '.join(r.risks)}")
        if r.complementary_solutions:
            lines.append(f"  関連: {', '.join(r.complementary_solutions)}")
        if r.product_pages:
            pages = ", ".join(f"[{p.get('title')}]({p.get('url')})" for p in r.product_pages)
            lines.append(f"  詳細: {pages}")
        lines.append("")
        
    return "推奨ソリューション:\n\n" + "\n".join(lines)



_DISPATCH = {
    "query_spr": query_spr,
    "find_deals": find_deals,
    "find_similar_deals": find_similar_deals_tool,
    "retrieve_playbook": retrieve_playbook_tool,
    "lookup_customer_environment": lookup_customer_environment,
    "get_product_info": get_product_info,
    "score_deal_health": score_deal_health,
    "review_sales_note": review_sales_note,
    "draft_daily_report": draft_daily_report,
    "route_to_expert": route_to_expert,
    "summarize_reports": summarize_reports,
    "get_seasonal_context": get_seasonal_context,
    # Manager + shared tools
    "morning_briefing": morning_briefing,
    "list_at_risk_deals": list_at_risk_deals,
    "team_pipeline_overview": team_pipeline_overview,
    "team_report_digest": team_report_digest,
    "rep_coaching_focus": rep_coaching_focus,
    "draft_message": draft_message,
    "web_search": web_search,
    "web_research": web_research,
    # Sales demo tools (ported from demo/tools.py, re-grounded on the store)
    "search_products": search_products,
    "create_quote": create_quote,
    "schedule_meeting": schedule_meeting,
    "send_email": send_email,
    "get_calendar": get_calendar,
    "search_knowledge": search_knowledge,
    "search_solutions": search_solutions,
    "search_notes": search_notes,
    "query_graph": query_graph,
    "segment_intelligence": segment_intelligence,
    "search_workspace_documents": search_workspace_documents,
    "edit_workspace_document": edit_workspace_document,
    "move_workspace_document": move_workspace_document,
    # Document generation (the chatbot's "do stuff" tools)
    "generate_proposal": generate_proposal,
    "generate_ringisho": generate_ringisho,
    "generate_pptx": generate_pptx,
    "generate_docx": generate_docx,
    "advise_solutions": advise_solutions,
}


_ALWAYS_CONFIRM_TOOLS = {
    "schedule_meeting",
    "edit_workspace_document",
    "move_workspace_document",
    "generate_proposal",
    "generate_ringisho",
    "generate_pptx",
    "generate_docx",
}


def _force_confirm_true(name: str, arguments: dict) -> dict:
    """Commit confirmation-gated tools in one call.

    The assistant prompt asks the model to pass confirm=True, but tool correctness
    should not depend on the model remembering that detail. Keep the coercion in the
    shared dispatch path so API chat, tests, and any future caller get the same
    behavior.
    """
    if name not in _ALWAYS_CONFIRM_TOOLS:
        return arguments
    coerced = dict(arguments)
    coerced["confirm"] = True
    return coerced


def dispatch(name: str, arguments: dict | str) -> str:
    """Execute a tool by name with arguments (dict or JSON string). Always
    returns a string; never raises (so the chat loop can't crash)."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return f"[error] could not parse arguments for {name}: {arguments!r}"
    if not isinstance(arguments, dict):
        arguments = {}
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"[error] unknown tool: {name}"
    arguments = _force_confirm_true(name, arguments)
    try:
        return str(fn(**arguments))
    except TypeError as e:
        return f"[error] bad arguments for {name}: {e}"
    except Exception as e:  # noqa: BLE001 — must never crash on a tool
        return f"[error] {name} failed: {e}"


if __name__ == "__main__":
    # Pick a deliberately dead deal so score/flags show real risk.
    for n, a in [
        ("query_spr", {"deal_id": "D001"}),
        ("query_spr", {"rep_id": "R05"}),
        ("find_deals", {"product_category": "サーバー", "size": "中規模", "outcome": "won", "limit": 5}),
        ("find_similar_deals", {"customer": "C01"}),
        ("retrieve_playbook", {"query": "お客様が決定を先延ばし", "tags": ["決定先延ばし"]}),
        ("search_notes", {"query": "予算が厳しく決裁が止まっている", "limit": 3}),
        ("lookup_customer_environment", {"customer": "C01"}),
        ("get_product_info", {"product": "MFP30"}),
        ("score_deal_health", {"deal_id": "D001"}),
        ("review_sales_note", {"note": "お客様は社内で検討してから連絡するとのこと。"}),
        ("draft_daily_report", {"activity": "アクメ商事を訪問しデモを実施", "deal_id": "D001"}),
        ("route_to_expert", {"question": "ネットワーク更改の構成相談", "tags": ["ネットワーク"]}),
        ("summarize_reports", {"rep_id": "R05"}),
        ("get_seasonal_context", {"month": 2}),
        ("morning_briefing", {"rep_id": "R12", "limit": 5}),
        ("list_at_risk_deals", {"limit": 5}),
        ("query_graph", {"intent": "reps_who_win", "category": "サーバー"}),
        ("query_graph", {"intent": "account", "customer": "C28"}),
        ("segment_intelligence", {"query": "製造業のサーバー案件はなぜ負ける？", "outcome": "lost"}),
        ("segment_intelligence", {"query": "どのカテゴリの勝率が低い？"}),
        ("team_pipeline_overview", {}),
        ("team_report_digest", {}),
        ("rep_coaching_focus", {}),
        ("draft_message", {"to": "伊藤さん", "about": "D003の進捗", "deal_id": "D003"}),
        ("web_search", {"query": "製造業 IT投資 動向"}),
        # Document tools: preview (no file) is deterministic; the grounded build is
        # GPU-free, the general tools need a model so they print their guard message.
        ("generate_proposal", {"deal_id": "D001"}),
        ("generate_proposal", {"deal_id": "D001", "confirm": True}),
        ("generate_ringisho", {"deal_id": "D001", "confirm": True}),
        ("generate_pptx", {"prompt": "GTA 6 の発売展望", "use_web": False}),
        ("generate_docx", {"prompt": "社内向けセキュリティ研修の概要"}),
    ]:
        print(f"\n### {n}({a})\n{dispatch(n, a)}")
````

## File: web/components/workspace/workspace.tsx
````typescript
"use client";

// Senpai Workspace shell (Phase 2).
//
// One conversational surface. A turn is either a user message or a SKILL turn
// that produces a pinned, typed Artifact. Phase 2 wires the `/review` skill:
//   /review <note>  →  api.coach() (deterministic sections, assembled into an
//                      immutable review Artifact)  +  narrateStream() (the
//                      senior's read, streamed live into the card).
//
// The transcript and each card's streamed commentary live in the keyed external
// store (chat-store), so generation survives navigation exactly like the
// standalone Coach and Assistant. This surface ships ALONGSIDE the Coach page —
// nav is not touched until Phase 4.

import React, { useEffect, useRef, useState } from "react";
import {
  Building2,
  ChevronRight,
  CornerDownLeft,
  GraduationCap,
  History,
  Loader2,
  Mic,
  Paperclip,
  Square,
  SquarePen,
  TerminalSquare,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api, narrateStream, chatStream, accountCommentaryStream, type ResolveCandidate, type ChatTurn as ChatHistoryTurn } from "@/lib/api";
import { assembleReviewArtifact, assembleAccountArtifact, assembleResearchArtifact, type Artifact, type ArtifactStatus, type EntityRef, type ResearchSourceLine } from "@/lib/artifacts";
import type { CoachExample, DealRow, Principle } from "@/lib/types";
import { useT } from "@/lib/i18n";
import { customerText, coachExampleText } from "@/lib/content-i18n";
import { useCachedState, useCachedConversationId, getCached, useWorkspaceFocus, snapshotByPrefix, restoreCached, type WorkspaceFocus } from "@/lib/chat-store";
import { useSession } from "@/lib/session";
import { HistoryDrawer } from "./history-drawer";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { ExecutionTimeline, type ExecutionPhase } from "@/components/agent/agent-lane";
import { ArtifactCard } from "./artifact-card";
import { MessageBubble, type Msg } from "@/components/assistant/message";
import { ExperiencePanel } from "@/components/coach/similar-cases";
import { CrewTurn } from "./crew-turn";
import { IntelTurn } from "./intel-turn";
import { parseInput } from "@/components/workspace/slash";

// --- thread model -----------------------------------------------------------
type AccountPickCandidate = { customer_id: string; name: string };

type WMsg =
  | { id: number; role: "user"; text: string; dealLabel?: string }
  | { id: number; role: "system"; text: string }
  | { id: number; role: "assistant"; text: string; history: ChatHistoryTurn[]; answer?: string; runId?: number; context?: string; dealId?: string }
  | { id: number; role: "loading" }
  | { id: number; role: "account_pick"; query: string; candidates: AccountPickCandidate[]; suggestedId?: string | null }
  | { id: number; role: "skill"; kind: "review"; note: string; dealId?: string; artifact: Artifact }
  | { id: number; role: "skill"; kind: "account_brief"; customerId: string; artifact: Artifact }
  | { id: number; role: "skill"; kind: "research"; query: string; entity?: EntityRef; artifact: Artifact }
  | { id: number; role: "crew"; mode: "deal" | "team"; query?: string; label?: string }
  | { id: number; role: "intel"; query: string };

// The serialized shape persisted per conversation (the opaque `blob` the backend
// round-trips). It carries the transcript array PLUS the separately-cached streamed
// strings (assistant text, artifact narration, crew contributions) and the id
// counter, so a reopened chat rehydrates full-fidelity without re-streaming.
type StoredThread = {
  version: 1;
  messages: WMsg[];
  cache: Record<string, unknown>;
  nextId: number;
  focus?: WorkspaceFocus;
};

function Avatar({ who }: { who: "senpai" | "user" }) {
  return who === "senpai" ? (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-navy text-white">
      <GraduationCap className="h-[18px] w-[18px]" />
    </div>
  ) : (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
      <UserRound className="h-[18px] w-[18px]" />
    </div>
  );
}

function Row({ who, name, children }: { who: "senpai" | "user"; name: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <Avatar who={who} />
      <div className="min-w-0 flex-1 space-y-2">
        <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">{name}</div>
        {children}
      </div>
    </div>
  );
}

function Dots() {
  return (
    <span className="flex gap-1">
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.3s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.15s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary" />
    </span>
  );
}

function ThinkingText({ role, lang }: { role: string; lang: "ja" | "en" }) {
  const [stage, setStage] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setStage((prev) => (prev + 1) % 4);
    }, 3000);
    return () => clearInterval(timer);
  }, []);

  const juniorPhrases = {
    ja: [
      "先輩の視点で読み解いています…",
      "商談の力学を分析中…",
      "プレイブックの知見を検索中…",
      "最適なアドバイスを作成中…",
    ],
    en: [
      "Reading it the way a senior would…",
      "Analyzing deal dynamics…",
      "Searching playbook insights…",
      "Drafting best advice…",
    ],
  };

  const managerPhrases = {
    ja: [
      "データを確認しています…",
      "パイプラインの状況を分析中…",
      "リスクシグナルを評価中…",
      "レポートをまとめています…",
    ],
    en: [
      "Pulling the data…",
      "Analyzing pipeline status…",
      "Evaluating risk signals…",
      "Synthesizing report…",
    ],
  };

  const phrases = role === "manager" ? managerPhrases : juniorPhrases;
  const list = phrases[lang] || phrases["ja"];
  return <span>{list[stage]}</span>;
}

// --- slash command picker ---------------------------------------------------
const SLASH_COMMANDS = [
  {
    cmd: "/review",
    labelEn: "Review a meeting note",
    labelJa: "商談メモをレビュー",
    descEn: "Paste a note — get a senior's structured read",
    descJa: "メモを貼り付け、先輩の視点で読み解く",
    managerOnly: false,
  },
  {
    cmd: "/account",
    labelEn: "Account intelligence",
    labelJa: "顧客インテリジェンス",
    descEn: "Pull a customer brief from internal records",
    descJa: "社内記録から顧客ブリーフを取得する",
    managerOnly: false,
  },
  {
    cmd: "/research",
    labelEn: "Research a topic",
    labelJa: "トピックをリサーチ",
    descEn: "Search internal data and the web",
    descJa: "社内データとWebを横断して調査する",
    managerOnly: false,
  },
  {
    cmd: "/crew",
    labelEn: "Multi-agent deal analysis",
    labelJa: "エージェントで商談分析",
    descEn: "A Researcher, Coach & Strategist analyse a deal together",
    descJa: "リサーチャー・コーチ・ストラテジストが商談を分析",
    managerOnly: false,
  },
  {
    cmd: "/intel",
    labelEn: "Website intel (crawl a site)",
    labelJa: "サイトインテル（サイトを巡回）",
    descEn: "Paste a company URL — watch it browse, get a pre-call brief",
    descJa: "企業URLを貼り付け、巡回の様子を見て事前準備資料を取得",
    managerOnly: false,
  },
  {
    cmd: "/team",
    labelEn: "Multi-agent team review",
    labelJa: "エージェントでチーム分析",
    descEn: "One analyst per rep, then a team-lead action list",
    descJa: "担当ごとに分析し、今週の優先アクションを提示",
    managerOnly: true,
  },
] as const;

export interface SlashPickerHandle {
  handleKey: (e: React.KeyboardEvent) => boolean; // returns true if consumed
}

const SlashPicker = React.forwardRef<
  SlashPickerHandle,
  {
    input: string;
    lang: string;
    role: "junior" | "manager";
    onSelect: (cmd: string) => void;
    onClose: () => void;
  }
>(function SlashPicker({ input, lang, role, onSelect, onClose }, ref) {
  const [active, setActive] = useState(0);

  // Filter commands by what the user has typed after "/" (and hide manager-only
  // skills like /team from the junior workspace).
  const typed = input.startsWith("/") ? input.slice(1).toLowerCase() : "";
  const filtered = SLASH_COMMANDS.filter((c) =>
    c.cmd.slice(1).startsWith(typed) && (!c.managerOnly || role === "manager")
  );

  // `active` can outrun a shrinking `filtered` (the user typed more and fewer
  // commands match). Clamp the index everywhere so we never read past the end,
  // and snap it back into range when the filter changes.
  const activeIdx = active < filtered.length ? active : 0;
  useEffect(() => {
    if (active !== 0 && active >= filtered.length) setActive(0);
  }, [filtered.length, active]);

  // Expose keyboard handler so parent Textarea can delegate without stealing focus
  React.useImperativeHandle(ref, () => ({
    handleKey(e: React.KeyboardEvent): boolean {
      if (filtered.length === 0) return false;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive((a) => (a + 1) % filtered.length);
        return true;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive((a) => (a - 1 + filtered.length) % filtered.length);
        return true;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        const sel = filtered[activeIdx];
        if (sel) onSelect(sel.cmd + " ");
        return true;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return true;
      }
      return false;
    },
  }), [filtered, activeIdx, onSelect, onClose]);

  // Close if nothing matches
  if (filtered.length === 0) return null;

  return (
    <div className="absolute bottom-full left-0 right-0 mb-2 overflow-hidden rounded-xl border border-border bg-card shadow-[0_8px_30px_-12px_rgba(16,24,40,0.35)]">
      <div className="flex items-center gap-1.5 border-b border-border px-3 py-2">
        <TerminalSquare className="h-3.5 w-3.5 text-primary" />
        <span className="text-[11px] font-semibold uppercase tracking-[0.07em] text-muted-foreground">
          {lang === "ja" ? "スキルを選択" : "Select a skill"}
        </span>
      </div>
      {filtered.map((c, i) => (
        <button
          key={c.cmd}
          onClick={() => onSelect(c.cmd + " ")}
          className={[
            "flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors",
            i === activeIdx
              ? "bg-primary/[0.07] text-foreground"
              : "text-foreground hover:bg-muted/60",
          ].join(" ")}
          onMouseEnter={() => setActive(i)}
        >
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10">
            <TerminalSquare className="h-3.5 w-3.5 text-primary" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[13px] font-semibold">{c.cmd}</span>
            <span className="block text-[11.5px] text-muted-foreground">
              {lang === "ja" ? c.descJa : c.descEn}
            </span>
          </span>
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/50" />
        </button>
      ))}
      <div className="border-t border-border px-3 py-1.5">
        <span className="text-[10.5px] text-muted-foreground">
          {lang === "ja"
            ? "↑↓ で移動、Enter で選択、Esc で閉じる"
            : "↑↓ navigate · Enter select · Esc close"}
        </span>
      </div>
    </div>
  );
});

// --- a review skill turn: holds the immutable artifact, streams its commentary
// The structured artifact is fixed at assembly; the senior's read streams into a
// SEPARATE keyed store entry, so switching tabs and returning restores it
// instead of re-streaming. Auto-start fires exactly once per card (cached
// `started` across navigation; a ref guards StrictMode's double-invoked effect).
function ReviewTurn({
  turnId, artifact, note, dealId, principles, onPick,
}: {
  turnId: number; artifact: Artifact; note: string; dealId?: string;
  principles: Principle[];
  onPick: (turnId: number, dealId: string, name: string) => void;
}) {
  const { lang } = useT();
  const key = artifact.id;
  const [commentary, setCommentary] = useCachedState<string | null>(`ws:art:${key}:narr`, null);
  const [done, setDone] = useCachedState<boolean>(`ws:art:${key}:done`, false);
  const [started, setStarted] = useCachedState<boolean>(`ws:art:${key}:started`, false);
  const [groundedName, setGroundedName] = useCachedState<string | null>(`ws:art:${key}:gname`, null);
  const [groundedDeal, setGroundedDeal] = useCachedState<string | null>(`ws:art:${key}:gdeal`, null);
  const [candidates, setCandidates] = useCachedState<ResolveCandidate[]>(`ws:art:${key}:cands`, []);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current || started) return;
    startedRef.current = true;
    setStarted(true);
    let acc = "";
    narrateStream(note, dealId, (e) => {
      switch (e.type) {
        case "context":
          if (e.grounded) {
            setGroundedName(e.customer ?? null);
            if (e.deal_id) setGroundedDeal(e.deal_id);
          }
          if (e.candidates?.length) setCandidates(e.candidates);
          break;
        case "delta":
          acc += e.text;
          setCommentary(acc);
          break;
        // done | unavailable | error → handled after the stream resolves
      }
    }, { lang, conversationId: artifact.threadId }).then(() => {
      setDone(true);
      if (!acc) setCommentary(null);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const status: ArtifactStatus = done ? "ready" : "building";
  const entity: EntityRef | undefined =
    artifact.entity ??
    (groundedName
      ? { type: "deal", id: dealId ?? groundedDeal ?? "", name: groundedName }
      : undefined);
  const merged: Artifact = { ...artifact, commentary, status, entity };

  // Customer still ambiguous → the rep must pick BEFORE we read anything. Show
  // only the picker (no card, no senior's read — the backend hasn't generated
  // one). Picking resolves THIS turn in place (re-runs grounded on the choice),
  // so the conversation stays in the same thread instead of spawning a new one.
  if (candidates.length > 0) {
    return (
      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-[0_4px_20px_-10px_rgba(16,24,40,0.2)]">
        <div className="flex items-center gap-1.5 border-b border-border px-3 py-2 text-[12px] font-medium text-muted-foreground">
          <UserRound className="h-3.5 w-3.5" />
          {candidates.length === 1
            ? (lang === "ja"
                ? "メモの社名は次の顧客に近い表記です。この顧客で合っていますか？"
                : "The name in the note is close to this customer — did you mean them?")
            : (lang === "ja"
                ? "メモの社名が複数の顧客に一致しました。どの顧客ですか？"
                : "The name in the note matches several customers — which one?")}
        </div>
        <div className="flex flex-col">
          {candidates.map((c) => (
            <button
              key={c.customer_id}
              onClick={() => onPick(turnId, c.deal_id ?? "", c.name)}
              className="flex items-center gap-2.5 px-3 py-2 text-left text-[13px] transition-colors hover:bg-muted/60"
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                <Building2 className="h-3 w-3 text-primary" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-medium text-foreground">{customerText(lang, c.name).text}</span>
                {c.deal_id && <span className="block font-mono text-[10.5px] text-muted-foreground">{c.deal_id}</span>}
              </span>
            </button>
          ))}
        </div>
        <div className="border-t border-border px-3 py-1.5 bg-muted/10">
          <p className="text-[11px] text-muted-foreground">
            {lang === "ja"
              ? "選択するとこのレビューがその顧客で読み込まれます。"
              : "Pick one and this same review fills in for that customer."}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <ArtifactCard artifact={merged} />
      {/* Experience pillar — past cases + relevant principles (collapsed, lazy).
          Only meaningful once grounded on a customer; matches the standalone
          Review Coach's "Similar Past Cases" + principle provenance. */}
      {principles.length > 0 && <ExperiencePanel note={note} dealId={dealId} principles={principles} />}
    </div>
  );
}

function AccountTurn({ artifact, customerId }: { artifact: Artifact; customerId: string }) {
  const { lang } = useT();
  const key = artifact.id;
  const [commentary, setCommentary] = useCachedState<string | null>(`ws:art:${key}:narr`, null);
  const [done, setDone] = useCachedState<boolean>(`ws:art:${key}:done`, false);
  const [started, setStarted] = useCachedState<boolean>(`ws:art:${key}:started`, false);
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current || started) return;
    startedRef.current = true;
    setStarted(true);
    let acc = "";
    accountCommentaryStream(customerId, (e) => {
      switch (e.type) {
        case "delta":
          acc += e.text;
          setCommentary(acc);
          break;
      }
    }, { lang, conversationId: artifact.threadId }).then(() => {
      setDone(true);
      if (!acc) setCommentary(null);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const status: ArtifactStatus = done ? "ready" : "building";
  const merged: Artifact = { ...artifact, commentary, status };

  return <ArtifactCard artifact={merged} />;
}

function ResearchTurn({
  turnId, artifact, query, entity, onPick,
}: {
  turnId: number; artifact: Artifact; query: string; entity?: EntityRef;
  onPick: (turnId: number, c: ResolveCandidate) => void;
}) {
  const { lang } = useT();
  const key = artifact.id;
  const [commentary, setCommentary] = useCachedState<string | null>(`ws:art:${key}:ans`, null);
  const [sources, setSources] = useCachedState<ResearchSourceLine[]>(`ws:art:${key}:src`, []);
  const [webUrls, setWebUrls] = useCachedState<string[]>(`ws:art:${key}:web`, []);
  const [candidates, setCandidates] = useCachedState<ResolveCandidate[]>(`ws:art:${key}:cands`, []);
  const [dealIds, setDealIds] = useCachedState<string[]>(`ws:art:${key}:deals`, []);
  const [done, setDone] = useCachedState<boolean>(`ws:art:${key}:done`, false);
  const [started, setStarted] = useCachedState<boolean>(`ws:art:${key}:started`, false);
  const [collapsed, setCollapsed] = useCachedState<boolean>(`ws:art:${key}:coll`, false);
  const [showArtifact, setShowArtifact] = useCachedState<boolean>(`ws:art:${key}:showart`, false);
  const startedRef = useRef(false);
  const collapseRef = useRef<NodeJS.Timeout | undefined>(undefined);

  useEffect(() => () => { if (collapseRef.current) clearTimeout(collapseRef.current); }, []);

  useEffect(() => {
    if (startedRef.current || started) return;
    startedRef.current = true;
    setStarted(true);
    let acc = "";
    let curSources: ResearchSourceLine[] = [];
    let curWebUrls: string[] = [];
    let curDealIds: string[] = [];

    chatStream(query, [], "research", (e) => {
      switch (e.type) {
        case "resolve":
          // Ambiguous customer → surface candidates; the rep picks BEFORE we
          // research, so we never summarize the wrong company's records.
          if (e.status === "ambiguous" && e.candidates?.length) setCandidates(e.candidates);
          break;
        case "deal_ids":
          curDealIds = [...curDealIds, ...e.deal_ids];
          setDealIds(curDealIds);
          break;
        case "source":
          curSources = [...curSources, { label: e.label, status: e.status, count: e.count }];
          setSources(curSources);
          break;
        case "web":
          if (e.results) {
            curWebUrls = [...curWebUrls, ...e.results.map(r => r.url).filter((u): u is string => !!u)];
            setWebUrls(curWebUrls);
          }
          break;
        case "delta":
          acc += e.text;
          setCommentary(acc);
          break;
        case "answer":
          // The research pipeline emits its synthesis as ONE answer event (not a
          // delta stream). Without this the card showed sources but no read.
          acc = e.text || acc;
          setCommentary(acc);
          break;
        case "unavailable":
        case "error":
          // Don't leave the card silent when the synthesis can't run — say so.
          if (!acc) setCommentary(lang === "ja"
            ? "（要約を生成できませんでした。ソースは上記のとおりです。）"
            : "(Couldn't generate the summary — sources are listed above.)");
          break;
      }
    }, { conversationId: artifact.threadId }).then(() => {
      setDone(true);
      setTimeout(() => setShowArtifact(true), 300);
      if (!collapsed) {
        collapseRef.current = setTimeout(() => setCollapsed(true), 1100);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Still ambiguous and nothing summarized yet → show ONLY the picker. Picking
  // resolves THIS turn in place (re-runs research grounded on the choice), so the
  // conversation stays in the same turn — same as the /review and /account picks.
  if (candidates.length > 0 && !commentary) {
    return (
      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-[0_4px_20px_-10px_rgba(16,24,40,0.2)]">
        <div className="flex items-center gap-1.5 border-b border-border px-3 py-2 text-[12px] font-medium text-muted-foreground">
          <Building2 className="h-3.5 w-3.5" />
          {candidates.length === 1
            ? (lang === "ja" ? "この顧客で合っていますか？" : "Did you mean this customer?")
            : (lang === "ja"
                ? "複数の顧客に一致しました。どの顧客を調べますか？"
                : "Several customers match — which one should I research?")}
        </div>
        <div className="flex flex-col">
          {candidates.map((c) => (
            <button
              key={c.customer_id}
              onClick={() => onPick(turnId, c)}
              className="flex items-center gap-2.5 px-3 py-2 text-left text-[13px] transition-colors hover:bg-muted/60"
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                <Building2 className="h-3 w-3 text-primary" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-medium text-foreground">{customerText(lang, c.name).text}</span>
                <span className="block font-mono text-[10.5px] text-muted-foreground">{c.customer_id}</span>
              </span>
            </button>
          ))}
        </div>
        <div className="border-t border-border px-3 py-1.5 bg-muted/10">
          <p className="text-[11px] text-muted-foreground">
            {lang === "ja"
              ? "選択するとこのリサーチがその顧客で読み込まれます。"
              : "Pick one and this same research fills in for that customer."}
          </p>
        </div>
      </div>
    );
  }

  // Prevent flashing before the first stream event arrives.
  if (candidates.length === 0 && sources.length === 0 && !commentary && !done) {
    return null;
  }

  const phases: ExecutionPhase[] = [];
  if (started || sources.length > 0) {
    phases.push({
      id: "researcher",
      label: lang === "ja" ? "データを収集・分析中" : "Gathering and analyzing data",
      emoji: "🔍",
      status: done ? "done" : "running",
      tools: sources.map(s => {
        let hint = "";
        if (s.status === "found") hint = lang === "ja" ? `${s.count ?? 1}件` : `Found ${s.count ?? 1}`;
        else if (s.status === "skipped") hint = lang === "ja" ? "スキップ" : "Skipped";
        else if (s.status === "not_found") hint = lang === "ja" ? "見つかりません" : "Not found";
        else if (s.status === "ambiguous") hint = lang === "ja" ? "複数該当" : "Ambiguous";
        else hint = s.status;
        return { name: s.label, summary: `${s.label}: ${hint}` };
      })
    });
  }

  const status: ArtifactStatus = done ? "ready" : "building";
  const merged = assembleResearchArtifact({
    threadId: artifact.threadId, turnId: artifact.turnId, live: artifact.live, lang,
    answer: commentary ?? "", sources, webUrls, entity, dealIds
  });
  merged.status = status;
  merged.id = artifact.id;

  return (
    <div className="flex flex-col gap-3 relative">
      <ExecutionTimeline
        phases={phases}
        collapsed={collapsed}
        onToggle={() => setCollapsed(!collapsed)}
        lang={lang}
      />
      {(showArtifact || done || commentary) && (
        <div className={cn("transition-all duration-700", !commentary ? "opacity-0" : "opacity-100 animate-fade-up")}>
          <ArtifactCard artifact={merged} />
        </div>
      )}
    </div>
  );
}

// A general chat turn. Streams one assistant reply over the SHARED thread
// conversation id, with the real prior turns threaded as history — so "what
// should I do about this?" sees the conversation (and the account a /review or
// /account brief put in focus on the server). No regex follow-up heuristic and
// no fake "[Context: …]" line: continuity is real conversation, not a guess.
//
// Renders the SAME grounded bubble as the standalone Assistant (tool ledger,
// grounding/routing badges, retrieval explorer, research source ledger, web
// citations, markdown) by capturing the full event stream into a Msg — so the
// Workspace chat is the Assistant, not a stripped single-shot.
const EMPTY_MSG: Msg = { role: "assistant", content: "", tools: [], status: "running" };

function ChatTurn({
  turnId, runId, message, history, role, conversationId, context, dealId, onDone, onPick,
}: {
  turnId: number; runId: number; message: string; history: ChatHistoryTurn[];
  role: "junior" | "manager"; conversationId: string; context?: string; dealId?: string;
  onDone: (text: string) => void;
  onPick: (c: ResolveCandidate, query: string) => void;
}) {
  const { t, lang } = useT();
  // Cache keys are namespaced by the CONVERSATION id, not just the integer
  // turnId. After Clear, thread.reset() mints a fresh conversation id and the
  // transcript empties, so turn ids restart from 1 — without the conversation
  // prefix a new turn id=1 would read the PREVIOUS thread's cached msg (with its
  // `started=true` flag) and render a stale answer instead of streaming a new one.
  // `runId` is bumped when an ambiguous turn is resolved by a pick, so the SAME
  // turn re-streams (grounded on the chosen customer) with a fresh cache slot.
  const [msg, setMsg] = useCachedState<Msg>(`ws:chat:${conversationId}:${turnId}:${runId}:msg`, EMPTY_MSG);
  const [started, setStarted] = useCachedState<boolean>(`ws:chat:${conversationId}:${turnId}:${runId}:started`, false);
  const startedRef = useRef(false);
  const ctrlRef = useRef<AbortController | null>(null);
  const abortedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current || started) return;
    startedRef.current = true;
    setStarted(true);
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;
    const patch = (fn: (m: Msg) => Msg) => setMsg((prev) => fn(prev));
    chatStream(message, history, role, (e) => {
      switch (e.type) {
        case "start":
          if (e.role === "research") patch((m) => ({ ...m, research: true, sources: [] }));
          break;
        // Fine-grained task DAG lifecycle — forwarded 1:1 from the real
        // orchestration engine (senpai/orchestration/events.py) whenever this
        // turn ran the document planner. One ExecutionPhase per task_id (the
        // task id IS the capability id, e.g. "crm"/"knowledge"/"documents" —
        // same ids message.tsx's TOOL_LABEL and agent-lane's PHASE_LABELS key
        // off), grouped by `group` ("gather" tasks run in parallel, then the
        // terminal "documents"/"workspace_write"/"workspace_organize" task).
        case "task_started":
          patch((m) => {
            const lanes = m.executionLanes ?? [];
            if (lanes.some((p) => p.id === e.task_id)) return m;
            const phase: ExecutionPhase = {
              id: e.task_id, label: e.summary || e.capability, emoji: "",
              status: "running", tools: [], group: e.group, startedAt: Date.now(),
            };
            return { ...m, executionLanes: [...lanes, phase] };
          });
          break;
        case "task_progress":
          patch((m) => ({
            ...m,
            executionLanes: (m.executionLanes ?? []).map((p) =>
              p.id === e.task_id ? { ...p, tools: [...p.tools, { name: e.task_id, summary: e.message }] } : p),
          }));
          break;
        case "task_evidence":
          patch((m) => ({
            ...m,
            executionLanes: (m.executionLanes ?? []).map((p) =>
              p.id === e.task_id
                ? { ...p, citationCount: e.citations?.length ?? 0,
                    resultHint: e.citations?.length ? `${e.citations.length}` : undefined }
                : p),
          }));
          break;
        case "group_completed":
          patch((m) => ({
            ...m,
            executionLanes: (m.executionLanes ?? []).map((p) =>
              p.group === e.group && p.status !== "done"
                ? { ...p, status: "done", endedAt: Date.now() }
                : p),
          }));
          break;
        case "tool":
          patch((m) => ({
            ...m,
            tools: [...m.tools, { name: e.name, args: e.args, result: e.result, document: e.document, documents: e.documents, crawl: e.crawl, crawlFrames: e.crawlFrames, batchId: e.batchId, intent: e.intent, outline: e.outline, internal: e.internal }],
            retrieval: e.retrieval ? [...(m.retrieval ?? []), ...e.retrieval] : m.retrieval,
          }));
          break;
        case "source":
          patch((m) => ({
            ...m, research: true,
            sources: [...(m.sources ?? []).filter((s) => s.key !== e.key),
              { key: e.key, label: e.label, status: e.status, count: e.count, detail: e.detail }],
          }));
          break;
        case "web":
          patch((m) => ({ ...m, webUrls: (e.results ?? []).filter((r) => r.url).map((r) => ({ title: r.title, url: r.url })) }));
          break;
        case "routing":
          patch((m) => ({ ...m, routing: { think: e.think, reason: e.reason, confidence: e.confidence, mode: e.mode } }));
          break;
        case "resolve":
          if (e.status === "ambiguous" && e.candidates?.length)
            patch((m) => ({ ...m, candidates: e.candidates, query: e.query }));
          break;
        case "delta":
          patch((m) => ({ ...m, content: m.content + e.text, status: "running" }));
          break;
        case "answer":
          patch((m) => ({ ...m, content: e.text || m.content, status: "done" }));
          break;
        case "done":
          // A turn that surfaced ambiguity candidates is a valid terminal state
          // even with no answer text — the picker IS the response, so it must not
          // be treated as an empty/failed turn.
          patch((m) => (m.status === "running" && (m.content || m.candidates?.length) ? { ...m, status: "done" } : m));
          break;
        case "unavailable":
        case "error":
          // An intentional stop ends the stream as an error too — keep whatever
          // streamed so far and mark it done, not failed. Candidates also count as
          // a successful end (the rep just needs to pick).
          patch((m) => ({ ...m, status: m.candidates?.length ? "done" : (abortedRef.current ? (m.content ? "done" : "error") : "error") }));
          break;
      }
    }, { conversationId, signal: ctrl.signal, context, dealId }).then(() => {
      ctrlRef.current = null;
      setMsg((prev) => {
        const final: Msg = prev.status === "running"
          ? { ...prev, status: (prev.content || prev.candidates?.length) ? "done" : "error" } : prev;
        onDone(final.content);
        return final;
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stop = () => { abortedRef.current = true; ctrlRef.current?.abort(); };
  const running = msg.status === "running";

  if (!msg.content && !msg.tools.length && !msg.sources?.length && !msg.executionLanes?.length && running) {
    return (
      <div className="flex items-center gap-2">
        <div className="inline-flex items-center gap-2 rounded-xl rounded-tl-sm border border-border bg-card px-4 py-3 text-[13px] text-muted-foreground shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
          <Dots /> <ThinkingText role={role} lang={lang} />
        </div>
        {ctrlRef.current && (
          <button onClick={stop} className="inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2.5 py-1.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground">
            <Square className="h-3 w-3" /> {t("assistant.stop")}
          </button>
        )}
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      <MessageBubble m={msg} t={t} lang={lang} onPick={(c) => onPick(c, msg.query ?? message)} />
      {running && ctrlRef.current && (
        <button onClick={stop} className="inline-flex items-center gap-1 rounded-lg border border-border bg-card px-2.5 py-1.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground">
          <Square className="h-3 w-3" /> {t("assistant.stop")}
        </button>
      )}
    </div>
  );
}

// Build the chat history the model sees from the visible transcript. User turns
// and prior chat answers go in verbatim; a skill turn contributes the senior's
// actual streamed read (labelled with its entity), so chat that follows a review
// or account brief has the real prior content — not a synthetic breadcrumb.
function buildChatHistory(messages: WMsg[]): ChatHistoryTurn[] {
  const h: ChatHistoryTurn[] = [];
  for (const m of messages) {
    if (m.role === "user") {
      h.push({ role: "user", content: m.text });
    } else if (m.role === "assistant" && m.answer) {
      h.push({ role: "assistant", content: m.answer });
    } else if (m.role === "skill") {
      const name = m.artifact.entity?.name;
      const head = m.kind === "review" ? "Review" : m.kind === "account_brief" ? "Account brief" : "Research";
      const label = name ? `${head} — ${name}` : head;
      const body =
        getCached<string>(`ws:art:${m.artifact.id}:narr`) ??
        getCached<string>(`ws:art:${m.artifact.id}:ans`) ?? "";
      h.push({ role: "assistant", content: body ? `[${label}]\n${body}` : `[${label}]` });
    }
  }
  return h;
}

// --- account ambiguity picker -----------------------------------------------
// Mirrors ReviewTurn's candidate button UI exactly: yellow warning banner +
// clickable pill buttons. The LLM-suggested best match is highlighted.
function AccountPickTurn({
  candidates,
  suggestedId,
  lang,
  onPick,
}: {
  candidates: AccountPickCandidate[];
  suggestedId?: string | null;
  lang: string;
  onPick: (customerId: string) => void;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-[0_4px_20px_-10px_rgba(16,24,40,0.2)]">
      <div className="flex items-center gap-1.5 border-b border-border px-3 py-2 text-[12px] font-medium text-muted-foreground">
        <Building2 className="h-3.5 w-3.5" />
        {lang === "ja"
          ? "複数の候補が見つかりました。どの会社ですか？"
          : "Several customers match — which one did you mean?"}
      </div>
      <div className="flex flex-col">
        {candidates.map((c) => {
          const isSuggested = c.customer_id === suggestedId;
          return (
            <button
              key={c.customer_id}
              onClick={() => onPick(c.customer_id)}
              className={cn(
                "flex items-center gap-2.5 px-3 py-2 text-left text-[13px] transition-colors",
                isSuggested ? "bg-primary/[0.07] hover:bg-primary/[0.12]" : "hover:bg-muted/60"
              )}
            >
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-primary/10">
                <Building2 className="h-3 w-3 text-primary" />
              </span>
              <span className="min-w-0 flex-1">
                <span className={cn("block font-medium", isSuggested ? "text-primary" : "text-foreground")}>
                  {c.name}
                  {isSuggested && (
                    <span className="ml-2 rounded-full bg-primary/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-primary">
                      {lang === "ja" ? "AI候補" : "AI pick"}
                    </span>
                  )}
                </span>
                <span className="block font-mono text-[10.5px] text-muted-foreground">{c.customer_id}</span>
              </span>
            </button>
          );
        })}
      </div>
      {suggestedId && (
        <div className="border-t border-border px-3 py-1.5 bg-muted/10">
          <p className="text-[11px] text-muted-foreground">
            {lang === "ja"
              ? "強調表示されているのはAIが最も可能性が高いと判断した候補です"
              : "The highlighted option is the AI's best guess — click to confirm"}
          </p>
        </div>
      )}
    </div>
  );
}

export function Workspace({
  examples, deals, principles = [], role = "junior", wide = false,
}: {
  examples: CoachExample[]; deals: DealRow[]; principles?: Principle[]; role?: "junior" | "manager";
  // When embedded in the Command Center we let the thread fill the available
  // width instead of the standalone reading column (max-w-3xl).
  wide?: boolean;
}) {
  const { t, lang } = useT();
  // The assistant's name differs by role: a junior gets a seasoned mentor
  // ("Senpai Coach"); a manager gets a peer staff voice ("Sales Analyst") — a
  // "senior coach" would talk down to someone who is already senior.
  const assistantName = t(role === "manager" ? "chat.assistant.manager" : "chat.assistant.junior");
  const [messages, setMessages] = useCachedState<WMsg[]>(`workspace:${role}:thread`, () => []);
  const [input, setInput] = useState("");
  const [dealId, setDealId] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPicker, setShowPicker] = useState(false);
  // An attached file's extracted text, pending until the next message is sent.
  // The chat is NOT a data-ingestion surface — the attachment is just context
  // the assistant answers over (structured ingestion lives on the Ingestion tab).
  const [attached, setAttached] = useState<{ fileName: string; text: string } | null>(null);
  const [attaching, setAttaching] = useState(false);
  // Mic dictation: record from the mic, then transcribe straight into the
  // composer (same /api/extract → Whisper path the audio-file attach uses).
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const thread = useCachedConversationId(`workspace:${role}:thread:id`);
  // Persistent chat history: the acting user (for per-user storage), the History
  // drawer's open state, and a tick bumped after each autosave so an open drawer
  // refreshes to show the live conversation.
  const { employeeId } = useSession();
  const [historyOpen, setHistoryOpen] = useState(false);
  const [savedTick, setSavedTick] = useState(0);

  // Shared focus from the Command Center's Context pane. When the rep clicks a
  // deal on the left, that deal becomes the grounding for the next turn — they
  // never have to touch the Deal selector below. We only mirror focus → the
  // local `dealId` when it actually changes, so the standalone Workspace (no
  // Context pane writing focus) behaves exactly as before, and a manual pick in
  // the selector isn't fought over on every render.
  const { focus, setFocus } = useWorkspaceFocus(role);
  const lastFocusDeal = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (focus.dealId && focus.dealId !== lastFocusDeal.current) {
      lastFocusDeal.current = focus.dealId;
      setDealId(focus.dealId);
    }
  }, [focus.dealId]);

  const idRef = useRef<number>(-1);
  if (idRef.current < 0) idRef.current = messages.reduce((mx, m) => Math.max(mx, m.id), 0) + 1;
  const nextId = () => idRef.current++;

  // --- Persistent chat history -------------------------------------------------
  const histRole: "junior" | "manager" = role === "manager" ? "manager" : "junior";

  // Serialize the whole conversation into the opaque blob the backend stores: the
  // transcript array plus every per-turn cache entry (streamed assistant text under
  // ws:chat:<cid>:, crew contributions under ws:crew:<cid>:, and each skill card's
  // artifact narration under ws:art:<artifactId>:) so a reopened chat rehydrates
  // full-fidelity. See the cache-key sites at workspace.tsx (ArtifactCard) and
  // crew-turn.tsx.
  function serializeThread(): string {
    const cid = thread.current;
    const prefixes = [`ws:chat:${cid}:`, `ws:crew:${cid}:`, `ws:intel:${cid}:`];
    for (const m of messages) {
      if (m.role === "skill" && m.artifact) prefixes.push(`ws:art:${m.artifact.id}:`);
    }
    const payload: StoredThread = {
      version: 1,
      messages,
      cache: snapshotByPrefix(prefixes),
      nextId: idRef.current,
      focus,
    };
    return JSON.stringify(payload);
  }

  function deriveTitle(): string {
    const first = messages.find((m) => m.role === "user") as { text?: string } | undefined;
    const text = (first?.text ?? "").trim().replace(/\s+/g, " ");
    if (!text) return lang === "ja" ? "無題のチャット" : "New chat";
    return text.length > 60 ? `${text.slice(0, 60)}…` : text;
  }

  // Autosave (debounced) after each completed turn. Skips while a turn is streaming
  // (busy) and skips transcripts without a real exchange. Failures are swallowed —
  // if the backend is down the chat still works ephemerally, just isn't persisted.
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!employeeId || busy) return;
    const hasUser = messages.some((m) => m.role === "user");
    const hasReply = messages.some(
      (m) => m.role === "assistant" || m.role === "skill" || m.role === "crew" || m.role === "intel",
    );
    if (!hasUser || !hasReply) return;
    const cid = thread.current;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      api
        .saveConversation(cid, {
          employee_id: employeeId,
          role: histRole,
          title: deriveTitle(),
          blob: serializeThread(),
          message_count: messages.length,
        })
        .then(({ live }) => {
          if (live) setSavedTick((n) => n + 1);
        });
    }, 800);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages, busy, employeeId, histRole]);

  // Reopen a saved conversation: rehydrate the transcript + all cached streamed
  // strings, adopt its id, and restore the id counter and focus.
  async function loadConversation(id: string) {
    if (busy) return;
    const { data } = await api.getConversation(id);
    if (!data) return;
    let parsed: StoredThread;
    try {
      parsed = JSON.parse(data.blob) as StoredThread;
    } catch {
      return;
    }
    if (!parsed || parsed.version !== 1) return;
    restoreCached(parsed.cache ?? {});
    thread.set(id);
    idRef.current =
      typeof parsed.nextId === "number"
        ? parsed.nextId
        : (parsed.messages ?? []).reduce((mx, m) => Math.max(mx, m.id), 0) + 1;
    setMessages(parsed.messages ?? []);
    setFocus(parsed.focus ?? {});
    setInput("");
    setDealId("");
    setHistoryOpen(false);
  }

  const bottomRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const pickerRef = useRef<SlashPickerHandle>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  // Attach a file as chat context — extract its text (voice→transcript,
  // image→OCR, or a plain-text file read client-side) and hold it as a pending
  // chip. On the next send, the text rides along as context the assistant
  // answers over. No structured ingestion here — that's the Ingestion tab.
  async function attachFile(file: File) {
    if (attaching || busy) return;
    setAttaching(true);
    let payload: { audio?: File; image?: File; text?: string };
    if (file.type.startsWith("audio")) payload = { audio: file };
    else if (file.type.startsWith("image")) payload = { image: file };
    else payload = { text: await file.text() };  // .txt/.md/.csv etc.
    const { data } = await api.extract(payload);
    setAttaching(false);
    if (data?.raw_text) {
      setAttached({ fileName: file.name, text: data.raw_text });
      composerRef.current?.focus();
    } else {
      setAttached({ fileName: file.name, text: "" });
    }
  }

  // Start/stop mic dictation. On stop, the recorded clip is sent to
  // /api/extract (Whisper) and the transcript is appended to the composer so
  // the user can review/edit before sending — no auto-send.
  async function toggleRecording() {
    if (transcribing || busy || attaching) return;
    if (recording) {
      recorderRef.current?.stop();  // fires onstop → transcribe
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setAttached({ fileName: t("mic.denied"), text: "" });
      return;
    }
    // Pick a container the browser actually supports (Safari lacks webm).
    const mime = ["audio/webm", "audio/mp4", "audio/ogg"].find(
      (m) => typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(m),
    );
    const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
    recorder.onstop = async () => {
      stream.getTracks().forEach((tk) => tk.stop());  // release the mic
      setRecording(false);
      const type = recorder.mimeType || "audio/webm";
      const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
      const blob = new Blob(chunks, { type });
      if (blob.size === 0) return;
      setTranscribing(true);
      const file = new File([blob], `dictation.${ext}`, { type });
      const { data } = await api.extract({ audio: file });
      setTranscribing(false);
      const text = data?.raw_text?.trim();
      if (text) {
        setInput((prev) => (prev ? `${prev} ${text}` : text));
        composerRef.current?.focus();
      }
    };
    recorderRef.current = recorder;
    recorder.start();
    setRecording(true);
  }

  async function runReview(note: string, deal: string) {
    const clean = note.trim();
    if (!clean || busy) return;
    const dealLabel = deal ? deals.find((d) => d.deal_id === deal)?.customer : undefined;
    const loadingId = nextId();
    setMessages((m) => [
      ...m,
      { id: nextId(), role: "user", text: clean, dealLabel },
      { id: loadingId, role: "loading" },
    ]);
    setInput("");
    setBusy(true);
    const { data, live } = await api.coach(clean, deal || undefined);
    const d = deals.find((x) => x.deal_id === deal);
    const entity: EntityRef | undefined = deal
      ? { type: "deal", id: deal, name: d?.customer }
      : undefined;
    const artifact = assembleReviewArtifact(data, {
      threadId: thread.current, turnId: String(loadingId), live, entity,
    });
    setMessages((m) =>
      m.map((msg) =>
        msg.id === loadingId
          ? { id: loadingId, role: "skill", kind: "review", note: clean, dealId: deal || undefined, artifact }
          : msg,
      ),
    );
    setBusy(false);
  }

  async function runAccount(nameOrId: string) {
    const clean = nameOrId.trim();
    if (!clean || busy) return;
    const loadingId = nextId();
    setMessages((m) => [
      ...m,
      { id: nextId(), role: "user", text: `/account ${clean}` },
      { id: loadingId, role: "loading" },
    ]);
    setInput("");
    setBusy(true);

    // Smart resolve: deterministic → fuzzy near-miss → LLM ranking in one call.
    // Progressive prefix stripping is still applied first so "C06 tell me more"
    // gets the right query token ("C06") before hitting the smart resolver.
    const words = clean.split(/\s+/);
    let smartRes: { status: string; customer?: { customer_id: string }; candidates?: { customer_id: string; name: string }[]; suggested_id?: string | null } | null = null;
    let resolvedWith = clean;

    for (let len = words.length; len >= 1; len--) {
      const query = words.slice(0, len).join(" ");
      // Use fast deterministic resolve first; only call smart-resolve if ambiguous/not_found
      const { data: quick } = await api.resolveCustomer(query);
      if (quick.status === "resolved") {
        smartRes = quick;
        resolvedWith = query;
        break;
      }
      if (quick.status === "ambiguous" || len === 1) {
        // Hit ambiguous or exhausted prefixes → use smart-resolve for LLM ranking
        const { data: smart } = await api.smartResolveCustomer(query, lang);
        smartRes = smart;
        resolvedWith = query;
        break;
      }
    }

    if (!smartRes || smartRes.status === "not_found") {
      setMessages((m) => m.map(msg => msg.id === loadingId
        ? { id: loadingId, role: "system" as const, text: lang === "ja" ? `「${clean}」は見つかりませんでした` : `Customer not found: ${clean}` }
        : msg));
      setBusy(false);
      return;
    }

    if (smartRes.status === "ambiguous" && smartRes.candidates?.length) {
      // Show clickable picker instead of a dead-end text message
      setMessages((m) => m.map(msg => msg.id === loadingId
        ? { id: loadingId, role: "account_pick" as const, query: resolvedWith, candidates: smartRes!.candidates!, suggestedId: smartRes!.suggested_id }
        : msg));
      setBusy(false);
      return;
    }

    const customerId = smartRes.customer?.customer_id || smartRes.candidates?.[0]?.customer_id || resolvedWith;
    await _loadAccountById(customerId, loadingId);
  }

  async function _loadAccountById(customerId: string, loadingId: number) {
    const { data: acct, live } = await api.account(customerId);
    if (!acct) {
      setMessages((m) => m.map(msg => msg.id === loadingId
        ? { id: loadingId, role: "system" as const, text: lang === "ja" ? "アカウント情報の取得に失敗しました" : "Error loading account" }
        : msg));
      setBusy(false);
      return;
    }
    const artifact = assembleAccountArtifact(acct, { threadId: thread.current, turnId: String(loadingId), live, lang });
    setMessages((m) => m.map(msg => msg.id === loadingId
      ? { id: loadingId, role: "skill" as const, kind: "account_brief", customerId, artifact }
      : msg));
    setBusy(false);
  }

  async function runResearch(query: string, deal: string) {
    const clean = query.trim();
    if (!clean || busy) return;
    const loadingId = nextId();
    setMessages((m) => [
      ...m,
      { id: nextId(), role: "user", text: `/research ${clean}` },
      { id: loadingId, role: "loading" },
    ]);
    setInput("");
    setBusy(true);
    
    const d = deals.find((x) => x.deal_id === deal);
    const entity: EntityRef | undefined = deal
      ? { type: "deal", id: deal, name: d?.customer }
      : undefined;
      
    const artifact = assembleResearchArtifact({
      threadId: thread.current, turnId: String(loadingId), live: true, lang,
      answer: "", sources: [], webUrls: [], entity
    });
    
    setMessages((m) => m.map(msg => msg.id === loadingId ? { id: loadingId, role: "skill", kind: "research", query: clean, entity, artifact } : msg));
    setBusy(false);
  }

  // Trigger an inline multi-agent crew the way you'd invoke a sub-agent: a single
  // contained turn that streams the agents working. /crew <customer|deal> analyses
  // one deal; /team (manager) fans out one analyst per rep. No new endpoint round
  // trip here — CrewTurn opens the stream itself and caches its own state.
  function runCrew(body: string, deal: string) {
    const clean = body.trim();
    const d = deal ? deals.find((x) => x.deal_id === deal) : undefined;
    const query = clean || (d ? `${d.deal_id} ${d.customer}` : "");
    if (!query) return;
    const id = nextId();
    setMessages((m) => [
      ...m,
      { id: nextId(), role: "user", text: `/crew ${query}` },
      { id, role: "crew", mode: "deal", query, label: d?.customer },
    ]);
    setInput("");
    setDealId("");
  }

  function runTeam() {
    const id = nextId();
    setMessages((m) => [
      ...m,
      { id: nextId(), role: "user", text: "/team" },
      { id, role: "crew", mode: "team" },
    ]);
    setInput("");
    setDealId("");
  }

  function runIntel(query: string) {
    const clean = query.trim();
    if (!clean || busy) return;
    const id = nextId();
    setMessages((m) => [
      ...m,
      { id: nextId(), role: "user", text: `/intel ${clean}` },
      { id, role: "intel", query: clean },
    ]);
    setInput("");
  }

  function runChat(text: string, deal?: string) {
     const clean = text.trim();
     if (!clean || busy) return;
     // Snapshot the conversation BEFORE appending this turn, so the assistant
     // turn carries the real prior history (shared thread context lives on the
     // server, keyed by thread.current).
     const history = buildChatHistory(messages);
     const replyId = nextId();
     // An attached file's text rides along as context for THIS turn only, then
     // the chip clears (it is not persisted into thread history).
     const ctx = attached?.text || undefined;
     // A deal picked from the Deal selector grounds the turn as a STRUCTURED field
     // (dealId), not by appending prose to the message. The backend scopes to that
     // exact deal directly — the model never has to re-resolve it from prose, and
     // the message it reasons over stays clean. The user bubble shows a deal badge.
     const d = deal ? deals.find((x) => x.deal_id === deal) : undefined;
     const userText = attached ? `📎 ${attached.fileName} — ${clean}` : clean;
     setMessages((m) => [
       ...m,
       { id: nextId(), role: "user", text: userText, dealLabel: d?.customer },
       { id: replyId, role: "assistant", text: clean, history, context: ctx, dealId: d?.deal_id },
     ]);
     setInput("");
     setAttached(null);
  }

  // Clear the conversation: empty the transcript and mint a fresh thread id so
  // the server-side conversation context (account in focus, history) starts clean.
  function clearThread() {
    if (busy) return;
    setMessages([]);
    setInput("");
    setDealId("");
    thread.reset();
  }

  function submit(raw: string, deal: string) {
    const p = parseInput(raw);
    if (p.command && !p.known) {
      setMessages((m) => [
        ...m,
        { id: nextId(), role: "user", text: raw.trim() },
        {
          id: nextId(), role: "system",
          text: lang === "ja"
            ? `/${p.command} は見つかりません。`
            : `/${p.command} is unknown.`,
        },
      ]);
      setInput("");
      return;
    }
    
    if (p.command === "review") {
      runReview(p.body, deal);
    } else if (p.command === "account") {
      runAccount(p.body);
    } else if (p.command === "research") {
      runResearch(p.body, deal);
    } else if (p.command === "crew") {
      runCrew(p.body, deal);
    } else if (p.command === "team") {
      runTeam();
    } else if (p.command === "intel") {
      runIntel(p.body);
    } else {
      runChat(p.body || raw.trim(), deal);
    }
    setDealId("");
  }

  // Picking an ambiguous candidate resolves the SAME review turn in place: re-run
  // the coach grounded on the chosen deal (or, if it has no open deal, on the full
  // name so it resolves uniquely) and swap in the grounded artifact. Because the
  // artifact id changes, ReviewTurn (keyed on it) remounts and streams the senior's
  // read for the chosen customer — no new user bubble, no second card, same thread.
  async function onPick(turnId: number, deal: string, name: string) {
    if (busy) return;
    const target = messages.find(
      (m): m is Extract<WMsg, { role: "skill"; kind: "review" }> =>
        m.id === turnId && m.role === "skill" && m.kind === "review",
    );
    const baseNote = target?.note ?? "";
    const groundNote = deal ? baseNote : `${name} ${baseNote}`.trim();
    setBusy(true);
    const { data, live } = await api.coach(groundNote, deal || undefined);
    const d = deals.find((x) => x.deal_id === deal);
    const entity: EntityRef | undefined = deal ? { type: "deal", id: deal, name: d?.customer } : undefined;
    const artifact = assembleReviewArtifact(data, {
      threadId: thread.current, turnId: String(turnId), live, entity,
    });
    setMessages((m) =>
      m.map((msg) =>
        msg.id === turnId && msg.role === "skill" && msg.kind === "review"
          ? { id: turnId, role: "skill", kind: "review", note: groundNote, dealId: deal || undefined, artifact }
          : msg,
      ),
    );
    setBusy(false);
  }

  // Picking an ambiguous candidate on a CHAT turn resolves in place: re-run the
  // same assistant turn grounded on the chosen customer (name prefixed so it
  // resolves uniquely) by bumping `runId` — ChatTurn is keyed on it, so it
  // remounts with a fresh cache slot and streams the grounded answer into the
  // same turn. No new user bubble; mirrors the /review, /account, /research picks.
  function onPickChat(turnId: number, c: ResolveCandidate, query: string) {
    setMessages((m) =>
      m.map((msg) =>
        msg.id === turnId && msg.role === "assistant"
          ? { ...msg, text: `${c.name} ${query}`.trim(), answer: undefined, runId: (msg.runId ?? 0) + 1 }
          : msg,
      ),
    );
  }

  // Picking a research candidate resolves the SAME research turn in place: re-run
  // grounded on the chosen customer (name prefixed so it resolves uniquely) and
  // swap in a fresh artifact. The artifact id changes, so ResearchTurn (keyed on
  // it) remounts and re-streams — no new user bubble, same thread/turn. Mirrors
  // the /review and /account in-place picks.
  function onPickResearch(turnId: number, c: ResolveCandidate) {
    const target = messages.find(
      (m): m is Extract<WMsg, { role: "skill"; kind: "research" }> =>
        m.id === turnId && m.role === "skill" && m.kind === "research",
    );
    const baseQuery = target?.query ?? "";
    const groundQuery = `${c.name} ${baseQuery}`.trim();
    const entity: EntityRef = { type: "account", id: c.customer_id, name: c.name };
    const artifact = assembleResearchArtifact({
      threadId: thread.current, turnId: String(turnId), live: true, lang,
      answer: "", sources: [], webUrls: [], entity,
    });
    setMessages((m) =>
      m.map((msg) =>
        msg.id === turnId && msg.role === "skill" && msg.kind === "research"
          ? { id: turnId, role: "skill", kind: "research", query: groundQuery, entity, artifact }
          : msg,
      ),
    );
  }

  return (
    <div className={cn("mx-auto flex h-full w-full flex-col min-h-0", wide ? "max-w-5xl" : "max-w-3xl")}>
      {/* Conversation controls pinned to the top of the chat pane, where
          they are immediately discoverable — instead of being buried inside the
          composer toolbar next to Mic/Attach/Send. */}
      <div className="flex items-center justify-between shrink-0 pt-3 pb-2 pr-1">
        <div>
          <button
            onClick={clearThread}
            disabled={busy}
            title={lang === "ja" ? "新しい会話" : "New chat"}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground hover:bg-muted disabled:opacity-50"
          >
            <SquarePen className="h-3.5 w-3.5" />
            <span className="font-medium">{lang === "ja" ? "新規" : "New chat"}</span>
          </button>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setHistoryOpen(true)}
            title={lang === "ja" ? "チャット履歴" : "Chat history"}
            className="inline-flex h-8 items-center gap-1 rounded-lg border border-border bg-card px-2.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground hover:bg-muted"
          >
            <History className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{lang === "ja" ? "履歴" : "History"}</span>
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto space-y-8 pb-6 pr-1 pt-1 min-h-0">
        {messages.length === 0 && (
          <div className="pt-1.5 pb-6">
            <p className="text-[15px] font-medium tracking-tight text-foreground">
              {lang === "ja" ? "Senpai ワークスペース" : "Senpai Workspace"}
            </p>
            <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">
              {lang === "ja"
                ? "顧客を調査する、商談をレビューする、戦略を立案する。"
                : "Investigate a customer, review a deal, build a strategy."}
            </p>

            <div className="mt-6">
              <div className="eyebrow mb-2.5">
                {lang === "ja" ? "スキルのショートカット" : "Skill shortcuts"}
              </div>
              <div className="flex flex-col gap-1">
                {[
                  {
                    chip: "/review",
                    hint: lang === "ja" ? "商談メモを貼り付けてレビュー" : "Paste a meeting note and review it",
                    value: "/review ",
                  },
                  {
                    chip: "/account Matsuda Office",
                    hint: lang === "ja" ? "松田事務所の顧客ブリーフを取得" : "Pull account brief for Matsuda Office",
                    value: "/account Matsuda Office",
                  },
                  {
                    chip: "/research discount strategy",
                    hint: lang === "ja" ? "値引き戦略を社内記録+Webで調査" : "Research discount strategy across internal + web",
                    value: "/research discount strategy",
                  },
                  {
                    chip: "/crew D168",
                    hint: lang === "ja" ? "案件D168の攻略プランを作成" : "Build a strategy for deal D168",
                    value: "/crew D168",
                  },
                  {
                    chip: "/team",
                    hint: lang === "ja" ? "要注意案件とパイプライン概況を確認" : "Review at-risk deals and pipeline status",
                    value: "/team",
                  },
                ].filter(s => role === "manager" || s.chip !== "/team").map((s) => (
                  <button
                    key={s.chip}
                    disabled={busy}
                    onClick={() => {
                      setInput(s.value);
                      setShowPicker(false);
                      composerRef.current?.focus();
                    }}
                    className="flex items-center gap-2.5 rounded-lg border border-border bg-card px-3 py-2 text-left font-mono text-[12.5px] transition-colors hover:border-primary/40 hover:bg-primary/[0.03] disabled:opacity-50 shadow-sm"
                  >
                    <span className="font-semibold text-foreground">{s.chip}</span>
                    <span className="ml-auto text-[11px] font-sans text-muted-foreground">{s.hint}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {messages.map((m) => {
          if (m.role === "user") {
            return (
              <Row key={m.id} who="user" name={t("chat.you")}>
                <div className="py-0.5">
                  {m.dealLabel && (
                    <Badge variant="accent" className="mb-2 font-jp">{m.dealLabel}</Badge>
                  )}
                  <span className="block whitespace-pre-wrap text-[13.5px] leading-relaxed text-foreground/90">{m.text}</span>
                </div>
              </Row>
            );
          }
          if (m.role === "system") {
            return (
              <Row key={m.id} who="senpai" name={assistantName}>
                <p className="py-0.5 text-[13px] leading-relaxed text-muted-foreground">
                  {m.text}
                </p>
              </Row>
            );
          }
          if (m.role === "loading") {
            return (
              <Row key={m.id} who="senpai" name={assistantName}>
                <div className="inline-flex items-center gap-2 py-1.5 text-[13px] text-muted-foreground">
                  <Dots /> <ThinkingText role={role} lang={lang} />
                </div>
              </Row>
            );
          }
          if (m.role === "assistant") {
            return (
              <Row key={m.id} who="senpai" name={assistantName}>
                <ChatTurn
                  key={`${m.id}:${m.runId ?? 0}`}
                  turnId={m.id}
                  runId={m.runId ?? 0}
                  message={m.text}
                  history={m.history}
                  role={role}
                  conversationId={thread.current}
                  context={m.context}
                  dealId={m.dealId}
                  onDone={(text) =>
                    setMessages((prev) => prev.map((msg) => (msg.id === m.id ? { ...msg, answer: text } : msg)))
                  }
                  onPick={(c, q) => onPickChat(m.id, c, q)}
                />
              </Row>
            );
          }
          if (m.role === "account_pick") {
            return (
              <Row key={m.id} who="senpai" name={assistantName}>
                <AccountPickTurn
                  candidates={m.candidates}
                  suggestedId={m.suggestedId}
                  lang={lang}
                  onPick={(customerId) => {
                    if (busy) return;
                    setBusy(true);
                    // Resolve in place: turn THIS picker turn into the loading →
                    // account brief, with no new "/account <id>" user bubble and
                    // no extra turn — mirrors the in-place /review candidate pick
                    // so the conversation stays in the same turn for both skills.
                    setMessages((prev) => prev.map((msg) =>
                      msg.id === m.id ? { id: m.id, role: "loading" as const } : msg));
                    _loadAccountById(customerId, m.id);
                  }}
                />
              </Row>
            );
          }
          if (m.role === "skill") {
            return (
              <Row key={m.id} who="senpai" name={assistantName}>
                {m.kind === "review" && <ReviewTurn key={m.artifact.id} turnId={m.id} artifact={m.artifact} note={m.note} dealId={m.dealId} principles={principles} onPick={onPick} />}
                {m.kind === "account_brief" && <AccountTurn key={m.artifact.id} artifact={m.artifact} customerId={m.customerId} />}
                {m.kind === "research" && <ResearchTurn key={m.artifact.id} turnId={m.id} artifact={m.artifact} query={m.query} entity={m.entity} onPick={onPickResearch} />}
              </Row>
            );
          }
          if (m.role === "crew") {
            return (
              <CrewTurn key={m.id} turnId={m.id} conversationId={thread.current} mode={m.mode} query={m.query} label={m.label} />
            );
          }
          if (m.role === "intel") {
            return (
              <IntelTurn key={m.id} turnId={m.id} conversationId={thread.current} query={m.query} />
            );
          }
          return null;
        })}

        <div ref={bottomRef} />
      </div>

      {/* composer */}
      <div className="sticky bottom-0 -mx-1 bg-background/85 px-1 pb-4 pt-3 backdrop-blur">
        <div className="relative">
          {showPicker && (
            <SlashPicker
              ref={pickerRef}
              input={input}
              lang={lang}
              role={role}
              onSelect={(cmd) => {
                setInput(cmd);
                setShowPicker(false);
                composerRef.current?.focus();
              }}
              onClose={() => setShowPicker(false)}
            />
          )}
          <div className="rounded-2xl border border-border bg-card p-2.5 shadow-[0_8px_30px_-22px_rgba(16,24,40,0.45)] focus-within:border-primary/40">
            {attached && (
              <div className="mb-2 flex items-center gap-2 rounded-lg border border-border bg-muted/50 px-2.5 py-1.5">
                <Paperclip className="h-3.5 w-3.5 shrink-0 text-navy" />
                <span className="truncate font-mono text-[11px] text-foreground">{attached.fileName}</span>
                {attached.text
                  ? <span className="shrink-0 text-[10.5px] text-muted-foreground">{t("attach.chars", { n: String(attached.text.length) })}</span>
                  : <span className="shrink-0 text-[10.5px] text-band-red">{t("attach.empty")}</span>}
                <button
                  onClick={() => setAttached(null)}
                  title={t("attach.remove")}
                  className="ml-auto inline-flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
            <Textarea
              ref={composerRef}
              value={input}
              onChange={(e) => {
                const v = e.target.value;
                setInput(v);
                // Show picker whenever the input looks like a partial slash command
                // (starts with "/" and no space after the command word yet).
                const isPartialSlash = /^\/[a-z]*$/i.test(v.trim());
                setShowPicker(isPartialSlash);
              }}
              onKeyDown={(e) => {
                if (showPicker && pickerRef.current) {
                  const consumed = pickerRef.current.handleKey(e);
                  if (consumed) return;
                }
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit(input, dealId);
                }
              }}
              placeholder={lang === "ja" ? "/review, /account, /research … または質問を入力" : "Type / to pick a skill, or ask a question…"}
              className="min-h-[64px] resize-none border-0 bg-transparent font-jp shadow-none focus-visible:ring-0"
            />
            <div className="flex items-center justify-between gap-2 px-1 pt-1">
              {/* Grounds /review (and /research) on a deal. Single source of
                  truth with the Context pane via shared focus: a deal clicked on
                  the left shows here as one chip; ✕ drops the grounding. When
                  nothing is focused, a compact picker lets standalone callers
                  (e.g. the Manager workspace, which has no Context pane) attach
                  one — and that selection writes focus too, so they stay synced. */}
              {dealId ? (
                <span className="flex h-8 max-w-[62%] items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/[0.06] pl-2.5 pr-1 text-[12px] text-primary">
                  <Paperclip className="h-3.5 w-3.5 shrink-0" />
                  {/* Canonical Japanese company name regardless of UI lang. */}
                  <span className="truncate font-jp">{deals.find((d) => d.deal_id === dealId)?.customer ?? dealId}</span>
                  <button
                    type="button"
                    title={lang === "ja" ? "対象の案件を解除" : "Clear focused deal"}
                    onClick={() => {
                      setDealId("");
                      setFocus({});
                      lastFocusDeal.current = undefined;
                    }}
                    className="ml-0.5 shrink-0 rounded p-1 transition-colors hover:bg-primary/10"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </span>
              ) : (
                <label
                  title={lang === "ja" ? "レビュー対象の案件を指定（任意）" : "Attach a deal to ground /review (optional)"}
                  className="flex h-8 max-w-[62%] items-center gap-1.5 rounded-lg border border-input bg-muted/40 pl-2.5 pr-1 text-[12px] text-muted-foreground transition-colors focus-within:border-primary/50"
                >
                  <Building2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
                  <span className="hidden shrink-0 sm:inline">{lang === "ja" ? "案件" : "Deal"}</span>
                  <select
                    value=""
                    onChange={(e) => {
                      const id = e.target.value;
                      if (!id) return;
                      const d = deals.find((x) => x.deal_id === id);
                      setDealId(id);
                      setFocus({ dealId: id, customerId: d?.customer_id, customerName: d?.customer });
                      lastFocusDeal.current = id;
                    }}
                    className="h-8 min-w-0 flex-1 cursor-pointer bg-transparent pr-1 text-[12px] outline-none [&>option]:text-foreground"
                  >
                    <option value="">{lang === "ja" ? "案件を指定（任意）" : "Attach a deal…"}</option>
                    {deals.map((d) => (
                      <option key={d.deal_id} value={d.deal_id}>
                        {d.deal_id} · {d.customer}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <div className="flex items-center gap-2">
                {/* Attach a file as context — its text is extracted (POST
                    /api/extract) and the assistant answers over it. Structured
                    data ingestion is a separate flow (Data Ingestion tab). */}
                <input
                  ref={fileRef}
                  type="file"
                  accept="audio/*,image/*,text/*,.txt,.md,.csv"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) attachFile(f);
                    e.target.value = "";
                  }}
                />
                {/* Mic dictation — record, then transcribe straight into the
                    composer via the same Whisper path as the audio attach. */}
                <button
                  onClick={toggleRecording}
                  disabled={busy || attaching || transcribing}
                  title={recording ? t("mic.stop") : t("mic.start")}
                  className={cn(
                    "inline-flex h-8 items-center gap-1 rounded-lg border px-2.5 text-[12px] transition-colors disabled:opacity-50",
                    recording
                      ? "border-band-red/40 bg-band-red/10 text-band-red"
                      : "border-border bg-card text-muted-foreground hover:text-foreground",
                  )}
                >
                  {transcribing
                    ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    : recording
                      ? <Square className="h-3.5 w-3.5 animate-pulse fill-current" />
                      : <Mic className="h-3.5 w-3.5" />}
                  <span className="hidden sm:inline">
                    {transcribing ? t("mic.transcribing") : recording ? t("mic.stop") : t("mic.short")}
                  </span>
                </button>
                <button
                  onClick={() => fileRef.current?.click()}
                  disabled={busy || attaching}
                  title={t("attach.title")}
                  className="inline-flex h-8 items-center gap-1 rounded-lg border border-border bg-card px-2.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
                >
                  {attaching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Paperclip className="h-3.5 w-3.5" />}
                  <span className="hidden sm:inline">{t("attach.short")}</span>
                </button>
                {messages.length > 0 && (
                  <button
                    onClick={clearThread}
                    disabled={busy}
                    title={lang === "ja" ? "クリア" : "Clear"}
                    className="inline-flex h-8 items-center gap-1 rounded-lg border border-border bg-card px-2.5 text-[12px] text-muted-foreground transition-colors hover:text-foreground hover:bg-muted disabled:opacity-50"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                    <span className="hidden sm:inline">{lang === "ja" ? "クリア" : "Clear"}</span>
                  </button>
                )}
                <Button variant="seal" size="sm" disabled={busy || (!input.trim() && !attached)} onClick={() => submit(input, dealId)} className="gap-1.5">
                  {t(role === "manager" ? "chat.send.manager" : "chat.send")} <CornerDownLeft className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        employeeId={employeeId}
        role={histRole}
        activeId={thread.current}
        reloadSignal={savedTick}
        onSelect={loadConversation}
        onDeletedActive={clearThread}
      />
    </div>
  );
}
````

## File: web/components/assistant/message.tsx
````typescript
"use client";

// Shared assistant message renderer.
//
// The grounded chat bubble — tool/grounding ledger, retrieval explorer, research
// source ledger, routing badge, web citations and markdown answer — extracted
// from the Assistant so the unified Workspace chat renders identically. One
// renderer, one trust surface: "grounded, not a chatbot" looks the same wherever
// chat appears.

import { useEffect, useState } from "react";
import {
  AlertTriangle, BookMarked, Brain, Building2, Calendar, Database, Download, ExternalLink,
  FileSpreadsheet, FileText, Globe, Layers, Loader2, Mail, Package, Presentation, Receipt, Route, Search,
  ShieldCheck, Sparkles, UserSearch, Wrench, Zap, ChevronRight, ChevronDown, FolderTree, type LucideIcon,
} from "lucide-react";
import { documentUrl, type ResolveCandidate, type RetrievalTrace, type CrawlPage, type CrawlFrame } from "@/lib/api";
import type { GeneratedDocument } from "@/lib/types";
import { cn } from "@/lib/utils";
import { RetrievalExplorer } from "@/components/assistant/retrieval-explorer";
import { CrawlReplay } from "@/components/assistant/crawl-replay";
import { downloadMessageAsDocx, downloadMessageAsXlsx } from "@/lib/artifact-export";


export type ToolCall = { name: string; args: string; result: string; document?: GeneratedDocument; crawl?: CrawlPage[]; crawlFrames?: CrawlFrame[]; batchId?: string | null; intent?: string; outline?: { title: string }[]; internal?: boolean };
export type SourceState = {
  key: string; label: string;
  status: "found" | "not_found" | "ambiguous" | "skipped" | "error";
  count?: number; detail?: string;
};
export type WebCitation = { title?: string; url?: string };
export type Msg = {
  role: "user" | "assistant";
  content: string;
  tools: ToolCall[];
  status?: "running" | "done" | "error";
  research?: boolean;         // turn was routed to the research pipeline
  sources?: SourceState[];    // research source ledger
  webUrls?: WebCitation[];    // external citations
  retrieval?: RetrievalTrace[]; // retrieval explorer trace (per-chunk provenance)
  routing?: { think: boolean; reason: string; confidence: number; mode: "reasoning" | "fast" };
  candidates?: ResolveCandidate[]; // ambiguous customer — surfaced for the user to pick
  query?: string;                  // the original message, so a pick can re-ask scoped
};

// Human labels + icons for each tool, so the grounding ledger reads like
// evidence ("社内ナレッジ照会") rather than a function name. `internal: false`
// marks the only non-grounded source (the open web).
export const TOOL_LABEL: Record<string, { ja: string; en: string; icon: LucideIcon; internal?: boolean }> = {
  query_spr: { ja: "社内の顧客・案件", en: "Internal records", icon: Database, internal: true },
  find_similar_deals: { ja: "類似案件", en: "Similar deals", icon: Layers, internal: true },
  retrieve_playbook: { ja: "プレイブック", en: "Playbook", icon: BookMarked, internal: true },
  search_knowledge: { ja: "社内ナレッジ照会", en: "Internal knowledge", icon: ShieldCheck, internal: true },
  search_solutions: { ja: "ソリューション・製品情報", en: "Solution & product info", icon: Package, internal: true },
  lookup_customer_environment: { ja: "IT環境", en: "IT environment", icon: Building2, internal: true },
  get_product_info: { ja: "製品情報", en: "Product info", icon: BookMarked, internal: true },
  search_products: { ja: "製品検索", en: "Product search", icon: Search, internal: true },
  create_quote: { ja: "見積作成", en: "Quote", icon: Receipt, internal: true },
  score_deal_health: { ja: "案件健全度", en: "Deal health", icon: AlertTriangle, internal: true },
  draft_daily_report: { ja: "日報下書き", en: "Daily report", icon: FileText, internal: true },
  schedule_meeting: { ja: "打合せ調整", en: "Schedule", icon: Calendar, internal: true },
  send_email: { ja: "メール下書き", en: "Email draft", icon: Mail, internal: true },
  get_calendar: { ja: "予定確認", en: "Calendar", icon: Calendar, internal: true },
  route_to_expert: { ja: "専門家へ橋渡し", en: "Route to expert", icon: Route, internal: true },
  get_seasonal_context: { ja: "時期・予算", en: "Seasonal context", icon: Calendar, internal: true },
  list_at_risk_deals: { ja: "リスク案件一覧", en: "At-risk deals", icon: AlertTriangle, internal: true },
  team_pipeline_overview: { ja: "パイプライン概況", en: "Pipeline overview", icon: Database, internal: true },
  team_report_digest: { ja: "日報ダイジェスト", en: "Report digest", icon: FileText, internal: true },
  rep_coaching_focus: { ja: "コーチング対象", en: "Coaching focus", icon: UserSearch, internal: true },
  draft_message: { ja: "メッセージ下書き", en: "Message draft", icon: Mail, internal: true },
  generate_proposal: { ja: "提案書(PPTX)生成", en: "Proposal (PPTX)", icon: Presentation, internal: true },
  generate_ringisho: { ja: "稟議書(DOCX)生成", en: "Ringi-sho (DOCX)", icon: FileText, internal: true },
  // General-purpose authoring tools: NOT inherently grounded in internal data —
  // they build from a free prompt (+ optional web). Only generate_proposal /
  // generate_ringisho are deal-grounded, so don't let these falsely claim
  // "grounded in internal data" on a generic deck.
  generate_pptx: { ja: "プレゼン(PPTX)生成", en: "Slides (PPTX)", icon: Presentation, internal: false },
  generate_docx: { ja: "文書(DOCX)生成", en: "Document (DOCX)", icon: FileText, internal: false },
  web_search: { ja: "Web検索", en: "Web search", icon: Globe, internal: false },
  // The document PLANNER (senpai/planner) emits these stable capability ids as
  // `name` (see _plan_stream in senpai/api/server.py) rather than baking a
  // Japanese label in server-side — same reasoning as every ReAct-loop tool
  // above: one lookup, ja/en picked by the existing `lang` switch, not hardcoded.
  conversation: { ja: "会話の文脈", en: "Conversation context", icon: Sparkles, internal: false },
  workspace: { ja: "ローカル文書", en: "Local documents", icon: FileText, internal: false },
  crm: { ja: "社内記録(SPR)", en: "Internal records (SPR)", icon: Database, internal: true },
  knowledge: { ja: "社内ナレッジ", en: "Internal knowledge", icon: ShieldCheck, internal: true },
  solutions: { ja: "ソリューション・製品情報", en: "Solution & product info", icon: Package, internal: true },
  // `documents` (the planner's terminal artifact task) is proposal/pptx/docx
  // depending on the goal — its `internal` grounding actually varies per turn, so
  // the event itself carries an explicit `internal` flag that overrides this
  // static default (see groundingBadge below).
  documents: { ja: "資料生成", en: "Document generation", icon: Presentation, internal: false },
  workspace_organize: { ja: "フォルダ整理", en: "Workspace Organize", icon: FolderTree, internal: false },
  workspace_write: { ja: "メモ保存", en: "Save Note", icon: FileText, internal: false },
};

function getToolHighlight(tool: ToolCall): string {
  try {
    const str = tool.args || "";
    
    // Extract a value formatted as key='value' or key=value
    const extract = (key: string) => {
      const regex = new RegExp(`${key}=(['"]?)(.*?)\\1(?:,|$)`);
      const match = str.match(regex);
      return match ? match[2] : null;
    };

    if (tool.name === "web_search") return extract("query") || "";
    if (tool.name === "search_products") return extract("keyword") || extract("category") || "";
    if (tool.name === "get_product_details") return extract("product_id") || "";
    if (tool.name === "list_recent_emails") return extract("query") || "";
    if (tool.name === "schedule_meeting") return extract("title") || "Meeting";
    
    const title = extract("title");
    if (title) return title;
    
    const prompt = extract("prompt");
    if (prompt) return prompt.substring(0, 50) + (prompt.length > 50 ? "..." : "");
    
    return extract("company_name") || extract("name") || "";
  } catch {
    return "";
  }
}

// search_knowledge / search_solutions (and their planner-path equivalents,
// same underlying formatter) return "- [kind] text（出典: ...）" lines — a real,
// already-cited structure that was previously just dumped as one monospace
// paragraph. Split it into {kind, text, url} so a citation can be an actual
// link instead of dead text; returns null for any other tool's plain result,
// which keeps rendering as before.
function parseCitedLines(result: string): { kind: string; text: string; citation?: string; url?: string }[] | null {
  const lines = (result || "").split("\n").map((l) => l.trim()).filter((l) => l.startsWith("- ["));
  if (lines.length === 0) return null;
  return lines.map((line) => {
    const kindMatch = line.match(/^- \[(.+?)\]\s*/);
    const kind = kindMatch ? kindMatch[1] : "";
    let text = kindMatch ? line.slice(kindMatch[0].length) : line.replace(/^- /, "");
    const citeMatch = text.match(/[（(]((?:出典|根拠)[:：].*?)[）)]\s*$/);
    let citation: string | undefined;
    if (citeMatch) {
      citation = citeMatch[1];
      text = text.slice(0, citeMatch.index).trim();
    }
    const urlMatch = citation?.match(/https?:\/\/\S+/);
    return { kind, text, citation, url: urlMatch ? urlMatch[0] : undefined };
  });
}

function ToolDisclosure({ tool, running, lang, isParallelItem = false }: { tool: ToolCall, running: boolean, lang: "ja" | "en", isParallelItem?: boolean }) {
  const [open, setOpen] = useState(false);
  const meta = TOOL_LABEL[tool.name];
  const Icon = meta?.icon ?? Wrench;
  const baseLabel = meta ? (lang === "ja" ? meta.ja : meta.en) : tool.name;
  const highlight = getToolHighlight(tool);
  
  // Extract sources if applicable (e.g. from web search results returning [1] Source Name)
  let sourcesCount = 0;
  if (tool.result && (tool.name === "web_search" || tool.name === "search_products")) {
    const lines = tool.result.split("\\n");
    sourcesCount = lines.filter(l => l.trim().startsWith("-")).length;
  }
  
  const displayLabel = highlight ? `${highlight} ${sourcesCount > 0 ? `(${sourcesCount} ${lang === "ja" ? "件" : "sources"})` : ""}` : baseLabel;
  const finalLabel = highlight ? `${displayLabel} — ${baseLabel}` : displayLabel;
  const citedLines = tool.result ? parseCitedLines(tool.result) : null;

  return (
    <div className={`flex flex-col gap-0.5 ${isParallelItem ? '' : 'rounded-md bg-card p-2'}`}>
      <div 
        className="flex items-center gap-1.5 cursor-pointer hover:bg-black/5 dark:hover:bg-white/5 p-1 -ml-1 rounded transition-colors text-[11.5px]"
        onClick={() => setOpen(!open)}
      >
        {isParallelItem ? (
          <span className="w-3 shrink-0 text-center font-mono text-[10px] text-primary">
            {running ? "●" : (open ? <ChevronDown className="h-3 w-3 inline" /> : <ChevronRight className="h-3 w-3 inline" />)}
          </span>
        ) : (
          <Icon className="h-3.5 w-3.5 shrink-0 text-primary/70" />
        )}
        <span className="text-foreground font-medium truncate flex-1">{finalLabel}</span>
      </div>
      
      {open && (
        <div className="ml-5 mt-1 border-l border-border/40 pl-3 py-1 flex flex-col gap-2 text-[11px]">
          <div>
            <div className="font-semibold text-foreground/80 mb-0.5">Query / Args</div>
            <div className="text-muted-foreground font-mono bg-muted/30 p-1.5 rounded break-all">{tool.args}</div>
          </div>
          <div>
            <div className="font-semibold text-foreground/80 mb-0.5">Result</div>
            {citedLines ? (
              <ul className="flex flex-col gap-1.5 max-h-[300px] overflow-y-auto">
                {citedLines.map((it, i) => (
                  <li key={i} className="flex flex-col gap-0.5 rounded bg-muted/30 p-1.5">
                    <div className="flex items-start gap-1.5">
                      {it.kind && (
                        <span className="shrink-0 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                          {it.kind}
                        </span>
                      )}
                      <span className="text-muted-foreground">{it.text}</span>
                    </div>
                    {it.citation && (
                      it.url ? (
                        <a
                          href={it.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="ml-1 inline-flex w-fit items-center gap-1 text-[10.5px] text-primary hover:underline"
                        >
                          <ExternalLink className="h-3 w-3" />
                          {it.citation}
                        </a>
                      ) : (
                        <span className="ml-1 text-[10.5px] text-muted-foreground/70">{it.citation}</span>
                      )
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-muted-foreground whitespace-pre-wrap max-h-[300px] overflow-y-auto">{tool.result}</div>
            )}
          </div>
          {tool.outline && tool.outline.length > 0 && (
            <div>
              <div className="font-semibold text-foreground/80 mb-0.5">
                {lang === "ja" ? "構成案" : "Outline"}
              </div>
              <ol className="list-decimal list-inside text-muted-foreground bg-muted/30 rounded p-1.5 space-y-0.5">
                {tool.outline.map((s, i) => (
                  <li key={i} className="truncate">{s.title || (lang === "ja" ? "(無題)" : "(untitled)")}</li>
                ))}
              </ol>
            </div>
          )}
          {tool.document && (
            <a
              href={documentUrl(tool.document.download_url)}
              download={tool.document.filename}
              className="mt-1 inline-flex w-fit items-center gap-1.5 rounded-md border border-primary/40 bg-primary/[0.06] px-2.5 py-1 text-[11px] font-medium text-primary transition-colors hover:bg-primary/10"
            >
              <Download className="h-3.5 w-3.5" />
              {lang === "ja" ? "ダウンロード" : "Download"}
              <span className="font-mono text-[10px] text-muted-foreground">{tool.document.filename}</span>
            </a>
          )}
        </div>
      )}
    </div>
  );
}

export function MessageBubble({ m, t, lang, onPick }: {
  m: Msg; t: (k: string) => string; lang: "ja" | "en"; onPick: (c: ResolveCandidate) => void;
}) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-primary px-3.5 py-2 text-[13.5px] text-primary-foreground">
          {m.content}
        </div>
      </div>
    );
  }

  const running = m.status === "running";
  const error = m.status === "error";

  return (
    <div className="flex w-full flex-col items-start gap-1.5">
      {/* 1. Thinking or Answer */}
      {error ? (
        <div className="rounded-xl bg-destructive/10 px-3.5 py-2 text-[13px] text-destructive">
          {t("assistant.error")}
        </div>
      ) : running && !m.content ? (
        <div className="inline-flex items-center gap-2 py-1 text-[13px] font-medium text-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> 
          {lang === "ja" ? "考え中..." : "Thinking..."}
        </div>
      ) : m.content ? (
        <div className="w-full pt-1.5">
          {!running && (
            <div className="mb-1.5 flex justify-end">
              <span className="flex items-center gap-2">
                <button
                  onClick={() => { void downloadMessageAsXlsx(m.content, lang); }}
                  title={lang === "ja" ? "Excel (.xlsx) で書き出す" : "Export to Excel (.xlsx)"}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-[11.5px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                >
                  <FileSpreadsheet className="h-3.5 w-3.5" />
                  Excel
                </button>
                <button
                  onClick={() => { void downloadMessageAsDocx(m.content, lang); }}
                  title={lang === "ja" ? "Word (.docx) で書き出す" : "Export to Word (.docx)"}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-[11.5px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                >
                  <FileText className="h-3.5 w-3.5" />
                  Word
                </button>
              </span>
            </div>
          )}
          <AnswerMd text={m.content} />
          {running && <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-foreground/40 align-middle" />}
        </div>
      ) : null}

      {/* 1b. Generated document downloads — surfaced at the RESPONSE level (not
           buried inside the collapsed tool card) so the deliverable is one click. */}
      {(() => {
        const all = m.tools.map((tl) => tl.document).filter(Boolean) as GeneratedDocument[];
        // Dedupe: several tool calls in one turn can reference the same document.
        const seen = new Set<string>();
        const docs = all.filter((doc) => {
          const id = doc.doc_id ?? `${doc.filename}|${doc.download_url}`;
          if (seen.has(id)) return false;
          seen.add(id);
          return true;
        });
        if (docs.length === 0) return null;
        return (
          <div className="flex w-full max-w-[88%] flex-wrap gap-2 pt-1">
            {docs.map((doc, i) => (
              <a
                key={`${doc.doc_id ?? doc.filename}-${i}`}
                href={documentUrl(doc.download_url)}
                download={doc.filename}
                className="inline-flex items-center gap-2 rounded-lg border border-primary/40 bg-primary/[0.06] px-3 py-2 text-[12.5px] font-medium text-primary transition-colors hover:bg-primary/10"
              >
                <Download className="h-4 w-4 shrink-0" />
                {lang === "ja" ? "ダウンロード" : "Download"}
                <span className="font-mono text-[11px] text-muted-foreground">{doc.filename}</span>
              </a>
            ))}
          </div>
        );
      })()}

      {/* 2. Execution Timeline (Level 2) */}
      {m.tools.length > 0 && (
        <details open={running} className="w-full max-w-[88%] text-[12px] group">
          <summary className="flex cursor-pointer items-center gap-1.5 py-1.5 font-medium text-muted-foreground select-none hover:text-foreground transition-colors list-none [&::-webkit-details-marker]:hidden">
            <span className="flex items-center justify-center w-4 h-4 shrink-0 transition-transform group-open:rotate-90">
              <ChevronRight className="h-4 w-4" />
            </span>
            {running 
              ? (lang === "ja" ? `実行中 (${m.tools.length} 操作)` : `Execution (${m.tools.length} operations)`)
              : (lang === "ja" ? `✓ 調査完了 (${m.tools.length} 操作)` : `✓ Investigation complete (${m.tools.length} operations)`)}
          </summary>
          <div className="space-y-2 border-l border-border/60 ml-2 pl-3 mt-1 pb-2.5">
            {m.tools.map((tool, i) => (
              <ToolDisclosure key={i} tool={tool} running={running} lang={lang} />
            ))}
          </div>
        </details>
      )}

      {/* Browser replay — when web_research crawled sites this turn, play back the
          captured scroll feed (the /intel path streams the same frames live). */}
      {(() => {
        const frames = m.tools.flatMap((t) => t.crawlFrames ?? []);
        const pages = m.tools.flatMap((t) => t.crawl ?? []);
        if (frames.length === 0 && !pages.some((p) => p.screenshot_b64)) return null;
        return <CrawlReplay frames={frames} pages={pages} lang={lang} />;
      })()}

      {/* Research source ledger */}
      {m.research && m.sources && m.sources.length > 0 && (
        <SourceLedger sources={m.sources} />
      )}

      {/* Retrieval Explorer */}
      {m.retrieval && m.retrieval.length > 0 && (
        <RetrievalExplorer traces={m.retrieval} open={running} lang={lang} />
      )}

      {/* Ambiguous candidates */}
      {m.candidates && m.candidates.length > 0 && (
        <div className="w-full max-w-[88%] rounded-lg border border-band-yellow/40 bg-band-yellow/[0.06] p-3">
          <div className="mb-1.5 flex items-center gap-1.5 text-[11.5px] font-semibold text-band-yellow">
            <UserSearch className="h-3.5 w-3.5" />
            {lang === "ja"
              ? `「${m.query ?? ""}」は複数の顧客に一致します。どの顧客ですか？`
              : `"${m.query ?? ""}" matches several customers — which one?`}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {m.candidates.map((c) => (
              <button
                key={c.customer_id}
                onClick={() => onPick(c)}
                className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-[12px] text-foreground transition-colors hover:border-primary/40 hover:text-primary"
              >
                <Building2 className="h-3 w-3 text-muted-foreground" />
                {c.name}
                {c.deal_id && <span className="font-mono text-[10px] text-muted-foreground">{c.deal_id}</span>}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Badges / Routing */}
      {m.routing && !running && m.content && (
        <div className="mt-1 flex flex-wrap items-center gap-1.5 pt-1.5">
          {m.routing && (
            <span
              title={`${m.routing.reason} (${Math.round(m.routing.confidence * 100)}%)`}
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-semibold",
                m.routing.think ? "bg-navy/10 text-navy" : "bg-muted text-muted-foreground",
              )}
            >
              {m.routing.think
                ? <><Brain className="h-3 w-3" /> {lang === "ja" ? "推論モード" : "Reasoning"}</>
                : <><Zap className="h-3 w-3" /> {lang === "ja" ? "高速モード" : "Fast"}</>}
            </span>
          )}
        </div>
      )}

      {/* Web citations */}
      {m.webUrls && m.webUrls.length > 0 && (
        <div className="w-full max-w-[88%] rounded-lg border border-border bg-card px-3 py-2 mt-2">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            <Globe className="h-3 w-3" /> {lang === "ja" ? "参照（Web）" : "Web sources"}
          </div>
          <ul className="space-y-1">
            {m.webUrls.map((c, i) => (
              <li key={i}>
                <a href={c.url} target="_blank" rel="noopener noreferrer"
                   className="inline-flex items-center gap-1 text-[12px] text-primary hover:underline">
                  <ExternalLink className="h-3 w-3 shrink-0" />
                  <span className="truncate">{c.title || c.url}</span>
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// --- research source ledger -------------------------------------------------
function SourceLedger({ sources }: { sources: SourceState[] }) {
  const ICONS: Record<string, LucideIcon> = {
    internal_records: Database, deals: AlertTriangle, activities: FileText,
    environment: Building2, web_search: Globe,
  };
  return (
    <div className="w-full max-w-[88%] rounded-lg border border-primary/25 bg-primary/[0.03] p-3">
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-primary">
        <Search className="h-3 w-3" />
        {sources.length} sources
      </div>
      <ul className="space-y-1">
        {sources.map((s) => {
          const Icon = ICONS[s.key] ?? Database;
          return (
            <li key={s.key} className="flex flex-wrap items-center gap-2 text-[12px] text-foreground/80">
              <Icon className="h-3.5 w-3.5 shrink-0 text-primary/70" />
              <span className="font-medium">{s.label}</span>
              <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", sourceStatusClass(s.status))}>
                {s.status}
              </span>
              {typeof s.count === "number" && <span className="font-mono text-[10.5px] text-muted-foreground">{s.count}</span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function sourceStatusClass(status: SourceState["status"]) {
  switch (status) {
    case "found": return "bg-conf-high/10 text-conf-high";
    case "ambiguous": return "bg-band-yellow/10 text-band-yellow";
    case "error": return "bg-band-red/10 text-band-red";
    default: return "bg-muted text-muted-foreground"; // not_found / skipped
  }
}

// --- lightweight markdown for answers ---------------------------------------
function inlineBold(s: string) {
  return s.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**")
      ? <strong key={i} className="font-semibold text-foreground">{p.slice(2, -2)}</strong>
      : <span key={i}>{p}</span>,
  );
}

export function AnswerMd({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  return (
    <div className="space-y-1.5 text-[13.5px] leading-relaxed text-foreground">
      {lines.map((ln, i) => {
        const tx = ln.trim();
        if (!tx) return <div key={i} className="h-1" />;
        if (/^---+$/.test(tx)) return <div key={i} className="my-1 border-t border-border" />;
        if (/^#{1,6}\s/.test(tx)) {
          return (
            <h4 key={i} className="pt-1 text-[12px] font-semibold uppercase tracking-[0.04em] text-primary">
              {tx.replace(/^#{1,6}\s+/, "")}
            </h4>
          );
        }
        if (/^[-*]\s/.test(tx)) {
          return (
            <div key={i} className="flex gap-2 pl-1">
              <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-primary/60" />
              <span>{inlineBold(tx.replace(/^[-*]\s+/, ""))}</span>
            </div>
          );
        }
        return <p key={i}>{inlineBold(tx)}</p>;
      })}
    </div>
  );
}
````

## File: senpai/llm/client.py
````python
"""OpenAI client + tool-calling loop for exp3 — ported from demo/app.py.

Keeps the demo's proven behaviour: native OpenAI `tool_calls` with a safe
`_parse_xlam` fallback for the XLAM-style text the model sometimes emits. The
tool loop is factored into `stream_turn` (used by the Gradio chat) and a thin
`simple_complete` (used by narration). Network/parse failures are surfaced as
strings or raised for the caller to fall back on — nothing here crashes the app.
"""
from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterator

from openai import OpenAI

from senpai import config
from senpai.llm import usage as _usage
from senpai.tools.impl import dispatch, _truncate_on_boundary
from senpai.tools import conversation as _conversation
from senpai.orchestration.scheduler import AdaptiveScheduler, ToolCall as SchedToolCall
from senpai.orchestration.engine import ExecutionEngine
from senpai.agent.capabilities import build_registry

_SCHEDULER = AdaptiveScheduler()
_ENGINE = ExecutionEngine(build_registry())
from senpai.tools.schemas import TOOLS

# A single OpenAI-compatible client. `timeout`/`max_retries` keep a slow or down
# inference server (vLLM/ollama) from hanging the API — callers fall back to the
# deterministic render on any error.
client = OpenAI(
    base_url=config.BASE_URL,
    api_key="dummy",
    timeout=config.LLM_TIMEOUT,
    max_retries=0,
)

fallback_client = OpenAI(
    base_url=config.FALLBACK_BASE_URL,
    api_key="dummy",
    timeout=config.LLM_TIMEOUT,
    max_retries=0,
)


def _synth_route(no_think: bool):
    """Hybrid model-decomposition router for the *final synthesis* round only.

    FAST (no_think) synthesis → the smaller FALLBACK model (8B Q4); THINK synthesis
    → the primary (27B), whose mentorship narrative we keep. Gated by
    `config.FAST_SYNTH_FALLBACK` (OFF by default, so the live path is unchanged —
    everything stays on the 27B). Tool *selection* never calls this; it is always
    the primary. Returns (synthesis_client, model_id, alt_client, alt_model) where
    `alt_*` is the other endpoint to fail over to. The Fast/Think decision itself
    stays with the existing reasoning router — this only picks who writes the
    already-decided FAST answer."""
    # SYNTH_ALL_FALLBACK: route ALL synthesis (FAST + THINK) to the 8B — latency
    # over accuracy. Otherwise the FAST→8B / THINK→27B hybrid.
    if config.SYNTH_ALL_FALLBACK or (no_think and config.FAST_SYNTH_FALLBACK):
        return fallback_client, config.FALLBACK_MODEL, client, config.MODEL
    return client, config.MODEL, fallback_client, config.FALLBACK_MODEL


def _parse_xlam(content: str | None):
    """exp3 sometimes emits XLAM-style `[func(a=1, b='x'), ...]` as plain text
    instead of OpenAI tool_calls. Parse it safely with `ast` (literal args only,
    never code). Returns a list of (name, args_dict) or None."""
    if not content:
        return None
    text = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip().strip("`")
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        node = ast.parse(text[start:end + 1], mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(node, ast.List):
        return None
    calls = []
    for el in node.elts:
        if isinstance(el, ast.Call) and isinstance(el.func, ast.Name):
            try:
                kwargs = {kw.arg: ast.literal_eval(kw.value) for kw in el.keywords}
            except (ValueError, SyntaxError):
                continue
            calls.append((el.func.id, kwargs))
    return calls or None


# Atlas (spark) controls reasoning via the chat template's `enable_thinking`
# kwarg, surfaced to the OpenAI SDK through extra_body→chat_template_kwargs.
# (The old empty-<think> assistant prefill — the only lever on the previous
# llama-server build — is a NO-OP on atlas: it still emits a <think> phase.)
# Atlas also requires explicit sampling: with none it decodes greedily and
# degenerates into repetition loops on long output. `_gen_kwargs` carries both
# into every create() call; `no_think=True` disables the reasoning phase.
def _gen_kwargs(no_think: bool) -> dict:
    return {
        "top_p": config.LLM_TOP_P,
        "extra_body": {
            "chat_template_kwargs": {"enable_thinking": not no_think},
            "top_k": config.LLM_TOP_K,
        },
    }


def _prep(messages: list[dict], no_think: bool) -> list[dict]:
    # Reasoning is now toggled via _gen_kwargs(enable_thinking); the messages
    # pass through unchanged (the empty-<think> prefill did nothing on atlas).
    return messages


def _record_stream_usage(usage_obj, msgs: list[dict], output: str, *,
                         model: str, endpoint: str, label: str) -> None:
    """Record token usage for a streamed call: measured from the server's
    usage-only final chunk when present, else a clearly-flagged estimate over the
    prompt + accumulated output."""
    if usage_obj is not None:
        _usage.record(model, endpoint,
                      getattr(usage_obj, "prompt_tokens", 0) or 0,
                      getattr(usage_obj, "completion_tokens", 0) or 0,
                      label=label, streamed=True)
        return
    prompt_text = "\n".join(str(m.get("content", "")) for m in msgs)
    _usage.record(model, endpoint,
                  _usage._estimate_tokens(prompt_text),
                  _usage._estimate_tokens(output),
                  label=label, streamed=True, estimated=True)


def simple_complete(messages: list[dict], temperature: float = 0.3,
                    max_tokens: int | None = None, *, no_think: bool = False,
                    allow_fallback: bool = True, fast_decomp: bool = False,
                    label: str = "complete") -> str:
    """One plain completion, no tools. Raises on transport error so callers
    (e.g. narration) can fall back to a templated string. Strips any
    `<think>...</think>` reasoning span (the served model is a reasoning
    distill) so callers get only the final coaching text. `no_think` disables the
    reasoning phase (low latency); `allow_fallback=False` pins the request to the
    primary endpoint and re-raises instead of silently switching models."""
    msgs = _prep(messages, no_think)
    primary_c, primary_m, alt_c, alt_m = (
        _synth_route(no_think) if fast_decomp else (client, config.MODEL, fallback_client, config.FALLBACK_MODEL))
    try:
        resp = primary_c.chat.completions.create(
            model=primary_m, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, **_gen_kwargs(no_think),
        )
        _usage.record_response(resp, model=primary_m, endpoint="primary", label=label)
    except Exception as e:
        if not allow_fallback:
            raise
        print(f"⚠️ Primary server {primary_m} failed ({e}). Trying fallback...")
        resp = alt_c.chat.completions.create(
            model=alt_m, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, **_gen_kwargs(no_think),
        )
        _usage.record_response(resp, model=alt_m, endpoint="fallback", label=label)
    content = resp.choices[0].message.content or ""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    return content.strip()


def _delta_reasoning(delta) -> str | None:
    """Some OpenAI-compatible servers (llama.cpp's llama-server, DeepSeek, vLLM
    with `--reasoning-parser`) split chain-of-thought into a separate
    `reasoning_content` field and leave `content`/`delta.content` empty until the
    answer begins. The openai SDK exposes such non-standard fields on
    `model_extra`; older builds attach them directly. Check both."""
    rc = getattr(delta, "reasoning_content", None)
    if rc is None:
        extra = getattr(delta, "model_extra", None)
        if extra:
            rc = extra.get("reasoning_content")
    return rc


def stream_complete(messages: list[dict], temperature: float = 0.3,
                    max_tokens: int | None = None, *, no_think: bool = False,
                    allow_fallback: bool = True, fast_decomp: bool = False,
                    label: str = "stream") -> Iterator[str]:
    """Stream a completion token-by-token from the OpenAI-compatible server.
    Yields a `<think>…</think>` reasoning span (when the backend emits one)
    followed by the answer deltas — a single text stream callers can split on
    `</think>`. Backends that inline `<think>` in `content` (vLLM/ollama) flow
    straight through unchanged; backends that put reasoning in a separate
    `reasoning_content` field (llama.cpp) are reconstructed into the same shape,
    so the thinking phase stays visible instead of streaming nothing.
    `no_think` disables reasoning for low latency; `allow_fallback=False` pins the
    request to the primary endpoint and re-raises instead of switching models.
    `fast_decomp=True` opts this call into the hybrid synthesis route (FAST → 8B)
    when `config.FAST_SYNTH_FALLBACK` is on — used by FAST grounded summaries
    (e.g. /research), not by narration. Raises on transport error so callers can
    fall back."""
    msgs = _prep(messages, no_think)
    primary_c, primary_m, alt_c, alt_m = (
        _synth_route(no_think) if fast_decomp else (client, config.MODEL, fallback_client, config.FALLBACK_MODEL))
    # include_usage asks the server for a final usage-only chunk so token
    # accounting on the streaming path is measured, not estimated.
    _opts = {"stream_options": {"include_usage": True}}
    used_model, used_endpoint = primary_m, "primary"
    try:
        stream = primary_c.chat.completions.create(
            model=primary_m, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, stream=True,
            **_opts, **_gen_kwargs(no_think),
        )
    except Exception as e:
        if not allow_fallback:
            raise
        print(f"⚠️ Synthesis server {primary_m} failed ({e}). Trying {alt_m}...")
        used_model, used_endpoint = alt_m, "fallback"
        stream = alt_c.chat.completions.create(
            model=alt_m, messages=msgs, temperature=temperature,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS, stream=True,
            **_opts, **_gen_kwargs(no_think),
        )
    think_open = think_closed = False
    _usage_obj = None
    _out_chars: list[str] = []
    for chunk in stream:
        if getattr(chunk, "usage", None):
            _usage_obj = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if not delta:
            continue
        reasoning = _delta_reasoning(delta)
        if reasoning:
            _out_chars.append(reasoning)
            if not think_open:
                think_open = True
                yield "<think>"
            yield reasoning
        if delta.content:
            _out_chars.append(delta.content)
            if think_open and not think_closed:
                think_closed = True
                yield "</think>"
            yield delta.content
    _record_stream_usage(_usage_obj, msgs, "".join(_out_chars),
                         model=used_model, endpoint=used_endpoint, label=label)


def stream_turn(convo: list[dict], tools: list[dict] | None = None):
    """Generator driving one user turn through the tool loop. Yields
    (tool_log, answer_or_None) after each round; the final yield has the answer.
    `convo` is mutated in place with assistant/tool messages (demo semantics).
    `tools` selects which tool schemas the model may call (defaults to all TOOLS);
    each front end passes its own role-scoped subset."""
    tools = tools if tools is not None else TOOLS
    tool_log: list[tuple[str, str, str]] = []
    answer = None
    for _ in range(config.MAX_TOOL_ROUNDS):
        try:
            resp = client.chat.completions.create(
                model=config.MODEL, messages=convo, tools=tools,
                tool_choice="auto", temperature=0.1, **_gen_kwargs(True),
            )
            _usage.record_response(resp, model=config.MODEL, endpoint="primary", label="tool_loop")
        except Exception as e:
            print(f"⚠️ Primary server failed in tool loop ({e}). Trying fallback...")
            try:
                resp = fallback_client.chat.completions.create(
                    model=config.FALLBACK_MODEL, messages=convo, tools=tools,
                    tool_choice="auto", temperature=0.1, **_gen_kwargs(True),
                )
                _usage.record_response(resp, model=config.FALLBACK_MODEL, endpoint="fallback", label="tool_loop")
            except Exception as fe:
                answer = f"⚠️ サーバーエラー: {e} (Fallback: {fe})"
                break

        msg = resp.choices[0].message
        if msg.tool_calls:
            calls = [(tc.id, tc.function.name, tc.function.arguments)
                     for tc in msg.tool_calls]
        else:
            parsed = _parse_xlam(msg.content)
            calls = [(f"call_{len(tool_log) + i}", name, json.dumps(args))
                     for i, (name, args) in enumerate(parsed)] if parsed else []

        if not calls:
            if tool_log:
                last_name, _, last_result = tool_log[-1]
                if last_name in _ACTION_TOOLS or last_name.startswith("generate_"):
                    answer = last_result
                    break
            answer = (msg.content or "").strip() or "(no response)"
            break

        convo.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": cid, "type": "function",
             "function": {"name": name, "arguments": args}}
            for cid, name, args in calls]})
        for cid, name, args in calls:
            result = dispatch(name, args)
            tool_log.append((name, _fmt_args(args), result))
            convo.append({"role": "tool", "tool_call_id": cid, "content": result})
        yield tool_log, None
    else:
        if tool_log:
            last_name, _, last_result = tool_log[-1]
            if last_name in _ACTION_TOOLS or last_name.startswith("generate_"):
                answer = last_result
        answer = answer or "⚠️ ツール呼び出しの上限に達しました。"
    yield tool_log, answer


def _fallback_answer(substantive: list[tuple[str, str]]) -> str:
    """A grounded last resort when synthesis yields nothing: the most recent
    substantive tool result, presented plainly. Empty when nothing useful was
    gathered (then the caller keeps the honest '(no response)')."""
    return substantive[-1][1] if substantive else ""


def _downsample_frames(frames: list[dict], cap: int) -> list[dict]:
    """Evenly thin a scroll-frame sequence down to at most `cap` frames so the chat
    browser-replay animates smoothly without bloating the SSE event (and persisted
    history) with every JPEG. Order is preserved."""
    if len(frames) <= cap:
        keep = frames
    else:
        step = len(frames) / cap
        keep = [frames[int(i * step)] for i in range(cap)]
    return [{"url": f.get("url", ""), "index": f.get("index", 0),
             "screenshot_b64": f.get("screenshot_b64", "")} for f in keep]


_ENTITY_DEAL_RE = re.compile(r"\bD\d{3,}\b")
_ENTITY_CUST_RE = re.compile(r"\bC\d{2,}\b")
_AUDIT_RE = re.compile(
    r"\b(?:audit|quarterly|pipeline review|research steps|faceted searches?)\b|"
    r"(?:監査|四半期|パイプライン.*レビュー|調査手順|ファセット検索)",
    re.IGNORECASE,
)
_STEP_RE = re.compile(r"(?:^|\n)\s*(?:\d+[.)]|[-*・])\s+", re.MULTILINE)
_REP_ID_RE = re.compile(r"\bR\d{2,}\b", re.IGNORECASE)
_QUOTE_RE = re.compile(r"['\"]([^'\"]+)['\"]")


def _json_call(prefix: str, idx: int, name: str, args: dict) -> tuple[str, str, str]:
    return (f"{prefix}_{idx}", name, json.dumps(args, ensure_ascii=False))


def _multi_entity_gather_calls(user_msg: str) -> list[tuple[str, str, str]]:
    """Deterministic fan-out for 'compare A, B, C' turns. If the user's message names
    ≥2 DISTINCT, KNOWN entity ids (deals D### / customers C##, validated against the
    store — same id discipline as SessionFocus), return the full gather bundle for all
    of them so the scheduler runs it in a SINGLE parallel round. The served model emits
    only one tool_call per response under the full prompt (verified), so it can't batch
    these itself.

    The bundle is grouped by tool — every deal's `score_deal_health`, then every deal's
    `query_spr`, then each standalone customer's `query_spr` — but since all are
    parallel-safe reads they execute concurrently in one round (no need to phase health
    before records: there is no dependency between them). Customers get records only
    (deal health needs a deal id).

    Returns [] when the pattern doesn't apply → the normal loop runs unchanged. Scoped
    intentionally narrow: explicit ids only, the compare pattern only."""
    if not user_msg:
        return []
    from senpai.data import store  # lazy
    used: set[str] = set()
    deal_ids: list[str] = []
    cust_ids: list[str] = []
    for did in _ENTITY_DEAL_RE.findall(user_msg):
        if did not in used and store.get_deal(did):
            used.add(did)
            deal_ids.append(did)
    for cid in _ENTITY_CUST_RE.findall(user_msg):
        if cid not in used and store.get_customer(cid):
            used.add(cid)
            cust_ids.append(cid)
    if len(used) < 2:   # threshold is DISTINCT entities, not calls
        return []
    gathers: list[tuple[str, dict]] = []
    gathers += [("score_deal_health", {"deal_id": d}) for d in deal_ids]  # all health, grouped
    gathers += [("query_spr", {"deal_id": d}) for d in deal_ids]          # then all deal records
    gathers += [("query_spr", {"customer": c}) for c in cust_ids]         # then customer records
    return [_json_call("exp", i, name, args) for i, (name, args) in enumerate(gathers)]


def _mentioned_customers(user_msg: str) -> list[str]:
    """Known customer display names mentioned in the prompt, in text order."""
    if not user_msg:
        return []
    from senpai.data import store  # lazy
    hits: list[tuple[int, str]] = []
    seen: set[str] = set()
    for c in store.all_customers():
        name = c.get("name", "")
        if not name or name in seen:
            continue
        pos = user_msg.find(name)
        if pos >= 0:
            hits.append((pos, name))
            seen.add(name)
    return [name for _pos, name in sorted(hits)]


def _audit_customers(user_msg: str) -> list[str]:
    customers = _mentioned_customers(user_msg)
    seen = set(customers)
    for line in (user_msg or "").splitlines():
        if not re.search(r"customer|account|顧客|取引先|会社|status|deal status", line, re.IGNORECASE):
            continue
        for quoted in _QUOTE_RE.findall(line):
            if quoted not in seen and not re.fullmatch(r"R\d{2,}|D\d{3,}|C\d{2,}", quoted, re.IGNORECASE):
                seen.add(quoted)
                customers.append(quoted)
    return customers


def _audit_faceted_deal_calls(user_msg: str) -> list[tuple[str, dict]]:
    """Extract simple faceted deal-search bullets from audit prompts."""
    calls: list[tuple[str, dict]] = []
    for raw in (user_msg or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if "status" in low or "current deal" in low:
            continue
        if "similar" in low or "comparable" in low or "類似" in line:
            continue
        if "product code" in low:
            m_code = re.search(r"['\"]?([A-Z]{2,}\d{2,})['\"]?", line)
            if m_code:
                calls.append(("find_deals", {"product_code": m_code.group(1), "limit": 10}))
            continue
        if "deal" not in low and "案件" not in line:
            continue

        quoted = _QUOTE_RE.findall(line)
        args: dict = {"limit": 10}
        if quoted:
            args["product_category"] = quoted[0]
        if len(quoted) >= 2:
            args["industry"] = quoted[1]
        if "won" in low or "受注" in line:
            args["outcome"] = "won"
        elif "lost" in low or "失注" in line:
            args["outcome"] = "lost"
        elif "open" in low or "進行中" in line:
            args["outcome"] = "open"
        amount = re.search(r"(?:over|above|>=|more than)\s*([\d,]+)", low)
        if amount:
            args["min_amount"] = int(amount.group(1).replace(",", ""))
        if any(k in args for k in ("product_category", "industry", "outcome", "min_amount")):
            calls.append(("find_deals", args))
    return calls


def _audit_similar_deal_calls(user_msg: str, customers: list[str]) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    for customer in customers:
        # Match: 'Customer' (in the 'Industry' industry)
        pat = re.compile(
            rf"['\"]{re.escape(customer)}['\"]\s*\([^)]*?['\"]([^'\"]+)['\"][^)]*?industry",
            re.IGNORECASE,
        )
        m = pat.search(user_msg or "")
        if m:
            calls.append(("find_similar_deals", {"customer": customer, "industry": m.group(1)}))
    return calls


def _audit_playbook_calls(user_msg: str) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    for line in (user_msg or "").splitlines():
        if not re.search(r"scenario|playbook|シナリオ|プレイブック", line, re.IGNORECASE):
            continue
        quoted = _QUOTE_RE.findall(line)
        if quoted:
            query = quoted[0]
            calls.append(("retrieve_playbook", {"query": query, "tags": [query]}))
    return calls


def _audit_gather_calls(user_msg: str) -> list[tuple[str, str, str]]:
    """Deterministic first-round fan-out for large read-only audit prompts.

    The operational system prompt tells the model to call a tool for every numbered
    item. That preserves completeness, but on audit prompts it often becomes one LLM
    round trip per lookup. This narrow expander recognizes the common audit shape and
    issues independent read-only gathers in one scheduler batch; the normal model
    still synthesizes and may ask for any missing follow-up tools afterward.
    """
    if not user_msg or not _AUDIT_RE.search(user_msg):
        return []
    if len(_STEP_RE.findall(user_msg)) < 3:
        return []

    from senpai.data import store  # lazy
    gathers: list[tuple[str, dict]] = []
    seen_reps: set[str] = set()
    for rep_id in _REP_ID_RE.findall(user_msg):
        rep_id = rep_id.upper()
        if rep_id not in seen_reps and store.get_rep(rep_id):
            seen_reps.add(rep_id)
            gathers.append(("query_spr", {"rep_id": rep_id}))

    customers = _audit_customers(user_msg)
    for customer in customers:
        gathers.append(("query_spr", {"customer": customer}))

    if re.search(r"semantic note|search notes?|日報|ノート|notes?", user_msg, re.IGNORECASE):
        note_terms = []
        if re.search(r"budget slashed", user_msg, re.IGNORECASE):
            note_terms.append("budget slashed")
        if "予算削減" in user_msg:
            note_terms.append("予算削減")
        if note_terms:
            query = " OR ".join(note_terms)
            for customer in customers:
                gathers.append(("search_notes", {"customer": customer, "query": query, "limit": 5}))

    gathers.extend(_audit_similar_deal_calls(user_msg, customers))
    gathers.extend(_audit_faceted_deal_calls(user_msg))
    gathers.extend(_audit_playbook_calls(user_msg))

    # Keep the trigger narrow: at least several read-only gathers, otherwise let the
    # model handle the turn normally.
    if len(gathers) < 6:
        return []
    return [_json_call("audit", i, name, args) for i, (name, args) in enumerate(gathers)]


_WS_AFFIRM_RE = None  # lazy-loaded below (avoids import cost when unused)


def _pending_workspace_edit_confirm(convo: list[dict]) -> tuple[str, str] | None:
    """Deterministic confirm-continuation for a pending `edit_workspace_document`
    preview (confirm=False). If the newest user message is a bare affirmation
    ("apply", "保存して", "はい"...) and the most recent assistant tool call was an
    unconfirmed edit_workspace_document, return (path, content) to re-commit with
    confirm=True ourselves — never left to the model to remember or, worse, to
    free-generate a "saved!" answer without ever calling the tool again (the exact
    bug this closes: a write claimed in prose with no tool call behind it)."""
    global _WS_AFFIRM_RE
    if _WS_AFFIRM_RE is None:
        from senpai.planner.selection import _AFFIRM_RE  # lazy: avoid import cycles
        _WS_AFFIRM_RE = _AFFIRM_RE
    user_msg = next((m.get("content") for m in reversed(convo)
                     if m.get("role") == "user" and m.get("content")), "")
    if not user_msg or not _WS_AFFIRM_RE.search(user_msg.strip()):
        return None
    for m in reversed(convo):
        if m.get("role") != "assistant":
            continue
        calls = m.get("tool_calls") or []
        edit_calls = [tc for tc in calls if tc["function"]["name"] == "edit_workspace_document"]
        if not edit_calls:
            continue  # nearest assistant tool turn wasn't an edit — nothing pending
        try:
            args = json.loads(edit_calls[-1]["function"]["arguments"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if args.get("confirm"):
            return None  # already committed — nothing left to confirm
        path, content = args.get("path"), args.get("content")
        return (path, content) if path and content else None
    return None


# Phrasing that signals "mutate a real local file" (apply/add/edit/update/save
# against a file/note/doc) rather than just asking about its contents. Used to
# nudge the model toward actually calling edit_workspace_document instead of
# just describing the merge in prose with no write behind it.
_WORKSPACE_WRITE_INTENT_RE = re.compile(
    r"\b(?:apply|add|append|edit|update|save|write|put)\b.{0,40}\b(?:file|note|notes|doc|document)\b|"
    r"\b(?:file|note|notes|doc|document)\b.{0,20}\b(?:apply|edit|update|add)\b|"
    r"(?:ファイル|メモ|ノート|文書).{0,15}(?:追加|追記|編集|更新|保存|反映|適用)|"
    r"(?:追加|追記|編集|更新|保存|反映|適用).{0,15}(?:ファイル|メモ|ノート|文書)",
    re.IGNORECASE)

_WORKSPACE_WRITE_NUDGE = (
    "（システム注記：ユーザーはローカルファイルへの反映を求めています。まだ "
    "edit_workspace_document が呼ばれていません。他のツールでの説明だけで終わらせず、"
    "変更後の全文を content に入れて edit_workspace_document を confirm=True で呼び出し、"
    "プレビューで止めずにこのターンで保存してください。)"
)


def _wants_workspace_write(user_msg: str) -> bool:
    return bool(user_msg) and bool(_WORKSPACE_WRITE_INTENT_RE.search(user_msg))


def _is_substantive(result: str) -> bool:
    """True when a tool result carries usable info (not an error / not-found). Drives
    both the answer fallback and the unproductive-round spiral guard — so a tool that
    keeps returning real data (multi-entity fan-out) is never mistaken for a spiral."""
    return not (result.startswith("[error]") or "見つかりません" in result
                or "ありません" in result[:20])


def _route_final_answer(convo, tools, tool_log, role, fallback_text: str = ""):
    """Decide FAST vs REASONING for the synthesis round via the ReasoningRouter,
    emit a `routing` event (observability), then stream the answer. Tool-selection
    stays fast regardless; only this round is dynamically routed. When the router
    is "off" we fall back to the static TOOLLOOP_NO_THINK behaviour. `fallback_text`
    is surfaced if synthesis comes back empty, so a turn never shows a blank."""
    no_think = config.TOOLLOOP_NO_THINK
    if config.REASONING_ROUTER and config.REASONING_ROUTER != "off":
        try:
            from senpai.llm.routing import get_reasoning_router, RoutingRequest
            user_msg = next((m.get("content") for m in reversed(convo)
                             if m.get("role") == "user" and m.get("content")), "")
            decision = get_reasoning_router().route(RoutingRequest(
                message=user_msg or "", role=role or "junior",
                tools_used=[name for name, _a, _r in tool_log], rounds=len(tool_log)))
            yield {"type": "routing", "think": decision.think,
                   "reason": decision.reason, "confidence": round(decision.confidence, 2),
                   "mode": "reasoning" if decision.think else "fast"}
            no_think = not decision.think
        except Exception:  # noqa: BLE001 — a router fault must never break the turn
            pass  # fall back to the static TOOLLOOP_NO_THINK default
    # Observability: surface which model writes this (already-decided) synthesis,
    # so the hybrid eval can record FAST→8B / THINK→27B ground truth.
    _sc, _sm, _, _ = _synth_route(no_think)
    yield {"type": "synth", "model_id": _sm,
           "tier": "atlas", "no_think": no_think}
    yield from _stream_final_answer(convo, tools, no_think=no_think,
                                    fallback_text=fallback_text)


# Sentinel tool for the "finish-tool" loop. With tool_choice="required" the model
# must emit a tool call every round, so it can never burn time generating a
# throwaway answer just to signal "no more tools" (the old double-generation). When
# it has enough — or the question needs no internal tool — it calls `finish`, which
# we intercept (never dispatched) and hand to the single routed synthesis round.
_FINISH_TOOL = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": (
            "回答に必要な情報が揃ったら、または社内ツールが不要な質問なら、これを呼ぶこと。"
            "回答文は自分で書かず finish を呼ぶ。finish を呼ぶと最終回答の生成に進む。 "
            "Call this as soon as you have enough to answer, or when no internal tool "
            "is needed. Do NOT write the answer yourself — calling finish triggers the "
            "final answer."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

# Action tools that commit a side effect or produce a deliverable (a file, a booked
# meeting, a quote/email draft, a workspace file write/move) rather than retrieve facts.
_ACTION_TOOLS = {"schedule_meeting", "create_quote", "send_email",
                 "edit_workspace_document", "move_workspace_document"}


def _is_terminal_action(name: str, result: str) -> bool:
    """True when an action tool actually COMMITTED (file generated, meeting booked,
    draft produced, workspace file written) — meaning the turn is done and the model
    must not be allowed to re-invoke it. A confirm=false PREVIEW (which asks the rep
    to confirm first) and a failed call are NOT terminal, so the loop keeps going in
    those cases.

    This is what stops the model from re-calling generate_pptx (or re-writing a
    workspace file) every round and emitting duplicates: once the deliverable is
    committed, the turn ends on that result — the tool's own grounded text becomes
    the answer, leaving no room for the model to embellish or fabricate on top of it
    (the earlier bug: claiming a save happened with no commit behind it at all)."""
    if not (name in _ACTION_TOOLS or name.startswith("generate_")):
        return False
    if "プレビュー" in result or "confirm=true" in result.lower():
        return False  # a preview/draft awaiting the rep's confirmation
    if result.startswith("[error]") or "見つかりません" in result:
        return False  # a failed call — let the model recover
    return True


def stream_chat_turn(convo: list[dict], tools: list[dict] | None = None,
                     role: str | None = None):
    """Web-facing tool loop that *streams the final answer* token-by-token.

    Same loop as `stream_turn` (kept intact for the Gradio apps), but instead of
    a single blocking final completion it streams the answering round so the web
    Assistant feels as live as Review Coach. Yields typed event dicts:
      {"type": "tool", "name", "args", "result"}   — one per executed tool
      {"type": "routing", "think", "reason", "confidence", "mode"}  — synthesis mode
      {"type": "delta", "text"}                     — answer tokens as they arrive
      {"type": "answer", "text"}                    — the full answer (terminal)
    `convo` is mutated in place (demo semantics). Reasoning (`<think>…</think>`)
    is stripped so only the user-facing answer streams. `role` feeds the router."""
    tools = tools if tools is not None else TOOLS
    tool_log: list[tuple[str, str, str]] = []
    # Loop-intelligence bookkeeping (per turn): the results already gathered, keyed by
    # (name, canonical-args), plus each tool's count of consecutive UNPRODUCTIVE rounds
    # (ran but returned nothing substantive). Capping unproductive rounds — not total
    # rounds — is deliberate: a tool fetching distinct entities (query_spr for D133,
    # D012, D168) keeps returning real data so it never trips the cap, while a
    # rephrasing spiral (search X→Y→Z, all empty) trips it after two dry rounds.
    # `substantive` keeps the best real tool output so a turn can always answer.
    # `tool_call_count` is a hard absolute cap: once a tool has been dispatched
    # _MAX_CALLS_PER_TOOL times this turn (across all rounds), further calls are
    # short-circuited regardless of how novel each keyword/arg variant is.
    executed: dict[tuple[str, str], str] = {}
    tool_unproductive: dict[str, int] = {}
    tool_total_rounds: dict[str, int] = {}
    tool_call_count: dict[str, int] = {}
    substantive: list[tuple[str, str]] = []   # (tool_name, result) worth answering from
    # Multi-action tracking: committed deliverables (file generated, meeting booked, etc.)
    # so the loop can continue for additional tasks instead of hard-exiting after the first.
    committed_actions: list[tuple[str, str]] = []   # (tool_name, result) of completed actions
    from senpai.documents import registry as _docs
    from senpai.retrieval import trace as _trace
    from senpai.tools import crawl_trace as _crawl
    _trace.start()  # begin a retrieval trace for this turn (Retrieval Explorer)
    _docs.start()   # begin the per-turn generated-document buffer (download chips)
    _crawl.start()  # begin the per-turn web-crawl trace (web_research browse feed)

    # Tool-selection rounds must KEEP the <think> phase: this reasoning-distill
    # needs to reason before it will emit a tool call. Prefilling an empty
    # <think></think> here makes it skip deliberation and *narrate* the call as
    # prose ("Action: scheduling meeting…") instead of emitting a real tool_call —
    # so nothing runs and the UI shows no tool. (Verified A/B: empty-think → 0 tool
    # calls; think-on → schedule_meeting fires.) The latency knob only applies to
    # the FINAL answer round, which has its own fast/think routing below.
    # finish-tool loop: force a tool call every round (tool_choice="required") so the
    # model never generates a throwaway answer. `finish` is offered alongside the
    # real tools; calling it (or emitting no real tool) ends the loop → synthesis.
    sel_tools = [*tools, _FINISH_TOOL]
    sel_msgs = lambda: _prep(convo, False)
    user_msg = next((m.get("content") for m in reversed(convo)
                     if m.get("role") == "user" and m.get("content")), "")
    # One-shot guard for the write-intent nudge below — fires at most once per
    # turn so a model that still won't call edit_workspace_document can't loop
    # forever; it falls through to a normal (honest, tool-free) answer instead.
    write_nudge_used = False
    for round_i in range(config.MAX_TOOL_ROUNDS):
        last_round = round_i == config.MAX_TOOL_ROUNDS - 1

        # Deterministic confirm-continuation: a bare "apply"/"保存して"/"はい" right
        # after a pending edit_workspace_document preview re-commits that EXACT write
        # ourselves, with confirm=True — the model never gets a chance to skip the
        # call and free-generate a "saved!" answer instead (see _pending_workspace_edit_confirm).
        pending_edit = _pending_workspace_edit_confirm(convo) if round_i == 0 else None
        # Deterministic multi-entity fan-out: on the FIRST round, if the user named ≥2
        # known entities ("compare D133, D012, D168"), issue the gather reads ourselves
        # in ONE parallel round rather than letting the model dribble them out one per
        # round (it emits a single tool_call per response under the full prompt). The
        # scheduler runs them concurrently; the loop then proceeds normally.
        expanded = [] if pending_edit or round_i != 0 else (
            _audit_gather_calls(user_msg) or _multi_entity_gather_calls(user_msg))
        if pending_edit:
            path, content = pending_edit
            calls = [("confirm_edit_0", "edit_workspace_document",
                      json.dumps({"path": path, "content": content, "confirm": True},
                                ensure_ascii=False))]
        elif expanded:
            calls = expanded
        else:
            # tool_choice: FORCE a tool on the first round (the model must gather before
            # it can answer, and must not burn a round writing a throwaway answer). Once
            # we have evidence, relax to "auto" so the model can cleanly STOP — forcing
            # "required" every round is what makes it contort its final answer into a
            # bogus tool argument (the answer-as-arg leak) instead of just finishing.
            #
            # NB: parallel tool calls need "auto"+thinking-off (verified: "required"
            # applies XGrammar structural enforcement that caps output at ONE
            # <tool_call>). But the full operational system prompt suppresses batching
            # regardless (a minimal prompt fans out; this one emits one call even with an
            # explicit batch instruction), so keeping round-0 "required" costs no
            # parallelism we'd otherwise get, and buys the gather guarantee. Deterministic
            # fan-out for the compare pattern is handled by the expander above.
            tool_choice = "required" if not tool_log else "auto"
            try:
                resp = client.chat.completions.create(
                    model=config.MODEL, messages=sel_msgs(), tools=sel_tools,
                    tool_choice=tool_choice, temperature=0.1, **_gen_kwargs(True),
                )
            except Exception as e:  # noqa: BLE001
                print(f"⚠️ Primary server failed in tool loop ({e}). Trying fallback...")
                try:
                    resp = fallback_client.chat.completions.create(
                        model=config.FALLBACK_MODEL, messages=sel_msgs(), tools=sel_tools,
                        tool_choice=tool_choice, temperature=0.1, **_gen_kwargs(True),
                    )
                except Exception as fe:  # noqa: BLE001
                    yield {"type": "answer", "text": f"⚠️ サーバーエラー: {e} (Fallback: {fe})"}
                    return

            msg = resp.choices[0].message
            if msg.tool_calls:
                calls = [(tc.id, tc.function.name, tc.function.arguments)
                         for tc in msg.tool_calls]
            else:
                parsed = _parse_xlam(msg.content)
                calls = [(f"call_{len(tool_log) + i}", name, json.dumps(args))
                         for i, (name, args) in enumerate(parsed)] if parsed else []

        # Drop the `finish` sentinel — it is never dispatched. The model is done when
        # it calls finish (or emits no real tool) → hand to the routed synthesis round
        # (FAST→8B / THINK→27B), which generates the answer ONCE, streamed.
        real_calls = [(cid, name, args) for cid, name, args in calls if name != "finish"]
        # Guard the answer-as-arg leak: under forced tool_choice the model sometimes
        # packs its whole final answer (plus a stray <function=finish>/<tool_call> tag)
        # into a tool ARGUMENT instead of finishing. Dispatching that runs a bogus
        # query AND makes the turn generate the answer twice. Drop such calls; if
        # nothing real remains the model is effectively done → clean synthesis below.
        real_calls = [(cid, name, args) for cid, name, args in real_calls
                      if not _is_finish_leak(name, args)]
        if not real_calls:
            if committed_actions:
                # The model is done (called finish) and we have committed deliverables.
                # Route through synthesis so the model writes a coherent summary
                # incorporating all committed results, or fall back to concatenation.
                fallback = "\n\n".join(r for _, r in committed_actions)
                yield from _route_final_answer(convo, tools, tool_log, role, fallback)
                return
            if tool_log:
                last_name, _, last_result = tool_log[-1]
                if last_name in _ACTION_TOOLS or last_name.startswith("generate_"):
                    yield {"type": "answer", "text": last_result}
                    return
            # The model thinks it's done (finish / no tool), but the user actually
            # asked to mutate a real file and no edit_workspace_document call has
            # happened yet this turn — that combination is exactly the bug where the
            # model free-generates a "saved!" answer with no write behind it. Nudge
            # once instead of letting it finalize.
            if (not write_nudge_used and _wants_workspace_write(user_msg)
                    and not any(name == "edit_workspace_document" for name, _, _ in tool_log)):
                write_nudge_used = True
                # "user", not "system" — this served model's chat template rejects a
                # system message anywhere but index 0 ("System message must be at
                # the beginning"), which broke every turn that reached this nudge
                # mid-conversation. "user" is accepted anywhere and reads the same
                # to the model as an interstitial instruction.
                convo.append({"role": "user", "content": _WORKSPACE_WRITE_NUDGE})
                continue
            yield from _route_final_answer(convo, tools, tool_log, role, _fallback_answer(substantive))
            return

        convo.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": cid, "type": "function",
             "function": {"name": name, "arguments": args}}
            for cid, name, args in real_calls]})

        # Split into FRESH calls (worth running) and the rest (already gathered this
        # turn, or over the per-tool cap). Stale calls are NOT dispatched — they get
        # a terse "already have this" tool response so the model stops re-searching,
        # and they never hit the engine, the timeline, or the synthesis grounding.
        fresh, fresh_ids = [], set()
        seen_keys = set()
        for cid, name, args in real_calls:
            key = (name, _canon_args(args))
            # Freshness: not an exact repeat (dedup) AND this tool hasn't spiraled —
            # i.e. it hasn't run _TOOL_ROUND_CAP consecutive rounds WITHOUT producing
            # anything substantive. Distinct-entity fan-out (query_spr for D133/D012/
            # D168 across rounds) keeps returning real data, so it never trips the cap;
            # a rephrasing spiral (search X→Y→Z, all empty) trips it after two dry rounds.
            # Multiple calls of the same tool WITHIN one round all pass (fan-out intact).
            # _MAX_CALLS_PER_TOOL is a hard absolute cap on total dispatches per tool per
            # turn: prevents keyword-spray spirals where each call is a *fresh* key
            # (different keyword) so the dedup and round-cap never fire.
            max_calls = _MAX_CALLS_BY_TOOL.get(name, _DEFAULT_MAX_CALLS_PER_TOOL)
            if (key not in executed and key not in seen_keys
                    and tool_unproductive.get(name, 0) < _TOOL_ROUND_CAP
                    and tool_total_rounds.get(name, 0) < 10
                    and tool_call_count.get(name, 0) < max_calls):
                fresh.append((cid, name, args))
                fresh_ids.add(cid)
                seen_keys.add(key)

        sched_calls = [SchedToolCall(id=cid, name=name, arguments=args) for cid, name, args in fresh]
        plan = _SCHEDULER.schedule(sched_calls)

        # Drain any residual traces left over in the main thread before threading
        _trace.drain()
        _docs.drain()
        _crawl.drain()

        # Run the ExecutionPlan in parallel via the Engine
        def _ignore_events(evt: dict) -> None:
            pass
        # Snapshot generated-document ids BEFORE the run so a new file can be
        # attributed to its tool call by diffing the process-global registry. This
        # is robust across the threaded SSE path: Starlette resumes this sync
        # generator on different anyio threadpool threads between yields, so the
        # per-turn ContextVar buffer (_docs.start/drain) set on an earlier `next()`
        # is invisible here (different context) and comes back empty. registry._DOCS
        # is a plain module global shared by all threads, so the diff always sees it.
        docs_before = set(_docs._DOCS.keys())
        # Publish the live conversation so grounding-aware tools (generate_pptx/docx)
        # can ground on what's already in focus this session — a company/quote read
        # from a local file, a deal looked up earlier — instead of hallucinating.
        # Set here, in the same synchronous block as the engine run (no yield between),
        # so copy_context() in the engine carries it into the worker threads.
        _conversation.set_conversation(convo)
        bundle = _ENGINE.run(plan, _ignore_events) if fresh else None
        new_doc_ids = [d for d in _docs._DOCS if d not in docs_before]

        # Reconstruct the tool_log and yield UI events just like the sequential loop.
        # We preserve the order of `real_calls`.
        batch_id = f"batch_{id(plan)}" if len(fresh) > 1 else None

        # Per-round productivity, to update the unproductive-round spiral guard below.
        ran_fresh: set[str] = set()
        productive_fresh: set[str] = set()

        for cid, name, args in real_calls:
            key = (name, _canon_args(args))
            if cid not in fresh_ids:
                # Duplicate / over-cap: satisfy the API (every tool_call id needs a
                # response) but don't dispatch, don't surface a card, don't pad the
                # grounding — just nudge the model to answer with what it has.
                cached = executed.get(
                    key, "（取得済み。これ以上検索せず、収集済みの情報で回答してください。）")
                convo.append({"role": "tool", "tool_call_id": cid, "content": cached})
                continue

            ev_frag = bundle.get(cid) if bundle else None
            if not ev_frag:
                result = f"[error] Task skipped (cid={cid} not in bundle fragments. keys: {list(bundle.fragments.keys()) if bundle else 'None'})"
            else:
                result = ev_frag.data.get("text", "[error] Missing execution result")

            # TRUNCATE IF MASSIVE (prevents parallel calls from blowing up context
            # window). Cut on a natural boundary, not mid-string, so a fact — a company
            # name, a quote figure — isn't severed where the model then reads half of it.
            if len(result) > 1500:
                result = _truncate_on_boundary(result, 1500) + "\n... [truncated for length]"
            executed[key] = result
            # Remember genuinely informative results so the turn can always answer,
            # even if the synthesis round comes back empty (see _route_final_answer),
            # and track per-round productivity for the spiral guard.
            ran_fresh.add(name)
            tool_call_count[name] = tool_call_count.get(name, 0) + 1
            if _is_substantive(result):
                productive_fresh.add(name)
                substantive.append((name, result))

            tool_log.append((name, _fmt_args(args), result))
            convo.append({"role": "tool", "tool_call_id": cid, "content": result})

            ev = {"type": "tool", "name": name, "args": _fmt_args(args), "result": result, "batchId": batch_id}

            # Since threads might have dumped into the shared contextvar (or their own),
            # this is a known limitation in M1 for tracing parallel tasks. We do a global drain here.
            # In a future phase, ToolCapability will attach traces to Evidence natively.
            retrieval = _trace.drain()
            if retrieval:
                ev["retrieval"] = retrieval
            # Attach the pages web_research browsed this round (gated on the tool so
            # crawl pages can't misattribute to a different tool in the batch). Powers
            # the browser-sim replay on the tool card.
            if name == "web_research":
                drained = _crawl.drain()
                if drained:
                    pages = [d for d in drained if d.get("type") != "crawl_frame"]
                    frames = [d for d in drained if d.get("type") == "crawl_frame"]
                    if pages:
                        # Metadata only — the scroll frames carry the visuals, so the
                        # per-page screenshot is stripped to keep the event/history light.
                        ev["crawl"] = [{k: v for k, v in p.items() if k != "screenshot_b64"}
                                       for p in pages]
                    if frames:
                        # Thinned scroll sequence → an auto-playing browser replay on
                        # the chat card (the /intel path streams these live instead).
                        ev["crawlFrames"] = _downsample_frames(frames, 16)
            # Attach the file(s) this call produced. Most generate_* tools emit a single
            # deliverable, but generate_pptx now ships a whole export set (editable PPTX +
            # PDF + the source HTML) from one call, so surface them all as download chips.
            # `document` (singular) stays for backward compat = the primary editable office
            # file (pptx/docx), falling back to the newest id.
            if new_doc_ids and (name.startswith("generate_") or name in _ACTION_TOOLS):
                docs = [d for d in (_docs.get(i) for i in new_doc_ids) if d]
                if docs:
                    ev["documents"] = [{"doc_id": d["doc_id"], "kind": d["kind"],
                                        "filename": d["filename"],
                                        "download_url": d["download_url"]} for d in docs]
                    ev["document"] = next(
                        (d for d in ev["documents"]
                         if d["kind"] in ("pptx", "docx", "proposal", "ringisho")),
                        ev["documents"][-1])
            yield ev

            if _is_terminal_action(name, result):
                # The deliverable is done (file built / meeting booked / draft made).
                # Track it so re-invocation of the SAME tool is suppressed (anti-
                # duplicate), but do NOT exit the loop — the user may have asked
                # for multiple deliverables (e.g. proposal + ringisho) in one turn.
                committed_actions.append((name, result))
                if not last_round:
                    # "user", not "system" — see the write-nudge comment above; this
                    # served model's chat template 400s on a non-leading system message.
                    convo.append({"role": "user", "content":
                        f"✅ {name} が正常に完了しました。ユーザーの元のリクエストを確認してください。"
                        f"依頼されたタスクがすべて完了しましたか？ まだ残っている場合は次のツールを"
                        f"呼び出してください。すべて完了した場合は finish を呼んでください。"})

        # Spiral-guard bookkeeping: a tool that produced something substantive this
        # round resets to 0; one that ran but produced nothing counts an unproductive
        # round. The cap then short-circuits only sustained DRY repetition (a rephrasing
        # spiral), never productive multi-entity fan-out.
        for name in set(ran_fresh):
            tool_unproductive[name] = 0 if name in productive_fresh else tool_unproductive.get(name, 0) + 1
            tool_total_rounds[name] = tool_total_rounds.get(name, 0) + 1

        # Every call this round was a repeat → the model is spinning. Stop looping
        # and synthesize from what we already gathered instead of burning rounds.
        if not fresh:
            if (not write_nudge_used and _wants_workspace_write(user_msg)
                    and not any(name == "edit_workspace_document" for name, _, _ in tool_log)):
                write_nudge_used = True
                # "user", not "system" — this served model's chat template rejects a
                # system message anywhere but index 0 ("System message must be at
                # the beginning"), which broke every turn that reached this nudge
                # mid-conversation. "user" is accepted anywhere and reads the same
                # to the model as an interstitial instruction.
                convo.append({"role": "user", "content": _WORKSPACE_WRITE_NUDGE})
                continue
            yield from _route_final_answer(convo, tools, tool_log, role, _fallback_answer(substantive))
            return

        if last_round:
            # Hit the tool budget — force a final answer from what we have.
            if committed_actions:
                fallback = "\n\n".join(r for _, r in committed_actions)
                yield from _route_final_answer(convo, tools, tool_log, role, fallback)
                return
            if tool_log:
                last_name, _, last_result = tool_log[-1]
                if last_name in _ACTION_TOOLS or last_name.startswith("generate_"):
                    yield {"type": "answer", "text": last_result}
                    return
            yield from _route_final_answer(convo, tools, tool_log, role, _fallback_answer(substantive))
            return


def _stream_final_answer(convo: list[dict], tools: list[dict] | None, *,
                         no_think: bool = False, fallback_text: str = "",
                         label: str = "synthesis", _retry: bool = False):
    """Stream one tool-free completion as the answer, stripping any reasoning.
    Emits `delta` events live and a terminal `answer` with the full text.
    `no_think` prefills an empty think block so the reasoning distill skips its
    <think> phase and answers immediately (the dominant latency win)."""
    full, emitted = "", 0
    msgs = _prep(convo, no_think)
    synth_c, synth_m, alt_c, alt_m = _synth_route(no_think)
    try:
        stream = synth_c.chat.completions.create(
            model=synth_m, messages=msgs, temperature=config.SYNTH_TEMPERATURE,
            max_tokens=config.LLM_MAX_TOKENS, stream=True,
            stream_options={"include_usage": True}, **_gen_kwargs(no_think),
        )
    except Exception:  # noqa: BLE001 — fall back to a single blocking answer
        try:
            resp = alt_c.chat.completions.create(
                model=alt_m, messages=msgs, temperature=config.SYNTH_TEMPERATURE,
                max_tokens=config.LLM_MAX_TOKENS, **_gen_kwargs(no_think),
            )
            _usage.record_response(resp, model=alt_m, endpoint="fallback", label=label)
            text = re.sub(r"<think>.*?</think>", "",
                          resp.choices[0].message.content or "", flags=re.DOTALL).strip()
            yield {"type": "answer", "text": text or "(no response)"}
        except Exception as fe:  # noqa: BLE001
            yield {"type": "answer", "text": f"⚠️ サーバーエラー: {fe}"}
        return

    _usage_obj = None
    for chunk in stream:
        if getattr(chunk, "usage", None):
            _usage_obj = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None) if delta else None
        if not piece:
            continue
        full += piece
        # Strip any echoed reasoning span; only stream what follows it.
        if "</think>" in full:
            answer = full.split("</think>", 1)[1].lstrip("\n ")
        elif "<think>" in full:
            answer = ""
        else:
            answer = full
        new = answer[emitted:]
        if new:
            emitted += len(new)
            yield {"type": "delta", "text": new}

    _record_stream_usage(_usage_obj, msgs, full,
                         model=synth_m, endpoint="primary", label=label)
    final = re.sub(r"<think>.*?</think>", "", full, flags=re.DOTALL).strip()
    if final:
        yield {"type": "answer", "text": final}
        return
    # Empty answer — the reasoning phase ate the whole token budget, OR disabled
    # thinking broke the generation on this specific prompt (Atlas anomaly).
    # Retry ONCE with the INVERTED thinking mode.
    if not _retry:
        yield from _stream_final_answer(convo, tools, no_think=not no_think,
                                        fallback_text=fallback_text, _retry=True)
        return
    # Still empty even without thinking → surface the gathered evidence directly
    # rather than a blank turn. Only fall back to "(no response)" when we truly have
    # nothing.
    yield {"type": "answer", "text": fallback_text or "(no response)"}


def _fmt_args(arguments) -> str:
    try:
        d = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        return ", ".join(f"{k}={v!r}" for k, v in d.items())
    except Exception:
        return str(arguments)


_FINISH_LEAK_MARKERS = ("function=finish", "<tool_call>", "</think>", "</function>")
# Real tool args are short ({"deal_id":"D016"}, {"customer":"豊田製作所"}). An argument
# blob far larger than that is the model dumping its prose answer into a field.
_LEAK_ARG_LEN = 600


def _is_finish_leak(name: str, arguments) -> bool:
    """True when the model packed its final answer / a finish sentinel into a tool
    ARGUMENT instead of finishing cleanly (a `tool_choice=required` contortion). Such a
    call must not be dispatched — it runs a bogus query and double-generates the answer.
    Detected by a stray finish/think/tool_call marker or an answer-sized arg blob."""
    args = arguments if isinstance(arguments, str) else json.dumps(arguments or {}, ensure_ascii=False)
    low = args.lower()
    if any(mark in low for mark in _FINISH_LEAK_MARKERS):
        return True
    return len(args) > _LEAK_ARG_LEN


def _canon_args(arguments) -> str:
    """Order-independent, whitespace-normalized args form, for deduping tool calls
    within a turn ({"a":1,"b":2} and {"b":2,"a":1} collapse to one key)."""
    try:
        d = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
        return json.dumps(d, sort_keys=True, ensure_ascii=False)
    except Exception:
        return str(arguments)


# A tool that reappears in more than this many ROUNDS in one turn is almost always
# the model spiraling (rephrasing the same query across turns). Past the cap, further
# calls are short-circuited to a "you already have this" nudge instead of a real
# dispatch. Counting rounds (not calls) still allows a single round to fan out many
# parallel calls (the "search 4 laptops at once" case).
_TOOL_ROUND_CAP = 2

# Hard absolute cap on total dispatches of a single tool within one turn. This catches
# keyword-spray spirals (search_products with 40+ different keyword variants per turn)
# where every call has a unique (name, args) key so neither the dedup check nor the
# unproductive-round cap fires. Legitimate database query fan-out (like query_spr,
# search_notes, find_deals) can run up to 30 times to handle large pipeline audit requests.
_MAX_CALLS_BY_TOOL = {
    "search_products": 5,
}
_DEFAULT_MAX_CALLS_PER_TOOL = 30
````

## File: senpai/api/server.py
````python
"""FastAPI bridge — exposes the existing Senpai engines as JSON for the web UI.

Run:
    uvicorn senpai.api.server:app --reload --port 8000

Every handler is a thin serialiser over functions the Streamlit apps already
call. Nothing here changes scoring, coaching, or the knowledge pipeline; it only
reshapes their results into JSON the Next.js frontend consumes.

Design contract (kept stable for the frontend):
    GET  /api/health
    GET  /api/dashboard           team rows + KPIs + reliability flags
    GET  /api/deals/{deal_id}     one deal: signals, flags, notes, report
    POST /api/coach/review        free-text note -> a senior's reasoning scaffold
    GET  /api/coach/examples      seed notes for the demo "try one" state
    GET  /api/knowledge/principles
    GET  /api/knowledge/sources
    GET  /api/knowledge/items
    POST /api/knowledge/generate          {principle_id} -> draft item
    POST /api/knowledge/items/{id}/review {action, reviewer, notes}
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

# Windows' console defaults to the system codepage (cp1252), not UTF-8 — any
# print/log of Japanese text (customer names, deal summaries, LLM output)
# crashes the whole request with `'charmap' codec can't encode characters`.
# Reconfigure unconditionally so this can't bite regardless of how the process
# was launched (a dev's plain `uvicorn ...` with no PYTHONIOENCODING set).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

import asyncio
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from senpai import config
from senpai.api import auth
from senpai.coach.cases import find_similar_cases
from senpai.coach.context import build_commentary_context
from senpai.coaching import coaching_workspace
from senpai.coach.profile import rep_coaching_profile, team_coaching_profiles
from senpai.coach.progress import rep_progress
from senpai.growth import junior_reps, rep_growth
from senpai.coach.review import (
    commentary_prompt,
    format_review,
    narrate_review,
    narration_prompt,
    narration_prompt_en,
    review_note,
)
from senpai.data import store
from senpai.data import chat_store
from senpai.health.flags import deal_flags
from senpai.health.scoring import score_deal
from senpai.knowledge import generate as kgen
from senpai.knowledge import review as kreview
from senpai.knowledge import store as kstore
from senpai.research import shaping as _shaping
from senpai.retrieval.playbook import find_similar_deals
from senpai.tools.web import web_search_typed
from senpai.warroom import build_warroom

app = FastAPI(title="Senpai API", version="1.0", docs_url="/api/docs")

# The Next.js dev server runs on a different origin; allow it (and any, for the
# demo). Tighten ALLOWED_ORIGINS in production via env if needed.
_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_CHIP = {"red": "🔴", "yellow": "🟡", "green": "🟢"}

# The six reasoning lenses of the Coach, with the English chrome the UI labels
# them by. Keys match CoachReview fields; the UI renders these in order.
COACH_SECTIONS = [
    {"key": "observations", "ja": "経験豊富な営業が気づくこと", "en": "What a senior notices", "icon": "eye"},
    {"key": "missing_info", "ja": "確認できていない情報", "en": "Missing information", "icon": "search"},
    {"key": "risks", "ja": "リスクの兆候", "en": "Risk signals", "icon": "alert"},
    {"key": "questions", "ja": "次に聞くとよい質問", "en": "Questions to ask next", "icon": "message"},
    {"key": "next_actions", "ja": "取りうる次の一手", "en": "Possible next moves", "icon": "route"},
    {"key": "decision_factors", "ja": "判断に影響する要因", "en": "What should drive the choice", "icon": "scale"},
]

TEACH_NOTE = ("正解を一つ示すものではありません。先輩なら何に注目するか、"
              "その思考の型を提示します。状況に応じて自分で選んでください。")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _today() -> date:
    return config.today()


def _last_activity_date(acts: list[dict]) -> str | None:
    """Most recent activity_date for a deal (acts are newest-first)."""
    return next((a.get("activity_date") for a in acts if a.get("activity_date")), None)


def _scored_row(d: dict, today: date) -> tuple[dict, list[dict]]:
    acts = store.activities_for_deal(d["deal_id"])
    res = score_deal(d, acts, today=today)
    flags = deal_flags(d, acts, health_band=res.band, today=today)
    rep = store.rep_name(store.deal_rep_id(d))
    customer = store.customer_name(d["customer_id"])
    last = _last_activity_date(acts)
    stale_days = (today - date.fromisoformat(last)).days if last else None
    
    cd_history = d.get("close_date_history", [])
    slips = max(0, len(cd_history) - 1)
    
    row = {
        "deal_id": d["deal_id"],
        "customer": customer,
        "customer_id": d["customer_id"],
        "rep": rep,
        "stage": d.get("order_rank", ""),
        "amount": d.get("total_order_amount", 0),
        "band": res.band,
        "chip": _CHIP[res.band],
        "score": res.score,
        "days_stale": stale_days,
        "close_date": d.get("expected_order_date"),
        "slips": slips,
        "n_flags": len(flags),
        "decision_maker_identified": d.get("decision_maker_identified", False),
        "rep_close_likelihood": d.get("rep_close_likelihood"),
    }
    flag_rows = [
        {
            "deal_id": d["deal_id"],
            "customer": customer,
            "rep": rep,
            "severity": f.severity,
            "flag": f.name,
            "message": f.message,
        }
        for f in flags
    ]
    return row, flag_rows


def _build_timeline(deal_id: str, acts: list[dict]) -> list[dict]:
    """Chronological event log for a deal — Pillar 2, Experience. Folds the deal's
    sales activities, its quote, and any orders into one ascending timeline, and
    marks stretches of silence (>30 days) so juniors and managers can *see* how
    the deal actually moved. Pure read-over of existing records; the frontend
    localizes the type labels."""
    events: list[dict] = []
    for a in acts:
        d = a.get("activity_date")
        if not d:
            continue
        events.append({
            "date": d,
            "kind": "activity",
            "type": a.get("activity_type", ""),
            "title": a.get("business_card_info") or "",
            "detail": a.get("daily_report") or "",
            "amount": None,
        })
    q = store.quote_for_deal(deal_id)
    if q and q.get("quoted_at"):
        events.append({
            "date": q["quoted_at"], "kind": "quote", "type": q.get("quote_type", ""),
            "title": q.get("product_mid_category") or q.get("product_major_category") or "",
            "detail": "", "amount": q.get("quote_amount"),
        })
    for o in store.orders_for_deal(deal_id):
        if o.get("ordered_at"):
            events.append({
                "date": o["ordered_at"], "kind": "order", "type": "",
                "title": o.get("product_name") or "", "detail": o.get("supplier") or "",
                "amount": o.get("total_sales_amount"),
            })

    events.sort(key=lambda e: e["date"])

    # Insert silence markers between consecutive events more than 30 days apart.
    out: list[dict] = []
    prev: date | None = None
    for ev in events:
        try:
            cur = date.fromisoformat(ev["date"])
        except (ValueError, TypeError):
            cur = None
        if prev and cur and (cur - prev).days > 30:
            out.append({"date": prev.isoformat(), "kind": "gap", "type": "",
                        "title": "", "detail": "", "amount": None,
                        "days": (cur - prev).days})
        out.append(ev)
        if cur:
            prev = cur
    return out


def _principle_payload(p) -> dict:
    return {
        "principle_id": p.principle_id,
        "statement": p.statement,
        "tags": p.tags,
        "status": p.status,
        "interview_ids": p.interview_ids,
        "n_interviews": len(p.interview_ids),
        "support": [asdict(c) for c in p.support],
        "corroborating_surveys": [asdict(c) for c in p.corroborating_surveys],
        "added_by": p.added_by,
        "added_at": p.added_at,
    }


def _item_payload(it) -> dict:
    p = kstore.get_principle(it.provenance.principle_id)
    d = it.to_dict()
    d["confidence"] = it.confidence(p)
    d["principle_statement"] = p.statement if p else ""
    d["n_interviews"] = len(p.interview_ids) if p else 0
    return d


# ---------------------------------------------------------------------------
# system
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok", "today": _today().isoformat(),
            "pinned": bool(os.environ.get("SENPAI_TODAY"))}


# ---------------------------------------------------------------------------
# auth — simple demo signup/login (persisted, hashed accounts; see senpai.api.auth)
# ---------------------------------------------------------------------------
class SignupRequest(BaseModel):
    username: str          # login handle
    password: str
    name: str              # the new rep's display name
    manager_id: str        # the existing senior/expert they report to


class LoginRequest(BaseModel):
    username: str
    password: str


def _manager_pool() -> list[dict]:
    """The senior/expert reps a new junior can report to — the assignable manager
    pool. Any senior/expert qualifies (assignment is org-based via reports_to,
    not derived from existing coaching threads)."""
    return [{"employee_id": r["employee_id"], "name": r["name"], "role": r["role"],
             "department": r.get("department", ""), "division": r.get("division", "")}
            for r in store.all_reps() if r.get("role") in ("senior", "expert")]


@app.get("/api/reps/managers")
def reps_managers():
    """The manager pool for the junior signup picker: who's your manager?"""
    return {"managers": _manager_pool()}


@app.post("/api/auth/signup")
def auth_signup(req: SignupRequest):
    """Register a NEW junior. Creates a fresh seed-shape junior rep (no deals or
    coaching yet), assigned to an existing manager (reports_to), then an account
    linked to it. 400 on blank fields, a taken username, or an invalid manager.

    The new rep inherits the manager's department/division so it slots into the
    org cleanly. See store.append_rep / store.next_employee_id."""
    name, username = (req.name or "").strip(), (req.username or "").strip()
    if not name or not username or not req.password:
        raise HTTPException(400, "name, username and password are required")
    manager = store.get_rep(req.manager_id)
    if manager is None or manager.get("role") not in ("senior", "expert"):
        raise HTTPException(400, "choose your manager")
    if auth.username_exists(username):
        raise HTTPException(400, "username already taken")

    employee_id = store.next_employee_id()
    store.append_rep({
        "employee_id": employee_id,
        "name": name,
        "role": "junior",
        "department": manager.get("department", ""),
        "division": manager.get("division", ""),
        "specialty_tags": [],
        "is_top_performer": False,
        "reports_to": req.manager_id,
    })
    try:
        user = auth.create_user(username, req.password, "junior", employee_id=employee_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"token": auth.issue_token(), **user}


@app.post("/api/auth/login")
def auth_login(req: LoginRequest):
    """Authenticate. 401 on bad credentials. Returns a session token plus the
    account's username, role, and employee_id (role picks the experience; the
    employee_id scopes the data to that rep)."""
    user = auth.verify_user(req.username, req.password)
    if user is None:
        raise HTTPException(401, "invalid username or password")
    return {"token": auth.issue_token(), **user}


# ---------------------------------------------------------------------------
# documents — download a file the chatbot generated (PPTX/DOCX)
# ---------------------------------------------------------------------------
_DOC_MEDIA = {
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".html": "text/html; charset=utf-8",
}


@app.get("/api/documents/{doc_id}")
def download_document(doc_id: str):
    """Serve a generated document by id. Only files in the registry are reachable —
    the endpoint never accepts a raw path. The chat tool event carries the doc_id."""
    from senpai.documents import registry
    rec = registry.get(doc_id)
    if rec is None or not os.path.exists(rec["path"]):
        raise HTTPException(404, f"document {doc_id} not found")
    ext = os.path.splitext(rec["filename"])[1].lower()
    return FileResponse(rec["path"], filename=rec["filename"],
                        media_type=_DOC_MEDIA.get(ext, "application/octet-stream"))

class ExportDocRequest(BaseModel):
    text: str
    title: str = ""
    slug: str = ""


@app.post("/api/documents/export")
def export_document(req: ExportDocRequest):
    """Turn an assistant message's raw text into a downloadable .docx, verbatim —
    no LLM re-authoring, no re-gathering evidence. Same contract as a CSV export:
    the file matches exactly what's already on screen, just in a different format."""
    from senpai.documents.export import export_text_as_docx
    if not (req.text or "").strip():
        raise HTTPException(400, "text is empty")
    rec = export_text_as_docx(req.text, title=req.title, slug=req.slug)
    return {"document": rec}


# ---------------------------------------------------------------------------
# dashboard
# ---------------------------------------------------------------------------
@app.get("/api/dashboard")
def dashboard(rep: str | None = None, manager: str | None = None):
    today = _today()
    # A manager sees only their team (coachees + assigned juniors); None = all.
    team = {store.rep_name(e) for e in store.team_of(manager)} if manager else None
    rows, flagged = [], []
    for d in store.open_deals():
        if team is not None and store.rep_name(store.deal_rep_id(d)) not in team:
            continue
        row, frows = _scored_row(d, today)
        rows.append(row)
        flagged.extend(frows)
    if rep and rep != "(all)":
        rows = [r for r in rows if r["rep"] == rep]
        flagged = [f for f in flagged if f["rep"] == rep]

    order = {"high": 0, "medium": 1, "low": 2}
    flagged.sort(key=lambda r: order.get(r["severity"], 3))
    reps = sorted(team) if team is not None else \
        sorted({store.rep_name(store.deal_rep_id(d)) for d in store.open_deals()})
    kpis = {
        "open_deals": len(rows),
        "at_risk": sum(1 for r in rows if r["band"] == "red"),
        "watch": sum(1 for r in rows if r["band"] == "yellow"),
        "healthy": sum(1 for r in rows if r["band"] == "green"),
        "flagged_reports": len(flagged),
        "pipeline_total": sum(r["amount"] for r in rows),
    }
    return {"today": today.isoformat(), "kpis": kpis, "deals": rows,
            "flags": flagged, "reps": reps}


@app.get("/api/warroom")
def warroom(manager: str | None = None):
    """Pipeline War Room replay: every deal reconstructed and re-scored as of
    weekly snapshot dates (see senpai.warroom). `manager` scopes to a team."""
    return build_warroom(manager)


@app.get("/api/deals/{deal_id}")
def deal_detail(deal_id: str):
    d = store.get_deal(deal_id)
    if d is None:
        raise HTTPException(404, f"deal {deal_id} not found")
    today = _today()
    acts = store.activities_for_deal(deal_id)
    res = score_deal(d, acts, today=today)
    flags = deal_flags(d, acts, health_band=res.band, today=today)
    return {
        "deal": {
            "deal_id": d["deal_id"],
            "customer": store.customer_name(d["customer_id"]),
            "customer_id": d["customer_id"],
            "rep": store.rep_name(store.deal_rep_id(d)),
            "stage": d.get("order_rank", ""),
            "amount": d.get("total_order_amount", 0),
            "expected_close_date": d.get("expected_order_date"),
            "last_contact_date": _last_activity_date(acts),
            "decision_maker_identified": d.get("decision_maker_identified", False),
            "rep_close_likelihood": d.get("rep_close_likelihood"),
            "close_date_history": d.get("close_date_history", []),
            "stage_history": d.get("stage_history", []),
            "products": [d["product_category"]] if d.get("product_category") else [],
        },
        "score": res.score,
        "band": res.band,
        "signals": [asdict(s) for s in sorted(res.signals, key=lambda x: x.points, reverse=True)],
        "flags": [asdict(f) for f in flags],
        "notes": [
            {
                "note_id": f"{deal_id}-{i}",
                "date": a.get("activity_date"),
                "channel": a.get("activity_type", ""),
                "text": a.get("daily_report", ""),
            }
            for i, a in enumerate(acts)
        ],
        "timeline": _build_timeline(deal_id, acts),
        "report": None,
    }


# ---------------------------------------------------------------------------
# coach
# ---------------------------------------------------------------------------
class CoachRequest(BaseModel):
    note: str
    deal_id: str | None = None
    narrate: bool = False
    lang: str = "ja"  # narration output language ("ja" | "en") — presentation only
    conversation_id: str | None = None  # reuse a built context across re-narrates

class TranslateRequest(BaseModel):
    text: str
    target_lang: str

@app.post("/api/translate")
def translate_text(req: TranslateRequest):
    from senpai.llm.client import simple_complete
    prompt = f"Translate the following text to {req.target_lang}. Return ONLY the translated text. Do not include any other commentary. Original text:\n\n{req.text}"
    translated = simple_complete([{"role": "user", "content": prompt}], temperature=0.0)
    return {"translated_text": translated}


# Optional LLM narration. Off unless SENPAI_USE_LLM is truthy, so the coach
# stays deterministic by default; when on, the served model only *rephrases*
# the deterministic findings (never adds facts), with fallback baked in.
USE_LLM = os.environ.get("SENPAI_USE_LLM", "0").lower() not in ("0", "false", "", "no")


@app.post("/api/coach/review")
@app.post("/api/coach/review")
def coach_review(req: CoachRequest):
    deal = store.get_deal(req.deal_id) if req.deal_id else None
    acts = store.activities_for_deal(req.deal_id) if deal else None
    r = review_note(req.note, deal=deal, notes=acts, report=None)

    # Phase 3: Data vs Reality Check intercept
    reality_check_text = None
    if deal and acts is not None:
        today = _today()
        res = score_deal(deal, acts, today=today)
        flags = deal_flags(deal, acts, health_band=res.band, today=today)
        
        has_optimism_mismatch = any(f.name == "optimism_mismatch" for f in flags)
        rep_likelihood = deal.get("rep_close_likelihood")
        
        if has_optimism_mismatch or (rep_likelihood == "high" and res.band == "red"):
            flag_msgs = [f.message for f in flags if f.name == "optimism_mismatch"]
            reason = flag_msgs[0] if flag_msgs else "担当の見込みとデータの健全度が食い違っています。"
            reality_check_text = f"🚨 データと実態のズレを検知: {reason} 抜け漏れがないか再確認してください。"

    # Phase 1 & 2: Account Context Resolution
    from senpai.matsuda import build_account_context
    customer = None
    if deal:
        customer = store.get_customer(deal.get("customer_id"))
    else:
        customer = store.match_customer_in_text(req.note)

    account_context_payload = None
    if customer:
        try:
            ctx = build_account_context(customer["customer_id"])
            account_context_payload = ctx.to_llm_payload()
        except Exception:
            pass

    narration = None
    llm_model = None
    if USE_LLM and req.narrate:
        out = narrate_review(r, use_llm=True)
        if out and out.strip() != format_review(r).strip():
            narration = out
            llm_model = config.MODEL

    sections = list(COACH_SECTIONS)
    result_dict = {s["key"]: getattr(r, s["key"]) for s in COACH_SECTIONS}

    if reality_check_text:
        sections.insert(0, {
            "key": "reality_check",
            "ja": "データと実態のズレ",
            "en": "Data vs Reality Check",
            "icon": "alert"
        })
        result_dict["reality_check"] = [reality_check_text]

    ctx_text, ctx_meta = build_commentary_context(
        req.note, deal_id=req.deal_id, today=_today(), lang=req.lang)

    return {
        "teach_note": TEACH_NOTE,
        "sections": sections,
        "used_deal": r.used_deal,
        "result": result_dict,
        "narration": narration,
        "llm_model": llm_model,
        "account_context": account_context_payload,
        "resolution": {
            "customer": ctx_meta.get("customer"),
            "deal_id": ctx_meta.get("deal_id"),
            "confidence": ctx_meta.get("confidence", "none"),
            "match_method": ctx_meta.get("match_method", "none"),
            "grounded": ctx_meta.get("has_customer_context", False),
        },
        "explanations": [e.to_dict() for e in getattr(r, "explanations", [])],
    }


def _sse(obj: dict) -> str:
    """Encode one Server-Sent Event frame."""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


# Reasoning tags vary by sampling: the model emits either <think> or <thinking>
# (and the matching close). Match both spellings so a reasoning block is never
# leaked into the user-facing answer.
# Reasoning markers this distilled model may emit before its actual answer.
# Besides <think>/<thinking> it sometimes wraps its scratchpad in <analysis> or
# <reasoning> — all must be stripped so the chain-of-thought never leaks into a
# senior's read or a research summary.
_THINK_CLOSE = re.compile(r"</(?:think(?:ing)?|analysis|reasoning)>", re.IGNORECASE)
_THINK_OPEN = re.compile(r"<(?:think(?:ing)?|analysis|reasoning)>", re.IGNORECASE)


def _strip_reasoning(full: str) -> str | None:
    """The answer portion of a partial stream with any reasoning block removed.

    Returns None while still inside an unclosed <think>/<thinking> block (the
    caller surfaces a 'thinking' indicator); otherwise the visible answer text."""
    m = _THINK_CLOSE.search(full)
    if m:
        return full[m.end():].lstrip("\n -")
    if _THINK_OPEN.search(full):
        return None
    return full


@app.post("/api/coach/narrate")
def coach_narrate(req: CoachRequest):
    """Stream the Senior Commentary token-by-token (SSE).

    This is an experienced rep's *interpretation* layered on the deterministic
    coach — grounded in a retrieved business-context package (customer, deal
    health, activity, history, similar cases), NOT a restatement of the lenses.
    Reasoning is OFF by default (fast live path); set SENPAI_NARRATE_THINK=1 to let
    the model think first (slower, richer) — either way any <think>/<thinking>
    block is stripped before streaming. The request is pinned to the primary GGUF
    endpoint — on any failure we emit an explicit `unavailable`. Event types:
      start | context | thinking | delta | done | unavailable
    The frontend renders deltas live and shows "Senior commentary unavailable" on
    `unavailable`."""
    if not USE_LLM:
        return StreamingResponse(
            iter([_sse({"type": "unavailable", "reason": "llm_disabled"})]),
            media_type="text/event-stream",
        )

    # Conversation cache: re-narrating the SAME deal+note in a session reuses the
    # already-built deterministic context package (review_note + commentary context)
    # instead of recomputing it. The build is cheap, but caching keeps the grounded
    # context byte-identical across re-narrates and signals provenance to the UI.
    conversation_id = (req.conversation_id or "default").strip() or "default"
    cache = _COACH_CONTEXTS.get(conversation_id)
    cached_flag = bool(cache and cache["deal_id"] == req.deal_id and cache["note"] == req.note
                       and cache["lang"] == req.lang)
    if cached_flag:
        r, context_text, ctx_meta = cache["r"], cache["context_text"], cache["meta"]
    else:
        deal = store.get_deal(req.deal_id) if req.deal_id else None
        acts = store.activities_for_deal(req.deal_id) if deal else None
        r = review_note(req.note, deal=deal, notes=acts, report=None)
        context_text, ctx_meta = build_commentary_context(
            req.note, deal_id=req.deal_id, today=_today(), lang=req.lang)
        _COACH_CONTEXTS[conversation_id] = {
            "deal_id": req.deal_id, "note": req.note, "lang": req.lang,
            "r": r, "context_text": context_text, "meta": ctx_meta}
    prompt = commentary_prompt(req.note, r, context_text,
                               ctx_meta["has_customer_context"], lang=req.lang,
                               customer_name=ctx_meta.get("customer"),
                               deal_id=ctx_meta.get("deal_id"))

    # Workspace continuity: a grounded review puts its deal/customer "in focus" for
    # the shared conversation, so a follow-up chat turn stays scoped to it.
    if ctx_meta.get("has_customer_context"):
        _seed_chat_focus(conversation_id, ctx_meta.get("customer_id"),
                         ctx_meta.get("customer"), ctx_meta.get("deal_id"))

    def gen():
        from senpai.llm import client
        yield _sse({"type": "start", "model": config.MODEL,
                    "endpoint": config.BASE_URL, "conversation_id": conversation_id})
        # Workspace: this stream produces a `review` artifact. Entity is the
        # resolved deal when one was grounded (deterministic; never a name guess).
        _meta = {"type": "artifact_meta", "kind": "review"}
        if ctx_meta.get("deal_id"):
            _meta["entity_ref"] = {"type": "deal", "id": ctx_meta["deal_id"],
                                   "name": ctx_meta.get("customer")}
        yield _sse(_meta)
        # Tell the UI what real records the read is grounded in (or that none matched).
        yield _sse({"type": "context", "grounded": ctx_meta["has_customer_context"],
                    "customer": ctx_meta["customer"], "deal_id": ctx_meta["deal_id"],
                    "confidence": ctx_meta.get("confidence", "none"),
                    "match_method": ctx_meta.get("match_method", "none"),
                    "candidates": ctx_meta.get("ambiguous_candidates", []),
                    "cached": cached_flag})
        # Customer still unresolved (the note named an ambiguous / near-miss
        # company). Don't generate a senior's read yet — the rep must first pick
        # which customer. Generating now would (a) waste a ~15s call on a read the
        # rep discards, and (b) show a read before the choice is even made. Stop
        # after the candidates; the pick re-runs this grounded.
        if not ctx_meta["has_customer_context"] and ctx_meta.get("ambiguous_candidates"):
            yield _sse({"type": "awaiting_choice"})
            yield _sse({"type": "done", "model": config.MODEL})
            return
        full, emitted, last_think = "", 0, 0
        try:
            for piece in client.stream_complete(
                [{"role": "user", "content": prompt}],
                temperature=0.5, max_tokens=config.LLM_NARRATE_MAX_TOKENS,
                no_think=not config.NARRATE_THINK, allow_fallback=False,
            ):
                full += piece
                answer = _strip_reasoning(full)                 # hide any reasoning block
                if answer:
                    new = answer[emitted:]
                    if new:
                        emitted += len(new)
                        yield _sse({"type": "delta", "text": new})
                elif answer is None and len(full) - last_think >= 48:
                    last_think = len(full)
                    yield _sse({"type": "thinking", "chars": len(full)})
            if emitted:
                yield _sse({"type": "done", "model": config.MODEL})
            else:
                # Reasoning consumed the whole budget before any answer token (a
                # long <think> block on a contended GPU). Retry once with thinking
                # off so the rep always gets a grounded read, never a blank.
                fb, fb_emitted = "", 0
                for piece in client.stream_complete(
                    [{"role": "user", "content": prompt}],
                    temperature=0.5, max_tokens=config.LLM_NARRATE_MAX_TOKENS,
                    no_think=True, allow_fallback=False,
                ):
                    fb += piece
                    ans = _strip_reasoning(fb)
                    new = ans[fb_emitted:] if ans else ""
                    if new:
                        fb_emitted += len(new)
                        yield _sse({"type": "delta", "text": new})
                if fb_emitted:
                    yield _sse({"type": "done", "model": config.MODEL})
                else:
                    yield _sse({"type": "unavailable", "reason": "empty"})
        except Exception:  # noqa: BLE001 — primary endpoint down/timeout (no fallback)
            yield _sse({"type": "unavailable", "reason": "unreachable"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Ringi Boardroom Simulation — the Consensus Training Theater (稟議攻略シアター)
# ---------------------------------------------------------------------------
# Streams a deterministic multi-persona boardroom debate. simulate_ringi() decides
# EVERYTHING that matters — who speaks (課長/部長/社長), which objections fire, and
# every approval-meter delta — from the same engines the dashboard uses. The served
# model only rephrases each beat's Japanese for fluidity; if it's unreachable we
# stream the beat's deterministic text verbatim, so the theater never stalls.
class RingiRequest(BaseModel):
    deal_id: str
    overlay: list[dict] | None = None  # session-scoped sandbox drafts (re-run loop)


# How to voice each persona when the model polishes a beat's phrasing.
_RINGI_PERSONA_BRIEF = {
    "shacho": "最終決裁権を持つ社長(厳格で結論を急ぐ)",
    "bucho": "予算と決裁を握る部長(投資対効果と決裁者の所在に厳しい)",
    "kacho": "現場を仕切る課長(仕様・運用・情報の精度にこだわる)",
    "senpai": "若手を導く営業の先輩(冷静で的確、比喩がうまい)",
}


def _ringi_beat_messages(deal_name: str, customer: str, persona: str, text: str) -> list[dict]:
    """One-line brief: rephrase this exact objection in the persona's voice. The
    model only polishes — the meaning, facts, and numbers are already fixed."""
    role = _RINGI_PERSONA_BRIEF.get(persona, "会議の参加者")
    prompt = (
        f"あなたは日本企業の稟議(意思決定会議)に出席する{role}です。"
        f"取引先『{customer}』の案件『{deal_name}』について、次の主旨を"
        "あなたの立場と口調で1〜2文の自然な日本語の発言に言い換えてください。"
        "主旨・事実・数字は変えないこと。新しい数字の創作は禁止。"
        "前置きや解説は書かず、発言そのものだけを返してください。\n"
        f"主旨: {text}"
    )
    return [{"role": "user", "content": prompt}]


@app.post("/api/training/ringi/stream")
def ringi_stream(req: RingiRequest):
    """Stream the deterministic Ringi boardroom debate as SSE frames.

    Frames: meta → (speaker_start → delta* → speaker_end)* → intervention? → done.
    """
    from senpai.ingestion.persist import build_activity_record
    from senpai.simulation.ringi import simulate_ringi

    deal = store.get_deal(req.deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail=f"Unknown deal_id: {req.deal_id}")

    # Sandbox drafts → seed-shaped activities IN MEMORY (build_activity_record stamps
    # activity_date=today and never persists here; no store mutation, no disk write).
    overlay_acts: list[dict] = []
    for draft in (req.overlay or []):
        if isinstance(draft, dict):
            overlay_acts.append(build_activity_record(
                draft, deal["customer_id"], req.deal_id, store.deal_rep_id(deal)))

    script = simulate_ringi(req.deal_id, overlay_activities=overlay_acts, today=_today())

    def gen():
        import time

        from senpai.llm import client

        # Pacing so the debate plays out live instead of dumping at once. (This
        # sync generator is iterated in a threadpool, so time.sleep is safe and
        # doesn't block the event loop.) The LLM path paces itself; only the
        # deterministic fallback text is typewriter-chunked here.
        FIRST_DELAY = 0.3      # after meta, before the room starts
        THINK_DELAY = 0.28     # after a speaker lights up, before they talk
        BEAT_PAUSE = 0.6       # gap between one member finishing and the next
        CHAR_CHUNK = 2         # fallback: chars emitted per delta
        CHAR_DELAY = 0.04      # fallback: pause between those chunks
        PRE_VERDICT = 0.5      # beat before the intervention / final verdict

        yield _sse({"type": "meta", "deal_id": script.deal_id,
                    "deal_name": script.deal_name, "customer": script.customer,
                    "base_approval": script.base_approval,
                    "final_approval": script.final_approval,
                    "band": script.band, "issues": script.issues})
        time.sleep(FIRST_DELAY)

        approval = 100  # rep's optimistic starting view; objections tick it to base_approval
        for i, beat in enumerate(script.beats):
            if i > 0:
                time.sleep(BEAT_PAUSE)  # let the floor pass between members
            yield _sse({"type": "speaker_start", "index": i,
                        "persona": beat.persona, "issue": beat.issue})
            time.sleep(THINK_DELAY)  # speaker's halo/pulse shows before they talk
            streamed = ""
            if USE_LLM:
                try:
                    full, emitted = "", 0
                    for piece in client.stream_complete(
                        _ringi_beat_messages(script.deal_name, script.customer,
                                             beat.persona, beat.text),
                        temperature=config.SYNTH_TEMPERATURE, max_tokens=160,
                        no_think=True, allow_fallback=False, label="ringi",
                    ):
                        full += piece
                        ans = _strip_reasoning(full)
                        new = ans[emitted:] if ans else ""
                        if new:
                            emitted += len(new)
                            streamed += new
                            yield _sse({"type": "delta", "index": i, "text": new})
                except Exception:  # noqa: BLE001 — model down/timeout; use the template
                    streamed = ""
            if not streamed.strip():
                # Deterministic fallback — type the beat's own Japanese out in
                # small chunks so it reads as the persona speaking in real time.
                streamed = beat.text
                for j in range(0, len(beat.text), CHAR_CHUNK):
                    yield _sse({"type": "delta", "index": i,
                                "text": beat.text[j:j + CHAR_CHUNK]})
                    time.sleep(CHAR_DELAY)

            approval += beat.approval_delta
            yield _sse({"type": "speaker_end", "index": i, "persona": beat.persona,
                        "approval_delta": beat.approval_delta, "approval_now": approval,
                        "whisper": beat.whisper, "issue": beat.issue,
                        "text": streamed.strip()})

        time.sleep(PRE_VERDICT)
        if script.intervention:
            yield _sse({"type": "intervention", **script.intervention})
        yield _sse({"type": "done", "final_approval": script.final_approval,
                    "band": script.band, "model": config.MODEL})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# chat — the tool-calling assistant (junior / manager), streamed over SSE
# ---------------------------------------------------------------------------
# This exposes the SAME tool loop the Streamlit/Gradio chats use (stream_turn +
# the role-scoped tool schemas) to the web product. The model autonomously calls
# the deterministic sales tools — and web_search — grounding every answer in
# store data. Tools are imported here; the openai-backed client is imported
# lazily inside the generator so this module stays importable without a server.
from senpai.tools.schemas import JUNIOR_TOOLS, MANAGER_TOOLS, RESEARCH_TOOLS


# Concise system prompts (mirror senpai/apps/*_chat.py; inlined so we don't import
# gradio). today() is read per-request so a pinned SENPAI_TODAY is respected.
def _junior_system() -> str:
    return (
        "あなたは大塚商会の新人営業を支える『先輩(senpai)』アシスタントです。"
        "社内営業の専門アシスタントであると同時に、汎用アシスタントとしても役立ちます。\n"

        "【社内・顧客・案件・製品に関する質問】"
        "必ずツール(query_spr / search_knowledge / search_products / score_deal_health など)で"
        "社内データ(SPR・プレイブック・顧客環境・案件健全度)を確認してから答えてください。"
        "「どう対応すべきか」を問われたら、まず search_knowledge で社内ナレッジ"
        "(先輩の原則・承認済み事例・プレイブック)を引き、指定された構造化出典ID（例: Playbook PB12）を"
        "そのまま添えること。顧客・会社・製品・案件に関する質問は、回答前に必ず query_spr / "
        "search_knowledge / search_products のいずれかを呼び出して確認すること。"
        "また、特定の顧客に対して『何を提案すべきか』『推奨ソリューションは何か』と問われた場合は、必ず advise_solutions ツールを呼び出して推奨製品を取得すること。"
        "ツールを呼ばずに『社内データに無い』と述べてはいけません。"
        "社内の数値は与えられたものだけを使い、人名や提供者名は絶対に推測・生成しないこと。"
        "ツール結果に含まれる氏名は、英語で文書を作成する場合でも絶対に別の名前に"
        "置き換えたり英語風の名前に創作したりせず、ツール結果の表記のまま使うこと。"
        "製品の相談には search_products / create_quote、訪問調整には schedule_meeting、"
        "連絡文の準備には send_email を使えます(いずれも下書きで、送信・確定はしません)。"
        "社内案件で自信が持てない時は route_to_expert で先輩に橋渡ししてください。"
        "ツールが必要な操作（予定調整・見積作成・検索・社内データ確認など）では、"
        "『〜します』と手順を説明したり、呼び出し内容を文章で書き出したりせず、"
        "直接ツールを呼び出すこと。ツール結果が返ってから簡潔に回答する。"
        "独立した複数の情報が必要なときは、ツールを1つずつ順番に呼ばず、"
        "1ターンでまとめて並行呼び出しして往復回数を減らすこと。\n"

        "【文書作成（PPTX / DOCX）】\n"
        "提案書、稟議書、スライド(PPTX)、文書(DOCX)の作成を依頼されたら、"
        "絶対に口頭で許可を求めたりプレビューを提示するのではなく、**直ちに該当ツールを `confirm=True` で呼び出し**、ファイルを即座に生成してください。\n"
        "ツールを使わずにプレビューを自作（ハルシネーション）したり、Pythonコードを出力することは固く禁じます。\n"

        "【複数タスク】\n"
        "ユーザーが1つのメッセージで複数の作業（例: 提案書と稟議書の両方を作成、または"
        "調査してから文書を作成）を依頼した場合、最初のタスクが完了しても"
        "**残りのタスクを忘れずに順番に実行**すること。"
        "全てのタスクが完了してから最終回答をまとめること。"
        "特に、メッセージが番号付き・箇条書きの手順リスト（1. 2. 3. ... や複数の"
        "「〜について調べて」の並び）である場合、**リストされた項目1つ1つに対して"
        "個別にツールを呼び出す**こと。数個だけ実行して途中で満足して回答するのは禁止。"
        "独立した項目は1ターンにまとめて並行呼び出しし、全項目のツール結果が揃うまで"
        "最終回答を書かないこと。\n"

        "【一般的な質問（社外の事実・為替・市場価格・一般知識など）】"
        "汎用アシスタントとして、断らずに役立つ回答をしてください。"
        "市場価格・在庫・為替レート・ニュース・最新の製品仕様や型番など、時間とともに変わる"
        "事実や具体的な数値は、記憶から答えてはいけない。必ず web_search を呼び、結果の出典(URL)"
        "を添えて回答すること。web_search を呼べない/結果が得られない場合はその旨を明示し、"
        "不確かな価格・型番・数値を創作しないこと。"
        "用語の定義や一般的な概念など、時間で変わらない安定した知識のみ、あなたの知識で直接答えてよい。"
        "『社内データに無い』という理由だけで一般的な質問を断ってはいけません。\n"

        "【口調】"
        "経験豊富な先輩として、新人に寄り添い『なぜそうするのか』まで噛み砕いて教える、"
        "丁寧で面倒見のよい語り口。一歩先輩の視点で導く。\n"

        "【共通】"
        "質問の言語に合わせて回答する（英語の質問には英語で答える）。"
        "回答は読みやすいMarkdownで整える: 区切りには短い**太字の見出しラベル**"
        "（例: **状況:** …）や見出しを使い、列挙は箇条書きにし、簡潔かつ実務的にまとめる。"
        f"本日は {_today().isoformat()} です。"
    )


def _manager_system() -> str:
    return (
        "あなたは大塚商会の営業マネージャーを支えるアシスタントです。"
        "チーム運営の専門アシスタントであると同時に、汎用アシスタントとしても役立ちます。\n"

        "【チーム・案件・社内データに関する質問】"
        "チーム全体の案件健全度・日報・パイプラインを把握し、リスクの高い案件や"
        "コーチングが必要な担当を、必ずツールで取得した社内データに基づいて示します。"
        "数字は与えられたものだけを使い、創作しないこと。コーチングの根拠は "
        "search_knowledge で社内ナレッジ(先輩の原則・承認済み事例・プレイブック)を引き、"
        "指定された構造化出典ID（例: Playbook PB12）をそのまま添えて示すこと。"
        "特定の顧客に対して『何を提案すべきか』と問われた場合は、必ず advise_solutions ツールを呼び出して推奨製品を取得すること。"
        "絶対に人名や提供者名を推測・生成しないでください。"
        "ツール結果に含まれる氏名は、英語で文書を作成する場合でも絶対に別の名前に"
        "置き換えたり英語風の名前に創作したりせず、ツール結果の表記のまま使うこと。"
        "製品の確認や見積例には search_products / create_quote、"
        "調整や連絡文の準備には schedule_meeting / send_email を使えます"
        "(いずれも下書きで、送信・確定はしません)。"
        "ツールが必要な操作では、『〜します』と手順を説明したり呼び出し内容を文章で"
        "書き出したりせず、直接ツールを呼び出すこと。ツール結果が返ってから簡潔に回答する。"
        "独立した複数の情報が必要なときは、ツールを1つずつ順番に呼ばず、1ターンでまとめて"
        "並行呼び出しして往復回数を減らすこと。\n"

        "【文書作成（PPTX / DOCX）】\n"
        "提案書、稟議書、スライド(PPTX)、文書(DOCX)の作成を依頼されたら、"
        "絶対に口頭で許可を求めたりプレビューを提示するのではなく、**直ちに該当ツールを `confirm=True` で呼び出し**、ファイルを即座に生成してください。\n"
        "ツールを使わずにプレビューを自作（ハルシネーション）したり、Pythonコードを出力することは固く禁じます。\n"

        "【複数タスク】\n"
        "ユーザーが1つのメッセージで複数の作業（例: 提案書と稟議書の両方を作成、または"
        "調査してから文書を作成）を依頼した場合、最初のタスクが完了しても"
        "**残りのタスクを忘れずに順番に実行**すること。"
        "全てのタスクが完了してから最終回答をまとめること。"
        "特に、メッセージが番号付き・箇条書きの手順リスト（1. 2. 3. ... や複数の"
        "「〜について調べて」の並び）である場合、**リストされた項目1つ1つに対して"
        "個別にツールを呼び出す**こと。数個だけ実行して途中で満足して回答するのは禁止。"
        "独立した項目は1ターンにまとめて並行呼び出しし、全項目のツール結果が揃うまで"
        "最終回答を書かないこと。\n"

        "【一般的な質問（社外の事実・為替・市場価格・一般知識など）】"
        "汎用アシスタントとして、断らずに役立つ回答をしてください。"
        "市場価格・在庫・為替レート・ニュース・最新の製品仕様など、時間とともに変わる事実や"
        "具体的な数値は記憶から答えず、必ず web_search を呼んで出典(URL)を添えること。"
        "web_search を呼べない/結果が無い場合はその旨を明示し、不確かな数値を創作しないこと。"
        "時間で変わらない安定した一般知識のみ、あなたの知識で直接答えてよい。"
        "『社内データに無い』という理由だけで一般的な質問を断ってはいけません。\n"

        "【口調】"
        "経験豊富なマネージャーを支える有能なスタッフ・アナリストとして、対等で簡潔に、"
        "要点と数字を先に出す。指導や説教はせず、相手の経験を前提に判断材料を提供することに徹する。\n"

        "【共通】"
        "質問の言語に合わせて回答する。"
        "回答は読みやすいMarkdownで整える: 区切りには短い**太字の見出しラベル**"
        "（例: **要点:** …）や見出しを使い、列挙は箇条書きにし、簡潔にまとめる。"
        f"本日は {_today().isoformat()} です。"
    )


def _research_system() -> str:
    # The research assistant answers "tell me about / research this customer"
    # questions. Strict source priority — internal first, web only to fill gaps —
    # so it stays a grounded research tool, NOT a generic chatbot.
    return (
        "あなたは大塚商会の営業担当が顧客訪問前に使う『顧客リサーチ』アシスタントです。"
        "顧客について調べる質問に、必ずツールを使って答えます。\n"
        "厳守する調査手順（この順序を逆にしないこと）:\n"
        "1. まず query_spr で社内の顧客・案件情報を確認する（英語/ローマ字の社名でも"
        "そのまま渡せば内部で名寄せされる。例: 'Aozora Services'）。\n"
        "2. 案件があれば score_deal_health で健全度、find_similar_deals で類似案件、"
        "lookup_customer_environment でIT環境、get_product_info で製品情報を補う。"
        "顧客が分かった後のこれらの補完ツールは互いに独立しているので、1つずつではなく"
        "1ターンでまとめて並行呼び出しし、往復回数を減らすこと。\n"
        "3. 社内情報で答えられない外部情報（事業内容・業界動向・競合・最新ニュース）が"
        "必要なときに限り web_search を使う。\n"
        "回答ルール: 社内データを最優先で示し、その後に外部情報を添える。"
        "社内に記録がない場合はその旨を明記し、事実を創作しない。"
        "web_search の結果は出典（URL）を添えて引用する。"
        "日本語で、要点を構造化して簡潔に答えます。"
        f"本日は {_today().isoformat()} です。"
    )


_CHAT_ROLES = {
    "junior": (JUNIOR_TOOLS, _junior_system),
    "manager": (MANAGER_TOOLS, _manager_system),
    "research": (RESEARCH_TOOLS, _research_system),
}


@dataclass
class ResearchBundle:
    query: str
    target: str
    resolution: dict
    customer: dict | None = None
    active_deal_id: str | None = None
    active_deal: dict | None = None
    deals: list[dict] = field(default_factory=list)
    activities: list[dict] = field(default_factory=list)
    environment: dict | None = None
    products: list[dict] = field(default_factory=list)
    similar_deals: list[dict] = field(default_factory=list)
    web: dict | None = None
    provenance: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


_RESEARCH_PREFIXES = [
    r"^\s*tell\s+me\s+about\s+",
    r"^\s*research\s+",
    r"^\s*background\s+on\s+",
    r"^\s*find\s+out\s+about\s+",
    r"^\s*what\s+should\s+i\s+know\s+about\s+",
    r"^\s*use\s+web_search\s+and\s+tell\s+me\s+about\s+",
    r"^\s*switch\s+to\s+",
]

_RESEARCH_CONTEXTS: dict[str, ResearchBundle] = {}
# Conversation caches (mirror _RESEARCH_CONTEXTS) so a multi-turn session keeps its
# context across turns: the Assistant remembers the account in focus; Review Coach
# reuses the built commentary-context package for the same deal instead of rebuilding.
_CHAT_CONTEXTS: dict[str, dict] = {}        # conversation_id -> {customer_id, customer, deal_id}
_COACH_CONTEXTS: dict[str, dict] = {}       # conversation_id -> {deal_id, note, r, context_text, meta}
_DEAL_ID_RE = re.compile(r"\bD\d{3}\b", flags=re.IGNORECASE)


def _seed_chat_focus(conversation_id: str | None, customer_id: str | None,
                     customer: str | None, deal_id: str | None) -> None:
    """Cross-seed the chat 'account in focus' from a skill turn (a /review or
    /account brief) so a later bare chat follow-up — "what should I do about
    this?" — stays scoped to the same customer even though the user never
    re-typed the name. This is what makes the Workspace one continuous
    conversation across skills and chat, rather than a row of isolated requests.

    Deterministic: the focus is the entity the skill already resolved (or the
    deal's own customer), never a name guess."""
    if not conversation_id:
        return
    if not customer_id and deal_id:
        d = store.get_deal(deal_id)
        if d:
            customer_id = d["customer_id"]
            customer = customer or store.customer_name(customer_id)
    if not customer_id:
        return
    _CHAT_CONTEXTS[conversation_id] = {
        "customer_id": customer_id, "customer": customer, "deal_id": deal_id}
_FOLLOWUP_RE = re.compile(
    r"^\s*(what|who|when|why|how|which|are|is|do|does|should)\b|"
    r"\b(risk|risks|decision maker|last meeting|products?|next|happened|activity|activities)\b|"
    # Japanese continuation/question cues (no word boundaries in Japanese): follow-ups
    # about the account already in focus — 次/何をすべき/リスク/直近/決裁 etc.
    r"(次|今後|何を|どう|なぜ|いつ|誰|リスク|決裁|直近|前回|製品|案件|べき|他には|では)",
    flags=re.IGNORECASE,
)


def _research_target(message: str) -> str:
    target = (message or "").strip()
    for pat in _RESEARCH_PREFIXES:
        target = re.sub(pat, "", target, flags=re.IGNORECASE)
    return target.strip(" \t\r\n?？。.")


def _deal_id_in_text(message: str) -> str | None:
    m = _DEAL_ID_RE.search(message or "")
    return m.group(0).upper() if m else None


# Explicit "look in my local files" intent. When the user scopes the question to
# their own documents, the turn should be answered from the Workspace tool and NOT
# wander into the CRM/internal-record tools — that scope-bleed is what makes a simple
# "what's in my file" spiral through query_spr/search_notes. Kept narrow: it must
# name files/documents/the workspace, not merely mention "generate a file".
_FILE_SCOPE_RE = re.compile(
    # Possessive/locative framing around files/documents — "my files", "in the
    # documents", "search my docs" — NOT bare "a document" (that's generate_docx).
    r"\b(?:my|the|these|those)\s+(?:files?|documents?|docs?)\b|"
    r"\b(?:in|from|search|read|check|open|look(?:ing)?\s+(?:in|at|through))\s+"
    r"(?:my|the|these|those)?\s*(?:files?|documents?|folder)\b|"
    r"\bworkspace\b|\blocal files?\b|"
    r"(?:私の|自分の|マイ)(?:ファイル|資料|ドキュメント|文書)|"
    r"(?:ファイル|資料|ドキュメント|文書)(?:の中|内|から|を見|を調|を検索|を確認|に|にある)|"
    r"ワークスペース|ローカル(?:ファイル|文書)",
    re.IGNORECASE,
)


# Analytical / ranking intent — questions that need CRM + scoring, not a file read.
# When present, we do NOT lock the turn to workspace-only even if it mentions "files":
# "best performing company among my files" wants analysis (deal health / SPR), which
# the local notes don't contain. Leaving file-scope off keeps ALL tools available
# (workspace AND CRM), so the model can ground on files yet still rank via CRM,
# instead of spinning on filename-only search over notes that hold no metrics.
_ANALYTICAL_RE = re.compile(
    r"\b(?:best|top|worst|highest|lowest|rank(?:ing|ed)?|compare|comparison|"
    r"which\s+(?:is|are|one|deal|company|customer)|best[- ]performing|"
    r"performance|revenue|win\s*rate|pipeline)\b|"
    r"(?:一番|最も|最高|最良|最悪|ランキング|比較|順位|パフォーマンス|業績|勝率|売上|"
    r"どれが|どちらが|どの(?:案件|会社|顧客))",
    re.IGNORECASE,
)


def _is_file_scoped(message: str) -> bool:
    msg = message or ""
    # Ranking/performance intent overrides file-scope: it needs CRM, not just files.
    if _ANALYTICAL_RE.search(msg):
        return False
    return bool(_FILE_SCOPE_RE.search(msg))


# Planner intent → the LLMPlanner (capability graph), not the ReAct loop. Covers
# document GENERATION (proposal / deck / docx …), workspace NOTE writes, and workspace
# ORGANIZE. The detection lives in senpai.planner.selection (the planner owns intent);
# these thin aliases keep the router readable and the names stable for tests. Ordinary
# tool asks ("draft an email", "make a quote", "tell me about X") stay in the chat
# loop; 稟議 (ringisho) has its own tool and is excluded.
from senpai.planner.selection import (
    is_document_goal as _is_document_goal,
    resolve_route as _resolve_planner_route,
)


def _is_followup(message: str, has_context: bool) -> bool:
    if not has_context or _deal_id_in_text(message):
        return False
    text = (message or "").strip()
    if not text or len(text) > 220:
        return False
    if any(re.search(pat, text, flags=re.IGNORECASE) for pat in _RESEARCH_PREFIXES):
        return False
    return bool(_FOLLOWUP_RE.search(text))


# Japanese research cues. Kept narrow on purpose: paired with a customer-resolution
# check below so coaching questions ("値引きについて教えて") never get hijacked.
_RESEARCH_CUES_JA = ("について教えて", "について調べて", "のことを教えて",
                     "の情報を教えて", "を調べて", "について知りたい",
                     "リサーチ", "背景を教えて")


def _is_research_intent(message: str) -> bool:
    """True when the message is a customer-research request *and* names a customer
    we actually have. Auto-routes those turns to the source-grounded research
    pipeline; everything else stays in the tool-calling loop."""
    msg = (message or "").strip()
    has_cue = (
        any(re.search(p, msg, flags=re.IGNORECASE) for p in _RESEARCH_PREFIXES)
        or any(cue in msg for cue in _RESEARCH_CUES_JA)
    )
    if not has_cue:
        return False
    target = _research_target(msg)
    if not target:
        return False
    return store.resolve_customer_detailed(target).status in ("resolved", "ambiguous")


# Shaping helpers live canonically in senpai.research.shaping (M3 consolidation):
# these are thin server-side aliases preserving the existing call sites + the
# implicit _today() default. The bodies are no longer duplicated here.
def _public_customer(c: dict | None) -> dict | None:
    return _shaping.public_customer(c)


def _deal_summary(d: dict) -> dict:
    return _shaping.deal_summary(d, _today())


def _activity_summary(a: dict) -> dict:
    return _shaping.activity_summary(a)


def _products_for_deals(deals: list[dict]) -> list[dict]:
    return _shaping.products_for_deals(deals)


def _deal_resolution(deal: dict) -> dict:
    c = store.get_customer(deal["customer_id"])
    return {
        "status": "resolved",
        "query": deal["deal_id"],
        "customer": _public_customer(c),
        "candidates": [],
    }


def _build_deal_context_bundle(message: str, target: str, deal: dict) -> ResearchBundle:
    customer = store.get_customer(deal["customer_id"])
    raw_activities = store.activities_for_deal(deal["deal_id"])
    bundle = ResearchBundle(
        query=message,
        target=target,
        resolution=_deal_resolution(deal),
        customer=_public_customer(customer),
        active_deal_id=deal["deal_id"],
        active_deal=_deal_summary(deal),
        deals=[_deal_summary(deal)],
        activities=[_activity_summary(a) for a in raw_activities[:20]],
        environment=store.get_environment(deal["customer_id"]),
        products=_products_for_deals([deal]),
        similar_deals=[_deal_summary(d) for d in find_similar_deals(
            customer_id=deal["customer_id"],
            industry=(customer or {}).get("industry", ""),
        )[:3]],
    )
    bundle.provenance.extend([
        {"source": "active_deal_context", "priority": 1, "deal_id": deal["deal_id"]},
        {"source": "internal_records", "priority": 1, "status": "found"},
        {"source": "deals", "priority": 2, "count": 1},
        {"source": "activities", "priority": 3, "count": len(bundle.activities),
         "truncated": len(raw_activities) > len(bundle.activities)},
        {"source": "environment", "priority": 4,
         "status": "found" if bundle.environment else "not_found"},
    ])
    return bundle


def _open_deals(deals: list[dict]) -> list[dict]:
    return [d for d in deals if config.is_open_rank(d.get("order_rank"))]


def _deal_choices_answer(deals: list[dict]) -> str:
    lines = ["この顧客にはアクティブな案件が複数あります。どの案件について調べるか、案件IDで指定してください。"]
    for d in sorted(deals, key=lambda x: x.get("total_order_amount", 0), reverse=True):
        s = _deal_summary(d)
        lines.append(
            f"- {s['deal_id']}: {s['customer']} / {s['stage']} / "
            f"¥{s['amount']:,} / {s['product_category']} / health={s['health']['band']}"
        )
    return "\n".join(lines)


def _source_event(key: str, label: str, status: str, count: int | None = None,
                  detail: str = "") -> str:
    obj = {"type": "source", "key": key, "label": label, "status": status}
    if count is not None:
        obj["count"] = count
    if detail:
        obj["detail"] = detail
    return _sse(obj)


def _build_research_bundle(message: str, target: str, resolution) -> ResearchBundle:
    bundle = ResearchBundle(
        query=message,
        target=target,
        resolution=resolution.to_dict(),
        customer=_public_customer(resolution.customer),
    )
    if resolution.status != "resolved" or not resolution.customer:
        return bundle

    cid = resolution.customer["customer_id"]
    raw_deals = store.deals_for_customer(cid)
    raw_activities = store.activities_for_customer(cid)
    bundle.deals = [_deal_summary(d) for d in raw_deals]
    bundle.activities = [_activity_summary(a) for a in raw_activities[:20]]
    bundle.environment = store.get_environment(cid)
    bundle.products = _products_for_deals(raw_deals)
    bundle.similar_deals = [_deal_summary(d) for d in find_similar_deals(
        customer_id=cid, industry=resolution.customer.get("industry", ""))[:3]]
    bundle.provenance.extend([
        {"source": "internal_records", "priority": 1, "status": "found"},
        {"source": "deals", "priority": 2, "count": len(bundle.deals)},
        {"source": "activities", "priority": 3, "count": len(bundle.activities),
         "truncated": len(raw_activities) > len(bundle.activities)},
        {"source": "environment", "priority": 4,
         "status": "found" if bundle.environment else "not_found"},
    ])
    return bundle


# --- Orchestration-backed builders (M1) -------------------------------------
# Same signatures and identical output as the two legacy builders above, but the
# gather runs on the orchestration engine (six research capabilities, a small DAG)
# instead of an inline sequence. The legacy builders are kept as the parity oracle
# for the golden tests (tests/test_research_parity.py); these are what the live
# `/research` path calls. See senpai.research and docs/orchestration-architecture.md.
def _build_research_bundle_orch(message: str, target: str, resolution) -> ResearchBundle:
    if resolution.status != "resolved" or not resolution.customer:
        return ResearchBundle(query=message, target=target,
                              resolution=resolution.to_dict(),
                              customer=_public_customer(resolution.customer))
    from senpai.research import research_bundle_fields
    fields = research_bundle_fields(
        mode="customer", query=message, target=target,
        resolution=resolution.to_dict(), customer=_public_customer(resolution.customer),
        customer_id=resolution.customer["customer_id"], deal_id=None,
        industry=resolution.customer.get("industry", ""), today=_today())
    return ResearchBundle(**fields)


def _build_deal_context_bundle_orch(message: str, target: str, deal: dict) -> ResearchBundle:
    from senpai.research import research_bundle_fields
    customer = store.get_customer(deal["customer_id"])
    fields = research_bundle_fields(
        mode="deal", query=message, target=target, resolution=_deal_resolution(deal),
        customer=_public_customer(customer), customer_id=deal["customer_id"],
        deal_id=deal["deal_id"], industry=(customer or {}).get("industry", ""),
        today=_today())
    return ResearchBundle(**fields)


def _research_summary_prompt(bundle: ResearchBundle) -> str:
    return (
        "You are Senpai's customer research summarizer for Otsuka salespeople.\n"
        "Use ONLY the JSON evidence bundle below. Do not add facts from memory.\n"
        "Internal records have higher priority than web results. If web results are present, "
        "label them as external. If internal records are missing, say that clearly.\n"
        "Answer in concise Japanese with sections useful before a sales conversation.\n\n"
        f"Evidence bundle:\n{json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2)}"
    )


def _ambiguity_answer(candidates: list[dict]) -> str:
    lines = ["該当する可能性のある顧客が複数あります。誤った顧客情報を使わないため、候補を選んでください。"]
    for c in candidates:
        aliases = "、".join(c.get("matched_aliases") or [])
        suffix = f"（一致: {aliases}）" if aliases else ""
        lines.append(f"- {c.get('customer_id')}: {c.get('name')}{suffix}")
    return "\n".join(lines)


def _emit_bundle_sources(bundle: ResearchBundle, cached: bool = False):
    yield _source_event("internal_records", "Internal Records", "found", count=1,
                        detail="cached" if cached else "")
    yield _source_event("deals", "Deals", "found" if bundle.deals else "not_found",
                        count=len(bundle.deals), detail="cached" if cached else "")
    yield _source_event("activities", "Activities",
                        "found" if bundle.activities else "not_found",
                        count=len(bundle.activities), detail="cached" if cached else "")
    yield _source_event("environment", "Environment",
                        "found" if bundle.environment else "not_found",
                        detail="cached" if cached else "")
    yield _source_event("web_search", "Web Search", "skipped",
                        detail="active_deal_context" if bundle.active_deal_id else "internal_record_found")


def _summarize_research_bundle(bundle: ResearchBundle):
    try:
        from senpai.llm.client import stream_complete, fallback_client, _synth_route
        # Research summaries are always FAST grounded restatement → a hybrid 8B
        # target. Surface which model synthesizes (FAST→8B when the flag is on).
        _sc, _sm, _, _ = _synth_route(True)
        yield _sse({"type": "synth", "model_id": _sm,
                    "tier": "8B" if _sc is fallback_client else "27B", "no_think": True})
        text = ""
        for piece in stream_complete(
            [{"role": "user", "content": _research_summary_prompt(bundle)}],
            temperature=0.2,
            max_tokens=config.LLM_MAX_TOKENS,
            no_think=True,
            allow_fallback=False,
            fast_decomp=True,
        ):
            text += piece
        text = (_strip_reasoning(text) or "").strip()
        yield _sse({"type": "answer", "text": text or "リサーチ結果を生成できませんでした。"})
        yield _sse({"type": "done", "model": config.MODEL})
    except Exception:  # noqa: BLE001 - research must not silently use fallback
        yield _sse({"type": "unavailable", "reason": "llm_unreachable"})
        yield _sse({"type": "done", "model": config.MODEL})


def research_stream(req: ChatRequest):
    conversation_id = (getattr(req, "conversation_id", None) or "default").strip() or "default"
    cached_bundle = _RESEARCH_CONTEXTS.get(conversation_id)
    target = _research_target(req.message)
    deal_id = _deal_id_in_text(req.message)
    use_cached = _is_followup(req.message, bool(cached_bundle))

    yield _sse({"type": "start", "model": config.MODEL,
                "endpoint": config.BASE_URL, "role": "research",
                "conversation_id": conversation_id})
    # Workspace: this stream produces a `research` artifact. Entity (if any) is
    # surfaced later via the resolve/context events as the customer is grounded.
    yield _sse({"type": "artifact_meta", "kind": "research"})

    if use_cached and cached_bundle:
        cached_bundle.query = req.message
        yield _sse({"type": "context", "status": "active",
                    "conversation_id": conversation_id,
                    "deal_id": cached_bundle.active_deal_id,
                    "customer": cached_bundle.customer,
                    "cached": True})
        for ev in _emit_bundle_sources(cached_bundle, cached=True):
            yield ev
        yield from _summarize_research_bundle(cached_bundle)
        return

    if deal_id:
        deal = store.get_deal(deal_id)
        if not deal:
            yield _sse({"type": "resolve", "status": "not_found", "query": deal_id,
                        "customer": None, "candidates": []})
            yield _source_event("internal_records", "Internal Records", "not_found")
            yield _sse({"type": "unavailable", "reason": "deal_not_found"})
            yield _sse({"type": "done", "model": config.MODEL})
            return
        bundle = _build_deal_context_bundle_orch(req.message, deal_id, deal)
        _RESEARCH_CONTEXTS[conversation_id] = bundle
        yield _sse({"type": "resolve", **bundle.resolution})
        yield _sse({"type": "context", "status": "active",
                    "conversation_id": conversation_id, "deal_id": deal_id,
                    "customer": bundle.customer, "cached": False})
        for ev in _emit_bundle_sources(bundle):
            yield ev
        yield _sse({"type": "deal_ids", "deal_ids": [deal_id]})
        yield from _summarize_research_bundle(bundle)
        return

    resolution = store.resolve_customer_detailed(target)
    if resolution.status == "not_found":
        # The target may be an action/verb-wrapped request ("create a quotation
        # for akebono") rather than a bare name. Locate the customer named inside
        # the message so we hit internal records (and surface ambiguity) instead
        # of falling through to a web search.
        in_text = store.resolve_customer_in_text(req.message)
        if in_text.status != "not_found":
            resolution = in_text
    res_obj = resolution.to_dict()
    yield _sse({"type": "resolve", **res_obj})

    if resolution.status == "ambiguous":
        yield _source_event("internal_records", "Internal Records", "ambiguous",
                            count=len(res_obj["candidates"]))
        yield _source_event("deals", "Deals", "skipped")
        yield _source_event("activities", "Activities", "skipped")
        yield _source_event("environment", "Environment", "skipped")
        yield _source_event("web_search", "Web Search", "skipped",
                            detail="ambiguous_customer")
        # No textual "which one?" answer: the `resolve` candidates above drive a
        # deterministic picker in the UI (both the /research card and the chat
        # bubble). Emitting an answer too would duplicate the picker as a redundant
        # markdown table — and would pre-empt the picker before the rep has chosen.
        yield _sse({"type": "done", "model": config.MODEL})
        return

    if resolution.status == "resolved" and resolution.customer:
        raw_deals = store.deals_for_customer(resolution.customer["customer_id"])
        active_deals = _open_deals(raw_deals)
        if len(active_deals) > 1:
            yield _source_event("internal_records", "Internal Records", "found", count=1)
            yield _source_event("deals", "Deals", "ambiguous", count=len(active_deals),
                                detail="multiple_active_deals")
            yield _source_event("activities", "Activities", "skipped")
            yield _source_event("environment", "Environment", "skipped")
            yield _source_event("web_search", "Web Search", "skipped",
                                detail="select_deal_first")
            yield _sse({"type": "deal_choices", "status": "ambiguous",
                        "deals": [_deal_summary(d) for d in active_deals]})
            yield _sse({"type": "answer", "text": _deal_choices_answer(active_deals)})
            yield _sse({"type": "done", "model": config.MODEL})
            return
        if len(active_deals) == 1:
            bundle = _build_deal_context_bundle_orch(req.message, target, active_deals[0])
            _RESEARCH_CONTEXTS[conversation_id] = bundle
            yield _sse({"type": "context", "status": "active",
                        "conversation_id": conversation_id,
                        "deal_id": bundle.active_deal_id,
                        "customer": bundle.customer,
                        "cached": False})
            for ev in _emit_bundle_sources(bundle):
                yield ev
            yield _sse({"type": "deal_ids", "deal_ids": [bundle.active_deal_id]})
            yield from _summarize_research_bundle(bundle)
            return

    bundle = _build_research_bundle_orch(req.message, target, resolution)

    if resolution.status == "resolved":
        for ev in _emit_bundle_sources(bundle):
            yield ev
        # Emit deal ids so the client can show them in the evidence drawer.
        if bundle.deals:
            deal_ids = [d["deal_id"] for d in bundle.deals if d.get("deal_id")]
            if deal_ids:
                yield _sse({"type": "deal_ids", "deal_ids": deal_ids})
    else:
        yield _source_event("internal_records", "Internal Records", "not_found")
        yield _source_event("deals", "Deals", "skipped")
        yield _source_event("activities", "Activities", "skipped")
        yield _source_event("environment", "Environment", "skipped")
        # Web fallback stays on the direct seam (web_search_typed): it is a single
        # external call, not gather orchestration, and existing tests patch this
        # symbol. The engine-backed WebCapability is exercised by the golden tests.
        web = web_search_typed(f"{target} company overview latest news")
        bundle.web = web
        bundle.provenance.append({"source": "web_search", "priority": 2,
                                  "status": web.get("status"), "query": web.get("query")})
        yield _sse({"type": "web", **web})
        yield _source_event("web_search", "Web Search",
                            "found" if web.get("status") == "found" else "error",
                            count=len(web.get("results") or []),
                            detail=web.get("reason", ""))
        if web.get("status") != "found":
            yield _sse({"type": "unavailable",
                        "reason": "no_internal_record_and_web_unavailable"})
            yield _sse({"type": "done", "model": config.MODEL})
            return

    yield from _summarize_research_bundle(bundle)


class ChatMessage(BaseModel):
    role: str       # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []          # prior user/assistant turns (no system)
    role: str = "junior"                     # "junior" | "manager"
    conversation_id: str | None = None
    context: str = ""                        # attached-file text (chat-over-attachment)
    deal_id: str | None = None               # deal picked from the selector (structured)


@app.post("/api/chat")
def chat(req: ChatRequest):
    """Stream one assistant turn through the tool loop (SSE).

    The model decides which tools to call; each executed tool is surfaced to the
    UI (name, args, result) before the final answer is sent. Grounded entirely in
    the deterministic store/scoring engine plus web_search. Event types:
      start | tool | delta | answer | done | error
    The final answer streams token-by-token (`delta` events) so the Assistant
    feels as live as Review Coach. On any model/transport failure the loop emits
    a single `answer` with the error text (never a crash).

    Research intent ("tell me about / research <customer>") is auto-detected and
    routed to the dedicated, source-grounded `research_stream` — one Assistant
    surface, the right pipeline behind it."""
    if req.role == "research" or _is_research_intent(req.message):
        return StreamingResponse(
            research_stream(req),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Planner goal ("make a proposal for …", "organize my files", "save this as a
    # note") → route the SAME chat turn through the LLMPlanner: it selects a capability
    # graph (Conversation / Workspace / CRM / Knowledge / Web / Documents / Write /
    # Organize), runs it on the engine, and returns the artifact. No /plan prefix — a
    # normal prompt just works. An attached file rides along as conversation context; a
    # selector-picked deal is authoritative. Everything else stays in the ReAct loop.
    if _resolve_planner_route(req.message, req.history):
        convo: list[dict] = []
        for m in req.history:
            if m.role in ("user", "assistant") and m.content:
                convo.append({"role": m.role, "content": m.content})
        if req.context.strip():
            convo.append({"role": "user",
                          "content": f"【添付ファイルの内容】\n{req.context.strip()}"})
        convo.append({"role": "user", "content": req.message})
        sel_deal = (req.deal_id or "").strip().upper() or None
        return StreamingResponse(
            _plan_stream(req.message, convo, req.role, deal_id=sel_deal),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    tools, system_fn = _CHAT_ROLES.get(req.role, _CHAT_ROLES["junior"])

    # Conversation context cache: remember the account in focus so follow-ups that
    # don't re-name the customer ("what should I do next?", "what happened recently
    # with this account?") stay scoped to the same customer. This also drives the
    # Phase-1 account-scoped retrieval: the cached customer is injected into the
    # system prompt so the model passes it to search_notes.
    conversation_id = (req.conversation_id or "default").strip() or "default"
    cached_ctx = _CHAT_CONTEXTS.get(conversation_id)
    cust = store.match_customer_in_text(req.message)
    msg_deal = _deal_id_in_text(req.message)
    sel_deal = (req.deal_id or "").strip().upper() or None
    active: dict | None = None
    cached_flag = False
    selected_flag = False
    if sel_deal and (sd := store.get_deal(sel_deal)):
        # Deal picked from the selector — authoritative. Skip prose parsing and,
        # crucially, tell the model it is already identified so it doesn't spend a
        # tool round re-resolving the customer/deal.
        active = {"customer_id": sd["customer_id"],
                  "customer": store.customer_name(sd["customer_id"]), "deal_id": sel_deal}
        selected_flag = True
    elif cust:
        active = {"customer_id": cust["customer_id"], "customer": cust.get("name"),
                  "deal_id": msg_deal or (cached_ctx or {}).get("deal_id")}
    elif msg_deal and (d := store.get_deal(msg_deal)):
        active = {"customer_id": d["customer_id"],
                  "customer": store.customer_name(d["customer_id"]), "deal_id": msg_deal}
    elif cached_ctx and _is_followup(req.message, True):
        active, cached_flag = cached_ctx, True
    if active and active.get("customer_id"):
        _CHAT_CONTEXTS[conversation_id] = active

    # Ambiguous customer stem (e.g. "marusan" → 4 丸三 companies) and nothing else
    # pinned it down → surface the candidates instead of guessing one's facts.
    amb_candidates: list[dict] = []
    if not active:
        for c in store.ambiguous_match_in_text(req.message):
            d = next((x for x in store.deals_for_customer(c["customer_id"])
                      if config.is_open_rank(x.get("order_rank"))), None)
            amb_candidates.append({"customer_id": c["customer_id"],
                                   "name": c.get("name", ""),
                                   "deal_id": d["deal_id"] if d else None})

    system = system_fn()
    if active and active.get("customer"):
        focus = active["customer"] + (f"（案件 {active['deal_id']}）" if active.get("deal_id") else "")
        if selected_flag:
            # The user already pinned the exact deal. Use it directly — no
            # identification searches — so the turn resolves in as few rounds as
            # possible.
            system += (f"\n\n【選択中の案件】ユーザーは {focus} を明示的に選択済み。"
                       f"案件IDが必要なツール（generate_proposal 等）には "
                       f"deal_id='{active['deal_id']}' をそのまま渡すこと。案件や顧客を"
                       f"特定するための追加検索(query_spr/search_notes)は不要 — すでに確定している。")
        else:
            system += (f"\n\n【現在の対象顧客】{focus}。アカウント固有の質問では、"
                       f"search_notes に customer='{active['customer']}' を渡し、この顧客の"
                       f"記録に限定して回答すること。")
    # An ambiguous customer (amb_candidates) short-circuits to the picker below
    # before the LLM runs, so no ambiguity clause is added to the system prompt.

    # File-scoped question → pin the turn to the Workspace tool. Without this the
    # model bleeds into CRM/internal-record tools ("yamato" → a wrong customer
    # lookup) even though the answer is in a local file. Explicit scope, one tool.
    if _is_file_scoped(req.message):
        system += ("\n\n【スコープ: ローカル文書】ユーザーは自分のファイル/資料に限定して"
                   "質問している。search_workspace_documents だけを使い、その結果のみに基づいて"
                   "回答すること。CRM・社内記録のツール(query_spr/search_notes/find_deals 等)は"
                   "呼ばない。文書に答えが無ければ、その旨を述べる（推測しない）。")

    convo: list[dict] = [{"role": "system", "content": system}]
    for m in req.history:
        if m.role in ("user", "assistant") and m.content:
            convo.append({"role": m.role, "content": m.content})
    # An attached file's extracted text rides along as context for THIS turn only
    # (not persisted into history). The model answers the question grounded in it.
    user_content = req.message
    if req.context.strip():
        user_content = (
            "【添付ファイルの内容 / Attached file content】\n"
            f"{req.context.strip()}\n\n"
            "【質問 / Question】\n"
            f"{req.message}"
        )
    convo.append({"role": "user", "content": user_content})

    def gen():
        from senpai.llm.client import stream_chat_turn  # lazy: keep import light
        yield _sse({"type": "start", "model": config.MODEL,
                    "endpoint": config.BASE_URL, "role": req.role,
                    "conversation_id": conversation_id})
        if active:
            yield _sse({"type": "context", "status": "active",
                        "conversation_id": conversation_id,
                        "customer": active.get("customer"),
                        "deal_id": active.get("deal_id"), "cached": cached_flag})
        elif amb_candidates:
            # Ambiguous customer and nothing else pinned it down → surface the
            # candidates and STOP. The deterministic picker is the whole response;
            # running the LLM here only produces a redundant "which one?" message
            # that duplicates the picker and pre-empts the rep's choice. The pick
            # re-runs this turn in place, grounded on the chosen customer.
            yield _sse({"type": "resolve", "status": "ambiguous",
                        "query": req.message, "candidates": amb_candidates})
            yield _sse({"type": "done", "model": config.MODEL})
            return
        try:
            for ev in stream_chat_turn(convo, tools=tools, role=req.role):
                yield _sse(ev)
            yield _sse({"type": "done", "model": config.MODEL})
        except Exception as e:  # noqa: BLE001 — never crash the stream
            yield _sse({"type": "error", "reason": str(e)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Persistent chat history ------------------------------------------------
# Durable copilot transcripts so a rep can close the tab and resume a past chat.
# The frontend owns the transcript (it's the only place the full-fidelity WMsg[]
# and skill/artifact cards exist), so it POSTs an opaque JSON `blob` here after each
# completed turn; the server only reads the small header fields for listing. Storage
# is SQLite via senpai.data.chat_store — separate from the seed/overlay `store`.
# Identity is passed explicitly as employee_id (like /api/coach/rep-profile/{id});
# the streaming /api/chat endpoint above is intentionally left untouched.
class SaveConversationRequest(BaseModel):
    employee_id: str
    role: str = "junior"
    title: str
    blob: str
    message_count: int = 0


class RenameConversationRequest(BaseModel):
    title: str


# --- Live web-research / site-intel crawl (the /intel browser-sim feed) ------
class IntelCrawlRequest(BaseModel):
    input: str                 # a URL/bare-domain OR a research question
    max_pages: int = 6
    max_sites: int = 3


def _intel_crawl_stream(req: IntelCrawlRequest):
    """SSE generator for the live browser feed. Runs the crawler in a worker thread
    (Playwright's sync API needs a thread with no event loop) and relays each page it
    visits to the client in real time via a queue, then a final `intel` brief event.

    Event types: start | research_plan | crawl_page | crawl_status | intel | error | done
    """
    import queue
    import threading
    from senpai.tools import crawl as _cr

    text = (req.input or "").strip()
    yield _sse({"type": "start", "input": text,
                "mode": "site" if _cr.looks_like_url(text) else "question"})
    if not text:
        yield _sse({"type": "error", "reason": "empty_input"})
        yield _sse({"type": "done"})
        return

    q: "queue.Queue[dict | None]" = queue.Queue(maxsize=256)  # room for scroll-frame bursts

    def emit(ev: dict) -> None:
        try:
            q.put(ev, timeout=1.0)
        except Exception:
            pass  # a slow/gone client must never wedge the crawl

    def worker() -> None:
        try:
            mp = max(1, min(int(req.max_pages), 12))
            if _cr.looks_like_url(text):
                url = text if text.startswith(("http://", "https://")) else "https://" + text
                if not _cr.is_safe_url(url):
                    q.put({"type": "error", "reason": "unsafe_or_unreachable_url", "url": url})
                    return
                intel = _cr.crawl_site(url, max_pages=mp, max_depth=2, emit=emit)
                if not intel.get("ok"):
                    q.put({"type": "error", "reason": intel.get("reason", "no_pages")})
                    return
                brief = _cr.build_brief(intel, use_llm=USE_LLM, emit=emit)
                q.put({"type": "intel", "markdown": brief["markdown"],
                       "sources": brief["sources"], "backend": intel["backend"],
                       "assets": {"products": len(intel["products"]),
                                  "news": len(intel["news"]), "pdfs": len(intel["pdfs"])},
                       "pdfs": intel["pdfs"][:12]})
            else:
                bundle = _cr.research_web(text, max_sites=max(1, min(int(req.max_sites), 5)),
                                          max_pages_per_site=min(mp, 3), emit=emit)
                answer = _cr._research_answer(bundle, use_llm=USE_LLM)
                sources = [{"url": p["url"], "title": p["title"]}
                           for c in bundle["crawls"] for p in c["pages"]]
                q.put({"type": "intel", "markdown": answer, "sources": sources,
                       "sites": bundle["sites"], "backend": "requests"})
        except Exception as e:  # noqa: BLE001 — surface, never crash the stream
            q.put({"type": "error", "reason": str(e)})
        finally:
            q.put(None)  # sentinel: worker done

    threading.Thread(target=worker, daemon=True).start()
    while True:
        ev = q.get()
        if ev is None:
            break
        yield _sse(ev)
    yield _sse({"type": "done"})


@app.post("/api/intel/crawl")
def intel_crawl(req: IntelCrawlRequest):
    """Stream a live website crawl → grounded intel brief (the /intel browser-sim)."""
    return StreamingResponse(
        _intel_crawl_stream(req), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/chat/history")
def chat_history_list(employee_id: str, role: str = "junior"):
    """List one user's saved conversations (headers only), newest first."""
    return {"conversations": chat_store.list_conversations(employee_id, role)}


@app.get("/api/chat/history/{conversation_id}")
def chat_history_get(conversation_id: str):
    """Fetch one full conversation (header + opaque blob) for resume."""
    convo = chat_store.get_conversation(conversation_id)
    if convo is None:
        raise HTTPException(404, f"conversation {conversation_id} not found")
    return convo


@app.put("/api/chat/history/{conversation_id}")
def chat_history_save(conversation_id: str, req: SaveConversationRequest):
    """Create or update a conversation (autosaved after each turn). Returns header."""
    title = req.title.strip() or "Untitled chat"
    return chat_store.upsert_conversation(
        conversation_id=conversation_id,
        employee_id=req.employee_id,
        role=req.role,
        title=title,
        blob=req.blob,
        message_count=req.message_count,
    )


@app.patch("/api/chat/history/{conversation_id}")
def chat_history_rename(conversation_id: str, req: RenameConversationRequest):
    """Rename a conversation."""
    title = req.title.strip()
    if not title:
        raise HTTPException(400, "title is required")
    if not chat_store.rename_conversation(conversation_id, title):
        raise HTTPException(404, f"conversation {conversation_id} not found")
    return {"ok": True, "conversation_id": conversation_id, "title": title}


@app.delete("/api/chat/history/{conversation_id}")
def chat_history_delete(conversation_id: str):
    """Delete a conversation."""
    if not chat_store.delete_conversation(conversation_id):
        raise HTTPException(404, f"conversation {conversation_id} not found")
    return {"ok": True, "conversation_id": conversation_id}


# --- LLMPlanner: goal -> capability graph -> document ------------------------
# The minimal planner surface (milestone 1: document generation). Unlike /api/chat
# (a ReAct tool loop), this translates ONE goal into a static capability plan, runs
# it on the shared ExecutionEngine, and returns the artifact. Same event shapes as
# chat (tool / document / answer) so the existing frontend renders it unchanged.
class PlanRequest(BaseModel):
    message: str                             # the document goal
    history: list[ChatMessage] = []          # prior user/assistant turns (for grounding)
    role: str = "junior"
    conversation_id: str | None = None


# Which gather capabilities count as "internal company data" for the UI's
# grounding badge — mirrors TOOL_LABEL's `internal` flag in the frontend
# (web/components/assistant/message.tsx), which the badge is computed from.
_CAP_INTERNAL = {"crm": True, "knowledge": True, "conversation": False,
                 "workspace": False, "web": False}


def _plan_stream(goal: str, convo: list[dict], role: str, deal_id: str | None = None):
    """Shared planner SSE generator: goal → capability graph → engine → artifact.
    Emits the same `plan | tool | document | answer | done` events used by /api/chat,
    so both the dedicated /api/plan surface and the auto-routed chat turn render
    identically. `deal_id` (selector pick) is authoritative when provided.

    Tool cards stream LIVE as each capability finishes (via `run_document_goal`'s
    `emit` callback, drained off a queue exactly like the /crew researcher/coach
    lanes) rather than all landing in one burst after the whole plan has already
    finished — otherwise the turn reads as the answer/file appearing before any
    tool was actually called, when in fact they ran first; the UI just never saw
    them until everything was already done."""
    import queue
    import threading

    from senpai.orchestration import events as oevents
    from senpai.planner import run_document_goal

    yield _sse({"type": "start", "model": config.MODEL,
                "endpoint": config.BASE_URL, "role": role, "surface": "planner"})

    # An ambiguous customer stem in the goal (e.g. "matsuda" → several 松田
    # companies) and no selector-picked deal to override it → surface the picker
    # and STOP, exactly like /api/chat and /api/agent/crew do. Otherwise the
    # planner silently falls through to an ungrounded free deck (no CRM entity),
    # which reads as the model hallucinating instead of asking which company.
    if not deal_id and not store.match_customer_in_text(goal):
        amb_candidates = []
        for c in store.ambiguous_match_in_text(goal):
            d = next((x for x in store.deals_for_customer(c["customer_id"])
                      if config.is_open_rank(x.get("order_rank"))), None)
            amb_candidates.append({"customer_id": c["customer_id"],
                                   "name": c.get("name", ""),
                                   "deal_id": d["deal_id"] if d else None})
        if amb_candidates:
            yield _sse({"type": "resolve", "status": "ambiguous",
                        "query": goal, "candidates": amb_candidates})
            yield _sse({"type": "done", "model": config.MODEL})
            return

    q: "queue.Queue" = queue.Queue()
    box: dict = {}

    def worker() -> None:
        try:
            box["result"] = run_document_goal(
                goal, conversation=convo, role=role, deal_id=deal_id,
                emit=lambda ev: q.put(ev))
        except Exception as e:  # noqa: BLE001 — never crash the stream
            box["error"] = str(e)
        finally:
            q.put({"type": "_worker_done"})

    threading.Thread(target=worker, daemon=True).start()

    doc_kind = "pptx"
    while True:
        ev = q.get()
        etype = ev.get("type")
        if etype == "_worker_done":
            break
        if etype == "selection.ready":
            sel = ev["selection"]
            doc_kind = sel["doc_kind"]
            # The capability graph the planner chose (the UI may render it; unknown
            # to the current chat handler, which safely ignores it).
            yield _sse({"type": "plan", "goal": goal, "doc_kind": sel["doc_kind"],
                        "capabilities": sel["capabilities"], "reason": sel.get("reason", ""),
                        "target": sel.get("target"), "deal_id": sel.get("deal_id"),
                        "tasks": ev["plan"]})
            # Focus chip: the resolved entity, so the account context stays visible.
            if sel.get("target") or sel.get("deal_id"):
                yield _sse({"type": "context", "status": "active",
                            "customer": sel.get("target"), "deal_id": sel.get("deal_id"),
                            "cached": False})
        elif etype == oevents.TASK_STARTED:
            # Fine-grained lane state for the execution-timeline UI — additive,
            # existing `tool`/`plan` handling below is unaffected by this.
            yield _sse({"type": "task_started", "task_id": ev.get("task_id", ""),
                        "capability": ev.get("capability", ""), "op": ev.get("op", ""),
                        "group": ev.get("group", ""), "summary": ev.get("summary", "")})
        elif etype == oevents.TASK_PROGRESS:
            yield _sse({"type": "task_progress", "task_id": ev.get("task_id", ""),
                        "message": ev.get("message", "")})
        elif etype == oevents.TASK_EVIDENCE:
            yield _sse({"type": "task_evidence", "task_id": ev.get("task_id", ""),
                        "status": ev.get("status", ""), "confidence": ev.get("confidence"),
                        "citations": ev.get("citations") or []})
        elif etype == oevents.GROUP_COMPLETED:
            yield _sse({"type": "group_completed", "group": ev.get("group", "")})
        elif etype == oevents.TASK_COMPLETED:
            tid = ev.get("task_id", "")
            if ev.get("status") not in ("ok", "partial"):
                continue
            data = ev.get("data") or {}
            if tid in _CAP_INTERNAL:
                if not data.get("text"):
                    continue  # gathered nothing — no card, same as before
                # `name` is the stable capability id, not a pre-baked Japanese
                # string — the frontend's TOOL_LABEL picks ja/en the same way it
                # already does for every ReAct-loop tool, so this reads in
                # whichever language the UI is set to, not Japanese-only.
                yield _sse({"type": "tool", "name": tid, "args": f"「{goal}」",
                            "result": "根拠を収集しました。",
                            "internal": _CAP_INTERNAL.get(tid, False)})
            elif tid == "documents" and data.get("document"):
                # A "proposal" is deal-grounded (real CRM financials/products/
                # comparables); pptx/docx are free-authored — same internal/
                # general split as generate_proposal vs generate_pptx/docx.
                yield _sse({"type": "tool", "name": "documents",
                            "args": f"kind={doc_kind}", "result": data.get("text", ""),
                            "document": data["document"],
                            "documents": data.get("documents") or [data["document"]],
                            "outline": data.get("outline") or [],
                            "internal": doc_kind == "proposal"})

    result = box.get("result")
    if result is None:
        yield _sse({"type": "error", "reason": box.get("error", "planner failed")})
        yield _sse({"type": "done", "model": config.MODEL})
        return

    text = result.get("text", "") or "資料を生成できませんでした。"
    outline = result.get("outline") or []
    if outline:
        titles = "\n".join(f"{i}. {s.get('title', '')}" for i, s in enumerate(outline, 1)
                           if s.get("title"))
        if titles:
            text = f"{text}\n\n構成:\n{titles}"
    yield _sse({"type": "answer", "text": text})
    yield _sse({"type": "done", "model": config.MODEL})


@app.post("/api/plan")
def plan_document(req: PlanRequest):
    """Plan a document goal into a capability graph, execute it, stream the result.
    The dedicated planner surface; `/api/chat` also auto-routes document goals here."""
    convo: list[dict] = []
    for m in req.history:
        if m.role in ("user", "assistant") and m.content:
            convo.append({"role": m.role, "content": m.content})
    convo.append({"role": "user", "content": req.message})
    return StreamingResponse(
        _plan_stream(req.message, convo, req.role),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Multi-agent crew -------------------------------------------------------
# A small crew of role-specialised agents (Researcher / Coach / Strategist)
# analyse one deal together — the "not a chatbot" surface. Researcher and Coach
# run in parallel; the Strategist merges their findings. Triggered from the chat
# workspace via /crew (deal) and /team (manager fan-out). See senpai.agent.crew.
class CrewRequest(BaseModel):
    deal_id: str | None = None
    message: str | None = None      # free text ("fujimoto") — resolved to a deal


@app.post("/api/agent/crew")
def agent_crew(req: CrewRequest):
    """Stream a multi-agent crew analysis of one deal (SSE). Accepts an explicit
    deal_id, or free `message` text that is resolved to the customer's worst open
    deal. Event types: crew | agent | agent_tool | final | done | error"""
    from senpai.agent import crew

    deal_id = (req.deal_id or "").strip()
    short_circuit: list[dict] | None = None
    if not deal_id:
        target = crew.resolve_crew_target(req.message or "")
        if target["status"] == "resolved":
            deal_id = target["deal_id"]
        elif target["status"] == "ambiguous":
            # Same picker the chat/research surfaces use — let the rep choose rather
            # than guess. The query shown is the matched stem ("fujimoto"), not the
            # whole sentence. The CrewTurn re-runs this with the chosen deal_id.
            short_circuit = [
                {"type": "resolve", "status": "ambiguous",
                 "query": target.get("stem") or (req.message or ""),
                 "candidates": target["candidates"]},
                {"type": "done"}]
        else:
            short_circuit = [{"type": "error", "reason": "not_found"}, {"type": "done"}]

    def gen():
        try:
            if short_circuit is not None:
                for ev in short_circuit:
                    yield _sse(ev)
                return
            for ev in crew.run_crew(deal_id):
                yield _sse(ev)
        except Exception as e:  # noqa: BLE001 — never crash the stream
            yield _sse({"type": "error", "reason": str(e)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/agent/team")
def agent_team():
    """Stream a manager fan-out — one analyst agent per rep in parallel, then a team
    lead synthesis (SSE). Same event contract as /api/agent/crew."""
    from senpai.agent import crew

    def gen():
        try:
            for ev in crew.run_team():
                yield _sse(ev)
        except Exception as e:  # noqa: BLE001 — never crash the stream
            yield _sse({"type": "error", "reason": str(e)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/coach/similar-cases")
def coach_similar_cases(req: CoachRequest):
    """Real past deals that rhyme with the current situation — Pillar 2,
    Experience. Read-only retrieval over closed deals; each case carries its
    outcome and the validated principle it teaches (see senpai.coach.cases)."""
    deal = store.get_deal(req.deal_id) if req.deal_id else None
    cases = find_similar_cases(req.note, deal=deal, max_n=3, today=_today())
    return {"cases": cases}


@app.get("/api/coach/examples")
def coach_examples():
    # Each seed example is anchored to a REAL, stable deal_id, so "try one" always
    # runs the grounded path (build_commentary_context resolves the deal at high
    # confidence) — never the "no matching customer" fallback. The notes are
    # deliberately customer-AGNOSTIC: the seed regenerates (deal_id is stable but
    # its customer/dates are not), so naming a company in the note text would
    # eventually mismatch the deal's actual customer. The deal_id alone grounds it.
    return {
        "examples": [
            {
                "title": "前向きだが決裁者が不明",
                "deal_id": "D001",
                "note": "担当者は前向きで『ほぼ決まり』との感触。受注確度は高いと見ている。"
                        "ただ決裁者にはまだ会えていない。",
                "hint": "高い確度が案件の実態・決裁者の状況と噛み合っているか",
            },
            {
                "title": "競合と比較中",
                "deal_id": "D021",
                "note": "競合製品と比較中。価格が高いと言われ、見積は提示済み。"
                        "次回までに再提案する予定。",
                "hint": "価格勝負に流される前に差別化軸を考える",
            },
            {
                "title": "初回訪問・IT環境を確認",
                "deal_id": "D016",
                "note": "初回訪問。先方のPC環境とネットワーク構成を一通り確認できた。"
                        "担当者は忙しそうだった。",
                "hint": "情報収集に走り、関係構築と決裁者の把握が後回しに",
            },
            {
                "title": "部長は前向き",
                "deal_id": "D008",
                "note": "部長は前向きで好感触。現場のIT担当にはまだ会えていない。",
                "hint": "決裁者の感触だけで成約間近と判断していないか",
            },
        ]
    }


# ---------------------------------------------------------------------------
# account intelligence — account-level (not deal-level) reasoning
# ---------------------------------------------------------------------------
@app.get("/api/customers/resolve")
def resolve_customer(q: str):
    """Deterministic name→customer resolution (alias-aware, never a name guess).
    Used by the Workspace /account skill to turn a typed name into a customer_id.
    Returns {status: resolved|ambiguous|not_found, query, customer, candidates}."""
    return store.resolve_customer_detailed((q or "").strip()).to_dict()


class SmartResolveRequest(BaseModel):
    query: str
    lang: str = "ja"


@app.post("/api/customers/smart-resolve")
def smart_resolve_customer(body: SmartResolveRequest):
    """Intelligent customer resolution: deterministic first, fuzzy near-miss second,
    LLM ranking third.

    Returns:
      { status: "resolved"|"ambiguous"|"not_found",
        query, customer, candidates, suggested_id? }

    - `suggested_id`: the candidate the model considers most likely (may differ from
      candidates[0] after sorting). Only present when the LLM is available.
    - `candidates`: always sorted by LLM confidence when LLM available, else
      deterministic order.
    """
    q = (body.query or "").strip()
    lang = body.lang or "ja"
    if not q:
        return {"status": "not_found", "query": q, "customer": None, "candidates": []}

    # 1. Deterministic resolve — exact / alias
    res = store.resolve_customer_detailed(q)
    if res.status == "resolved":
        return {**res.to_dict(), "suggested_id": res.customer["customer_id"]}

    candidates = []
    if res.status == "ambiguous":
        candidates = res.candidates  # already found via alias index

    # 2. Fuzzy near-miss — enrich "not_found" with difflib candidates
    if not candidates:
        # Build candidates by scoring each alias key the same way fuzzy_match_customer_in_text
        # does: slide a window the length of the key over the query and take the best ratio.
        # Threshold 0.68 and top-5 cap keeps noise out of the LLM prompt.
        import difflib
        FUZZY_THRESHOLD = 0.68
        MAX_CANDIDATES = 5
        scored: list[tuple[float, str]] = []  # (score, customer_id)
        low = q.lower()
        seen_cids: set[str] = set()
        for key, ids in store._alias_index().items():
            if len(key) < 4 or len(ids) != 1:
                continue
            cid = next(iter(ids))
            if cid in seen_cids:
                continue
            klen = len(key)
            best = 0.0
            if klen > len(low):
                best = difflib.SequenceMatcher(None, key, low, autojunk=False).ratio()
            else:
                for start in range(len(low) - klen + 1):
                    r = difflib.SequenceMatcher(None, key, low[start:start + klen], autojunk=False).ratio()
                    if r > best:
                        best = r
            if best >= FUZZY_THRESHOLD:
                seen_cids.add(cid)
                scored.append((best, cid))

        scored.sort(key=lambda x: (-x[0], x[1]))
        from senpai.data.store import CustomerCandidate, get_customer
        candidates = [
            CustomerCandidate(
                customer_id=cid,
                name=(get_customer(cid) or {}).get("name", cid),
                matched_aliases=[],
            )
            for _, cid in scored[:MAX_CANDIDATES]
            if get_customer(cid)
        ]
        if not candidates:
            return {"status": "not_found", "query": q, "customer": None,
                    "candidates": [], "suggested_id": None}


    # 3. LLM ranking — ask the model which candidate best matches the user's query
    suggested_id: str | None = None
    sorted_candidates = candidates  # default: original order

    if USE_LLM and len(candidates) > 1:
        try:
            from senpai.llm import client as llm_client
            names_block = "\n".join(
                f"  {i+1}. {c.customer_id}: {c.name}"
                for i, c in enumerate(candidates)
            )
            if lang == "ja":
                prompt = (
                    f"ユーザーが入力したキーワードは「{q}」です。\n"
                    f"以下の顧客候補の中から、最も可能性が高い顧客を1つ選んでください。\n"
                    f"顧客リスト:\n{names_block}\n\n"
                    "回答形式: 顧客IDのみを返してください（例: C06）。説明不要。"
                )
            else:
                prompt = (
                    f"The user typed: \"{q}\"\n"
                    f"From the following customers, pick the single best match:\n"
                    f"{names_block}\n\n"
                    "Reply with only the customer_id (e.g. C06). No explanation."
                )
            answer = llm_client.simple_complete(
                [{"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=16, no_think=True,
            ).strip()
            # Extract the first Cxx token from the answer
            import re as _re
            m = _re.search(r"C\d+", answer)
            if m:
                suggested_id = m.group(0)
                # Re-sort: put the suggested candidate first
                sorted_candidates = sorted(
                    candidates,
                    key=lambda c: (0 if c.customer_id == suggested_id else 1, c.customer_id),
                )
        except Exception:  # noqa: BLE001 — LLM failure must never break the picker
            pass

    return {
        "status": "ambiguous" if len(candidates) > 1 else "resolved",
        "query": q,
        "customer": sorted_candidates[0].__dict__ if len(candidates) == 1 else None,
        "candidates": [{"customer_id": c.customer_id, "name": c.name}
                       for c in sorted_candidates],
        "suggested_id": suggested_id or (sorted_candidates[0].customer_id if sorted_candidates else None),
    }



@app.get("/api/account/{customer_id}")
def account(customer_id: str):
    """One grounded roll-up of a whole customer relationship: headline aggregates,
    account health, relationship-trajectory patterns and expansion opportunities.
    Deterministic; see senpai.account."""
    from senpai.account import build_account_summary
    s = build_account_summary(customer_id, today=_today())
    if s is None:
        raise HTTPException(404, f"customer {customer_id} not found")
    return s.to_dict()


@app.post("/api/account/{customer_id}/commentary")
def account_commentary(customer_id: str, lang: str = "ja",
                       conversation_id: str | None = None):
    """Stream a senior account-manager's read of the whole relationship (SSE).
    Grounded in the deterministic account context package; reasoning disabled for
    low latency, pinned to the primary endpoint (no silent fallback). Event types:
      start | context | delta | done | unavailable"""
    from senpai.account import account_commentary_prompt
    from senpai.account.gather import gather_account_context

    if not USE_LLM:
        return StreamingResponse(
            iter([_sse({"type": "unavailable", "reason": "llm_disabled"})]),
            media_type="text/event-stream",
        )

    # Gather runs on the orchestration engine (M3); identical (context_text, meta).
    context_text, ctx_meta = gather_account_context(customer_id, lang=lang, today=_today())
    if not ctx_meta["has_account"]:
        return StreamingResponse(
            iter([_sse({"type": "unavailable", "reason": "account_not_found"})]),
            media_type="text/event-stream",
        )
    prompt = account_commentary_prompt(context_text, lang=lang)

    # Workspace continuity: pulling an account brief puts that customer "in focus"
    # for the shared conversation, so a follow-up chat turn stays scoped to it.
    _seed_chat_focus(conversation_id, customer_id, ctx_meta.get("customer"), None)

    def gen():
        from senpai.llm import client
        yield _sse({"type": "start", "model": config.MODEL, "endpoint": config.BASE_URL})
        # Workspace: this stream produces an `account_brief` artifact.
        yield _sse({"type": "artifact_meta", "kind": "account_brief",
                    "entity_ref": {"type": "account", "id": customer_id,
                                   "name": ctx_meta.get("customer")}})
        yield _sse({"type": "context", "customer": ctx_meta["customer"],
                    "customer_id": customer_id, "score": ctx_meta["score"],
                    "band": ctx_meta["band"]})
        # Transparency: surface the deterministic strategic stance (tier + region +
        # the rationale for why it was chosen) so the rep sees it alongside the read.
        if ctx_meta.get("strategy"):
            yield _sse({"type": "strategy", **ctx_meta["strategy"]})
        full, emitted = "", 0
        try:
            for piece in client.stream_complete(
                [{"role": "user", "content": prompt}],
                temperature=0.5, max_tokens=config.LLM_NARRATE_MAX_TOKENS,
                no_think=True, allow_fallback=False,
            ):
                full += piece
                if "</think>" in full:
                    answer = full.split("</think>", 1)[1].lstrip("\n ")
                elif "<think>" in full:
                    answer = ""
                else:
                    answer = full
                new = answer[emitted:]
                if new:
                    emitted += len(new)
                    yield _sse({"type": "delta", "text": new})
            if emitted:
                yield _sse({"type": "done", "model": config.MODEL})
            else:
                yield _sse({"type": "unavailable", "reason": "empty"})
        except Exception:  # noqa: BLE001 — primary endpoint down/timeout (no fallback)
            yield _sse({"type": "unavailable", "reason": "unreachable"})

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# manager coaching workspace ("where should I coach today?")
# ---------------------------------------------------------------------------
@app.get("/api/coaching")
def coaching(manager: str | None = None):
    """Manager's daily workspace — Needs Coaching queue, team trends, Confidence
    vs Reality, and a weekly digest. Read-only aggregation over the existing
    deal-health + flags engines; see senpai.coaching. `manager` (an employee_id)
    scopes it to that manager's team; omit for the whole team."""
    rep_ids = store.team_of(manager) if manager else None
    return coaching_workspace(today=_today(), rep_ids=rep_ids)


@app.get("/api/coach/rep-profile/{employee_id}")
def coach_rep_profile(employee_id: str):
    """Per-rep coaching profile (the 1:1 page): recurring weaknesses grounded in
    real deals + a validated principle + a real case + an action, plus strengths,
    talking points and coaching-thread status. See senpai.coach.profile."""
    return rep_coaching_profile(employee_id, today=_today())


@app.get("/api/coach/rep-profiles")
def coach_rep_profiles(manager: str | None = None):
    """Team rollup: one compact profile per rep, worst-needing-coaching first.
    `manager` (an employee_id) limits it to that manager's team."""
    rep_ids = store.team_of(manager) if manager else None
    return {"reps": team_coaching_profiles(today=_today(), rep_ids=rep_ids)}


@app.get("/api/coach/team")
def coach_team(manager: str | None = None):
    """A manager's 'My team' roster — every rep on their team (coachees + assigned
    juniors), each with their open-deal count. Unlike the rep-profiles rollup this
    KEEPS zero-deal reps, so a freshly-assigned junior is visible. Empty team when
    `manager` is omitted."""
    ids = store.team_of(manager) if manager else set()
    reps = []
    for eid in ids:
        rep = store.get_rep(eid) or {}
        open_deals = sum(1 for d in store.deals_for_rep(eid)
                         if config.is_open_rank(d.get("order_rank")))
        reps.append({
            "employee_id": eid,
            "name": rep.get("name", eid),
            "role": rep.get("role", ""),
            "open_deals": open_deals,
        })
    reps.sort(key=lambda r: (-r["open_deals"], r["employee_id"]))
    return {"reps": reps}


@app.get("/api/coach/rep-progress/{employee_id}")
def coach_rep_progress(employee_id: str, windows: int = 4):
    """Longitudinal coaching progress for a rep — per-fiscal-year weakness rates,
    per-issue trend, and whether past coaching was acted on. See coach.progress."""
    return rep_progress(employee_id, today=_today(), windows=windows)


@app.get("/api/coach/threads")
def coach_threads(rep_id: str | None = None, deal_id: str | None = None):
    """Manager↔rep coaching threads, filtered by rep or deal (newest first)."""
    if deal_id:
        rows = store.coaching_threads_for_deal(deal_id)
    elif rep_id:
        rows = store.coaching_threads_for_rep(rep_id)
    else:
        rows = store.all_coaching_threads()
    return {"threads": rows}


# ---------------------------------------------------------------------------
# growth (Pillar 3 — Motivation)
# ---------------------------------------------------------------------------
@app.get("/api/growth")
def growth(rep: str | None = None):
    """A junior's 'My Growth' picture — reviews, principles touched, coaching
    streak, monthly activity, and skill progression. Read-only over the store;
    see senpai.growth. `rep` is an employee_id; defaults to the first junior."""
    juniors = junior_reps()
    eid = rep or (juniors[0]["employee_id"] if juniors else "")
    return {
        "growth": rep_growth(eid, today=_today()),
        "juniors": [{"employee_id": r["employee_id"], "name": r["name"]} for r in juniors],
    }


# ---------------------------------------------------------------------------
# knowledge
# ---------------------------------------------------------------------------
@app.get("/api/knowledge/sources")
def knowledge_sources():
    return {"sources": [asdict(s) for s in kstore.all_sources()]}


@app.get("/api/knowledge/principles")
def knowledge_principles():
    ps = [_principle_payload(p) for p in kstore.all_principles()]
    return {
        "principles": ps,
        "counts": {
            "total": len(ps),
            "approved": sum(1 for p in ps if p["status"] == "approved"),
            "pending": sum(1 for p in ps if p["status"] != "approved"),
            "two_source": sum(1 for p in ps if p["n_interviews"] >= 2),
        },
    }


@app.get("/api/knowledge/items")
def knowledge_items():
    items = [_item_payload(it) for it in kstore.all_items()]
    return {
        "items": items,
        "counts": {
            "total": len(items),
            "approved": sum(1 for i in items if i["review"]["status"] == "approved"),
            "pending": sum(1 for i in items if i["review"]["status"] in ("draft", "needs_edit")),
        },
    }


class GenerateRequest(BaseModel):
    principle_id: str
    use_llm: bool = False


@app.post("/api/knowledge/generate")
def knowledge_generate(req: GenerateRequest):
    p = kstore.get_principle(req.principle_id)
    if p is None:
        raise HTTPException(404, f"principle {req.principle_id} not found")
    if p.status != "approved":
        raise HTTPException(400, "only approved principles may seed a draft")
    item = kgen.generate_item(p, use_llm=req.use_llm)
    kstore.save_item(item)
    return {"item": _item_payload(item)}


class AddPrincipleRequest(BaseModel):
    statement: str               # the tacit knowledge / advice (the principle)
    situation: str = ""          # the context the manager is grounding it in
    tags: list[str] = []         # → Coach retrieval
    added_by: str = "manager"


@app.post("/api/knowledge/principles")
def knowledge_add_principle(req: AddPrincipleRequest):
    """Manager-contributed tacit knowledge → a Layer-1 Principle (status
    'candidate'), grounded in a manager-note Source. Written to the ingested
    overlay (committed seed untouched); flows through the existing review queue
    to become an approved principle juniors can see. See senpai.knowledge."""
    from senpai.knowledge.schema import Citation, Principle, Source

    statement = (req.statement or "").strip()
    if not statement:
        raise HTTPException(400, "statement is required")

    sid = kstore.next_source_id()
    kstore.save_source(Source(
        source_id=sid, kind="manager_note", participant_role="manager",
        date=_today().isoformat(), notes=req.situation.strip(),
    ))
    pid = kstore.next_principle_id()
    principle = Principle(
        principle_id=pid, statement=statement,
        support=[Citation(source_id=sid, quote=(req.situation.strip() or statement))],
        tags=[t.strip() for t in req.tags if t.strip()],
        status="candidate", added_by=req.added_by or "manager",
    )
    kstore.save_principle(principle)
    return {"principle": _principle_payload(principle)}


class ReviewRequest(BaseModel):
    action: str          # approve | request_edit | reject
    reviewer: str = "web_reviewer"
    notes: str = ""


@app.post("/api/knowledge/items/{item_id}/review")
def knowledge_item_review(item_id: str, req: ReviewRequest):
    fn = {"approve": kreview.approve, "request_edit": kreview.request_edit,
          "reject": kreview.reject}.get(req.action)
    if fn is None:
        raise HTTPException(400, f"unknown action {req.action}")
    try:
        item = fn(item_id, req.reviewer, req.notes)
    except KeyError:
        raise HTTPException(404, f"item {item_id} not found")
    return {"item": _item_payload(item)}


# --- Multimodal ingestion ---------------------------------------------------
async def _uploads_to_raw_text(
    audio: UploadFile | None, image: UploadFile | None, text: str | None,
) -> str:
    """Transcribe/OCR any uploads and join with raw text. Shared by /api/extract
    (chat-over-attachment) and /api/ingest (structured draft). Raises 400 if empty."""
    import os
    import tempfile

    from senpai.ingestion import multimodal as mm

    parts: list[str] = []
    for upload, extract in ((audio, mm.transcribe_audio), (image, mm.extract_text_from_image)):
        if upload is None:
            continue
        suffix = os.path.splitext(upload.filename or "")[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await upload.read())
            tmp_path = tmp.name
        try:
            out = extract(tmp_path)
            if out:
                parts.append(out)
        finally:
            os.unlink(tmp_path)

    if text and text.strip():
        parts.append(text.strip())

    if not parts:
        raise HTTPException(400, "provide at least one of: audio, image, text")
    return "\n\n".join(parts)


@app.post("/api/extract")
async def extract_text(
    audio: UploadFile | None = File(default=None),
    image: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
):
    """Extract plain text from an attachment for chat context.

    Voice note → transcript, image → OCR, or raw text — returns just `raw_text`.
    Unlike /api/ingest this does NOT run structured-activity extraction: the
    workspace chat attaches this text as context and lets the user ask about it.
    Data ingestion is a separate flow (/api/ingest, /api/ingest/save)."""
    raw = await _uploads_to_raw_text(audio, image, text)
    return {"raw_text": raw}


@app.post("/api/ingest")
async def ingest(
    audio: UploadFile | None = File(default=None),
    image: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
):
    """Capture → structured sales-activity draft.

    Accepts a voice note (audio), a business-card/whiteboard photo (image),
    and/or raw text — any combination — and returns an editable draft matching
    the `sales_activities` schema (activity_type, daily_report, business_card_info,
    customer_challenge, product_major_category). Wraps senpai.ingestion.multimodal
    unchanged; falls back to deterministic mock extraction offline (no multimodal
    API key). The draft is NOT persisted — the caller reviews/edits it, then POSTs
    it to /api/ingest/save."""
    from senpai.ingestion import multimodal as mm

    raw = await _uploads_to_raw_text(audio, image, text)
    draft = mm.extract_structured_activity(raw)
    return {"raw_text": raw, "draft": draft, "multimodal": config.have_multimodal()}


class SaveActivityRequest(BaseModel):
    draft: dict                  # edited ActivityDraft (activity_type, daily_report, …)
    customer_id: str
    deal_id: str
    employee_id: str


@app.post("/api/ingest/save")
def ingest_save(req: SaveActivityRequest):
    """Persist a reviewed daily-report draft as a real sales_activities row.

    Builds the record in exact seed shape (correct Japanese fiscal year/quarter,
    rep dept/division, derived order stats) and appends it to the gitignored
    overlay (senpai/data/ingested/) — the committed seed is never mutated. The new
    activity is immediately visible to scoring/timeline for the running process."""
    if not store.get_deal(req.deal_id):
        raise HTTPException(404, f"deal {req.deal_id} not found")
    if not store.get_customer(req.customer_id):
        raise HTTPException(404, f"customer {req.customer_id} not found")
    from senpai.ingestion import persist
    record = persist.save_activity(req.draft, req.customer_id, req.deal_id, req.employee_id)
    return {"saved": True, "activity": record}


# ===========================================================================
# ADMIN PORTAL  (internal-only; NO auth by design — see the plan's caveat).
# Read-only reshapes over existing engines + one reassignment write + the
# Graph-RAG showcase feed. Kept in this flat file to match the rest of the API.
# ===========================================================================
_MANAGER_ROLES = ("senior", "expert")


def _is_manager(rep: dict) -> bool:
    return rep.get("role") in _MANAGER_ROLES


def _account_emp_ids() -> set[str]:
    """Employee ids that have a login account."""
    return {u.get("employee_id") for u in auth.list_users() if u.get("employee_id")}


def _open_deal_count(employee_id: str) -> int:
    return sum(1 for d in store.deals_for_rep(employee_id)
               if config.is_open_rank(d.get("order_rank")))


def _direct_reports(manager_id: str) -> list[dict]:
    """The canonical org chart the admin portal manages: reps whose reports_to is
    this manager. reports_to is the single editable source of truth here (see the
    plan) — distinct from store.team_of, which unions coaching threads for the
    product's coaching views."""
    return [r for r in store.all_reps() if r.get("reports_to") == manager_id]


def _rep_row(rep: dict, accounts: set[str]) -> dict:
    """A rep enriched for the admin tables: manager name, team size, login flag."""
    eid = rep.get("employee_id", "")
    mgr_id = rep.get("reports_to") or ""
    mgr = store.get_rep(mgr_id) if mgr_id else None
    return {
        "employee_id": eid,
        "name": rep.get("name", eid),
        "role": rep.get("role", ""),
        "department": rep.get("department", ""),
        "division": rep.get("division", ""),
        "reports_to": mgr_id,
        "manager_name": (mgr or {}).get("name", "") if mgr else "",
        "is_manager": _is_manager(rep),
        "team_size": len(_direct_reports(eid)) if _is_manager(rep) else 0,
        "has_account": eid in accounts,
        "open_deals": _open_deal_count(eid),
        "is_top_performer": bool(rep.get("is_top_performer")),
    }


@app.get("/api/admin/overview")
def admin_overview():
    """Headline counts + health for the admin home."""
    from senpai.graph import communities as _comm
    from senpai.knowledge import store as _kstore
    reps = store.all_reps()
    managers = [r for r in reps if _is_manager(r)]
    juniors = [r for r in reps if r.get("role") == "junior"]
    accounts = auth.list_users()
    try:
        pending = max(len(_kstore.all_items()) - len(_kstore.approved_items()), 0)
    except Exception:  # noqa: BLE001
        pending = 0
    usage_totals = _usage_summary()["totals"]
    return {
        "reps": len(reps),
        "managers": len(managers),
        "juniors": len(juniors),
        "accounts": len(accounts),
        "deals": len(store.all_deals()),
        "open_deals": len(store.open_deals()),
        "communities": len(_comm.load_reports()),
        "knowledge_pending": pending,
        "tokens_total": usage_totals["total_tokens"],
        "llm_calls": usage_totals["calls"],
    }


@app.get("/api/admin/reps")
def admin_reps():
    """Every rep (seed + overlay), enriched — the People table."""
    accounts = _account_emp_ids()
    rows = [_rep_row(r, accounts) for r in store.all_reps()]
    rows.sort(key=lambda r: (not r["is_manager"], r["employee_id"]))
    return {"reps": rows, "managers": [
        {"employee_id": r["employee_id"], "name": r["name"]}
        for r in rows if r["is_manager"]]}


@app.get("/api/admin/org")
def admin_org():
    """Managers with their teams + an Unassigned bucket — the org/assignment view."""
    accounts = _account_emp_ids()
    reps = store.all_reps()
    managers = [r for r in reps if _is_manager(r)]
    placed: set[str] = set()
    groups = []
    for m in sorted(managers, key=lambda r: r["employee_id"]):
        mid = m["employee_id"]
        team_rows = sorted(_direct_reports(mid), key=lambda r: r.get("employee_id", ""))
        placed.update(r["employee_id"] for r in team_rows)
        groups.append({
            "manager": _rep_row(m, accounts),
            "team": [_rep_row(r, accounts) for r in team_rows],
        })
    unassigned = [_rep_row(r, accounts) for r in reps
                  if not r.get("reports_to") and not _is_manager(r)]
    unassigned.sort(key=lambda r: r["employee_id"])
    return {"groups": groups, "unassigned": unassigned,
            "manager_pool": [{"employee_id": m["employee_id"], "name": m.get("name", "")}
                             for m in managers]}


class ReassignRequest(BaseModel):
    manager_id: str


@app.post("/api/admin/reps/{employee_id}/reassign")
def admin_reassign(employee_id: str, req: ReassignRequest):
    """Move a rep under a manager by rewriting reports_to (see store.set_reports_to)."""
    try:
        store.set_reports_to(employee_id, req.manager_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"rep": _rep_row(store.get_rep(employee_id) or {}, _account_emp_ids())}


@app.get("/api/admin/activity")
def admin_activity(limit: int = 100):
    """Reverse-chronological system activity: latest coaching-thread messages and
    daily reports. Best-effort, capped."""
    events: list[dict] = []
    for t in store.all_coaching_threads():
        msgs = t.get("messages") or []
        if not msgs:
            continue
        last = msgs[-1]
        events.append({
            "type": "coaching",
            "date": last.get("date", ""),
            "rep": t.get("employee_id", ""),
            "manager": t.get("manager_id", ""),
            "deal": t.get("deal_id", ""),
            "text": (last.get("text", "") or "")[:200],
        })
    for rep in store.all_reps():
        eid = rep.get("employee_id", "")
        for dr in store.daily_reports_for_rep(eid)[-3:]:
            events.append({
                "type": "daily_report",
                "date": dr.get("activity_date", ""),
                "rep": eid,
                "customer": dr.get("customer_id", ""),
                "deal": dr.get("deal_id", ""),
                "text": (dr.get("daily_report", "") or "")[:200],
            })
    events.sort(key=lambda e: e.get("date", ""), reverse=True)
    return {"events": events[:limit]}


@app.get("/api/admin/accounts")
def admin_accounts():
    """Login accounts (public shape) joined to rep names — who can sign in."""
    out = []
    for u in auth.list_users():
        eid = u.get("employee_id")
        rep = store.get_rep(eid) if eid else None
        out.append({**u, "rep_name": (rep or {}).get("name", "")})
    return {"accounts": out}


@app.get("/api/admin/pipeline-health")
def admin_pipeline_health():
    """System-wide deal health from the grounded community layer: where the
    business is losing (lowest win-rate leaves) and the failure-signal mix."""
    from collections import Counter
    from senpai.graph import communities as _comm
    reports = _comm.load_reports()
    leaves = [r for r in reports if r.get("level") == "leaf"]
    signals: Counter = Counter()
    for r in leaves:
        for s in r.get("top_failure_signals", []):
            name = s.get("signal") if isinstance(s, dict) else s
            count = s.get("count", 1) if isinstance(s, dict) else 1
            if name:
                signals[name] += count
    segments = sorted(
        [{"category": r.get("category", ""), "industry": r.get("industry", ""),
          "n_deals": r.get("n_deals", 0), "n_won": r.get("n_won", 0),
          "n_lost": r.get("n_lost", 0), "n_open": r.get("n_open", 0),
          "win_rate": r.get("win_rate", 0.0),
          "top_failure_signals": r.get("top_failure_signals", [])}
         for r in leaves],
        key=lambda s: (s["win_rate"], -s["n_lost"]))
    totals = {
        "n_deals": sum(r.get("n_deals", 0) for r in leaves),
        "n_won": sum(r.get("n_won", 0) for r in leaves),
        "n_lost": sum(r.get("n_lost", 0) for r in leaves),
        "n_open": sum(r.get("n_open", 0) for r in leaves),
    }
    return {"totals": totals,
            "failure_signals": [{"signal": k, "count": v} for k, v in signals.most_common()],
            "lowest_win_segments": segments[:10]}


@app.get("/api/admin/system-status")
def admin_system_status():
    """Operational snapshot for 'is the demo healthy'."""
    from senpai.retrieval import semantic as _sem
    try:
        retrieval_mode = _sem.mode()
    except Exception:  # noqa: BLE001
        retrieval_mode = "unknown"
    ingested = config.INGESTED_DIR
    overlays = sorted(p.name for p in ingested.glob("*.json")) if ingested.exists() else []
    return {
        "use_llm": USE_LLM,
        "today": str(_today()),
        "retrieval_mode": retrieval_mode,
        "endpoints": {
            "primary": {"base_url": config.BASE_URL, "model": config.MODEL},
            "fallback": {"base_url": config.FALLBACK_BASE_URL, "model": config.FALLBACK_MODEL},
        },
        "flags": {
            "FAST_SYNTH_FALLBACK": config.FAST_SYNTH_FALLBACK,
            "SYNTH_ALL_FALLBACK": config.SYNTH_ALL_FALLBACK,
        },
        "data": {"reps": len(store.all_reps()), "deals": len(store.all_deals()),
                 "overlays": overlays},
    }


def _usage_summary() -> dict:
    from senpai.llm import usage as _u
    return _u.summary()


@app.get("/api/admin/usage")
def admin_usage():
    """LLM token accounting: totals, per-day, by model, by feature, recent calls."""
    return _usage_summary()


# --- Visualization (Graph-RAG showcase) ------------------------------------
def _node_label(nid: str, data: dict) -> str:
    kind = data.get("kind", "")
    if kind in ("category", "industry", "acttype") and ":" in nid:
        return nid.split(":", 1)[-1]
    return data.get("name") or nid


@app.get("/api/admin/graph")
def admin_graph(kind: str | None = None):
    """The real NetworkX graph serialized for react-force-graph. Optional ?kind=
    filters to one node kind (edges kept only between surviving nodes)."""
    from senpai.graph import build as _build
    G = _build.graph()
    nodes = []
    for nid, data in G.nodes(data=True):
        k = data.get("kind", "")
        if kind and k != kind:
            continue
        nodes.append({"id": nid, "kind": k, "label": _node_label(nid, data),
                      "degree": G.degree(nid), "outcome": data.get("outcome"),
                      "category": data.get("category"), "industry": data.get("industry")})
    keep = {n["id"] for n in nodes}
    links = [{"source": u, "target": v, "rel": d.get("rel", "")}
             for u, v, d in G.edges(data=True) if u in keep and v in keep]
    return {"nodes": nodes, "links": links, "stats": _build.stats()}


@app.get("/api/admin/communities")
def admin_communities():
    """The 44 grounded communities (7 category rollups + 37 thick leaves)."""
    from senpai.graph import communities as _comm
    return {"communities": [dict(r) for r in _comm.load_reports()]}


def _est_tokens(text: str) -> int:
    """One consistent token estimate applied to BOTH pipelines in the head-to-head,
    so the comparison is a measured ratio of measured quantities."""
    from senpai.llm import usage as _u
    return _u._estimate_tokens(text)


def _nx_seed_nodes(G, query: str) -> list[str]:
    """Resolve a free-form query to seed graph nodes by substring-matching its text
    against grouping-node keys (category/industry/acttype) and product/customer names.
    Deliberately naive — this is the *ungrounded* baseline, not the curated selector."""
    q = query or ""
    seeds: list[str] = []
    for n, a in G.nodes(data=True):
        kind = a.get("kind") or ""
        if kind in ("category", "industry", "acttype") and ":" in n:
            key = n.split(":", 1)[1]
        elif kind in ("product", "customer"):
            key = a.get("name") or ""
        else:
            continue
        if key and len(key) >= 2 and key in q:
            seeds.append(n)
    return seeds[:12]


def _answer_for(query: str, context: str, *, label: str) -> dict:
    """Generate an answer to `query` from ONLY the given retrieved `context`, so the
    three methods are judged on the same generation step over their own evidence.
    Measures generation latency and answer tokens. Never raises."""
    import time
    if not (context or "").strip():
        return {"text": "(no context retrieved — nothing to answer from)",
                "latency_ms": 0.0, "tokens": 0}
    from senpai.llm.client import simple_complete
    msgs = [
        {"role": "system", "content": (
            "You are a B2B sales-intelligence assistant. Answer the user's question "
            "using ONLY the provided context. Be concise (3-4 sentences). If the "
            "context does not contain the answer, say the context is insufficient.")},
        {"role": "user", "content": f"Question: {query}\n\nContext:\n{context}"},
    ]
    t0 = time.perf_counter()
    try:
        text = simple_complete(msgs, temperature=0.2, no_think=True, label=f"versus:{label}")
    except Exception:  # noqa: BLE001 — a failed generation must not break the demo
        text = "(answer generation failed)"
    gen_ms = (time.perf_counter() - t0) * 1000.0
    return {"text": text, "latency_ms": round(gen_ms, 1), "tokens": _est_tokens(text)}


def _run_networkx_baseline(query: str) -> tuple[dict, str]:
    """A naive NetworkX graph-retrieval baseline: seed nodes from the query, expand
    the one-hop ego neighborhood, rank it by degree centrality, and dump the raw
    neighborhood as context. No curated community reports — the honest 'graph but
    ungrounded' middle ground between vector RAG and grounded Graph RAG. Returns
    (side, context). Never raises: on any failure it degrades to an empty-but-measured
    side. Degree (not PageRank) so the baseline stays scipy-free and deterministic."""
    import time
    from senpai.graph.build import graph as _graph

    t0 = time.perf_counter()
    try:
        G = _graph()
        seeds = _nx_seed_nodes(G, query)
        UG = G.to_undirected(as_view=True)
        nbrs: set[str] = set(seeds)
        for s in seeds:
            nbrs.update(UG.neighbors(s))
        sub = G.subgraph(nbrs) if nbrs else G.subgraph([])
        deg = dict(sub.degree()) if sub.number_of_nodes() else {}
        ranked = sorted(sub.nodes(data=True), key=lambda x: deg.get(x[0], 0), reverse=True)
        # Raw neighborhood dump: every deal node reachable from the seeds, ungrounded.
        deal_texts = [
            f'{a.get("name","")} · {a.get("outcome","")} · {a.get("category","")} × '
            f'{a.get("industry","")} · ¥{a.get("amount",0)}'
            for _n, a in ranked if a.get("kind") == "deal"
        ]
        ctx = "\n\n".join(deal_texts)
        nx_ms = (time.perf_counter() - t0) * 1000.0
        sample = [
            {"label": a.get("name") or n, "kind": a.get("kind", ""),
             "score": deg.get(n, 0)}
            for n, a in ranked[:6]
        ]
        side = {"label": "NetworkX (naive graph traversal)",
                "chunks": len(deal_texts),
                "context_chars": len(ctx),
                "context_tokens": _est_tokens(ctx),
                "latency_ms": round(nx_ms, 1),
                "note": f"raw ego-graph neighborhood from {len(seeds)} seed nodes, ungrounded",
                "sample": sample}
        return side, ctx
    except Exception:  # noqa: BLE001 — the baseline must never break the scorecard
        nx_ms = (time.perf_counter() - t0) * 1000.0
        return ({"label": "NetworkX (naive graph traversal)", "chunks": 0,
                 "context_chars": 0, "context_tokens": 0, "latency_ms": round(nx_ms, 1),
                 "note": "no seed nodes matched the query", "sample": []}, "")


def _run_graph_rag_stream(query: str):
    """SSE generator: animate the graph query, stream the real retrieval trace,
    and end with a MEASURED (never fabricated) three-way scorecard —
    grounded Graph RAG vs a naive NetworkX baseline vs traditional retrieval."""
    import time
    from senpai.graph import query as _gq
    from senpai.graph import communities as _comm
    from senpai.retrieval import semantic as _sem
    from senpai.retrieval import trace as _trace

    yield _sse({"type": "start", "query": query})

    # --- Graph side: community selection + a representative graph query --------
    _trace.start()
    t0 = time.perf_counter()
    segments = _comm.select(query, limit=5)
    reps_rows = _gq.reps_who_win(min_deals=2)[:5]
    graph_ms = (time.perf_counter() - t0) * 1000.0
    graph_ctx = "\n\n".join(_comm.format_report(s) for s in segments)

    # Emit the nodes the graph actually consulted (honest: these are the segments
    # and the reps/deals behind the answer), so the UI can light them up.
    for s in segments:
        yield _sse({"type": "node_visited", "kind": "community",
                    "label": f'{s.get("category","")} × {s.get("industry","") or "—"}',
                    "n_deals": s.get("n_deals", 0), "win_rate": s.get("win_rate", 0.0)})
        time.sleep(0.4)  # Visual delay to animate traversal
    for row in reps_rows:
        rep_id = row.get("rep_id") or row.get("rep") or row.get("employee_id") or "?"
        yield _sse({"type": "node_visited", "kind": "rep", "label": rep_id,
                    "won": row.get("won", 0), "closed": row.get("closed", 0)})
        time.sleep(0.3)
        for did in (row.get("example_deal_ids") or row.get("deals") or [])[:3]:
            yield _sse({"type": "edge_traversed", "source": rep_id, "target": did,
                        "rel": "OWNS"})
            time.sleep(0.2)

    trace_items = _trace.drain()
    for ev in trace_items:
        yield _sse({"type": "retrieved", **ev})

    # --- Traditional side: the real hybrid retriever on the SAME query ---------
    t0 = time.perf_counter()
    trad = _sem.semantic_search(query, corpus="activities", limit=8)
    trad_ms = (time.perf_counter() - t0) * 1000.0
    trad_ctx = "\n\n".join(x.get("text", "") or x.get("snippet", "") for x in trad)
    try:
        trad_mode = _sem.mode()
    except Exception:  # noqa: BLE001
        trad_mode = "hybrid"

    # --- NetworkX side: naive ungrounded graph traversal on the SAME query -------
    nx_side, nx_ctx = _run_networkx_baseline(query)

    graph_sample = [{"label": f'{s.get("category","")} × {s.get("industry","") or "—"}',
                     "n_deals": s.get("n_deals", 0), "win_rate": s.get("win_rate", 0.0)}
                    for s in segments]
    trad_sample = [{"customer": x.get("customer_id", ""), "deal": x.get("deal_id", ""),
                    "score": round(x.get("score", 0.0), 3),
                    "snippet": (x.get("snippet") or x.get("text", ""))[:80]}
                   for x in trad[:6]]
    yield _sse({"type": "comparison", "measured": True, "query": query,
                "graph": {"label": "Graph RAG (communities + graph)",
                          "chunks": len(segments),
                          "context_chars": len(graph_ctx),
                          "context_tokens": _est_tokens(graph_ctx),
                          "latency_ms": round(graph_ms, 1),
                          "note": f"grounded over {len(_comm.load_reports())} communities",
                          "sample": graph_sample},
                "networkx": nx_side,
                "traditional": {"label": f"Traditional retrieval ({trad_mode})",
                                "chunks": len(trad),
                                "context_chars": len(trad_ctx),
                                "context_tokens": _est_tokens(trad_ctx),
                                "latency_ms": round(trad_ms, 1),
                                "note": "raw daily-report chunks",
                                "sample": trad_sample}})

    # --- Generation: answer the SAME query from each method's own retrieved context.
    # Streamed one at a time so the UI fills in progressively (3 LLM calls). This is
    # what turns a retrieval scorecard into a real end-to-end quality comparison.
    for method, ctx in (("graph", graph_ctx), ("networkx", nx_ctx), ("traditional", trad_ctx)):
        ans = _answer_for(query, ctx, label=method)
        yield _sse({"type": "answer", "method": method, "text": ans["text"],
                    "latency_ms": ans["latency_ms"], "tokens": ans["tokens"]})

    yield _sse({"type": "done"})


class GraphRagRequest(BaseModel):
    query: str


@app.post("/api/admin/graph-rag/run")
def admin_graph_rag_run(req: GraphRagRequest):
    """Stream a live Graph-RAG run (SSE): graph traversal, real retrieval trace,
    and a measured head-to-head vs traditional retrieval."""
    return StreamingResponse(_run_graph_rag_stream(req.query or ""),
                             media_type="text/event-stream")
````
