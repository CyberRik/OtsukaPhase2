"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpenCheck, Landmark, Play, RotateCcw } from "lucide-react";
import { ringiStream } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { Band, RingiDraft, RingiEvent, RingiPersona } from "@/lib/types";
import { ApprovalGauge } from "@/components/training/approval-gauge";
import { BoardroomRing, type Flow } from "@/components/training/boardroom-ring";
import { SenpaiHud, type Whisper } from "@/components/training/senpai-hud";
import { SpeechFeed, type FeedLine } from "@/components/training/speech-feed";
import { SandboxCard } from "@/components/training/sandbox-card";

// Curated at-risk demo deals for the standalone training shell. D005 crashes to
// red then recovers to green after the sandbox intervention. (Names fill in from
// `meta`.) When launched from a real deal (?deal=), that id is used instead.
const DEMO_DEALS = [
  { id: "D005", ja: "D005 · セキュリティ案件(高リスク)", en: "D005 · Security deal (high risk)" },
  { id: "D001", ja: "D001 · ディスプレイ案件(高リスク)", en: "D001 · Display deal (high risk)" },
  { id: "D010", ja: "D010 · 案件(要注意)", en: "D010 · At-risk deal" },
];

// Approval% → band, matching senpai.config band cutoffs (risk 55/25 ⇒ appr 45/75).
function approvalBand(v: number): Band {
  if (v <= 45) return "red";
  if (v <= 75) return "yellow";
  return "green";
}

// Only committee members sit at the table; coach turns don't move the pulse.
const AT_TABLE = new Set<RingiPersona>(["shacho", "bucho", "kacho"]);

type RunState = "idle" | "streaming" | "done";

