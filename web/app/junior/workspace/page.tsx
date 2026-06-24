import { api } from "@/lib/api";
import { Workspace } from "@/components/workspace/workspace";

export const dynamic = "force-dynamic";

// Phase 2: the unified Workspace ships ALONGSIDE the standalone Coach so the two
// can be compared directly. Reachable at /junior/workspace; not yet promoted in
// nav (Phase 4). Wires the /review skill over the existing coach + narrate APIs.
export default async function JuniorWorkspacePage() {
  const [{ data: ex }, { data: db }] = await Promise.all([
    api.coachExamples(),
    api.dashboard(),
  ]);

  return <Workspace examples={ex.examples} deals={db.deals} role="junior" />;
}
