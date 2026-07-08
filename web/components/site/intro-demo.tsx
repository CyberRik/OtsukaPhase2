"use client";

import { useEffect, useRef, useState } from "react";
import {
  motion,
  useMotionValueEvent,
  useReducedMotion,
  useScroll,
  useTransform,
  type MotionValue,
} from "framer-motion";
import { ArrowRight, ChevronDown } from "lucide-react";
import { useT } from "@/lib/i18n";

/**
 * First-visit scroll intro — a dark cinematic sequence, deliberately unlike
 * the product UI. A single particle field (canvas) morphs through three
 * formations as you scroll — the 大塚 kanji → a drifting constellation → the
 * word 先輩 — then warps into light-streaks while the void dissolves into
 * the real landing page underneath. All scrubbed off scroll position.
 */
export function IntroDemo({ onDone }: { onDone: () => void }) {
  const { t } = useT();
  const reduced = useReducedMotion();
  const containerRef = useRef<HTMLDivElement>(null);
  const [leaving, setLeaving] = useState(false);

  const { scrollYProgress: p } = useScroll({ container: containerRef });

  // Reduced-motion users skip the intro entirely.
  useEffect(() => {
    if (reduced) onDone();
  }, [reduced, onDone]);

  // Lock the page behind the overlay while it is up.
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  // Scrolling all the way through completes the intro.
  useMotionValueEvent(p, "change", (v) => {
    if (v >= 0.995) setLeaving(true);
  });

  // Final reveal: the DOM layer blasts past the camera while the dark void
  // and the particle canvas dissolve, exposing the light landing page.
  const stageScale = useTransform(p, [0.84, 1], [1, 7]);
  const stageOpacity = useTransform(p, [0.9, 1], [1, 0]);
  const voidOpacity = useTransform(p, [0.86, 1], [1, 0]);
  const canvasOpacity = useTransform(p, [0.9, 1], [1, 0]);
  const hintOpacity = useTransform(p, [0, 0.05], [1, 0]);

  if (reduced) return null;

  return (
    <motion.div
      ref={containerRef}
      className={`fixed inset-0 z-50 overflow-y-auto overflow-x-hidden overscroll-contain ${
        leaving ? "pointer-events-none" : ""
      }`}
      initial={{ opacity: 0 }}
      animate={{ opacity: leaving ? 0 : 1 }}
      transition={{ duration: leaving ? 0.7 : 0.5, ease: "easeInOut" }}
      onAnimationComplete={() => leaving && onDone()}
      aria-label="intro"
    >
      <div className="relative h-[520vh]">
        {/* The void — near-black navy with a faint indigo core. */}
        <motion.div
          className="fixed inset-0"
          style={{
            opacity: voidOpacity,
            background:
              "radial-gradient(80% 70% at 50% 45%, hsl(235 60% 14%) 0%, hsl(228 45% 7%) 55%, hsl(225 40% 4%) 100%)",
          }}
        />

        <motion.div className="fixed inset-0" style={{ opacity: canvasOpacity }}>
          <ParticleField p={p} />
        </motion.div>

        <div className="sticky top-0 h-[100dvh] overflow-hidden">
          <motion.div className="relative h-full w-full" style={{ scale: stageScale, opacity: stageOpacity }}>
            {/* Act I — the kanji burns in the void. */}
            <Headline p={p} range={[0.03, 0.07, 0.15, 0.2]} depth={1.4} position="low">
              {t("landing.intro.h1")}
            </Headline>

            {/* Act II — the constellation. */}
            <Headline p={p} range={[0.3, 0.36, 0.44, 0.5]} depth={1.8}>
              {t("landing.intro.h2")}
            </Headline>

            {/* Act III — 先輩 re-forms. */}
            <Headline p={p} range={[0.6, 0.66, 0.72, 0.78]} depth={1.6} position="low" glow>
              {t("landing.intro.h3")}
            </Headline>

            {/* Act IV — the send-off, riding the warp. */}
            <SceneEnter p={p} title={t("landing.intro.s4.title")} cta={t("landing.intro.s4.cta")} onEnter={() => setLeaving(true)} />
          </motion.div>

          <button
            onClick={() => setLeaving(true)}
            className="fixed right-5 top-5 rounded-full border border-white/15 bg-white/5 px-3.5 py-1.5 text-[12px] font-medium text-white/60 backdrop-blur transition-colors hover:text-white"
          >
            {t("landing.intro.skip")}
          </button>

          <motion.div
            className="fixed inset-x-0 bottom-6 flex flex-col items-center gap-1 text-white/50"
            style={{ opacity: hintOpacity }}
          >
            <span className="text-[11px] font-medium uppercase tracking-[0.16em]">{t("landing.intro.scroll")}</span>
            <motion.span animate={{ y: [0, 6, 0] }} transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}>
              <ChevronDown className="h-4 w-4" />
            </motion.span>
          </motion.div>
        </div>
      </div>
    </motion.div>
  );
}