export default function RingiSimulationPage() {
  const { t, lang } = useT();
  const ja = lang === "ja";

  const [dealId, setDealId] = useState("D005");
  const [runState, setRunState] = useState<RunState>("idle");
  const [hasOverlay, setHasOverlay] = useState(false);
  const [launchedFromDeal, setLaunchedFromDeal] = useState(false);

  // Meter
  const [gauge, setGauge] = useState<{ value: number; band: Band; pulse?: { delta: number; id: number } }>(
    { value: 100, band: "green" },
  );
  // Boardroom
  const [speaking, setSpeaking] = useState<RingiPersona | null>(null);
  const [lines, setLines] = useState<Partial<Record<RingiPersona, string>>>({});
  const [spoke, setSpoke] = useState<Set<RingiPersona>>(new Set());
  const [flow, setFlow] = useState<Flow | null>(null);
  // Side panels
  const [feed, setFeed] = useState<FeedLine[]>([]);
  const [whispers, setWhispers] = useState<Whisper[]>([]);
  const [meta, setMeta] = useState<Extract<RingiEvent, { type: "meta" }> | null>(null);
  const [intervention, setIntervention] = useState<Extract<RingiEvent, { type: "intervention" }> | null>(null);
  const [error, setError] = useState("");

  const abortRef = useRef<AbortController | null>(null);
  const speakingRef = useRef<RingiPersona | null>(null);    // current speaker (delta frames omit it)
  const prevSeatRef = useRef<RingiPersona | null>(null);    // last committee speaker (for the pulse)
  const wid = useRef(0);   // whisper id counter
  const fid = useRef(0);   // feed line id counter
  const flid = useRef(0);  // flow id counter

  const run = useCallback(async (overlay?: RingiDraft[], dealOverride?: string) => {
    const id = dealOverride ?? dealId;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    // Reset the stage for a fresh debate.
    setError("");
    setRunState("streaming");
    setSpeaking(null);
    setLines({});
    setSpoke(new Set());
    setFlow(null);
    prevSeatRef.current = null;
    setFeed([]);
    setWhispers([]);
    setIntervention(null);
    setGauge({ value: 100, band: "green" }); // optimistic start; objections tick it down

    await ringiStream(id, overlay, (e: RingiEvent) => {
      switch (e.type) {
        case "meta":
          setMeta(e);
          break;
        case "speaker_start":
          speakingRef.current = e.persona;
          setSpeaking(e.persona);
          setLines((m) => ({ ...m, [e.persona]: "" }));
          setFeed((f) => [...f, { id: ++fid.current, persona: e.persona, text: "", streaming: true }]);
          // Send a pulse from the previous committee member to this one.
          if (AT_TABLE.has(e.persona)) {
            setFlow({ from: prevSeatRef.current, to: e.persona, id: ++flid.current });
            prevSeatRef.current = e.persona;
          }
          break;
        case "delta": {
          const p = speakingRef.current;
          if (p) setLines((m) => ({ ...m, [p]: (m[p] ?? "") + e.text }));
          setFeed((f) => {
            const last = f[f.length - 1];
            if (!last) return f;
            return [...f.slice(0, -1), { ...last, text: last.text + e.text }];
          });
          break;
        }
        case "speaker_end": {
          setLines((m) => ({ ...m, [e.persona]: e.text }));
          setSpoke((s) => new Set(s).add(e.persona));
          setFeed((f) => {
            const last = f[f.length - 1];
            if (!last) return f;
            return [...f.slice(0, -1), { ...last, text: e.text, streaming: false }];
          });
          if (e.whisper) {
            setWhispers((w) => [...w, {
              id: ++wid.current, text: e.whisper,
              tone: e.issue ? "risk" : "info",
              flag: e.issue ?? undefined,
            }]);
          }
          setGauge({
            value: e.approval_now,
            band: approvalBand(e.approval_now),
            pulse: e.approval_delta !== 0 ? { delta: e.approval_delta, id: wid.current + 1000 * fid.current } : undefined,
          });
          break;
        }
        case "intervention":
          setIntervention(e);
          break;
        case "done":
          setSpeaking(null);
          setFlow(null);
          setGauge({ value: e.final_approval, band: e.band });
          if (e.band === "green") {
            setWhispers((w) => [...w, {
              id: ++wid.current,
              text: ja ? "承認見込み。リスクフラグが解消され、稟議が通る水準に達しました。" : "Likely approval — the risk flags cleared and the review reached a passing level.",
              tone: "win",
            }]);
          }
          setRunState("done");
          break;
        case "error":
          setError(ja ? "接続に失敗しました。APIサーバーが起動しているか確認してください。" : "Connection failed — is the API server running?");
          setRunState("idle");
          break;
      }
    }, ac.signal);
  }, [dealId, ja]);

  const applyOverlay = useCallback((draft: RingiDraft) => {
    setHasOverlay(true);
    run([draft]);
  }, [run]);

  const resetAll = useCallback(() => {
    abortRef.current?.abort();
    setHasOverlay(false);
    setRunState("idle");
    setMeta(null);
    setIntervention(null);
    setFeed([]);
    setWhispers([]);
    setLines({});
    setSpoke(new Set());
    setFlow(null);
    prevSeatRef.current = null;
    setGauge({ value: 100, band: "green" });
  }, []);

  // Launched from a real deal (DealDrawer → ?deal=D0xx): adopt that id and run.
  const didAuto = useRef(false);
  useEffect(() => {
    if (didAuto.current) return;
    didAuto.current = true;
    const q = new URLSearchParams(window.location.search).get("deal");
    if (q && /^D\d{3,}$/.test(q)) {
      setDealId(q);
      setLaunchedFromDeal(true);
      run(undefined, q);
    }
  }, [run]);

  const streaming = runState === "streaming";
  const showSandbox = runState === "done";

  return (
    <div className="space-y-6">
      {/* Header */}
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1.5">
          <div className="eyebrow flex items-center gap-1.5 text-primary">
            <Landmark className="h-3.5 w-3.5" /> {t("nav.ringi")}
          </div>
          <h1 className="text-[26px] font-semibold leading-tight tracking-tight md:text-[28px]">
            {ja ? "稟議シミュレーション" : "Consensus Simulation"}
          </h1>
          <p className="max-w-2xl text-[14px] leading-relaxed text-muted-foreground">
            {ja
              ? "顧客の稟議(意思決定会議)がどう進むかを予行。誰が何に反対するか、承認確率、その増減はすべて健全度エンジンが決定論的に算出しています。"
              : "A rehearsal of how the customer's Ringi will unfold. Who objects, the approval odds and every swing are computed deterministically by the deal-health engine."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!launchedFromDeal && (
            <select
              value={dealId}
              onChange={(e) => { resetAll(); setDealId(e.target.value); }}
              disabled={streaming}
              className="rounded-lg border border-border bg-card px-2.5 py-2 text-[13px] disabled:opacity-50"
            >
              {DEMO_DEALS.map((d) => <option key={d.id} value={d.id}>{ja ? d.ja : d.en}</option>)}
            </select>
          )}
          {runState === "idle" ? (
            <button onClick={() => run()} disabled={streaming}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-primary/90 disabled:opacity-50">
              <Play className="h-3.5 w-3.5" /> {ja ? "シミュレーション開始" : "Run simulation"}
            </button>
          ) : (
            <button onClick={resetAll} disabled={streaming}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-4 py-2 text-[13px] font-semibold text-foreground transition-colors hover:bg-muted disabled:opacity-50">
              <RotateCcw className="h-3.5 w-3.5" /> {ja ? "リセット" : "Reset"}
            </button>
          )}
        </div>
      </header>

      {error && (
        <div className="rounded-xl border border-band-red/30 bg-band-red/5 px-4 py-3 text-[13px] text-band-red">{error}</div>
      )}

      {/* Deal context strip */}
      {meta && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl border border-border bg-card px-4 py-2.5 text-[13px]">
          <span className="font-semibold text-foreground">{meta.deal_name}</span>
          <span className="text-muted-foreground">{meta.customer}</span>
          {launchedFromDeal && (
            <span className="rounded-full bg-primary/[0.08] px-2 py-0.5 text-[11px] font-semibold text-primary">
              {ja ? "実案件から起動" : "From a live deal"}
            </span>
          )}
          {hasOverlay && (
            <span className="rounded-full bg-band-green/[0.08] px-2 py-0.5 text-[11px] font-semibold text-band-green">
              {ja ? "介入後の再判定" : "Post-intervention re-run"}
            </span>
          )}
        </div>
      )}

      {/* Main stage: gauge + ring (left), coach's read (right) */}
      <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4 rounded-2xl border border-border bg-background/40 p-5">
          <div className="flex justify-center">
            <ApprovalGauge value={gauge.value} band={gauge.band} pulse={gauge.pulse} lang={lang} />
          </div>
          <BoardroomRing speaking={speaking} lines={lines} spoke={spoke} flow={flow} lang={lang} />
        </div>
        <div className="min-h-[360px]">
          <SenpaiHud whispers={whispers} lang={lang} />
        </div>
      </div>

      {/* Live transcript */}
      <SpeechFeed lines={feed} lang={lang} />

      {/* Intervention + sandbox (after a run completes) */}
      {showSandbox && (
        <div className="grid gap-5 lg:grid-cols-2">
          {intervention && (
            <div className="rounded-2xl border border-primary/25 bg-primary/[0.03] p-4">
              <div className="mb-2 flex items-center gap-2">
                <BookOpenCheck className="h-4 w-4 text-primary" />
                <span className="text-[14px] font-semibold text-foreground">
                  {ja ? "推奨アクション(プレイブック)" : "Recommended play"}
                </span>
                {intervention.entry_id && (
                  <span className="rounded-full bg-primary/[0.1] px-2 py-0.5 font-mono text-[10px] font-semibold text-primary">
                    {intervention.entry_id}
                  </span>
                )}
              </div>
              <p className="font-jp text-[13.5px] leading-relaxed text-foreground/90">「{intervention.text}」</p>
              {intervention.tags.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {intervention.tags.map((tg) => (
                    <span key={tg} className="rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">#{tg}</span>
                  ))}
                </div>
              )}
            </div>
          )}
          <SandboxCard onApply={applyOverlay} applying={streaming} lang={lang} />
        </div>
      )}

      {/* Success banner */}
      {runState === "done" && gauge.band === "green" && hasOverlay && (
        <div className={cn("rounded-xl border border-band-green/30 bg-band-green/5 px-4 py-3 text-[13px] font-medium text-band-green")}>
          {ja
            ? "承認見込みに到達。営業規律の一手で、停滞していた稟議が通る水準まで回復しました。"
            : "Reached likely-approval — one disciplined move recovered the stalled review to a passing level."}
        </div>
      )}
    </div>
  );
}
