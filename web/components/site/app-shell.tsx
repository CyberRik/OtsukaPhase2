"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  FileText,
  GraduationCap,
  Home,
  LayoutDashboard,
  Library,
  Lightbulb,
  ListTree,
  LogOut,
  type LucideIcon,
  ShieldAlert,
  Target,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { useSession, type Role } from "@/lib/session";
import { Brand } from "./brand";
import { LangToggle } from "./lang-toggle";

type NavItem = { href: string; key: string; icon: LucideIcon };

const NAV: Record<Role, NavItem[]> = {
  junior: [
    { href: "/junior", key: "nav.home", icon: Home },
    { href: "/junior/coach", key: "nav.coach", icon: GraduationCap },
    { href: "/junior/prepare", key: "nav.prepare", icon: Target },
    { href: "/junior/knowledge", key: "nav.knowledge", icon: Library },
    { href: "/junior/reports", key: "nav.reports", icon: FileText },
  ],
  manager: [
    { href: "/manager", key: "nav.dashboard", icon: LayoutDashboard },
    { href: "/manager/pipeline", key: "nav.pipeline", icon: ListTree },
    { href: "/manager/coaching", key: "nav.coaching", icon: Lightbulb },
    { href: "/manager/reliability", key: "nav.reliability", icon: ShieldAlert },
    { href: "/manager/knowledge", key: "nav.mknowledge", icon: Library },
  ],
};

export function AppShell({ role, children }: { role: Role; children: React.ReactNode }) {
  const { t } = useT();
  const { role: active, ready, logout } = useSession();
  const pathname = usePathname();
  const router = useRouter();

  // Demo guard: if not signed in as this role, bounce to the landing page.
  useEffect(() => {
    if (ready && active !== role) router.replace("/");
  }, [ready, active, role, router]);

  if (ready && active !== role) return null;

  const nav = NAV[role];
  const roleLabel = t(role === "junior" ? "role.junior" : "role.manager");

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="sticky top-0 hidden h-screen w-[252px] shrink-0 flex-col border-r border-border bg-card px-3.5 py-5 lg:flex">
        <div className="px-2">
          <Brand tagline={t("app.tagline")} />
        </div>

        <div className="mt-6 px-2">
          <span className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[11px] font-medium",
            role === "manager" ? "bg-navy/[0.06] text-navy" : "bg-primary/[0.08] text-primary",
          )}>
            <span className={cn("h-1.5 w-1.5 rounded-full", role === "manager" ? "bg-navy" : "bg-primary")} />
            {roleLabel}
          </span>
        </div>

        <nav className="mt-4 flex flex-col gap-0.5">
          {nav.map((item) => {
            const active = item.href === `/${role}` ? pathname === item.href : pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] font-medium transition-colors",
                  active ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                )}
              >
                <Icon className={cn("h-[18px] w-[18px]", active ? "text-primary" : "")} />
                {t(item.key)}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto space-y-3 px-1">
          <div className="rounded-lg border border-border bg-muted/40 p-3">
            <div className="eyebrow mb-1.5">{t("diff.promiseTitle")}</div>
            <p className="text-[11.5px] leading-relaxed text-muted-foreground">{t("diff.promise")}</p>
          </div>
          <button
            onClick={() => { logout(); router.replace("/"); }}
            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <LogOut className="h-[18px] w-[18px]" /> {t("common.signOut")}
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-border bg-background/85 px-5 py-3 backdrop-blur md:px-8">
          <div className="flex items-center gap-2 lg:hidden">
            <Brand compact />
          </div>
          <div className="hidden text-[13px] font-medium text-muted-foreground lg:block">{roleLabel}</div>
          <div className="flex items-center gap-2">
            <LangToggle />
            <button
              onClick={() => { logout(); router.replace("/"); }}
              className="hidden items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1.5 text-[12px] font-medium text-muted-foreground transition-colors hover:text-foreground sm:flex lg:hidden"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          </div>
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 space-y-8 px-5 py-7 md:px-8 md:py-10">
          {children}
        </main>
      </div>
    </div>
  );
}
