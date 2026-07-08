"use client";

// Pipeline War Room — an animated replay of the whole pipeline, driven entirely
// by the deterministic snapshot series from /api/warroom (senpai/warroom.py).
// One time scrubber + one rep filter scope everything on the page: the bubble
// field, the stat tiles, and the rank→outcome sankey all read the same slice.
//
// Encoding notes (deliberate, see the dataviz conventions):
// - Band color is STATUS (reserved traffic-light), and is never the only
//   channel: vertical position carries the same risk score, and the zone
//   labels + table view restate it in text.
// - The sankey's left column is an ORDINAL rank ramp (one indigo hue, validated
//   monotone lightness steps), not categorical hues.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pause, Play, RotateCcw } from "lucide-react";
import { useT } from "@/lib/i18n";
import { cn, compactYen, formatYen } from "@/lib/utils";
import type { Band, WarroomData, WarroomDeal, WarroomPoint } from "@/lib/types";
import { BandDot, BandPill } from "@/components/band";
import { DealDrawer } from "@/components/dashboard/deal-drawer";

// --- geometry ---------------------------------------------------------------
const VB_W = 960, VB_H = 440;
const PL = 48, PR = 18, PT = 20, PB = 36;
const PLOT_W = VB_W - PL - PR, PLOT_H = VB_H - PT - PB;

// Ordinal rank ramp (single indigo hue, monotone lightness — validated).
// Darkest = strongest rank. Ranks outside the open band fall back to the tail.
const RANK_RAMP: Record<string, string> = {
  "2_A+": "#2d3a9e", "3_A": "#3f51c4", "4_B": "#5b6fdc", "5_C": "#8090e6", "6_P": "#a7b1ee",
};
const RANK_ORDER = ["2_A+", "3_A", "4_B", "5_C", "6_P"];
const RANK_SHORT: Record<string, string> = {
  "2_A+": "A+", "3_A": "A", "4_B": "B", "5_C": "C", "6_P": "P",
};

const BAND_FILL: Record<Band, string> = {
  red: "hsl(var(--band-red))",
  yellow: "hsl(var(--band-yellow))",
  green: "hsl(var(--band-green))",
};

interface BubblePos {
  deal: WarroomDeal;
  x: number; y: number; r: number;
  band: Band; score: number; rank: string;
  alive: boolean;      // open at the current snapshot (fades out otherwise)
}

// A pipeline move between the previous snapshot and the current one — the unit
// of the "this week" feed that narrates the replay.
type MoveType = "won" | "lost" | "danger" | "recovered" | "riskUp" | "riskDown" | "new";
const MOVE_PRIORITY: MoveType[] = ["won", "lost", "danger", "recovered", "riskUp", "riskDown", "new"];

interface Move {
  type: MoveType;
  deal: WarroomDeal;
  delta?: number; // score change, for riskUp/riskDown
}

