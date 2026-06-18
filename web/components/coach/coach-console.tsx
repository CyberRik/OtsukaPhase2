"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Eye,
  Lightbulb,
  type LucideIcon,
  MessagesSquare,
  Route,
  Scale,
  Search,
  Sparkles,
} from "lucide-react";
import { api } from "@/lib/api";
import type { CoachExample, CoachResponse, DealRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { LiveBadge } from "@/components/site/live-badge";
import { ConfidenceBadge } from "@/components/confidence-badge";
import { SourceChips } from "@/components/source-chip";

const ICONS: Record<string, LucideIcon> = {
  eye: Eye,
  search: Search,
  alert: AlertTriangle,
  message: MessagesSquare,
  route: Route,
  scale: Scale,
};

const TONES: Record<string, string> = {
  observations: "text-primary",
  missing_info: "text-conf-low",
  risks: "text-band-red",
  questions: "text-vermilion",
  next_actions: "text-conf-high",
  decision_factors: "text-band-yellow",
};

// "先輩の知見(出典 I01・I02 / 確度high): …" → a cited senior-knowledge card.
const SENIOR_RE = /^先輩の知見\(出典 (.+?) \/ 確度(.+?)\): ([\s\S]+)$/;

function SeniorTip({ raw }: { raw: string }) {
  const m = raw.match(SENIOR_RE);
  if (!m) return <span>{raw}</span>;
  const [, srcs, conf, tip] = m;
  const ids = srcs.split("・").map((s) => s.trim()).filter((s) => s && s !== "—");
  return (
    <div className="rounded-md border border-vermilion/20 bg-vermilion/[0.04] p-3">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1 text-[10px] font-medium uppercase tracking-eyebrow text-vermilion">
          <Sparkles className="h-3 w-3" /> 先輩の引き出し
        </span>
        <SourceChips ids={ids} />
        <ConfidenceBadge level={(conf.trim() as never) || "unverified"} />
      </div>
      <p className="font-jp text-[13px] leading-relaxed text-foreground/90">{tip}</p>
    </div>
  );
}

function LensCard({
  meta,
  items,
}: {
  meta: { key: string; ja: string; en: string; icon: string };
  items: string[];
}) {
  const Icon = ICONS[meta.icon] ?? Lightbulb;
  const tone = TONES[meta.key] ?? "text-primary";
  return (
    <div className="flex flex-col rounded-lg border border-border bg-card p-5 shadow-card">
      <div className="flex items-center gap-2.5">
        <span className={cn("flex h-8 w-8 items-center justify-center rounded-md bg-muted", tone)}>
          <Icon className="h-[18px] w-[18px]" />
        </span>
        <div className="leading-tight">
          <div className="text-[10px] uppercase tracking-eyebrow text-muted-foreground">{meta.en}</div>
          <div className="font-jp text-[14px] font-medium text-foreground">{meta.ja}</div>
        </div>
      </div>
      <ul className="mt-4 space-y-2.5">
        {items.length === 0 && (
          <li className="text-[13px] text-muted-foreground">— 該当なし</li>
        )}
        {items.map((it, i) =>
          it.startsWith("先輩の知見") ? (
            <li key={i}>
              <SeniorTip raw={it} />
            </li>
          ) : (
            <li key={i} className="flex gap-2.5 font-jp text-[13.5px] leading-relaxed text-foreground/90">
              <span className={cn("mt-[7px] h-1 w-1 shrink-0 rounded-full", tone, "bg-current")} />
              <span>{it}</span>
            </li>
          ),
        )}
      </ul>
    </div>
  );
}

export function CoachConsole({
  examples,
  deals,
}: {
  examples: CoachExample[];
  deals: DealRow[];
}) {
  const [note, setNote] = useState(examples[0]?.note ?? "");
  const [dealId, setDealId] = useState<string>("");
  const [resp, setResp] = useState<CoachResponse | null>(null);
  const [live, setLive] = useState(true);
  const [loading, setLoading] = useState(false);
  const [ran, setRan] = useState(false);
  const didInit = useRef(false);

  async function run(n: string, d: string) {
    setLoading(true);
    const { data, live } = await api.coach(n, d || undefined);
    setResp(data);
    setLive(live);
    setLoading(false);
    setRan(true);
  }

  // Demo state: auto-coach the first example on mount so the screen is alive.
  useEffect(() => {
    if (didInit.current) return;
    didInit.current = true;
    if (examples[0]) run(examples[0].note, "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sections = resp?.sections ?? [];

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
      {/* Input column */}
      <div className="space-y-4 lg:sticky lg:top-6 lg:self-start">
        <div className="rounded-lg border border-border bg-card p-5 shadow-card">
          <div className="mb-3 flex items-center justify-between">
            <span className="eyebrow">日報・メモ</span>
            <span className="text-[11px] text-muted-foreground">Daily report / note</span>
          </div>
          <Textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="商談メモや日報を貼り付けてください…"
            className="min-h-[150px] font-jp"
          />
          <div className="mt-3 space-y-2">
            <label className="eyebrow">関連案件 (任意) · Relate to a deal</label>
            <select
              value={dealId}
              onChange={(e) => setDealId(e.target.value)}
              className="h-10 w-full rounded-md border border-input bg-card px-3 text-[13px] shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="">（なし — テキストのみ）</option>
              {deals.map((d) => (
                <option key={d.deal_id} value={d.deal_id}>
                  {d.deal_id} · {d.customer} ({d.band})
                </option>
              ))}
            </select>
          </div>
          <Button
            variant="seal"
            className="mt-4 w-full"
            disabled={loading || !note.trim()}
            onClick={() => run(note, dealId)}
          >
            {loading ? "考え中…" : "このメモをコーチに見せる"}
          </Button>
        </div>

        <div className="rounded-lg border border-border bg-card p-5 shadow-card">
          <div className="eyebrow mb-3">例を試す · Try one</div>
          <div className="space-y-2">
            {examples.map((ex) => (
              <button
                key={ex.title}
                onClick={() => {
                  setNote(ex.note);
                  setDealId("");
                  run(ex.note, "");
                }}
                className={cn(
                  "w-full rounded-md border px-3 py-2.5 text-left transition-colors",
                  note === ex.note ? "border-vermilion/40 bg-vermilion/[0.04]" : "border-border hover:bg-muted",
                )}
              >
                <div className="text-[13px] font-medium text-foreground">{ex.title}</div>
                <div className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{ex.hint}</div>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Output column */}
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed border-vermilion/30 bg-vermilion/[0.03] px-4 py-3">
          <p className="font-jp text-[13px] leading-relaxed text-foreground/80">
            <span className="font-medium text-vermilion">考え方の型</span>です。
            {resp?.teach_note ?? "正解を一つ示すものではありません。状況に応じて自分で選んでください。"}
          </p>
          {ran && <LiveBadge live={live} />}
        </div>

        {loading && !resp ? (
          <div className="grid gap-4 md:grid-cols-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-40" />
            ))}
          </div>
        ) : resp ? (
          <div className="grid animate-fade-up gap-4 md:grid-cols-2">
            {sections.map((meta) => (
              <LensCard key={meta.key} meta={meta} items={resp.result[meta.key] ?? []} />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
