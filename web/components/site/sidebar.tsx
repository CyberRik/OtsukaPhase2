"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { GraduationCap, LayoutDashboard, Library, Home } from "lucide-react";
import { cn } from "@/lib/utils";
import { Brand } from "./brand";

const NAV = [
  { href: "/", label: "Home", ja: "ホーム", icon: Home, desc: "What Senpai is" },
  { href: "/coach", label: "Sales Review Coach", ja: "営業レビュー・コーチ", icon: GraduationCap, desc: "Think like a senior" },
  { href: "/knowledge", label: "Knowledge Explorer", ja: "ナレッジ・エクスプローラー", icon: Library, desc: "Principles & provenance" },
  { href: "/dashboard", label: "Manager Dashboard", ja: "マネージャー・ダッシュボード", icon: LayoutDashboard, desc: "Deal-health & reliability" },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="sticky top-0 hidden h-screen w-[264px] shrink-0 flex-col border-r border-border bg-paper/60 px-4 py-6 lg:flex">
      <div className="px-2">
        <Brand />
      </div>

      <nav className="mt-9 flex flex-col gap-1">
        <div className="px-3 pb-2 eyebrow">Platform</div>
        {NAV.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "group flex items-start gap-3 rounded-lg px-3 py-2.5 transition-colors",
                active ? "bg-card shadow-card" : "hover:bg-card/60",
              )}
            >
              <Icon
                className={cn(
                  "mt-0.5 h-[18px] w-[18px] shrink-0",
                  active ? "text-vermilion" : "text-muted-foreground group-hover:text-foreground",
                )}
              />
              <div className="leading-tight">
                <div className={cn("text-[13px] font-medium", active ? "text-foreground" : "text-foreground/80")}>
                  {item.label}
                </div>
                <div className="text-[11px] text-muted-foreground">{item.desc}</div>
              </div>
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto rounded-lg border border-border bg-card/50 p-3.5">
        <div className="eyebrow mb-2">The promise</div>
        <p className="text-[12px] leading-relaxed text-muted-foreground">
          No synthetic expertise. Every piece of advice traces to a real interview
          sentence and carries a <span className="text-foreground">computed confidence</span>.
        </p>
      </div>
    </aside>
  );
}

export function MobileTopbar() {
  return (
    <div className="flex items-center justify-between border-b border-border bg-paper/80 px-4 py-3 backdrop-blur lg:hidden">
      <Brand />
    </div>
  );
}
