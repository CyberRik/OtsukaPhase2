"use client";

import type { ReactNode } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { useT } from "@/lib/i18n";
import { useCachedState } from "@/lib/chat-store";
import type { Role } from "@/lib/session";
import type { CoachExample, DealRow, Principle } from "@/lib/types";
import { Workspace } from "./workspace";

/**
 * The Command Center shell: a live context pane (left) beside the Copilot
 * thread (right). The left pane is role-supplied via `contextSlot` — Junior
 * passes its deal/account context, Manager passes team triage — while the
 * collapsible chrome and the Workspace stay shared. Clicking an item in the
 * context pane grounds the Copilot via the shared workspace focus.
 *
 * Collapsing the context column hands its width to the chat, so the user can
 * run a focused conversation full-bleed and pop the context back open when they
 * need to switch. The open/closed state is cached so it survives navigation.
 */
export function CommandCenter({
  examples,
  deals,
  principles,
  contextSlot,
  role = "junior",
}: {
  examples: CoachExample[];
  deals: DealRow[];
  principles: Principle[];
  contextSlot: ReactNode;
  role?: Role;
}) {
  const { t } = useT();
  const [open, setOpen] = useCachedState<boolean>(`workspace:${role}:ctxOpen`, true);

  return (
    <div
      className={cn(
        "relative grid gap-4 lg:gap-8 h-full w-full min-h-0",
        open ? "lg:grid-cols-[280px_minmax(0,1fr)]" : "lg:grid-cols-1",
      )}
    >
      {!open && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          title={t("cc.todayWork")}
          className="absolute left-0 lg:-left-8 top-3 z-30 flex h-8 items-center gap-1.5 rounded-lg lg:rounded-l-none lg:rounded-r-lg lg:border-l-0 border border-border bg-card px-2.5 text-[12px] text-muted-foreground shadow-sm transition-colors hover:bg-muted hover:text-foreground shrink-0"
        >
          <PanelLeftOpen className="h-4 w-4" />
          <span className="lg:hidden xl:inline">{t("cc.todayWork")}</span>
        </button>
      )}

      {open && (
        <aside className="overflow-y-auto rounded-xl border border-border bg-card/40 p-3 h-full flex flex-col min-h-0 max-lg:max-h-[42vh]">
          <div className="mb-2 flex items-center justify-between shrink-0">
            <span className="eyebrow">{t("cc.context")}</span>
            <button
              type="button"
              onClick={() => setOpen(false)}
              title={t("cc.hidePanel")}
              className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <PanelLeftClose className="h-4 w-4" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto min-h-0">
            {contextSlot}
          </div>
        </aside>
      )}

      <div className={cn("min-w-0 h-full flex flex-col min-h-0", !open && "pl-12 lg:pl-16")}>
        <Workspace examples={examples} deals={deals} principles={principles} role={role} wide />
      </div>
    </div>
  );
}
