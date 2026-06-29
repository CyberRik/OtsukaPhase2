import { api } from "@/lib/api";
import { CommandCenter } from "@/components/workspace/command-center";
import { ContextPane } from "@/components/workspace/context-pane";

export const dynamic = "force-dynamic";

// The Junior home is the unified Command Center: live deal/account context on
// the left, the Copilot (Workspace) on the right. Same server-side fetch the
// standalone Workspace page used.
export default async function JuniorHome() {
  const [{ data: ex }, { data: db }, { data: pr }, { data: gr }] = await Promise.all([
    api.coachExamples(),
    api.dashboard(),
    api.principles(),
    api.growth(),
  ]);

  return (
    <CommandCenter
      examples={ex.examples}
      deals={db.deals}
      principles={pr.principles}
      role="junior"
      contextSlot={<ContextPane deals={db.deals} role="junior" profile={gr.growth} />}
    />
  );
}