/* ------------------------------------------------------------------------ */
/* Kinetic headline: arrives from deep in the frame, holds, flies past.      */
/* `depth` controls how hard it zooms; `range` = [in-start, hold, hold-end,  */
/* out-end] in scroll progress.                                              */
/* ------------------------------------------------------------------------ */
function Headline({
  p,
  range,
  depth,
  position = "center",
  glow = false,
  children,
}: {
  p: MotionValue<number>;
  range: [number, number, number, number];
  depth: number;
  position?: "center" | "low";
  glow?: boolean;
  children: React.ReactNode;
}) {
  const [a, b, c, d] = range;
  const opacity = useTransform(p, [a, b, c, d], [0, 1, 1, 0]);
  const scale = useTransform(p, [a, c, d], [0.55, 1, depth]);
  const y = useTransform(p, [a, d], [70, -70]);
  const blur = useTransform(p, [a, b, c, d], [8, 0, 0, 6]);
  const filter = useTransform(blur, (v) => `blur(${v}px)`);

  return (
    <motion.div
      className={`absolute inset-0 flex flex-col items-center px-6 text-center ${
        position === "low" ? "justify-end pb-[16dvh]" : "justify-center"
      }`}
      style={{ opacity }}
    >
      <motion.h2
        className={`max-w-3xl text-balance text-[30px] font-semibold leading-[1.15] tracking-tight text-white md:text-[52px] ${
          glow ? "[text-shadow:0_0_60px_hsl(235_84%_65%/0.55)]" : "[text-shadow:0_0_40px_rgba(0,0,0,0.6)]"
        }`}
        style={{ scale, y, filter }}
      >
        {children}
      </motion.h2>
    </motion.div>
  );
}

/* ------------------------------------------------------------------------ */
/* Act IV — CTA riding the warp streaks.                                     */
/* ------------------------------------------------------------------------ */
function SceneEnter({
  p,
  title,
  cta,
  onEnter,
}: {
  p: MotionValue<number>;
  title: string;
  cta: string;
  onEnter: () => void;
}) {
  const opacity = useTransform(p, [0.8, 0.87], [0, 1]);
  const scale = useTransform(p, [0.8, 0.9], [0.5, 1]);

  return (
    <motion.div
      className="absolute inset-0 flex flex-col items-center justify-center px-6 text-center"
      style={{ opacity, scale }}
    >
      <h2 className="text-balance text-[34px] font-semibold leading-tight tracking-tight text-white [text-shadow:0_0_80px_hsl(235_84%_65%/0.7)] md:text-[52px]">
        {title}
      </h2>
      <button
        onClick={onEnter}
        className="mt-9 inline-flex items-center gap-2 rounded-full bg-white px-7 py-3.5 text-[15px] font-semibold text-[hsl(228,45%,10%)] shadow-[0_0_50px_hsl(235_84%_65%/0.45)] transition-transform hover:scale-[1.04]"
      >
        {cta}
        <ArrowRight className="h-4 w-4" />
      </button>
    </motion.div>
  );
}

/* ------------------------------------------------------------------------ */
/* The particle field. One system, four states driven by scroll progress:    */
/*   form 大塚 → disperse into constellation → re-form as 先輩 → warp.       */
/* Each particle has a depth factor (z) so camera zoom and warp move the     */
/* planes at different speeds — the parallax is real, not faked per-layer.   */
/* ------------------------------------------------------------------------ */
const COUNT = 2200;
const HUBS = 90;

type Particle = {
  x: number;
  y: number;
  ax: number;
  ay: number; // formation A: 大塚
  bx: number;
  by: number; // formation B: constellation
  cx2: number;
  cy2: number; // formation C: 先輩
  z: number; // depth 0.35..1.8
  size: number;
  tw: number; // twinkle phase
};

function smooth(v: number, lo: number, hi: number) {
  const t = Math.min(1, Math.max(0, (v - lo) / (hi - lo)));
  return t * t * (3 - 2 * t);
}

