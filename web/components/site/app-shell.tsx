"use client";

import { Fragment, useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Building2,
  FileText,
  Home,
  Library,
  Lightbulb,
  LogOut,
  type LucideIcon,
  Sparkles,
  Upload,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { useSession, type Role } from "@/lib/session";
import { Brand } from "./brand";
import { LangToggle } from "./lang-toggle";

type NavItem = { href: string; key: string; icon: LucideIcon; group?: string };

const NAV: Record<Role, NavItem[]> = {
  // Junior: the Command Center (Home) is the whole daily job — the old
  // Workspace lives inside it (chat + context panes), so it's gone from the
  // rail. Accounts / Knowledge / Reports / Ingestion are a visually separated
  // secondary group: Accounts is the browse-everything directory that
  // complements the Home pane's focused daily work; the rest are occasional,
  // deliberate tasks.
  junior: [
    { href: "/junior", key: "nav.home", icon: Home, group: "main" },
    { href: "/junior/accounts", key: "nav.accounts", icon: Building2, group: "more" },
    { href: "/junior/knowledge", key: "nav.knowledge", icon: Library, group: "more" },
    { href: "/junior/reports", key: "nav.reports", icon: FileText, group: "more" },
    { href: "/junior/ingestion", key: "nav.ingestion", icon: Upload, group: "more" },
  ],
  // Manager: Home is the overview-first team dashboard (Overview / All deals /
  // Flags tabs — the former Dashboard + Pipeline + Reliability routes). The
  // Copilot is its own tab. Knowledge absorbs the old principle-authoring
  // "Ingestion" page. Accounts / Coaching round out the secondary group.
  manager: [
    { href: "/manager", key: "nav.home", icon: Home, group: "main" },
    { href: "/manager/workspace", key: "nav.copilot", icon: Sparkles, group: "more" },
    { href: "/manager/coaching", key: "nav.coaching", icon: Lightbulb, group: "more" },
    { href: "/manager/accounts", key: "nav.accounts", icon: Building2, group: "more" },
    { href: "/manager/knowledge", key: "nav.mknowledge", icon: Library, group: "more" },
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
    <div className="flex h-screen overflow-hidden bg-background">
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
          {nav.map((item, i) => {
            const active = item.href === `/${role}` ? pathname === item.href : pathname.startsWith(item.href);
            const Icon = item.icon;
            // Separate nav groups (e.g. Junior's primary vs. secondary items).
            const showDivider = i > 0 && item.group !== nav[i - 1].group;
            return (
              <Fragment key={item.href}>
                {showDivider && <div className="mx-2.5 my-2 border-t border-border/60" />}
                <Link
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] font-medium transition-colors",
                    active ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                  )}
                >
                  <Icon className={cn("h-[18px] w-[18px]", active ? "text-primary" : "")} />
                  {t(item.key)}
                </Link>
              </Fragment>
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
      <div className="flex min-w-0 flex-1 flex-col h-full overflow-hidden">
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

        <main className="w-full flex-1 overflow-hidden px-5 py-4 md:px-8 md:py-5 max-w-none flex flex-col min-h-0">
          {children}
        </main>
      </div>
    </div>
  );
}
