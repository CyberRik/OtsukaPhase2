// Shared display metadata for the Ringi boardroom personas. The backend only
// emits a persona key ("kacho" | "bucho" | "shacho" | "senpai"); everything
// visual (emoji, titles, seat colour, table position) is defined here so the
// theater looks consistent across the ring, the feed and the HUD.
import type { RingiPersona } from "@/lib/types";

export interface PersonaMeta {
  key: RingiPersona;
  emoji: string;
  nameJa: string;
  nameEn: string;
  roleJa: string;
  roleEn: string;
  // Tailwind token tints — kept inside the Senpai design system.
  seat: string;   // card ring/border when idle
  glow: string;   // ring colour while speaking
  chip: string;   // small role chip
}

export const PERSONAS: Record<RingiPersona, PersonaMeta> = {
  shacho: {
    key: "shacho", emoji: "👑",
    nameJa: "社長", nameEn: "Shacho",
    roleJa: "最終決裁者", roleEn: "CEO · Final approver",
    seat: "border-navy/20", glow: "ring-navy/50",
    chip: "bg-navy/[0.07] text-navy",
  },
  bucho: {
    key: "bucho", emoji: "💼",
    nameJa: "部長", nameEn: "Bucho",
    roleJa: "経済的決裁者", roleEn: "Dept. Manager · Economic buyer",
    seat: "border-primary/20", glow: "ring-primary/50",
    chip: "bg-primary/[0.08] text-primary",
  },
  kacho: {
    key: "kacho", emoji: "⚙️",
    nameJa: "課長", nameEn: "Kacho",
    roleJa: "技術チャンピオン", roleEn: "Section Manager · Tech champion",
    seat: "border-band-green/25", glow: "ring-band-green/50",
    chip: "bg-band-green/[0.08] text-band-green",
  },
  senpai: {
    key: "senpai", emoji: "🪽",
    nameJa: "先輩", nameEn: "Senpai",
    roleJa: "ガーディアン・エンジェル", roleEn: "Guardian angel coach",
    seat: "border-band-yellow/25", glow: "ring-band-yellow/50",
    chip: "bg-band-yellow/[0.10] text-band-yellow",
  },
};

export function personaName(key: RingiPersona, lang: string): string {
  const p = PERSONAS[key];
  return lang === "ja" ? p.nameJa : p.nameEn;
}

export function personaRole(key: RingiPersona, lang: string): string {
  const p = PERSONAS[key];
  return lang === "ja" ? p.roleJa : p.roleEn;
}
