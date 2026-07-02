"use client";

import { Fragment } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart3,
  GitBranch,
  Home,
  type LucideIcon,
  Network,
  Server,
  ShieldAlert,
  Sparkles,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Brand } from "./brand";
import { LangToggle } from "./lang-toggle";

type NavItem = { href: string; label: string; icon: LucideIcon; group?: string };

// Internal-only portal. NO role guard by design (see the plan) — reaching /admin
// is the only gate. English labels: this is an ops surface, not the product UI.
const NAV: NavItem[] = [
  { href: "/admin", label: "Overview", icon: Home, group: "main" },
  { href: "/admin/people", label: "People", icon: Users, group: "main" },
  { href: "/admin/org", label: "Org & Assignments", icon: GitBranch, group: "main" },
  { href: "/admin/activity", label: "Activity", icon: Activity, group: "main" },
  { href: "/admin/usage", label: "LLM Usage", icon: BarChart3, group: "main" },
  { href: "/admin/pipeline-health", label: "Pipeline Health", icon: ShieldAlert, group: "ops" },
  { href: "/admin/status", label: "System Status", icon: Server, group: "ops" },
  { href: "/admin/visualization", label: "Visualization", icon: Sparkles, group: "demo" },
];

const VIZ_NAV: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/admin/visualization/network", label: "Network Graph", icon: Network },
  { href: "/admin/visualization/communities", label: "Community Map", icon: Sparkles },
  { href: "/admin/visualization/live", label: "Live Graph-RAG", icon: Activity },
  { href: "/admin/visualization/versus", label: "vs Traditional", icon: BarChart3 },
];

export function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const inViz = pathname.startsWith("/admin/visualization");

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <aside className="sticky top-0 hidden h-screen w-[252px] shrink-0 flex-col border-r border-border bg-card px-3.5 py-5 lg:flex">
        <div className="px-2"><Brand tagline="Admin Portal" /></div>
        <div className="mt-6 px-2">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-navy/[0.06] px-2 py-1 text-[11px] font-medium text-navy">
            <span className="h-1.5 w-1.5 rounded-full bg-navy" />
            Internal · Admin
          </span>
        </div>

        <nav className="mt-4 flex flex-col gap-0.5">
          {NAV.map((item, i) => {
            const active = item.href === "/admin" ? pathname === item.href : pathname.startsWith(item.href);
            const Icon = item.icon;
            const showDivider = i > 0 && item.group !== NAV[i - 1].group;
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
                  {item.label}
                </Link>
                {/* Visualization sub-nav appears nested when inside that section */}
                {item.href === "/admin/visualization" && inViz && (
                  <div className="mb-1 ml-3.5 mt-0.5 flex flex-col gap-0.5 border-l border-border/60 pl-2.5">
                    {VIZ_NAV.map((v) => {
                      const vActive = pathname.startsWith(v.href);
                      const VIcon = v.icon;
                      return (
                        <Link
                          key={v.href}
                          href={v.href}
                          className={cn(
                            "flex items-center gap-2 rounded-md px-2 py-1.5 text-[12.5px] transition-colors",
                            vActive ? "text-primary" : "text-muted-foreground hover:text-foreground",
                          )}
                        >
                          <VIcon className="h-3.5 w-3.5" />
                          {v.label}
                        </Link>
                      );
                    })}
                  </div>
                )}
              </Fragment>
            );
          })}
        </nav>

        <div className="mt-auto px-1">
          <Link href="/" className="flex items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
            ← Back to app
          </Link>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col h-full overflow-hidden">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-border bg-background/85 px-5 py-3 backdrop-blur md:px-8">
          <div className="flex items-center gap-2 lg:hidden"><Brand compact /></div>
          <div className="hidden text-[13px] font-medium text-muted-foreground lg:block">Admin Portal · 内部管理</div>
          <LangToggle />
        </header>
        <main className="w-full flex-1 overflow-y-auto px-5 py-4 md:px-8 md:py-5 max-w-none flex flex-col min-h-0">
          {children}
        </main>
      </div>
    </div>
  );
}