export function WarRoom({ data, live }: { data: WarroomData; live: boolean }) {
  const { t, lang } = useT();
  const ja = lang === "ja";
  const last = Math.max(0, data.snapshots.length - 1);

  const [idx, setIdx] = useState(last);
  const [playing, setPlaying] = useState(false);
  const [rep, setRep] = useState("all");
  const [view, setView] = useState<"chart" | "table">("chart");
  const [hover, setHover] = useState<{ id: string; xPct: number; yPct: number } | null>(null);
  const [flowHover, setFlowHover] = useState<{ key: string; label: string; count: number; amount: number } | null>(null);
  const [drawerDeal, setDrawerDeal] = useState<string | null>(null);

  // Replay clock. Stops itself at the end of the timeline.
  useEffect(() => {
    if (!playing) return;
    const h = setInterval(() => {
      setIdx((i) => {
        if (i >= last) { setPlaying(false); return i; }
        return i + 1;
      });
    }, 850);
    return () => clearInterval(h);
  }, [playing, last]);

  const togglePlay = useCallback(() => {
    if (!playing && idx >= last) setIdx(0); // replay from the start
    setPlaying((p) => !p);
  }, [playing, idx, last]);

  const reps = useMemo(() => {
    const seen = new Map<string, string>();
    for (const d of data.deals) if (!seen.has(d.rep_id)) seen.set(d.rep_id, d.rep_name);
    return [...seen.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [data.deals]);

  const deals = useMemo(
    () => (rep === "all" ? data.deals : data.deals.filter((d) => d.rep_id === rep)),
    [data.deals, rep],
  );

  // x-scale: expected close date. Domain over deals that are ever OPEN in the
  // replay window (closed-before-window deals never render as bubbles), and
  // stable across the rep filter so bubbles don't re-scale when filtering.
  // Long-overdue outliers are floored two months before the window and their
  // bubbles clamp to the left edge — the tooltip carries the true date.
  const xDomain = useMemo(() => {
    const ms = data.deals
      .filter((d) => d.series.some((p) => p?.st === "open"))
      .map((d) => (d.expected_order_date ? Date.parse(d.expected_order_date) : NaN))
      .filter((v) => !Number.isNaN(v));
    if (!ms.length) return [0, 1] as const;
    const pad = 14 * 86400_000;
    const floor = Date.parse(data.snapshots[0] ?? "") - 60 * 86400_000;
    const lo = Math.max(Math.min(...ms), Number.isNaN(floor) ? -Infinity : floor);
    return [lo - pad, Math.max(...ms) + pad] as const;
  }, [data.deals, data.snapshots]);

  const xOf = useCallback(
    (dateStr: string) => {
      const v = Date.parse(dateStr);
      const x = PL + ((v - xDomain[0]) / (xDomain[1] - xDomain[0])) * PLOT_W;
      return Math.min(Math.max(x, PL), PL + PLOT_W);
    },
    [xDomain],
  );
  const yOf = (score: number) => PT + (1 - score / 100) * PLOT_H;

  const maxAmount = useMemo(
    () => Math.max(1, ...data.deals.map((d) => d.amount || 0)),
    [data.deals],
  );
  const rOf = (amount: number) => 5 + 17 * Math.sqrt((amount || 0) / maxAmount);

  // Bubble positions at the current snapshot. A deal is placed at its LAST open
  // point at or before `idx`, and marked dead (fading) once it closes — so won/
  // lost bubbles fade out where they last stood instead of teleporting.
  const bubbles = useMemo(() => {
    const out: BubblePos[] = [];
    for (const d of deals) {
      if (!d.expected_order_date) continue;
      let lastOpen = -1;
      for (let i = idx; i >= 0; i--) {
        const p = d.series[i];
        if (p && p.st === "open") { lastOpen = i; break; }
      }
      if (lastOpen < 0) continue;
      const p = d.series[lastOpen]!;
      out.push({
        deal: d,
        x: xOf(d.expected_order_date),
        y: yOf(p.s ?? 0),
        r: rOf(d.amount),
        band: (p.b ?? "green") as Band,
        score: p.s ?? 0,
        rank: p.r ?? d.initial_rank,
        alive: d.series[idx]?.st === "open",
      });
    }
    // Big bubbles first so small ones stay hoverable on top.
    return out.sort((a, b) => b.r - a.r);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deals, idx, xOf, maxAmount]);

  // Tallies at the current snapshot (tiles + legend + sankey share them).
  const tally = useMemo(() => {
    let open = 0, won = 0, lost = 0, danger = 0, pipeline = 0;
    const bands: Record<Band, number> = { red: 0, yellow: 0, green: 0 };
    const flows = new Map<string, { count: number; amount: number }>();
    for (const d of deals) {
      const p = d.series[idx];
      if (!p) continue;
      if (p.st === "open") {
        open += 1; pipeline += d.amount || 0;
        bands[(p.b ?? "green") as Band] += 1;
        if (p.b === "red") danger += 1;
      } else if (p.st === "won") won += 1;
      else lost += 1;
      const key = `${d.initial_rank}→${p.st}`;
      const f = flows.get(key) ?? { count: 0, amount: 0 };
      f.count += 1; f.amount += d.amount || 0;
      flows.set(key, f);
    }
    return { open, won, lost, danger, pipeline, bands, flows };
  }, [deals, idx]);

  // Same counters one snapshot back, for the week-over-week chips on the tiles.
  const prevTally = useMemo(() => {
    if (idx === 0) return null;
    let open = 0, won = 0, lost = 0, danger = 0;
    for (const d of deals) {
      const p = d.series[idx - 1];
      if (!p) continue;
      if (p.st === "open") { open += 1; if (p.b === "red") danger += 1; }
      else if (p.st === "won") won += 1;
      else lost += 1;
    }
    return { open, won, lost, danger };
  }, [deals, idx]);

  // What changed between the previous snapshot and this one. Score wobble under
  // 15 points is noise; band crossings and closes always count.
  const moves = useMemo(() => {
    if (idx === 0) return [] as Move[];
    const out: Move[] = [];
    for (const d of deals) {
      const prev = d.series[idx - 1];
      const cur = d.series[idx];
      if (!cur) continue;
      if (!prev) {
        if (cur.st === "open") out.push({ type: "new", deal: d });
        continue;
      }
      if (prev.st === "open" && cur.st === "won") out.push({ type: "won", deal: d });
      else if (prev.st === "open" && cur.st === "lost") out.push({ type: "lost", deal: d });
      else if (prev.st === "open" && cur.st === "open") {
        const delta = (cur.s ?? 0) - (prev.s ?? 0);
        if (prev.b !== "red" && cur.b === "red") out.push({ type: "danger", deal: d, delta });
        else if (prev.b === "red" && cur.b !== "red") out.push({ type: "recovered", deal: d, delta });
        else if (delta >= 15) out.push({ type: "riskUp", deal: d, delta });
        else if (delta <= -15) out.push({ type: "riskDown", deal: d, delta });
      }
    }
    return out.sort((a, b) => MOVE_PRIORITY.indexOf(a.type) - MOVE_PRIORITY.indexOf(b.type));
  }, [deals, idx]);

  // Month ticks across the x domain; quarterly when the domain is wide. The
  // first tick and every January carry the year so months are unambiguous.
  const ticks = useMemo(() => {
    const months: Date[] = [];
    const d = new Date(xDomain[0]);
    d.setDate(1); d.setMonth(d.getMonth() + 1);
    while (d.getTime() < xDomain[1]) { months.push(new Date(d)); d.setMonth(d.getMonth() + 1); }
    const kept = months.length > 14 ? months.filter((m) => m.getMonth() % 3 === 0) : months;
    return kept.map((m, i) => {
      const withYear = i === 0 || m.getMonth() === 0;
      const label = ja
        ? withYear ? `${m.getFullYear()}年${m.getMonth() + 1}月` : `${m.getMonth() + 1}月`
        : m.toLocaleString("en", { month: "short", ...(withYear ? { year: "2-digit" } : {}) });
      return { x: PL + ((m.getTime() - xDomain[0]) / (xDomain[1] - xDomain[0])) * PLOT_W, label };
    });
  }, [xDomain, ja]);

  const snapDate = data.snapshots[idx] ?? "";
  const snapMs = Date.parse(snapDate);
  const markerX = snapMs >= xDomain[0] && snapMs <= xDomain[1]
    ? PL + ((snapMs - xDomain[0]) / (xDomain[1] - xDomain[0])) * PLOT_W
    : null;

  const { yellow, red } = data.thresholds;
  const hovered = hover ? bubbles.find((b) => b.deal.deal_id === hover.id) : null;

  if (!data.deals.length) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-muted/30 px-5 py-8 text-center text-[13px] text-muted-foreground">
        {live ? t("warroom.offline") : t("warroom.offline")}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Controls: play + scrubber + date, then the filters that scope the page */}
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={togglePlay}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-primary px-3.5 text-[13px] font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
        >
          {playing
            ? <><Pause className="h-3.5 w-3.5" /> {t("warroom.pause")}</>
            : idx >= last
              ? <><RotateCcw className="h-3.5 w-3.5" /> {t("warroom.replay")}</>
              : <><Play className="h-3.5 w-3.5" /> {t("warroom.play")}</>}
        </button>
        <input
          type="range"
          min={0}
          max={last}
          value={idx}
          onChange={(e) => { setPlaying(false); setIdx(Number(e.target.value)); }}
          className="h-1.5 min-w-[180px] flex-1 cursor-pointer accent-[hsl(var(--primary))]"
          aria-label={t("warroom.asOfMarker")}
        />
        <span className="w-[92px] font-mono text-[13px] tabular-nums text-foreground">{snapDate}</span>
        <select
          value={rep}
          onChange={(e) => setRep(e.target.value)}
          className="h-9 rounded-lg border border-border bg-card px-2.5 text-[13px]"
        >
          <option value="all">{t("warroom.allReps")}</option>
          {reps.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
        <div className="flex overflow-hidden rounded-lg border border-border">
          {(["chart", "table"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={cn(
                "px-3 py-1.5 text-[12px] font-medium transition-colors",
                view === v ? "bg-navy text-navy-foreground" : "bg-card text-muted-foreground hover:text-foreground",
              )}
            >
              {t(v === "chart" ? "warroom.viewChart" : "warroom.viewTable")}
            </button>
          ))}
        </div>
      </div>

      {/* Stat tiles at the selected date */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {([
          { label: t("warroom.open"), value: tally.open, sub: compactYen(tally.pipeline), prev: prevTally?.open },
          { label: t("warroom.won"), value: tally.won, dot: "green" as Band, prev: prevTally?.won },
          { label: t("warroom.lost"), value: tally.lost, dot: "red" as Band, prev: prevTally?.lost },
          { label: t("warroom.danger"), value: tally.danger, dot: "red" as Band, prev: prevTally?.danger, alarm: true },
        ]).map((s, i) => {
          const delta = s.prev === undefined ? 0 : s.value - s.prev;
          return (
            <div key={i} className="card-surface px-4 py-3">
              <div className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
                {s.dot && <BandDot band={s.dot} className="h-2 w-2" />}
                {s.label}
              </div>
              <div className="mt-0.5 flex items-baseline text-[24px] font-semibold leading-tight">
                {s.value}
                {s.sub && <span className="ml-2 text-[13px] font-normal text-muted-foreground">{s.sub}</span>}
                {delta !== 0 && (
                  <span
                    className={cn(
                      "ml-auto font-mono text-[12px] font-medium tabular-nums",
                      s.alarm && delta > 0 ? "text-[hsl(var(--band-red))]" : "text-muted-foreground",
                    )}
                    title={t("warroom.vsPrev")}
                  >
                    {delta > 0 ? `+${delta}` : delta} <span className="font-sans font-normal text-muted-foreground">{t("warroom.vsPrev")}</span>
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {view === "chart" ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_264px]">
        <div className="card-surface relative p-4">
          <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="w-full">
            {/* Band zones — the y-axis meaning, tinted just enough to read */}
            <rect x={PL} y={PT} width={PLOT_W} height={yOf(red) - PT} fill="hsl(var(--band-red) / 0.045)" />
            <rect x={PL} y={yOf(red)} width={PLOT_W} height={yOf(yellow) - yOf(red)} fill="hsl(var(--band-yellow) / 0.05)" />
            <rect x={PL} y={yOf(yellow)} width={PLOT_W} height={yOf(0) - yOf(yellow)} fill="hsl(var(--band-green) / 0.04)" />

            {/* hairline grid at the thresholds + frame baseline */}
            {[0, yellow, red, 100].map((s) => (
              <g key={s}>
                <line x1={PL} x2={VB_W - PR} y1={yOf(s)} y2={yOf(s)} stroke="hsl(var(--border))" strokeWidth={1} />
                <text x={PL - 8} y={yOf(s) + 4} textAnchor="end" className="fill-[hsl(var(--muted-foreground))] text-[11px] tabular-nums">{s}</text>
              </g>
            ))}
            {/* zone labels, right edge */}
            {([
              { s: (red + 100) / 2, key: "warroom.zoneDanger", band: "red" as Band },
              { s: (yellow + red) / 2, key: "warroom.zoneWatch", band: "yellow" as Band },
              { s: yellow / 2, key: "warroom.zoneSafe", band: "green" as Band },
            ]).map((z) => (
              <g key={z.key}>
                <circle cx={VB_W - PR - 66} cy={yOf(z.s) - 4} r={3} fill={BAND_FILL[z.band]} />
                <text x={VB_W - PR - 58} y={yOf(z.s)} className="fill-[hsl(var(--muted-foreground))] text-[11px]">{t(z.key)}</text>
              </g>
            ))}

            {/* month ticks */}
            {ticks.map((tk) => (
              <g key={tk.x}>
                <line x1={tk.x} x2={tk.x} y1={yOf(0)} y2={yOf(0) + 4} stroke="hsl(var(--border))" strokeWidth={1} />
                <text x={tk.x} y={VB_H - 12} textAnchor="middle" className="fill-[hsl(var(--muted-foreground))] text-[11px]">{tk.label}</text>
              </g>
            ))}
            {/* as-of marker: bubbles left of this line are past their close date */}
            {markerX !== null && (
              <g>
                <line x1={markerX} x2={markerX} y1={PT - 4} y2={yOf(0)} stroke="hsl(var(--foreground) / 0.3)" strokeWidth={1} />
                <text
                  x={markerX + (markerX > PL + PLOT_W * 0.75 ? -5 : 5)}
                  y={PT + 6}
                  textAnchor={markerX > PL + PLOT_W * 0.75 ? "end" : "start"}
                  className="fill-[hsl(var(--foreground))] text-[10.5px] font-medium"
                >
                  {t("warroom.asOfMarker")} {snapDate}
                </text>
              </g>
            )}

            {/* bubbles */}
            {bubbles.map((b) => (
              <g
                key={b.deal.deal_id}
                style={{
                  transform: `translate(${b.x}px, ${b.y}px)`,
                  transition: "transform 700ms cubic-bezier(0.4,0,0.2,1), opacity 600ms ease",
                  opacity: b.alive ? 1 : 0,
                  pointerEvents: b.alive ? "auto" : "none",
                }}
              >
                <circle
                  r={b.r}
                  fill={BAND_FILL[b.band]}
                  fillOpacity={0.85}
                  stroke="hsl(var(--card))"
                  strokeWidth={2}
                  style={{ transition: "fill 500ms ease, r 500ms ease" }}
                  pointerEvents="none"
                />
                {/* oversized transparent hit target */}
                <circle
                  r={Math.max(b.r + 8, 16)}
                  fill="transparent"
                  className="cursor-pointer"
                  onPointerEnter={() => setHover({ id: b.deal.deal_id, xPct: (b.x / VB_W) * 100, yPct: (b.y / VB_H) * 100 })}
                  onPointerLeave={() => setHover(null)}
                  onClick={() => setDrawerDeal(b.deal.deal_id)}
                />
              </g>
            ))}
          </svg>

          {/* tooltip */}
          {hovered && hover && (
            <div
              className="pointer-events-none absolute z-10 w-max max-w-[260px] rounded-lg border border-border bg-card px-3 py-2 shadow-lg"
              style={{ left: `${hover.xPct}%`, top: `${hover.yPct}%`, transform: "translate(-50%, calc(-100% - 14px))" }}
            >
              <div className="text-[12.5px] font-semibold leading-snug">{hovered.deal.deal_name}</div>
              <div className="text-[11.5px] text-muted-foreground">{hovered.deal.customer} · {hovered.deal.rep_name}</div>
              <div className="mt-1.5 flex items-center gap-2 text-[12px]">
                <BandPill band={hovered.band} score={hovered.score} />
                <span className="font-mono text-[11px] text-muted-foreground">{hovered.rank}</span>
              </div>
              <div className="mt-1 text-[12px] font-medium tabular-nums">{formatYen(hovered.deal.amount)}</div>
              <Sparkline series={hovered.deal.series} idx={idx} last={last} red={red} band={hovered.band} label={t("warroom.trend")} />
            </div>
          )}

          {/* legend: status counts at t + how to read the encoding */}
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border pt-3 text-[12px] text-muted-foreground">
            {(["green", "yellow", "red"] as Band[]).map((b) => (
              <span key={b} className="inline-flex items-center gap-1.5">
                <BandDot band={b} className="h-2 w-2" />
                {t(b === "green" ? "warroom.zoneSafe" : b === "yellow" ? "warroom.zoneWatch" : "warroom.zoneDanger")}
                <span className="font-mono tabular-nums">{tally.bands[b]}</span>
              </span>
            ))}
            <span className="ml-auto">{t("warroom.legendNote")}{markerX !== null ? ` · ${t("warroom.overdueNote")}` : ""}</span>
          </div>
        </div>
        <MovesFeed moves={moves} atStart={idx === 0} onOpen={setDrawerDeal} />
        </div>
      ) : (
        <WarRoomTable bubbles={bubbles.filter((b) => b.alive).sort((a, b) => b.score - a.score)} onOpen={setDrawerDeal} />
      )}

      {/* Sankey: initial rank → status at the selected date */}
      <div className="card-surface relative p-4">
        <div className="mb-1 text-[14px] font-semibold">{t("warroom.sankeyTitle")}</div>
        <p className="mb-3 text-[12px] text-muted-foreground">{t("warroom.sankeySub")}</p>
        <RankFlow
          flows={tally.flows}
          onHover={setFlowHover}
          labels={{ won: t("warroom.won"), open: t("warroom.stillOpen"), lost: t("warroom.lost") }}
        />
        {flowHover && (
          <div className="pointer-events-none absolute bottom-4 right-4 rounded-lg border border-border bg-card px-3 py-2 text-[12px] shadow-md">
            <span className="font-semibold">{flowHover.label}</span>
            <span className="ml-2 font-mono tabular-nums">{flowHover.count}{ja ? t("warroom.count") : ` ${t("warroom.count")}`}</span>
            <span className="ml-2 text-muted-foreground">{compactYen(flowHover.amount)}</span>
          </div>
        )}
      </div>

      <DealDrawer dealId={drawerDeal} open={drawerDeal !== null} onOpenChange={(o) => !o && setDrawerDeal(null)} />
    </div>
  );
}

// --- this-week feed: narrates the diff between snapshot t-1 and t ------------
const MOVE_META: Record<MoveType, { band?: Band; labelKey: string }> = {
  won: { band: "green", labelKey: "warroom.won" },
  lost: { band: "red", labelKey: "warroom.lost" },
  danger: { band: "red", labelKey: "warroom.evDanger" },
  recovered: { band: "green", labelKey: "warroom.evRecovered" },
  riskUp: { band: "yellow", labelKey: "warroom.score" },
  riskDown: { band: "yellow", labelKey: "warroom.score" },
  new: { labelKey: "warroom.evNew" },
};

function MovesFeed({ moves, atStart, onOpen }: { moves: Move[]; atStart: boolean; onOpen: (id: string) => void }) {
  const { t } = useT();
  return (
    <div className="card-surface flex flex-col p-4">
      <div className="text-[13px] font-semibold">{t("warroom.thisWeek")}</div>
      {atStart || !moves.length ? (
        <div className="mt-2 rounded-md border border-dashed border-border px-3 py-4 text-center text-[12px] text-muted-foreground">
          {t(atStart ? "warroom.firstWeek" : "warroom.noMoves")}
        </div>
      ) : (
        <div className="mt-1.5 -mx-2 max-h-[400px] flex-1 overflow-y-auto">
          {moves.map((m) => {
            const meta = MOVE_META[m.type];
            const isScoreMove = m.type === "riskUp" || m.type === "riskDown";
            const delta = m.delta !== undefined && m.delta !== 0
              ? ` ${m.delta > 0 ? "+" : ""}${Math.round(m.delta)}`
              : "";
            return (
              <button
                key={`${m.type}:${m.deal.deal_id}`}
                onClick={() => onOpen(m.deal.deal_id)}
                className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted/60"
              >
                {meta.band
                  ? <BandDot band={meta.band} className="mt-[5px] h-2 w-2 shrink-0" />
                  : <span className="mt-[5px] h-2 w-2 shrink-0 rounded-full bg-muted-foreground/40" />}
                <span className="min-w-0">
                  <span className="block truncate text-[12.5px] font-medium leading-snug">{m.deal.deal_name}</span>
                  <span className="text-[11.5px] text-muted-foreground">
                    {t(meta.labelKey)}
                    {isScoreMove ? <span className="font-mono tabular-nums">{delta}</span> : delta && <span className="font-mono tabular-nums"> ({t("warroom.score")}{delta})</span>}
                    <span className="mx-1">·</span>{m.deal.rep_name}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// --- tooltip sparkline: the deal's real score series up to the scrubber ------
function Sparkline({
  series, idx, last, red, band, label,
}: {
  series: (WarroomPoint | null)[]; idx: number; last: number; red: number; band: Band; label: string;
}) {
  const W = 210, H = 36, P = 4;
  const pts: { x: number; y: number }[] = [];
  for (let i = 0; i <= idx; i++) {
    const p = series[i];
    if (p?.st === "open") {
      pts.push({ x: P + (i / Math.max(1, last)) * (W - 2 * P), y: P + (1 - (p.s ?? 0) / 100) * (H - 2 * P) });
    }
  }
  if (pts.length < 2) return null;
  const end = pts[pts.length - 1];
  const yRed = P + (1 - red / 100) * (H - 2 * P);
  return (
    <div className="mt-1.5 border-t border-border pt-1.5">
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={label}>
        <line x1={P} x2={W - P} y1={yRed} y2={yRed} stroke="hsl(var(--band-red) / 0.4)" strokeWidth={1} strokeDasharray="3 3" />
        <polyline
          points={pts.map((p) => `${p.x},${p.y}`).join(" ")}
          fill="none"
          stroke="hsl(var(--muted-foreground))"
          strokeWidth={1.5}
          strokeLinejoin="round"
        />
        <circle cx={end.x} cy={end.y} r={3} fill={BAND_FILL[band]} />
      </svg>
      <div className="text-[10.5px] text-muted-foreground">{label}</div>
    </div>
  );
}

// --- table view (the accessibility mirror of the bubble field) ---------------
function WarRoomTable({ bubbles, onOpen }: { bubbles: BubblePos[]; onOpen: (id: string) => void }) {
  const { t } = useT();
  return (
    <div className="card-surface overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted-foreground">
            <th className="px-4 py-2.5 font-semibold">{t("warroom.deal")}</th>
            <th className="px-3 py-2.5 font-semibold">{t("warroom.customer")}</th>
            <th className="px-3 py-2.5 font-semibold">{t("warroom.rep")}</th>
            <th className="px-3 py-2.5 font-semibold">{t("warroom.rank")}</th>
            <th className="px-3 py-2.5 font-semibold">{t("warroom.score")}</th>
            <th className="px-3 py-2.5 text-right font-semibold">{t("warroom.amount")}</th>
          </tr>
        </thead>
        <tbody>
          {bubbles.map((b) => (
            <tr
              key={b.deal.deal_id}
              onClick={() => onOpen(b.deal.deal_id)}
              className="cursor-pointer border-b border-border/60 last:border-0 hover:bg-muted/50"
            >
              <td className="px-4 py-2 font-medium">{b.deal.deal_name}</td>
              <td className="px-3 py-2 text-muted-foreground">{b.deal.customer}</td>
              <td className="px-3 py-2 text-muted-foreground">{b.deal.rep_name}</td>
              <td className="px-3 py-2 font-mono text-[12px]">{b.rank}</td>
              <td className="px-3 py-2"><BandPill band={b.band} score={b.score} /></td>
              <td className="px-3 py-2 text-right font-mono tabular-nums">{formatYen(b.deal.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// --- two-column sankey: initial rank (ordinal ramp) → outcome at t ----------
const FLOW_W = 760, FLOW_H = 280, FLOW_PL = 96, FLOW_PR = 116, NODE_W = 12, NODE_GAP = 8, FLOW_PT = 8;

function RankFlow({
  flows, labels, onHover,
}: {
  flows: Map<string, { count: number; amount: number }>;
  labels: { won: string; open: string; lost: string };
  onHover: (h: { key: string; label: string; count: number; amount: number } | null) => void;
}) {
  const [hoverKey, setHoverKey] = useState<string | null>(null);

  const model = useMemo(() => {
    const leftTotals = new Map<string, number>();
    const rightTotals = new Map<string, number>();
    for (const [key, f] of flows) {
      const [rank, st] = key.split("→");
      leftTotals.set(rank, (leftTotals.get(rank) ?? 0) + f.count);
      rightTotals.set(st, (rightTotals.get(st) ?? 0) + f.count);
    }
    const leftOrder = [
      ...RANK_ORDER.filter((r) => leftTotals.has(r)),
      ...[...leftTotals.keys()].filter((r) => !RANK_ORDER.includes(r)).sort(),
    ];
    const rightOrder = (["won", "open", "lost"] as const).filter((s) => rightTotals.has(s));
    const total = [...leftTotals.values()].reduce((a, b) => a + b, 0);
    if (!total) return null;

    const usable = FLOW_H - 2 * FLOW_PT;
    const scale = (usable - NODE_GAP * Math.max(0, leftOrder.length - 1)) / total;
    const scaleR = (usable - NODE_GAP * Math.max(0, rightOrder.length - 1)) / total;

    // Node y-extents.
    const leftNodes = new Map<string, { y0: number; y1: number }>();
    let y = FLOW_PT;
    for (const r of leftOrder) {
      const h = Math.max(3, leftTotals.get(r)! * scale);
      leftNodes.set(r, { y0: y, y1: y + h });
      y += h + NODE_GAP;
    }
    const rightNodes = new Map<string, { y0: number; y1: number }>();
    y = FLOW_PT;
    for (const s of rightOrder) {
      const h = Math.max(3, rightTotals.get(s)! * scaleR);
      rightNodes.set(s, { y0: y, y1: y + h });
      y += h + NODE_GAP;
    }

    // Ribbons, stacked within each node in a stable order.
    const leftOff = new Map(leftOrder.map((r) => [r, leftNodes.get(r)!.y0]));
    const rightOff = new Map(rightOrder.map((s) => [s, rightNodes.get(s)!.y0]));
    const ribbons: { key: string; rank: string; st: string; sy0: number; sy1: number; ty0: number; ty1: number; count: number; amount: number }[] = [];
    for (const r of leftOrder) {
      for (const s of rightOrder) {
        const f = flows.get(`${r}→${s}`);
        if (!f) continue;
        const hL = f.count * scale, hR = f.count * scaleR;
        const sy0 = leftOff.get(r)!, ty0 = rightOff.get(s)!;
        ribbons.push({ key: `${r}→${s}`, rank: r, st: s, sy0, sy1: sy0 + hL, ty0, ty1: ty0 + hR, count: f.count, amount: f.amount });
        leftOff.set(r, sy0 + hL);
        rightOff.set(s, ty0 + hR);
      }
    }
    return { leftOrder, rightOrder, leftNodes, rightNodes, leftTotals, rightTotals, ribbons };
  }, [flows]);

  if (!model) return null;
  const x0 = FLOW_PL + NODE_W, x1 = FLOW_W - FLOW_PR - NODE_W, mx = (x0 + x1) / 2;
  const stFill: Record<string, string> = {
    won: "hsl(var(--band-green))", lost: "hsl(var(--band-red))", open: "hsl(var(--muted-foreground) / 0.55)",
  };

  return (
    <svg viewBox={`0 0 ${FLOW_W} ${FLOW_H}`} className="w-full">
      {model.ribbons.map((rb) => (
        <path
          key={rb.key}
          d={`M ${x0} ${rb.sy0} C ${mx} ${rb.sy0}, ${mx} ${rb.ty0}, ${x1} ${rb.ty0} L ${x1} ${rb.ty1} C ${mx} ${rb.ty1}, ${mx} ${rb.sy1}, ${x0} ${rb.sy1} Z`}
          fill={RANK_RAMP[rb.rank] ?? "#8090e6"}
          fillOpacity={hoverKey === null ? 0.2 : hoverKey === rb.key ? 0.42 : 0.08}
          style={{ transition: "fill-opacity 200ms ease" }}
          onPointerEnter={() => {
            setHoverKey(rb.key);
            onHover({
              key: rb.key,
              label: `${RANK_SHORT[rb.rank] ?? rb.rank} → ${labels[rb.st as keyof typeof labels]}`,
              count: rb.count,
              amount: rb.amount,
            });
          }}
          onPointerLeave={() => { setHoverKey(null); onHover(null); }}
        />
      ))}
      {model.leftOrder.map((r) => {
        const n = model.leftNodes.get(r)!;
        return (
          <g key={r}>
            <rect x={FLOW_PL} y={n.y0} width={NODE_W} height={n.y1 - n.y0} rx={2} fill={RANK_RAMP[r] ?? "#8090e6"} />
            <text x={FLOW_PL - 8} y={(n.y0 + n.y1) / 2 + 4} textAnchor="end" className="fill-[hsl(var(--foreground))] text-[12px] font-medium">
              {RANK_SHORT[r] ?? r}
              <tspan className="fill-[hsl(var(--muted-foreground))] text-[11px]"> {model.leftTotals.get(r)}</tspan>
            </text>
          </g>
        );
      })}
      {model.rightOrder.map((s) => {
        const n = model.rightNodes.get(s)!;
        return (
          <g key={s}>
            <rect x={FLOW_W - FLOW_PR - NODE_W} y={n.y0} width={NODE_W} height={n.y1 - n.y0} rx={2} fill={stFill[s]} />
            <text x={FLOW_W - FLOW_PR + 8} y={(n.y0 + n.y1) / 2 + 4} className="fill-[hsl(var(--foreground))] text-[12px] font-medium">
              {labels[s]}
              <tspan className="fill-[hsl(var(--muted-foreground))] text-[11px]"> {model.rightTotals.get(s)}</tspan>
            </text>
          </g>
        );
      })}
    </svg>
  );
}
