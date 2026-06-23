import { api } from "@/lib/api";
import { CoachChat } from "@/components/coach/coach-chat";

export const dynamic = "force-dynamic";

export default async function JuniorCoachPage() {
  const [{ data: ex }, { data: db }, { data: pr }, { data: it }] = await Promise.all([
    api.coachExamples(),
    api.dashboard(),
    api.principles(),
    api.items(),
  ]);

  return (
    <CoachChat
      examples={ex.examples}
      deals={db.deals}
      principles={pr.principles}
      items={it.items}
    />
  );
}
