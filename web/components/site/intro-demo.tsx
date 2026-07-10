"use client";

import { useEffect, useRef, useState } from "react";
import {
  animate,
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
 * the product UI. One particle field morphs through three formations as you
 * scroll — 大塚商会 → a living knowledge graph → 先輩 — with a feature act of
 * stat shards flying past the camera in between, then warps into light
 * streaks as the void dissolves into the real landing page underneath.
 * Everything is scrubbed off scroll position. Headlines are bilingual
 * lockups: the active language leads, the other echoes underneath.
 */

// Act boundaries, in scroll progress (0–1).
const GATHER_END = 0.05; // particles fly in and form 大塚商会
const M1_START = 0.48; // 大塚商会 → constellation
const M1_END = 0.53;
const M2_START = 0.855; // constellation → 先輩
const M2_END = 0.9;
const WARP_START = 0.94;

export function IntroDemo({ onDone }: { onDone: () => void }) {
  const { t } = useT();
  const reduced = useReducedMotion();
  const containerRef = useRef<HTMLDivElement>(null);
  const [leaving, setLeaving] = useState(false);

  const { scrollYProgress: p } = useScroll({ container: containerRef });
  const animRef = useRef<any>(null);

  // Stop custom scroll animation on manual user scroll intervention
  const handleUserInteraction = () => {
    if (animRef.current) {
      animRef.current.stop();
      animRef.current = null;
    }
  };

  const handleContainerClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest("button")) return;

    const container = containerRef.current;
    if (!container) return;

    const currentScroll = container.scrollTop;
    const maxScroll = container.scrollHeight - container.clientHeight;
    if (maxScroll <= 0) return;

    const currentP = currentScroll / maxScroll;
    
    const snapPoints = [0, 0.055, 0.13, 0.205, 0.28, 0.355, 0.43, 0.535, 0.63, 0.71, 0.79, 0.855, 0.9, 0.95];
    const nextPoint = snapPoints.find((val) => val > currentP + 0.01);
    
    if (nextPoint !== undefined) {
      const targetScroll = nextPoint * maxScroll;
      if (animRef.current) animRef.current.stop();
      
      animRef.current = animate(container.scrollTop, targetScroll, {
        duration: 1.8,
        ease: "easeInOut",
        onUpdate: (v) => {
          container.scrollTop = v;
        }
      });
    }
  };

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
  // 3x is enough to sell the blast; higher magnifications force the browser
  // to re-rasterize huge text layers mid-warp and drop frames.
  const stageScale = useTransform(p, [WARP_START, 1], [1, 1.3]);
  const stageOpacity = useTransform(p, [0.955, 0.99], [1, 0]);
  const voidOpacity = useTransform(p, [0.955, 1], [1, 0]);
  const canvasOpacity = useTransform(p, [0.965, 1], [1, 0]);
  const hintOpacity = useTransform(p, [0, 0.02, 0.08], [0, 1, 0]);

  if (reduced) return null;

  return (
    <motion.div
      ref={containerRef}
      className={`fixed inset-0 z-50 overflow-y-auto overflow-x-hidden overscroll-contain snap-y snap-proximity ${leaving ? "pointer-events-none" : ""
        }`}
      initial={{ opacity: 0 }}
      animate={{ opacity: leaving ? 0 : 1 }}
      transition={{ duration: leaving ? 0.7 : 0.5, ease: "easeInOut" }}
      onAnimationComplete={() => leaving && onDone()}
      aria-label="intro"
      onClick={handleContainerClick}
      onWheel={handleUserInteraction}
      onTouchStart={handleUserInteraction}
    >
      <div className="relative h-[2600vh]">
        {/* Native CSS Scroll Snapping Keyframe Targets (mapped exactly using scrollHeight - clientHeight) */}
        {/* Act I — six problem beats over 大塚商会 */}
        <div className="absolute h-px w-full snap-start pointer-events-none" style={{ top: "0vh" }} />
        <div className="absolute h-px w-full snap-start pointer-events-none" style={{ top: "143vh" }} />
        <div className="absolute h-px w-full snap-start pointer-events-none" style={{ top: "338vh" }} />
        <div className="absolute h-px w-full snap-start pointer-events-none" style={{ top: "533vh" }} />
        <div className="absolute h-px w-full snap-start pointer-events-none" style={{ top: "728vh" }} />
        <div className="absolute h-px w-full snap-start pointer-events-none" style={{ top: "923vh" }} />
        <div className="absolute h-px w-full snap-start pointer-events-none" style={{ top: "1118vh" }} />
        {/* Act II — knowledge graph */}
        <div className="absolute h-px w-full snap-start pointer-events-none" style={{ top: "1391vh" }} />
        {/* Act III — feature shards */}
        <div className="absolute h-px w-full snap-start pointer-events-none" style={{ top: "1638vh" }} />
        <div className="absolute h-px w-full snap-start pointer-events-none" style={{ top: "1846vh" }} />
        <div className="absolute h-px w-full snap-start pointer-events-none" style={{ top: "2054vh" }} />
        {/* Finale / Senpai Re-form */}
        <div className="absolute h-px w-full snap-start pointer-events-none" style={{ top: "2223vh" }} />
        <div className="absolute h-px w-full snap-start pointer-events-none" style={{ top: "2340vh" }} />
        <div className="absolute h-px w-full snap-start pointer-events-none" style={{ top: "2470vh" }} />
        {/* The void — near-black navy with a faint indigo core. */}
        <motion.div
          className="fixed inset-0"
          style={{
            opacity: voidOpacity,
            background:
              "radial-gradient(80% 70% at 50% 45%, hsl(235 55% 13%) 0%, hsl(228 45% 7%) 55%, hsl(225 40% 4%) 100%)",
          }}
        />

        <motion.div className="fixed inset-0" style={{ opacity: canvasOpacity }}>
          <ParticleField p={p} />
        </motion.div>

        <div className="sticky top-0 h-[100dvh] overflow-hidden">
          <motion.div 
            className="relative h-full w-full" 
            style={{ scale: stageScale, opacity: stageOpacity, willChange: "transform, opacity" }}
          >
            {/* Act I — the problem, in six beats over 大塚商会 burning in the void. */}
            <DualHeadline p={p} range={[0.02, 0.055, 0.09, 0.115]} position="low" main={t("landing.intro.a1.h1")} sub={t("landing.intro.a1.h1.sub")} />
            <DualHeadline p={p} range={[0.095, 0.13, 0.165, 0.19]} position="low" main={t("landing.intro.a1.h2")} sub={t("landing.intro.a1.h2.sub")} />
            <DualHeadline p={p} range={[0.17, 0.205, 0.24, 0.265]} position="low" main={t("landing.intro.a1.h3")} sub={t("landing.intro.a1.h3.sub")} />
            <DualHeadline p={p} range={[0.245, 0.28, 0.315, 0.34]} position="low" main={t("landing.intro.a1.h4")} sub={t("landing.intro.a1.h4.sub")} />
            <DualHeadline p={p} range={[0.32, 0.355, 0.39, 0.415]} position="low" main={t("landing.intro.a1.h5")} sub={t("landing.intro.a1.h5.sub")} />
            <DualHeadline p={p} range={[0.395, 0.43, 0.46, 0.485]} position="low" main={t("landing.intro.a1.h6")} sub={t("landing.intro.a1.h6.sub")} />

            {/* Act II — the living knowledge graph. */}
            <DualHeadline p={p} range={[0.535, 0.565, 0.595, 0.62]} main={t("landing.intro.a2.h1")} sub={t("landing.intro.a2.h1.sub")} />
            <DualHeadline p={p} range={[0.6, 0.63, 0.655, 0.68]} main={t("landing.intro.a2.h2")} sub={t("landing.intro.a2.h2.sub")} />

            {/* Act III — feature shards fly past the camera, alternating sides:
                tools → guardrails → ringi → deterministic checks → doc gen →
                war room → bilingual. */}
            <FeatureShard p={p} range={[0.655, 0.673, 0.693, 0.711]} side="left" big={t("landing.intro.f1.big")} label={t("landing.intro.f1.label")} sub={t("landing.intro.f1.sub")} />
            <FeatureShard p={p} range={[0.679, 0.697, 0.717, 0.735]} side="right" big={t("landing.intro.f6.big")} label={t("landing.intro.f6.label")} sub={t("landing.intro.f6.sub")} />
            <FeatureShard p={p} range={[0.703, 0.721, 0.741, 0.759]} side="left" big={t("landing.intro.f2.big")} label={t("landing.intro.f2.label")} sub={t("landing.intro.f2.sub")} />
            <FeatureShard p={p} range={[0.727, 0.745, 0.765, 0.783]} side="right" big={t("landing.intro.f3.big")} label={t("landing.intro.f3.label")} sub={t("landing.intro.f3.sub")} />
            <FeatureShard p={p} range={[0.751, 0.769, 0.789, 0.807]} side="left" big={t("landing.intro.f4.big")} label={t("landing.intro.f4.label")} sub={t("landing.intro.f4.sub")} />
            <FeatureShard p={p} range={[0.775, 0.793, 0.813, 0.831]} side="right" big={t("landing.intro.f7.big")} label={t("landing.intro.f7.label")} sub={t("landing.intro.f7.sub")} />
            <FeatureShard p={p} range={[0.799, 0.817, 0.837, 0.855]} side="center" big={t("landing.intro.f5.big")} label={t("landing.intro.f5.label")} sub={t("landing.intro.f5.sub")} />

            {/* Act IV — 先輩 re-forms; the money line rides into the warp. */}
            <DualHeadline p={p} range={[0.865, 0.895, 0.915, 0.935]} position="low" glow main={t("landing.intro.a4.h1")} sub={t("landing.intro.a4.h1.sub")} />
            <EnterScene
              p={p}
              main={t("landing.intro.a4.h2")}
              sub={t("landing.intro.a4.h2.sub")}
              cta={t("landing.intro.s4.cta")}
              onEnter={() => setLeaving(true)}
            />
          </motion.div>

          <div className="fixed right-5 top-5 z-20 flex items-center gap-2">
            <button
              onClick={() => setLeaving(true)}
              className="rounded-full border border-white/15 bg-white/5 px-3.5 py-1.5 text-[12px] font-medium text-white/60 backdrop-blur transition-colors hover:text-white"
            >
              {t("landing.intro.skip")}
            </button>
          </div>

          <motion.div
            className="fixed inset-x-0 bottom-6 z-20 flex flex-col items-center gap-1 text-white/50"
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
/* Bilingual kinetic headline: the active language leads, the other echoes   */
/* beneath. Arrives blurred from deep in the frame, holds, flies past.       */
/* `range` = [in-start, hold-start, hold-end, out-end].                      */
/* ------------------------------------------------------------------------ */
function DualHeadline({
  p,
  range,
  main,
  sub,
  position = "center",
  glow = false,
}: {
  p: MotionValue<number>;
  range: [number, number, number, number];
  main: string;
  sub: string;
  position?: "center" | "low";
  glow?: boolean;
}) {
  const [a, b, c, d] = range;
  const opacity = useTransform(p, [a, b, c, d], [0, 1, 1, 0]);
  const scale = useTransform(p, [a, c, d], [0.6, 1, 1.6]);
  const y = useTransform(p, [a, d], [60, -60]);
  const blur = useTransform(p, [a, b, c, d], [8, 0, 0, 6]);
  const filter = useTransform(blur, (v) => `blur(${v}px)`);
  // Unmount from the compositor when invisible — blurred text layers are
  // expensive even at opacity 0.
  const display = useTransform(opacity, (v) => (v < 0.02 ? "none" : "flex"));

  return (
    <motion.div
      className={`absolute inset-0 flex flex-col items-center px-6 text-center ${position === "low" ? "justify-end pb-[14dvh]" : "justify-center"
        }`}
      style={{ opacity, display }}
    >
      <motion.div style={{ scale, y, filter }}>
        <h2
          className={`max-w-3xl text-balance text-[28px] font-semibold leading-[1.2] tracking-tight text-white md:text-[48px] ${glow ? "[text-shadow:0_0_60px_hsl(235_84%_65%/0.55)]" : "[text-shadow:0_0_40px_rgba(0,0,0,0.6)]"
            }`}
        >
          {main}
        </h2>
        <div className="mt-5 flex flex-col items-center gap-3">
          <span className="h-px w-10 bg-[hsl(235_84%_70%/0.55)] md:w-14" />
          <p className="max-w-[44ch] text-balance font-plex text-[15px] font-medium leading-snug text-white/75 [text-shadow:0_0_24px_rgba(0,0,0,0.75)] md:text-[19px]">
            {sub}
          </p>
        </div>
      </motion.div>
    </motion.div>
  );
}

/* ------------------------------------------------------------------------ */
/* Act III — a feature shard: a glassy stat card that flies in from one side */
/* and past the camera, riding the constellation backdrop.                   */
/* ------------------------------------------------------------------------ */
function FeatureShard({
  p,
  range,
  side,
  big,
  label,
  sub,
}: {
  p: MotionValue<number>;
  range: [number, number, number, number];
  side: "left" | "right" | "center";
  big: string;
  label: string;
  sub: string;
}) {
  const [a, b, c, d] = range;
  const opacity = useTransform(p, [a, b, c, d], [0, 1, 1, 0]);
  const scale = useTransform(p, [a, c, d], [0.45, 1, 2]);
  const x = useTransform(p, [a, d], side === "left" ? ["-26vw", "-10vw"] : side === "right" ? ["26vw", "10vw"] : ["0vw", "0vw"]);
  const y = useTransform(p, [a, d], [40, -40]);
  const blur = useTransform(p, [a, b, c, d], [10, 0, 0, 8]);
  const filter = useTransform(blur, (v) => `blur(${v}px)`);
  const display = useTransform(opacity, (v) => (v < 0.02 ? "none" : "flex"));

  return (
    <motion.div className="absolute inset-0 flex items-center justify-center px-6" style={{ opacity, display }}>
      <motion.div
        className="max-w-[320px] rounded-2xl border border-white/12 bg-white/[0.05] px-7 py-6 text-center shadow-[0_0_60px_hsl(235_84%_60%/0.18)] backdrop-blur-sm md:max-w-[380px]"
        style={{ scale, x, y, filter }}
      >
        <div className="text-[40px] font-bold leading-none tracking-tight text-white [text-shadow:0_0_40px_hsl(235_84%_65%/0.6)] md:text-[52px]">
          {big}
        </div>
        <div className="mt-2.5 text-[15px] font-semibold text-white/85 md:text-[17px]">{label}</div>
        <div className="mt-2 font-plex text-[13px] leading-relaxed text-white/65 md:text-[14px]">{sub}</div>
      </motion.div>
    </motion.div>
  );
}

/* ------------------------------------------------------------------------ */
/* Act IV finale — the one-line pitch plus CTA, riding the warp streaks.     */
/* ------------------------------------------------------------------------ */
function EnterScene({
  p,
  main,
  sub,
  cta,
  onEnter,
}: {
  p: MotionValue<number>;
  main: string;
  sub: string;
  cta: string;
  onEnter: () => void;
}) {
  const opacity = useTransform(p, [0.9, 0.945], [0, 1]);
  const scale = useTransform(p, [0.9, 0.96], [0.55, 1]);
  const display = useTransform(opacity, (v) => (v < 0.02 ? "none" : "flex"));

  return (
    <motion.div
      className="absolute inset-0 flex flex-col items-center justify-center px-6 text-center bg-black/10"
      style={{ opacity, scale, display }}
    >
      <h2 className="max-w-3xl text-balance text-[30px] font-semibold leading-[1.25] tracking-tight text-white [text-shadow:0_0_24px_hsl(235_84%_65%/0.5)] md:text-[46px]">
        {main}
      </h2>
      <div className="mt-5 flex flex-col items-center gap-3">
        <span className="h-px w-10 bg-[hsl(235_84%_70%/0.55)] md:w-14" />
        <p className="max-w-[44ch] text-balance font-plex text-[15px] font-medium leading-snug text-white/75 [text-shadow:0_0_24px_rgba(0,0,0,0.75)] md:text-[19px]">
          {sub}
        </p>
      </div>
      <button
        onClick={onEnter}
        className="mt-9 inline-flex items-center gap-2 rounded-full bg-white px-7 py-3.5 text-[15px] font-semibold text-[hsl(228,45%,10%)] shadow-[0_0_25px_hsl(235_84%_65%/0.4)] transition-transform hover:scale-[1.04]"
      >
        {cta}
        <ArrowRight className="h-4 w-4" />
      </button>
    </motion.div>
  );
}



/* ------------------------------------------------------------------------ */
/* The particle field. One system, four states driven by scroll progress:    */
/*   fly in and form 大塚商会 → disperse into a knowledge-graph               */
/*   constellation → re-form as 先輩 → warp into hyperspace streaks.          */
/* Each particle has a depth factor (z) so camera zoom, cursor scatter and   */
/* warp move near/far planes at different speeds — real depth parallax.      */
/* ------------------------------------------------------------------------ */
type Particle = {
  x: number;
  y: number;
  ox: number;
  oy: number; // fly-in origin, far off-screen
  ax: number;
  ay: number; // formation A: 大塚商会
  bx: number;
  by: number; // formation B: constellation
  cx2: number;
  cy2: number; // formation C: 先輩
  z: number; // depth 0.35..1.8
  size: number;
  tw: number; // twinkle phase
  isNode: boolean; // constellation hub (brighter, carries edges)
};

function smooth(v: number, lo: number, hi: number) {
  const t = Math.min(1, Math.max(0, (v - lo) / (hi - lo)));
  return t * t * (3 - 2 * t);
}

const NODE_COUNT = 80;

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

    const sampleText = (text: string, fontSize: number, weight = 900) => {
      const off = document.createElement("canvas");
      off.width = W;
      off.height = H;
      const o = off.getContext("2d");
      if (!o) return [] as { x: number; y: number }[];
      o.fillStyle = "#fff";
      o.font = `${weight} ${fontSize}px "Noto Sans JP", "Meiryo", "MS PGothic", "Hiragino Kaku Gothic ProN", sans-serif`;
      o.textAlign = "center";
      o.textBaseline = "middle";
      o.fillText(text, W / 2, H / 2);
      const data = o.getImageData(0, 0, W, H).data;
      const out: { x: number; y: number }[] = [];
      const step = 1;
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

      const count = W > 768 ? 5400 : 2900;
      const otsuka = sampleText("大塚商会", Math.min(W / 4.4, H * 0.42));
      // Thinner weight for 先輩 — 輩's stroke count fuses into a blob at 900;
      // a lighter face keeps gaps between strokes so the dots can trace them.
      const senpai = sampleText("先輩", Math.min(W / 2.5, H * 0.45), 400);
      const cxm = W / 2;
      const cym = H / 2;

      pts = Array.from({ length: count }, (_, i) => {
        // Constellation: a loose galaxy spiral around the center.
        const ang = Math.random() * Math.PI * 2;
        const rad = Math.pow(Math.random(), 0.55) * Math.min(W, H) * 0.55;
        const arm = ang + rad * 0.006;
        // Stride evenly through the sampled points (which are in row-major
        // order) so the whole glyph is covered even when points > particles.
        const a = otsuka.length ? otsuka[Math.floor((i * otsuka.length) / count) % otsuka.length] : { x: cxm, y: cym };
        const c = senpai.length ? senpai[Math.floor((i * senpai.length) / count) % senpai.length] : { x: cxm, y: cym };
        const jit = () => (Math.random() - 0.5) * 1.1;
        const oAng = Math.random() * Math.PI * 2;
        return {
          ox: cxm + Math.cos(oAng) * W * 0.75,
          oy: cym + Math.sin(oAng) * H * 0.75,
          x: 0,
          y: 0,
          ax: a.x + jit(),
          ay: a.y + jit(),
          bx: cxm + Math.cos(arm) * rad,
          by: cym + Math.sin(arm) * rad * 0.72,
          cx2: c.x + jit(),
          cy2: c.y + jit(),
          z: 0.35 + Math.random() * 1.45,
          size: 0.6 + Math.random() * 1.6,
          tw: Math.random() * Math.PI * 2,
          isNode: i < NODE_COUNT,
        };
      });
      for (const pt of pts) {
        pt.x = pt.ox;
        pt.y = pt.oy;
      }

      // Precompute constellation edges among the hub subset (O(hubs²) once).
      edges = [];
      const maxD = Math.min(W, H) * 0.17;
      for (let i = 0; i < NODE_COUNT; i++) {
        for (let j = i + 1; j < NODE_COUNT; j++) {
          const d = Math.hypot(pts[i].bx - pts[j].bx, pts[i].by - pts[j].by);
          if (d < maxD) edges.push([i, j]);
          if (edges.length > 180) break;
        }
        if (edges.length > 180) break;
      }
    };

    const frame = (now: number) => {
      if (disposed) return;
      const t = p.get();
      
      const blurVal = t < 0.9 ? 0 : Math.min(10, ((t - 0.9) / 0.04) * 10);

      if (blurVal > 0.1) {
        canvas.style.filter = `blur(${blurVal}px)`;
        (canvas.style as any).webkitFilter = `blur(${blurVal}px)`;
      } else {
        canvas.style.filter = "none";
        (canvas.style as any).webkitFilter = "none";
      }

      const cxm = W / 2;
      const cym = H / 2;

      // Formation blends.
      const gather = smooth(t, 0, GATHER_END); // origins -> 大塚商会
      const m1 = smooth(t, M1_START, M1_END); // 大塚商会 -> constellation
      const m2 = smooth(t, M2_START, M2_END); // constellation -> 先輩
      const warp = smooth(t, WARP_START, 0.99); // -> hyperspace
      const networkAlive = m1 * (1 - m2);
      // How strongly particles are currently spelling text (A or C formation):
      // dots get bigger, brighter and steadier so the kanji reads clearly.
      const wForm = gather * (1 - m1) + m2 * (1 - warp);
      // Slow push-in per act; warp handles the final blast.
      const zoom = 1 + m1 * 0.1 + m2 * 0.08;
      // Heartbeat on 大塚商会 (fades with m1); 先輩 gets a glow surge instead.
      const beat = Math.pow(0.5 + 0.5 * Math.sin(now * 0.0016), 3) * (1 - m1);
      const pulse = 1 + beat * 0.035;
      const senpaiGlow = smooth(t, 0.85, 0.93) * (1 - warp);

      ctx.clearRect(0, 0, W, H);
      ctx.globalCompositeOperation = "lighter";

      // Warp streaks are batched into depth buckets: one stroke() per bucket
      // instead of one per particle, which is what made the outro stutter.
      const NB = 6;
      const warpPaths = warp > 0.02 ? Array.from({ length: NB }, () => new Path2D()) : null;

      // Constellation edges, only alive mid-sequence.
      const edgeAlpha = networkAlive * 0.22;
      if (edgeAlpha > 0.01 && warp < 0.05) {
        ctx.strokeStyle = `hsla(235, 84%, 72%, ${edgeAlpha})`;
        ctx.lineWidth = 0.6;
        ctx.beginPath();
        for (const [i, j] of edges) {
          ctx.moveTo(pts[i].x, pts[i].y);
          ctx.lineTo(pts[j].x, pts[j].y);
        }
        ctx.stroke();
      }

      // Additive "lighter" blending floods overlapping strokes into blobs —
      // fine for the loose constellation, but it's what makes dense glyphs
      // like 輩 unreadable. Switch to opaque compositing while the field is
      // actually spelling text so individual dots (and the gaps between
      // strokes) stay visible.
      ctx.globalCompositeOperation = wForm > 0.5 ? "source-over" : "lighter";

      for (const pt of pts) {
        // Where this particle wants to be right now: origin -> A -> B -> C.
        const fx = pt.ox + (pt.ax - pt.ox) * gather;
        const fy = pt.oy + (pt.ay - pt.oy) * gather;
        let tx = fx + (pt.bx - fx) * m1;
        let ty = fy + (pt.by - fy) * m1;
        tx = tx + (pt.cx2 - tx) * m2;
        ty = ty + (pt.cy2 - ty) * m2;

        // Depth-aware camera zoom around the center, breathing with the beat.
        const zf = (1 + (zoom - 1) * pt.z) * (1 + (pulse - 1) * pt.z);
        tx = cxm + (tx - cxm) * zf;
        ty = cym + (ty - cym) * zf;

        // Ambient drift so formations feel alive — almost still while
        // spelling text so glyph strokes stay sharp and readable.
        const drift = 1.9 - wForm * 1.85;
        tx += Math.sin(now * 0.0007 + pt.tw) * drift * pt.z;
        ty += Math.cos(now * 0.0009 + pt.tw * 1.3) * drift * pt.z;

        // Ease toward target (snappier while gathering and re-forming, and
        // tighter still once a glyph needs to read cleanly).
        const ease = 0.055 + gather * 0.02 + m2 * 0.05 + wForm * 0.05;
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
        let alpha = Math.min(1, (0.25 + 0.55 * twinkle) * (0.5 + pt.z * 0.4) * (1 + beat * 0.6));
        if (pt.isNode) alpha = Math.min(1, alpha * (1.1 + networkAlive * 0.6));
        // Legibility floor while spelling text: no dot in a glyph goes dim.
        alpha = Math.min(1, alpha + wForm * 0.3);

        if (warpPaths) {
          // Hyperspace: radial streaks, longer for nearer (higher z) particles.
          const dx = pt.x - cxm;
          const dy = pt.y - cym;
          const r = Math.hypot(dx, dy) || 1;
          const stretch = warp * warp * (30 + 160 * pt.z);
          const sx = (dx / r) * stretch;
          const sy = (dy / r) * stretch;
          pt.x += (dx / r) * warp * 14 * pt.z;
          pt.y += (dy / r) * warp * 14 * pt.z;
          const bucket = Math.min(NB - 1, Math.floor(((pt.z - 0.35) / 1.45) * NB));
          warpPaths[bucket].moveTo(pt.x - sx, pt.y - sy);
          warpPaths[bucket].lineTo(pt.x + sx * 0.2, pt.y + sy * 0.2);
        } else {
          // Glow through brightness and opacity instead of bloating dot size.
          const finalAlpha = Math.min(1, alpha + senpaiGlow * 0.5);
          ctx.fillStyle = `hsla(235, 84%, ${62 + twinkle * 22 + senpaiGlow * 28}%, ${finalAlpha * (0.15 + 0.85 * gather)})`;
          ctx.beginPath();
          ctx.arc(pt.x, pt.y, pt.size * (0.55 + pt.z * 0.25) * (1 + wForm * 0.2), 0, Math.PI * 2);
          ctx.fill();
        }
      }

      if (warpPaths) {
        ctx.globalCompositeOperation = "lighter";
        for (let b = 0; b < NB; b++) {
          const zb = 0.35 + ((b + 0.5) / NB) * 1.45; // bucket-representative depth
          ctx.strokeStyle = `hsla(${228 + zb * 8}, 90%, ${70 + warp * 20}%, ${Math.min(1, 0.35 + zb * 0.25 + warp * 0.4)})`;
          ctx.lineWidth = (0.6 + zb * 0.9) * (0.7 + warp);
          ctx.stroke(warpPaths[b]);
        }
      }

      // Bloom flash as the warp opens into the light landing page.
      const flash = smooth(t, WARP_START + 0.02, 0.99);
      if (flash > 0.01) {
        ctx.globalCompositeOperation = "source-over";
        ctx.fillStyle = `hsla(0, 0%, 100%, ${flash * 0.5})`;
        ctx.fillRect(0, 0, W, H);
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
