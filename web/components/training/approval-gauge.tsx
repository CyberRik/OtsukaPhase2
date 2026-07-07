"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import type { Band } from "@/lib/types";

const BAND_STROKE: Record<Band, string> = {
  red: "hsl(var(--band-red))",
  yellow: "hsl(var(--band-yellow))",
  green: "hsl(var(--band-green))",
};
const BAND_TEXT: Record<Band, string> = {
  red: "text-band-red", yellow: "text-band-yellow", green: "text-band-green",
};
const BAND_LABEL: Record<Band, { ja: string; en: string }> = {
  red: { ja: "高リスク", en: "High risk" },
  yellow: { ja: "要注意", en: "At risk" },
  green: { ja: "承認見込み", en: "Likely approve" },
};

/**
 * Radial approval meter (0–100%). The ring fills to `value`, tweened smoothly,
 * coloured by deal-health band. `pulse` shows a transient +/- delta chip that
 * pops and fades whenever a persona objects or the deal recovers.
 */
export function ApprovalGauge({
  value, band, pulse, lang,
}: {
  value: number;
  band: Band;
  pulse?: { delta: number; id: number };
  lang: string;
}) {
  const [display, setDisplay] = useState(value);
  const raf = useRef<number | null>(null);
  const from = useRef(value);

  // Tween the displayed number/arc toward the target value.
  useEffect(() => {
    const start = performance.now();
    const dur = 700;
    const a = from.current;
    const b = value;
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / dur);
      const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
      setDisplay(a + (b - a) * eased);
      if (t < 1) raf.current = requestAnimationFrame(step);
      else from.current = b;
    };
    raf.current = requestAnimationFrame(step);
    return () => { if (raf.current) cancelAnimationFrame(raf.current); };
  }, [value]);

  // Transient delta chip.
  const [chip, setChip] = useState<{ delta: number; id: number } | null>(null);
  useEffect(() => {
    if (!pulse || pulse.delta === 0) return;
    setChip(pulse);
    const timer = setTimeout(() => setChip(null), 1600);
    return () => clearTimeout(timer);
  }, [pulse?.id]);

  const R = 82;
  const C = 2 * Math.PI * R;
  const pct = Math.max(0, Math.min(100, display));
  const offset = C * (1 - pct / 100);
  const label = BAND_LABEL[band][lang === "ja" ? "ja" : "en"];

  return (
    <div className="relative flex flex-col items-center">
      <div className="relative h-[200px] w-[200px]">
        <svg viewBox="0 0 200 200" className="h-full w-full -rotate-90">
          <circle cx="100" cy="100" r={R} fill="none"
                  stroke="hsl(var(--muted))" strokeWidth="14" />
          <circle
            cx="100" cy="100" r={R} fill="none"
            stroke={BAND_STROKE[band]} strokeWidth="14" strokeLinecap="round"
            strokeDasharray={C} strokeDashoffset={offset}
            style={{ transition: "stroke 0.5s ease" }}
          />
        </svg>
        {/* Centre readout */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <div className={cn("text-[44px] font-bold leading-none tabular-nums", BAND_TEXT[band])}>
            {Math.round(pct)}<span className="text-[22px]">%</span>
          </div>
          <div className={cn("mt-1 text-[12px] font-semibold", BAND_TEXT[band])}>{label}</div>
        </div>
        {/* Delta pop */}
        {chip && (
          <div
            key={chip.id}
            className={cn(
              "animate-fade-up absolute left-1/2 top-1 -translate-x-1/2 rounded-full px-2.5 py-1 text-[13px] font-bold tabular-nums shadow-card",
              chip.delta < 0 ? "bg-band-red text-white" : "bg-band-green text-white",
            )}
          >
            {chip.delta > 0 ? "+" : ""}{chip.delta}%
          </div>
        )}
      </div>
      <div className="eyebrow mt-2 text-muted-foreground">
        {lang === "ja" ? "承認確率メーター" : "Approval Probability"}
      </div>
    </div>
  );
}
