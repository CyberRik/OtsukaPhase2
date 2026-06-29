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
        "grid gap-4 lg:items-start",
        open ? "lg:grid-cols-[280px_minmax(0,1fr)]" : "lg:grid-cols-1",
      )}
    >
      {open && (
        <aside className="max-h-[42vh] overflow-y-auto rounded-xl border border-border bg-card/40 p-3 lg:sticky lg:top-[4.5rem] lg:max-h-[calc(100vh-5.5rem)]">
          <div className="mb-2 flex items-center justify-between">
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
          {contextSlot}
        </aside>
      )}

      <div className="min-w-0">
        {!open && (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="mb-2 inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1.5 text-[12.5px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
          >
            <PanelLeftOpen className="h-4 w-4" /> {t("cc.todayWork")}
          </button>
        )}
        <Workspace examples={examples} deals={deals} principles={principles} role={role} wide />
      </div>
    </div>
  );
}
