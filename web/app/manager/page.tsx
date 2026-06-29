import { api } from "@/lib/api";
import { CommandCenter } from "@/components/workspace/command-center";
import { ManagerContextPane } from "@/components/workspace/manager-context-pane";

export const dynamic = "force-dynamic";

// The Manager home is the unified Command Center: team triage on the left
// (at-risk deals + reps needing coaching), the Copilot (Workspace) on the right.
// Clicking a deal or rep grounds the Copilot for the next question.
export default async function ManagerHome() {
  const [{ data: ex }, { data: db }, { data: pr }, { data: co }] = await Promise.all([
    api.coachExamples(),
    api.dashboard(),
    api.principles(),
    api.coaching(),
  ]);

  return (
    <CommandCenter
      examples={ex.examples}
      deals={db.deals}
      principles={pr.principles}
      role="manager"
      contextSlot={<ManagerContextPane deals={db.deals} needsCoaching={co.needs_coaching} />}
    />
  );
}
