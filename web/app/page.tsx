"use client";

import Link from "next/link";
import { ArrowRight, LayoutDashboard, ShieldCheck, Sparkles, UserRound } from "lucide-react";
import { useT } from "@/lib/i18n";
import { Brand } from "@/components/site/brand";
import { ClientBadge } from "@/components/site/client-badge";
import { LangToggle } from "@/components/site/lang-toggle";

export default function Landing() {
  const { t } = useT();

  const cards = [
    {
      role: "junior" as const,
      href: "/login?role=junior",
      icon: UserRound,
      title: t("landing.junior.title"),
      desc: t("landing.junior.desc"),
      cta: t("landing.junior.cta"),
      accent: "text-primary",
      ring: "hover:border-primary/40",
    },
    {
      role: "manager" as const,
      href: "/login?role=manager",
      icon: LayoutDashboard,
      title: t("landing.manager.title"),
      desc: t("landing.manager.desc"),
      cta: t("landing.manager.cta"),
      accent: "text-navy",
      ring: "hover:border-navy/40",
    },
  ];

  return (
    <div className="hero-wash min-h-screen">
      <header className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
        <Brand fullMark tagline={t("app.tagline")} />
        <div className="flex items-center gap-3 sm:gap-4">
          <ClientBadge />
          <div className="hidden h-5 w-px bg-border sm:block" />
          <LangToggle />
        </div>
      </header>

      <main className="mx-auto flex max-w-5xl flex-col items-center px-6 pb-20 pt-10 text-center md:pt-16">
        <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-[12px] text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          {t("landing.eyebrow")}
        </div>
        <h1 className="mt-6 max-w-3xl text-balance text-[34px] font-semibold leading-[1.1] tracking-tight text-foreground md:text-[48px]">
          {t("landing.title")}
        </h1>
        <p className="mt-5 max-w-2xl text-pretty text-[15px] leading-relaxed text-muted-foreground md:text-base">
          {t("landing.subtitle")}
        </p>

        <div className="mt-12 w-full">
          <div className="mb-5 text-[13px] font-medium uppercase tracking-[0.08em] text-muted-foreground">
            {t("landing.who")}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {cards.map((c) => {
              const Icon = c.icon;
              return (
                <Link
                  key={c.role}
                  href={c.href}
                  className={`group flex flex-col items-start rounded-2xl border border-border bg-card p-7 text-left shadow-[0_1px_2px_rgba(16,24,40,0.04)] transition-all hover:shadow-[0_12px_40px_-18px_rgba(16,24,40,0.35)] ${c.ring}`}
                >
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-muted">
                    <Icon className={`h-5 w-5 ${c.accent}`} />
                  </div>
                  <h2 className="mt-4 text-xl font-semibold tracking-tight">{c.title}</h2>
                  <p className="mt-2 flex-1 text-[14px] leading-relaxed text-muted-foreground">{c.desc}</p>
                  <span className="mt-5 inline-flex items-center gap-1.5 text-[14px] font-medium text-foreground">
                    {c.cta}
                    <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                  </span>
                </Link>
              );
            })}
          </div>
        </div>

        <div className="mt-12 flex items-center gap-2 text-[12px] text-muted-foreground">
          <ShieldCheck className="h-4 w-4 text-conf-high" />
          {t("diff.promise")}
        </div>
        <p className="mt-3 max-w-2xl text-[11px] leading-relaxed text-muted-foreground/80">{t("landing.footer")}</p>
      </main>
    </div>
  );
}
