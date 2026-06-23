import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatYen(n: number): string {
  return "¥" + new Intl.NumberFormat("ja-JP").format(Math.round(n));
}

export function compactYen(n: number): string {
  if (n >= 1_000_000) return `¥${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `¥${(n / 1_000).toFixed(0)}K`;
  return `¥${n}`;
}
