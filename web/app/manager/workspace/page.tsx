import { api } from "@/lib/api";
import { currentEmployeeId } from "@/lib/server-session";
import { CommandCenter } from "@/components/workspace/command-center";
import { ContextPane } from "@/components/workspace/context-pane";

export const dynamic = "force-dynamic";

// The Copilot tab — the same unified Command Center the Junior home uses: live
// deal/account context on the left, the Copilot (Workspace) on the right. Here
// the context pane is scoped to the manager's coachees. Reached from the nav,
// or from a deal's "Ask the Copilot" action which grounds it on that deal first.
export default async function ManagerCopilotPage() {
  const eid = await currentEmployeeId();
  const [{ data: ex }, { data: db }, { data: pr }] = await Promise.all([
    api.coachExamples(),
    api.dashboard(undefined, eid),
    api.principles(),
  ]);

  return (
    <CommandCenter
      examples={ex.examples}
      deals={db.deals}
      principles={pr.principles}
      role="manager"
      contextSlot={<ContextPane key="manager-context" deals={db.deals} role="manager" />}
    />
  );
}
