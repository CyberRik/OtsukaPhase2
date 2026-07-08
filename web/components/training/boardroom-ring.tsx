"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import type { RingiPersona } from "@/lib/types";
import { PersonaCard } from "./persona-card";

type Lines = Partial<Record<RingiPersona, string>>;

/** A hand-off between two committee seats, used to draw the traveling pulse. */
export interface Flow {
  from: RingiPersona | null;
  to: RingiPersona;
  id: number;
}

// SVG anchor points (viewBox 0 0 720 420) roughly centred on each seat card.
// Only the three committee members sit at the table; the coach has no seat.
const ANCHOR: Partial<Record<RingiPersona, { x: number; y: number }>> = {
  shacho: { x: 360, y: 74 },
  kacho: { x: 108, y: 348 },
  bucho: { x: 612, y: 348 },
};

const EDGES: [RingiPersona, RingiPersona][] = [
  ["shacho", "kacho"],
  ["shacho", "bucho"],
  ["kacho", "bucho"],
];

/**
 * The customer's closed-door consensus (稟議) committee. Three seats in a
 * triangle — Shacho (top), Kacho (bottom-left), Bucho (bottom-right) — over a
 * light guide ring (no skeuomorphic table). When the floor passes from one
 * member to another, a pulse travels along the connecting edge, so the room
 * reads as members actually addressing each other. Collapses to a stack on
 * narrow screens.
 */
export function BoardroomRing({
  speaking, lines, spoke, flow, lang,
}: {
  speaking: RingiPersona | null;
  lines: Lines;
  spoke: Set<RingiPersona>;
  flow: Flow | null;
  lang: string;
}) {
  // Transient traveling pulse — mirrors the gauge's delta-chip lifetime idiom.
  const [beam, setBeam] = useState<Flow | null>(null);
  useEffect(() => {
    if (!flow || !flow.from || flow.from === flow.to) return;
    if (!ANCHOR[flow.from] || !ANCHOR[flow.to]) return; // skip coach turns
    setBeam(flow);
    const timer = setTimeout(() => setBeam(null), 1100);
    return () => clearTimeout(timer);
  }, [flow?.id]);

  const seat = (p: RingiPersona) => (
    <PersonaCard
      persona={p}
      speaking={speaking === p}
      done={spoke.has(p)}
      line={lines[p] ?? ""}
      lang={lang}
    />
  );

  const a = beam?.from ? ANCHOR[beam.from] : undefined;
  const b = beam ? ANCHOR[beam.to] : undefined;

  return (
    <div className="relative">
      {/* Desktop: triangle around a light guide ring */}
      <div className="relative mx-auto hidden h-[420px] w-full max-w-[720px] md:block">
        {/* SVG guide ring + connecting edges + traveling pulse */}
        <svg viewBox="0 0 720 420" className="absolute inset-0 h-full w-full" aria-hidden>
          <ellipse
            cx="360" cy="216" rx="215" ry="96"
            fill="none" stroke="hsl(var(--border))" strokeWidth="1.5"
            strokeDasharray="4 6" opacity="0.7"
          />
          {EDGES.map(([p, q]) => {
            const pa = ANCHOR[p]!, qa = ANCHOR[q]!;
            const live = beam && ((beam.from === p && beam.to === q) || (beam.from === q && beam.to === p));
            return (
              <line
                key={`${p}-${q}`}
                x1={pa.x} y1={pa.y} x2={qa.x} y2={qa.y}
                stroke={live ? "hsl(var(--primary))" : "hsl(var(--border))"}
                strokeWidth={live ? 2 : 1}
                strokeOpacity={live ? 0.5 : 0.35}
                style={{ transition: "stroke 0.3s ease, stroke-opacity 0.3s ease" }}
              />
            );
          })}
          {a && b && (
            <circle key={beam!.id} r="6" fill="hsl(var(--primary))">
              <animateMotion dur="0.95s" repeatCount="1" path={`M${a.x},${a.y} L${b.x},${b.y}`} />
              <animate attributeName="opacity" values="0;1;1;0" dur="0.95s" repeatCount="1" fill="freeze" />
            </circle>
          )}
        </svg>

        <div className="absolute left-1/2 top-0 z-10 -translate-x-1/2">{seat("shacho")}</div>
        <div className="absolute bottom-0 left-0 z-10">{seat("kacho")}</div>
        <div className="absolute bottom-0 right-0 z-10">{seat("bucho")}</div>
      </div>

      {/* Mobile: stacked */}
      <div className="flex flex-col items-center gap-3 md:hidden">
        <div className={cn("flex items-center justify-center")}>{seat("shacho")}</div>
        <div className="flex flex-wrap justify-center gap-3">
          {seat("kacho")}
          {seat("bucho")}
        </div>
      </div>
    </div>
  );
}
