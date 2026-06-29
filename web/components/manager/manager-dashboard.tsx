"use client";

import { useRouter } from "next/navigation";
import { useWorkspaceFocus } from "@/lib/chat-store";
import { DashboardView } from "@/components/dashboard/dashboard-view";
import type { DashboardData } from "@/lib/types";

/**
 * The Manager home dashboard (full width, tabbed: Overview / All deals / Flags).
 * "Ask the Copilot about this deal" in the deal drawer grounds the shared
 * workspace focus and jumps to the Copilot tab — the focus persists across the
 * route change, so the conversation lands pre-grounded on that deal.
 */
export function ManagerDashboard({ dashboard, live }: { dashboard: DashboardData; live: boolean }) {
  const router = useRouter();
  const { setFocus } = useWorkspaceFocus("manager");

  return (
    <DashboardView
      initial={dashboard}
      live={live}
      onAskCopilot={(g) => {
        setFocus(g);
        router.push("/manager/workspace");
      }}
    />
  );
}
