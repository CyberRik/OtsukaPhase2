import { cn } from "@/lib/utils";
import type { Confidence } from "@/lib/types";

const MAP: Record<Confidence, { label: string; dot: string; text: string; ring: string; why: string }> = {
  high: {
    label: "確度 高 · High",
    dot: "bg-conf-high",
    text: "text-conf-high",
    ring: "ring-conf-high/25 bg-conf-high/5",
    why: "承認済み + 2名以上のインタビューが一致",
  },
  medium: {
    label: "確度 中 · Medium",
    dot: "bg-conf-medium",
    text: "text-conf-medium",
    ring: "ring-conf-medium/25 bg-conf-medium/5",
    why: "承認済み + 1名 + アンケートで裏づけ",
  },
  low: {
    label: "確度 低 · Low",
    dot: "bg-conf-low",
    text: "text-conf-low",
    ring: "ring-conf-low/25 bg-conf-low/5",
    why: "承認済みだが出典が1名のみ",
  },
  unverified: {
    label: "未検証 · Unverified",
    dot: "bg-conf-unverified",
    text: "text-conf-unverified",
    ring: "ring-conf-unverified/25 bg-conf-unverified/5",
    why: "未承認、または根拠チェック未通過 — コーチには出ない",
  },
};

export function ConfidenceBadge({
  level,
  showWhy = false,
  className,
}: {
  level: Confidence;
  showWhy?: boolean;
  className?: string;
}) {
  const m = MAP[level];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ring-1",
        m.ring,
        m.text,
        className,
      )}
      title={m.why}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", m.dot)} />
      {m.label}
      {showWhy && <span className="font-normal text-muted-foreground">— {m.why}</span>}
    </span>
  );
}

export const CONFIDENCE_RULES = MAP;
