import { api } from "@/lib/api";
import { currentEmployeeId } from "@/lib/server-session";
import { CommandCenter } from "@/components/workspace/command-center";
import { ContextPane } from "@/components/workspace/context-pane";

export const dynamic = "force-dynamic";

// The Junior home is the unified Command Center: live deal/account context on
// the left, the Copilot (Workspace) on the right. Same server-side fetch the
// standalone Workspace page used.
export default async function JuniorHome() {
  const eid = await currentEmployeeId();
  const [{ data: ex }, { data: db }, { data: pr }, { data: gr }] = await Promise.all([
    api.coachExamples(),
    api.dashboard(),
    api.principles(),
    api.growth(eid),
  ]);

  return (
    <CommandCenter
      examples={ex.examples}
      deals={db.deals}
      principles={pr.principles}
      role="junior"
      contextSlot={<ContextPane key="junior-context" deals={db.deals} role="junior" profile={gr.growth} />}
    />
  );
}
