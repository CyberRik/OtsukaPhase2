// Shared display metadata for the consensus (稟議) committee. The backend only
// emits a persona key ("kacho" | "bucho" | "shacho" | "senpai"); everything
// visual — kanji monogram, titles, band tint — lives here so the committee looks
// consistent across the seating, feed and coach panel. No emoji: personas are
// rendered as band-tinted monogram discs, matching the app's BandDot idiom.
import type { RingiPersona } from "@/lib/types";

export interface PersonaMeta {
  key: RingiPersona;
  mono: string;   // single-kanji monogram shown in the avatar disc
  nameJa: string;
  nameEn: string;
  roleJa: string;
  roleEn: string;
  // Tailwind token tints — kept inside the Senpai design system.
  seat: string;   // card border when idle
  glow: string;   // ring colour while speaking
  chip: string;   // small role chip
  disc: string;   // monogram avatar disc (bg + text + ring)
}

export const PERSONAS: Record<RingiPersona, PersonaMeta> = {
  shacho: {
    key: "shacho", mono: "社",
    nameJa: "社長", nameEn: "Shacho",
    roleJa: "最終決裁者", roleEn: "CEO · Final approver",
    seat: "border-navy/20", glow: "ring-navy/50",
    chip: "bg-navy/[0.07] text-navy",
    disc: "bg-navy/[0.08] text-navy ring-1 ring-navy/20",
  },
  bucho: {
    key: "bucho", mono: "部",
    nameJa: "部長", nameEn: "Bucho",
    roleJa: "経済的決裁者", roleEn: "Dept. Manager · Economic buyer",
    seat: "border-primary/20", glow: "ring-primary/50",
    chip: "bg-primary/[0.08] text-primary",
    disc: "bg-primary/[0.08] text-primary ring-1 ring-primary/20",
  },
  kacho: {
    key: "kacho", mono: "課",
    nameJa: "課長", nameEn: "Kacho",
    roleJa: "技術チャンピオン", roleEn: "Section Manager · Tech champion",
    seat: "border-band-green/25", glow: "ring-band-green/50",
    chip: "bg-band-green/[0.08] text-band-green",
    disc: "bg-band-green/[0.1] text-band-green ring-1 ring-band-green/25",
  },
  senpai: {
    key: "senpai", mono: "先",
    nameJa: "先輩コーチ", nameEn: "Senpai Coach",
    roleJa: "営業コーチ", roleEn: "Sales coach",
    seat: "border-band-yellow/25", glow: "ring-band-yellow/50",
    chip: "bg-band-yellow/[0.10] text-band-yellow",
    disc: "bg-band-yellow/[0.1] text-band-yellow ring-1 ring-band-yellow/25",
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
