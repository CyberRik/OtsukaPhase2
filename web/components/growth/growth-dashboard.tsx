"use client";

import { useEffect, useState } from "react";
import {
  BookMarked,
  Flame,
  GraduationCap,
  Layers,
  type LucideIcon,
  MessagesSquare,
  Sparkles,
  Star,
} from "lucide-react";
import { api } from "@/lib/api";
import type { GrowthResponse } from "@/lib/types";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { tagText } from "@/lib/content-i18n";
import { Badge } from "@/components/ui/badge";
import { TranslatedText } from "@/components/site/translated-text";

function monthLabel(ym: string, lang: "ja" | "en"): string {
  const [y, m] = ym.split("-").map(Number);
  if (!y || !m) return ym;
  return new Date(y, m - 1, 1).toLocaleString(lang === "ja" ? "ja-JP" : "en-US", { month: "short" });
}

function StatCard({ icon: Icon, value, label, sub, tone }: {
  icon: LucideIcon; value: number; label: string; sub?: string; tone: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-[0_1px_2px_rgba(16,24,40,0.04)]">
      <span className={cn("inline-flex h-8 w-8 items-center justify-center rounded-lg", tone)}>
        <Icon className="h-4 w-4" />
      </span>
      <div className="mt-3 flex items-baseline gap-1.5">
        <span className="text-[26px] font-semibold leading-none tracking-tight text-foreground">{value}</span>
        {sub && <span className="text-[11px] text-muted-foreground">{sub}</span>}
      </div>
      <div className="mt-1 text-[12px] text-muted-foreground">{label}</div>
    </div>
  );
}

function Stars({ n }: { n: number }) {
  return (
    <span className="flex gap-0.5">
      {Array.from({ length: 5 }).map((_, i) => (
        <Star
          key={i}
          className={cn("h-4 w-4", i < n ? "fill-band-yellow text-band-yellow" : "fill-none text-muted-foreground/30")}
        />
      ))}
    </span>
  );
}

export function GrowthDashboard({ initial }: { initial: GrowthResponse }) {
  const { t, lang } = useT();
  const [data, setData] = useState<GrowthResponse>(initial);
  const [rep, setRep] = useState<string>(initial.growth.rep.employee_id);
  const [loading, setLoading] = useState(false);
  const [translatedJuniors, setTranslatedJuniors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (lang === "ja") {
      setTranslatedJuniors({});
      return;
    }
    data.juniors.forEach((j) => {
      fetch("/api/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: j.name, lang: "en" })
      })
        .then(res => res.json())
        .then(resData => {
          setTranslatedJuniors(prev => ({
            ...prev,
            [j.employee_id]: resData.translated || j.name
          }));
        })
        .catch(() => {});
    });
  }, [data.juniors, lang]);

  useEffect(() => {
    if (rep === data.growth.rep.employee_id) return;
    let alive = true;
    setLoading(true);
    api.growth(rep).then(({ data: d }) => {
      if (alive) { setData(d); setLoading(false); }
    });
    return () => { alive = false; };
  }, [rep, data.growth.rep.employee_id]);

  const g = data.growth;
  const maxMonth = Math.max(1, ...g.monthly.map((m) => m.count));

  return (
    <div className={cn("space-y-6 transition-opacity", loading && "opacity-60")}>
      {/* who am I + selector */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card p-4">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-navy text-white">
            <GraduationCap className="h-5 w-5" />
          </span>
          <div>
            <div className="font-jp text-[15px] font-semibold text-foreground">
              <TranslatedText text={g.rep.name} />
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
              <span className="font-jp">
                <TranslatedText text={g.rep.department} />
              </span>
              {g.rep.specialty_tags.map((tg) => (
                <Badge key={tg} variant="default">#{tagText(lang, tg).text}</Badge>
              ))}
            </div>
          </div>
        </div>
        <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
          {t("growth.me")}
          <select
            value={rep}
            onChange={(e) => setRep(e.target.value)}
            className="h-8 rounded-lg border border-input bg-card px-2 text-[12px] text-foreground shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {data.juniors.map((j) => (
              <option key={j.employee_id} value={j.employee_id}>
                {translatedJuniors[j.employee_id] || j.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* headline stats */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard icon={MessagesSquare} value={g.totals.reviews} label={t("growth.stat.reviews")} tone="bg-primary/10 text-primary" />
        <StatCard icon={BookMarked} value={g.totals.principles} label={t("growth.stat.principles")} tone="bg-navy/10 text-navy" />
        <StatCard icon={Layers} value={g.totals.scenarios} label={t("growth.stat.scenarios")} tone="bg-conf-high/15 text-conf-high" />
        <StatCard icon={Flame} value={g.totals.streak_weeks} label={t("growth.stat.streak")} sub={t("growth.weeks", { n: String(g.totals.streak_weeks) })} tone="bg-band-yellow/15 text-band-yellow" />
      </div>

      {/* coaching journey — positive reinforcement */}
      <div className="rounded-2xl border border-primary/25 bg-gradient-to-br from-primary/[0.06] to-primary/[0.01] p-5">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[0.06em] text-primary">
          <Sparkles className="h-3.5 w-3.5" /> {t("growth.journeyTitle")}
        </div>
        <div className="mt-1 text-[12px] text-muted-foreground">{t("growth.journeyLead")} · {monthLabel(g.this_month.label, lang)}</div>
        <div className="mt-4 flex flex-wrap gap-x-8 gap-y-3">
          <JourneyStat n={g.this_month.reviews} label={t("growth.journey.reviews")} />
          <JourneyStat n={g.this_month.new_principles} label={t("growth.journey.principles")} />
          <JourneyStat n={g.this_month.strengths} label={t("growth.journey.strengths")} />
        </div>
        <p className="mt-4 text-[13px] leading-relaxed text-foreground/80">{t("growth.encourage")}</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* skill progression */}
        <section>
          <div className="eyebrow mb-1">{t("growth.skillsTitle")}</div>
          <p className="mb-3 text-[11.5px] text-muted-foreground">{t("growth.skillsSub")}</p>
          <div className="space-y-2.5">
            {g.skills.map((s) => (
              <div key={s.key} className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3">
                <span className="text-[13px] font-medium text-foreground">{t(`skill.${s.key}`)}</span>
                <Stars n={s.stars} />
              </div>
            ))}
          </div>
        </section>

        {/* monthly activity */}
        <section>
          <div className="eyebrow mb-3">{t("growth.monthlyTitle")}</div>
          <div className="rounded-xl border border-border bg-card p-4">
            <div className="flex h-40 items-end justify-between gap-2">
              {g.monthly.map((m) => (
                <div key={m.month} className="flex flex-1 flex-col items-center gap-1.5">
                  <span className="text-[10px] font-medium text-muted-foreground">{m.count}</span>
                  <div
                    className="w-full rounded-t-md bg-primary/70 transition-all"
                    style={{ height: `${Math.max(4, (m.count / maxMonth) * 100)}%` }}
                  />
                  <span className="text-[10px] text-muted-foreground">{monthLabel(m.month, lang)}</span>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

function JourneyStat({ n, label }: { n: number; label: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="text-[28px] font-semibold leading-none tracking-tight text-primary">{n}</span>
      <span className="text-[12.5px] text-foreground/70">{label}</span>
    </div>
  );
}
