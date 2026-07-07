"use client";

import { useCallback, useRef, useState } from "react";
import { BookOpenCheck, Landmark, Play, RotateCcw } from "lucide-react";
import { ringiStream } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { Band, RingiDraft, RingiEvent, RingiPersona } from "@/lib/types";
import { ApprovalGauge } from "@/components/training/approval-gauge";
import { BoardroomRing } from "@/components/training/boardroom-ring";
import { SenpaiHud, type Whisper } from "@/components/training/senpai-hud";
import { SpeechFeed, type FeedLine } from "@/components/training/speech-feed";
import { SandboxCard } from "@/components/training/sandbox-card";

// Curated at-risk demo deals. D005 crashes to red then recovers to green after
// the sandbox intervention — the show-stopper. (Names fill in from `meta`.)
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

type RunState = "idle" | "streaming" | "done";

export default function RingiTheaterPage() {
  const { t, lang } = useT();
  const ja = lang === "ja";

  const [dealId, setDealId] = useState("D005");
  const [runState, setRunState] = useState<RunState>("idle");
  const [hasOverlay, setHasOverlay] = useState(false);

  // Meter
  const [gauge, setGauge] = useState<{ value: number; band: Band; pulse?: { delta: number; id: number } }>(
    { value: 100, band: "green" },
  );
  // Boardroom
  const [speaking, setSpeaking] = useState<RingiPersona | null>(null);
  const [lines, setLines] = useState<Partial<Record<RingiPersona, string>>>({});
  const [spoke, setSpoke] = useState<Set<RingiPersona>>(new Set());
  // Side panels
  const [feed, setFeed] = useState<FeedLine[]>([]);
  const [whispers, setWhispers] = useState<Whisper[]>([]);
  const [meta, setMeta] = useState<Extract<RingiEvent, { type: "meta" }> | null>(null);
  const [intervention, setIntervention] = useState<Extract<RingiEvent, { type: "intervention" }> | null>(null);
  const [error, setError] = useState("");

  const abortRef = useRef<AbortController | null>(null);
  const speakingRef = useRef<RingiPersona | null>(null); // current speaker (delta frames omit it)
  const wid = useRef(0);   // whisper id counter
  const fid = useRef(0);   // feed line id counter

  const run = useCallback(async (overlay?: RingiDraft[]) => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    // Reset the stage for a fresh debate.
    setError("");
    setRunState("streaming");
    setSpeaking(null);
    setLines({});
    setSpoke(new Set());
    setFeed([]);
    setWhispers([]);
    setIntervention(null);
    setGauge({ value: 100, band: "green" }); // optimistic start; objections tick it down

    await ringiStream(dealId, overlay, (e: RingiEvent) => {
      switch (e.type) {
        case "meta":
          setMeta(e);
          break;
        case "speaker_start":
          speakingRef.current = e.persona;
          setSpeaking(e.persona);
          setLines((m) => ({ ...m, [e.persona]: "" }));
          setFeed((f) => [...f, { id: ++fid.current, persona: e.persona, text: "", streaming: true }]);
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
          setGauge({ value: e.final_approval, band: e.band });
          if (e.band === "green") {
            setWhispers((w) => [...w, {
              id: ++wid.current,
              text: ja ? "承認されました!リスクフラグが解消され、稟議が通りました。" : "Approved! The risk flags cleared and the Ringi passed.",
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
    setGauge({ value: 100, band: "green" });
  }, []);

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
            {ja ? "稟議攻略トレーニング・シアター" : "Consensus Training Theater"}
          </h1>
          <p className="max-w-2xl text-[14px] leading-relaxed text-muted-foreground">
            {ja
              ? "顧客の非公開の稟議(意思決定会議)を再現。数字も反対意見も、健全度エンジンが決定論的に算出しています。"
              : "A replay of the customer's closed-door Ringi. Every number and objection is computed deterministically by the deal-health engine."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={dealId}
            onChange={(e) => { resetAll(); setDealId(e.target.value); }}
            disabled={streaming}
            className="rounded-lg border border-border bg-card px-2.5 py-2 text-[13px] disabled:opacity-50"
          >
            {DEMO_DEALS.map((d) => <option key={d.id} value={d.id}>{ja ? d.ja : d.en}</option>)}
          </select>
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
          {hasOverlay && (
            <span className="rounded-full bg-band-green/[0.08] px-2 py-0.5 text-[11px] font-semibold text-band-green">
              {ja ? "介入後の再監査" : "Post-intervention re-run"}
            </span>
          )}
        </div>
      )}

      {/* Main stage: gauge + ring (left), Senpai HUD (right) */}
      <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4 rounded-2xl border border-border bg-background/40 p-5">
          <div className="flex justify-center">
            <ApprovalGauge value={gauge.value} band={gauge.band} pulse={gauge.pulse} lang={lang} />
          </div>
          <BoardroomRing speaking={speaking} lines={lines} spoke={spoke} lang={lang} />
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
            <div className="rounded-2xl border border-band-green/25 bg-band-green/[0.04] p-4">
              <div className="mb-2 flex items-center gap-2">
                <BookOpenCheck className="h-4 w-4 text-band-green" />
                <span className="text-[14px] font-bold text-foreground">
                  {ja ? "プレイブック介入カード" : "Playbook Intervention"}
                </span>
                {intervention.entry_id && (
                  <span className="rounded-full bg-band-green/[0.1] px-2 py-0.5 font-mono text-[10px] font-semibold text-band-green">
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
            ? "🎉 見事です。営業規律の一手で、閉ざされた稟議が承認に変わりました。"
            : "🎉 Brilliant — one disciplined move turned the closed-door Ringi into an approval."}
        </div>
      )}
    </div>
  );
}
