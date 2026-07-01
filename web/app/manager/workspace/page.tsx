import { api } from "@/lib/api";
import { currentEmployeeId } from "@/lib/server-session";
import { PageHeader } from "@/components/site/page-header";
import { Workspace } from "@/components/workspace/workspace";

export const dynamic = "force-dynamic";

// The Copilot tab — the full-width unified surface (chat + skills) running the
// manager tool-loop. Reached from the nav, or from a deal's "Ask the Copilot"
// action which grounds it on that deal first.
export default async function ManagerCopilotPage() {
  const [{ data: ex }, { data: db }, { data: pr }] = await Promise.all([
    api.coachExamples(),
    api.dashboard(undefined, await currentEmployeeId()),
    api.principles(),
  ]);

  return (
    <div className="space-y-8">
      <PageHeader eyebrowKey="nav.copilot" titleKey="assistant.title.manager" leadKey="assistant.lead.manager" />
      <Workspace examples={ex.examples} deals={db.deals} principles={pr.principles} role="manager" />
    </div>
  );
}