function ParticleField({ p }: { p: MotionValue<number> }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf = 0;
    let W = 0;
    let H = 0;
    let pts: Particle[] = [];
    let edges: [number, number][] = [];
    let disposed = false;
    // Cursor repulsion field (works for touch via pointer events too).
    const mouse = { x: -9999, y: -9999, active: false };
    const onPointer = (e: PointerEvent) => {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
      mouse.active = true;
    };
    const onPointerOut = () => {
      mouse.active = false;
    };

    const sampleText = (text: string, fontScale: number) => {
      const off = document.createElement("canvas");
      off.width = W;
      off.height = H;
      const o = off.getContext("2d");
      if (!o) return [] as { x: number; y: number }[];
      o.fillStyle = "#fff";
      o.font = `900 ${Math.min(W, H) * fontScale}px "Noto Sans JP", "Inter", sans-serif`;
      o.textAlign = "center";
      o.textBaseline = "middle";
      o.fillText(text, W / 2, H / 2);
      const data = o.getImageData(0, 0, W, H).data;
      const out: { x: number; y: number }[] = [];
      const step = 3;
      for (let y = 0; y < H; y += step)
        for (let x = 0; x < W; x += step) if (data[(y * W + x) * 4 + 3] > 128) out.push({ x, y });
      return out;
    };

    const init = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = window.innerWidth;
      H = window.innerHeight;
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      canvas.style.width = `${W}px`;
      canvas.style.height = `${H}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const kanji = sampleText("大塚", W > 640 ? 0.42 : 0.34);
      const word = sampleText("先輩", W > 640 ? 0.42 : 0.34);
      const cxm = W / 2;
      const cym = H / 2;

      pts = Array.from({ length: COUNT }, (_, i) => {
        // Constellation: a loose galaxy spiral around the center.
        const ang = Math.random() * Math.PI * 2;
        const rad = Math.pow(Math.random(), 0.55) * Math.min(W, H) * 0.55;
        const arm = ang + rad * 0.006;
        const a = kanji.length ? kanji[i % kanji.length] : { x: cxm, y: cym };
        const c = word.length ? word[i % word.length] : { x: cxm, y: cym };
        const jit = () => (Math.random() - 0.5) * 3;
        return {
          x: cxm + (Math.random() - 0.5) * W,
          y: cym + (Math.random() - 0.5) * H,
          ax: a.x + jit(),
          ay: a.y + jit(),
          bx: cxm + Math.cos(arm) * rad,
          by: cym + Math.sin(arm) * rad * 0.72,
          cx2: c.x + jit(),
          cy2: c.y + jit(),
          z: 0.35 + Math.random() * 1.45,
          size: 0.6 + Math.random() * 1.6,
          tw: Math.random() * Math.PI * 2,
        };
      });

      // Precompute constellation edges among a hub subset (kept O(hubs²) once).
      edges = [];
      const maxD = Math.min(W, H) * 0.16;
      for (let i = 0; i < HUBS; i++) {
        for (let j = i + 1; j < HUBS; j++) {
          const A = pts[i * 20];
          const B = pts[j * 20];
          if (!A || !B) continue;
          const d = Math.hypot(A.bx - B.bx, A.by - B.by);
          if (d < maxD) edges.push([i * 20, j * 20]);
          if (edges.length > 170) break;
        }
        if (edges.length > 170) break;
      }
    };

    const frame = (now: number) => {
      if (disposed) return;
      const t = p.get();
      const cxm = W / 2;
      const cym = H / 2;

      // Formation blends.
      const m1 = smooth(t, 0.17, 0.3); // kanji -> constellation
      const m2 = smooth(t, 0.5, 0.62); // constellation -> 先輩
      const warp = smooth(t, 0.78, 0.97); // -> hyperspace
      const scatterIn = smooth(t, 0, 0.05); // initial gather from chaos
      // Slow push-in per act; warp handles the final blast.
      const zoom = 1 + m1 * 0.12 + m2 * 0.1;
      // Heartbeat on the kanji: a sharpened sine so it reads as a beat, not a
      // wobble. Fades out as the formation disperses (1 - m1).
      const beat = Math.pow(0.5 + 0.5 * Math.sin(now * 0.0016), 3) * (1 - m1);
      const pulse = 1 + beat * 0.035;

      ctx.clearRect(0, 0, W, H);
      ctx.globalCompositeOperation = "lighter";

      // Constellation edges, only alive mid-sequence.
      const edgeAlpha = m1 * (1 - m2) * 0.22;
      if (edgeAlpha > 0.01) {
        ctx.strokeStyle = `hsla(235, 84%, 72%, ${edgeAlpha})`;
        ctx.lineWidth = 0.6;
        ctx.beginPath();
        for (const [i, j] of edges) {
          const A = pts[i];
          const B = pts[j];
          ctx.moveTo(A.x, A.y);
          ctx.lineTo(B.x, B.y);
        }
        ctx.stroke();
      }

      for (const pt of pts) {
        // Where this particle wants to be right now.
        let tx = pt.ax + (pt.bx - pt.ax) * m1 + (pt.cx2 - (pt.ax + (pt.bx - pt.ax) * m1)) * m2;
        let ty = pt.ay + (pt.by - pt.ay) * m1 + (pt.cy2 - (pt.ay + (pt.by - pt.ay) * m1)) * m2;

        // Depth-aware camera zoom around the center, breathing with the beat.
        const zf = (1 + (zoom - 1) * pt.z) * (1 + (pulse - 1) * pt.z);
        tx = cxm + (tx - cxm) * zf;
        ty = cym + (ty - cym) * zf;

        // Ambient drift so formations feel alive.
        tx += Math.sin(now * 0.0007 + pt.tw) * 2.2 * pt.z;
        ty += Math.cos(now * 0.0009 + pt.tw * 1.3) * 2.2 * pt.z;

        // Ease toward target (snappier while gathering).
        const ease = 0.055 + scatterIn * 0.03;
        pt.x += (tx - pt.x) * ease;
        pt.y += (ty - pt.y) * ease;

        // Cursor scatter: particles flee the pointer, nearer planes harder.
        // The formation pull above heals the hole as the cursor moves on.
        if (mouse.active && warp < 0.4) {
          const mdx = pt.x - mouse.x;
          const mdy = pt.y - mouse.y;
          const md = Math.hypot(mdx, mdy);
          const R = 130;
          if (md < R && md > 0.01) {
            const f = Math.pow(1 - md / R, 1.6) * 11 * pt.z;
            pt.x += (mdx / md) * f;
            pt.y += (mdy / md) * f;
          }
        }

        const twinkle = 0.55 + 0.45 * Math.sin(now * 0.002 + pt.tw);
        const alpha = Math.min(1, (0.25 + 0.55 * twinkle) * (0.5 + pt.z * 0.4) * (1 + beat * 0.6));

        if (warp > 0.02) {
          // Hyperspace: radial streaks, longer for nearer (higher z) particles.
          const dx = pt.x - cxm;
          const dy = pt.y - cym;
          const r = Math.hypot(dx, dy) || 1;
          const stretch = warp * warp * (30 + 160 * pt.z);
          const ox = (dx / r) * stretch;
          const oy = (dy / r) * stretch;
          pt.x += (dx / r) * warp * 14 * pt.z;
          pt.y += (dy / r) * warp * 14 * pt.z;
          ctx.strokeStyle = `hsla(${228 + pt.z * 8}, 90%, ${70 + warp * 20}%, ${Math.min(1, alpha + warp * 0.4)})`;
          ctx.lineWidth = pt.size * (0.7 + warp);
          ctx.beginPath();
          ctx.moveTo(pt.x - ox, pt.y - oy);
          ctx.lineTo(pt.x + ox * 0.2, pt.y + oy * 0.2);
          ctx.stroke();
        } else {
          ctx.fillStyle = `hsla(235, 84%, ${62 + twinkle * 22}%, ${alpha})`;
          ctx.beginPath();
          ctx.arc(pt.x, pt.y, pt.size * (0.7 + pt.z * 0.35), 0, Math.PI * 2);
          ctx.fill();
        }
      }

      raf = requestAnimationFrame(frame);
    };

    // Wait for fonts so the kanji sampling doesn't hit a fallback face.
    const start = () => {
      if (disposed) return;
      init();
      raf = requestAnimationFrame(frame);
    };
    if (document.fonts?.ready) document.fonts.ready.then(start);
    else start();

    const onResize = () => init();
    window.addEventListener("resize", onResize);
    window.addEventListener("pointermove", onPointer);
    window.addEventListener("pointerdown", onPointer);
    document.documentElement.addEventListener("pointerleave", onPointerOut);
    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("pointermove", onPointer);
      window.removeEventListener("pointerdown", onPointer);
      document.documentElement.removeEventListener("pointerleave", onPointerOut);
    };
  }, [p]);

  return <canvas ref={ref} className="h-full w-full" aria-hidden />;
}
