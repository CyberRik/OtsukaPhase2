"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, FileText, Flame, GraduationCap, Library, MessagesSquare, type LucideIcon, Users } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { principleText, repText, departmentText, tagText } from "@/lib/content-i18n";
import { cn } from "@/lib/utils";
import type { GrowthData, Principle } from "@/lib/types";
import { SourceChips } from "@/components/source-chip";
import { ConfidenceBadge } from "@/components/confidence-badge";
import { Badge } from "@/components/ui/badge";

export default function JuniorHome() {
  const { t, lang } = useT();
  const [principles, setPrinciples] = useState<Principle[]>([]);
  const [counts, setCounts] = useState({ approved: 0, items: 0, two: 0 });
  const [profile, setProfile] = useState<GrowthData | null>(null);

  useEffect(() => {
    Promise.all([api.principles(), api.items(), api.growth()]).then(([p, it, gr]) => {
      setPrinciples(p.data.principles);
      setCounts({
        approved: p.data.counts.approved ?? 0,
        two: p.data.counts.two_source ?? 0,
        items: it.data.counts.approved ?? 0,
      });
      setProfile(gr.data.growth);
    });
  }, []);

  const learn = principles.filter((p) => p.n_interviews >= 2 && p.status === "approved").slice(0, 4);

  const actions: { href: string; icon: LucideIcon; title: string; desc: string }[] = [
    { href: "/junior/coach", icon: GraduationCap, title: t("jhome.qa.coach"), desc: t("jhome.qa.coach.desc") },
    { href: "/junior/knowledge", icon: Library, title: t("jhome.qa.knowledge"), desc: t("jhome.qa.knowledge.desc") },
    { href: "/junior/reports", icon: FileText, title: t("jhome.qa.reports"), desc: t("jhome.qa.reports.desc") },
  ];

  const stats = [
    { v: counts.approved, label: t("jhome.principlesApproved") },
    { v: counts.items, label: t("jhome.itemsApproved") },
    { v: counts.two, label: t("jhome.twoSourceFull") },
  ];

  return (
    <div className="space-y-9">
      <header className="space-y-2">
        <div className="eyebrow text-primary">{t("jhome.eyebrow")}</div>
        <h1 className="max-w-2xl text-[26px] font-semibold leading-tight tracking-tight md:text-[30px]">{t("jhome.title")}</h1>
        <p className="max-w-2xl text-[14px] leading-relaxed text-muted-foreground">{t("jhome.lead")}</p>
      </header>

      {/* Profile strip */}
      {profile && (
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 rounded-xl border border-border bg-card px-4 py-3">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
            <span className="font-jp text-[14px] font-semibold text-foreground">
              {repText(lang, profile.rep.name).text}
            </span>
            <span className="text-muted-foreground/40 select-none">·</span>
            <span className="font-jp text-[13px] text-muted-foreground">
              {departmentText(lang, profile.rep.department).text}
            </span>
            {profile.rep.specialty_tags.map((tg) => (
              <Badge key={tg} variant="default" className="text-[10.5px]">
                #{tagText(lang, tg).text}
              </Badge>
            ))}
          </div>
          <div className="flex items-center gap-3 text-[12px] text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <MessagesSquare className="h-3.5 w-3.5 shrink-0" />
              <span>
                <span className="font-semibold text-foreground">{profile.totals.reviews}</span>
                {" "}{t("growth.journey.reviews")}
              </span>
            </span>
            <span className="text-muted-foreground/30 select-none">·</span>
            <span className="inline-flex items-center gap-1.5">
              <Flame className="h-3.5 w-3.5 shrink-0 text-band-yellow" />
              <span>{t("growth.weeks", { n: String(profile.totals.streak_weeks) })}</span>
            </span>
          </div>
        </div>
      )}

      {/* Quick actions */}
      <section className="space-y-3">
        <div className="eyebrow">{t("jhome.quick")}</div>
        <div className="grid gap-3 sm:grid-cols-2">
          {actions.map((a) => {
            const Icon = a.icon;
            return (
              <Link key={a.href} href={a.href}
                className="group flex items-start gap-3.5 rounded-xl border border-border bg-card p-5 shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-all hover:border-primary/30 hover:shadow-[0_8px_30px_-18px_rgba(16,24,40,0.3)]">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-muted">
                  <Icon className="h-5 w-5 text-primary" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between">
                    <h3 className="text-[15px] font-semibold">{a.title}</h3>
                    <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                  </div>
                  <p className="mt-0.5 text-[12.5px] leading-snug text-muted-foreground">{a.desc}</p>
                </div>
              </Link>
            );
          })}
        </div>
      </section>

      {/* Stats */}
      <section className="grid grid-cols-3 gap-px overflow-hidden rounded-xl border border-border bg-border">
        {stats.map((s) => (
          <div key={s.label} className="bg-card p-5">
            <div className="text-3xl font-semibold tracking-tight">{s.v}</div>
            <div className="mt-1 text-[12px] leading-snug text-muted-foreground">{s.label}</div>
          </div>
        ))}
      </section>

      {/* Principles to learn */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="eyebrow">{t("jhome.learn")}</div>
          <Link href="/junior/knowledge" className="inline-flex items-center gap-1 text-[12px] font-medium text-primary hover:underline">
            {t("common.viewAll")} <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {learn.map((p) => {
            return (
            <Link key={p.principle_id} href="/junior/knowledge"
              className="rounded-xl border border-border bg-card p-5 shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-colors hover:bg-muted/40">
              <div className="flex items-center justify-between">
                <span className="font-mono text-[11px] text-muted-foreground">{p.principle_id}</span>
                <Badge variant="accent" className="gap-1"><Users className="h-3 w-3" /> {t("jhome.twoSourceFull")}</Badge>
              </div>
              <span className="mt-2 text-[14px] leading-snug text-foreground/90 block">{principleText(lang, p).text}</span>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <SourceChips ids={p.interview_ids} />
                <ConfidenceBadge level="high" />
              </div>
            </Link>
            );
          })}
          {learn.length === 0 && (
            <div className="rounded-xl border border-dashed border-border p-8 text-center text-[13px] text-muted-foreground">
              {t("common.loading")}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
