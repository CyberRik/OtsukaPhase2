import { api } from "@/lib/api";
import { PageHeader } from "@/components/site/page-header";
import { CoachConsole } from "@/components/coach/coach-console";

export const dynamic = "force-dynamic";

export default async function CoachPage() {
  const [{ data: ex }, { data: db }] = await Promise.all([
    api.coachExamples(),
    api.dashboard(),
  ]);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Sales Review Coach · 営業レビュー・コーチ"
        title="See the note the way a senior would."
        lead="Paste a meeting note or daily report. Senpai makes a senior rep's mental checklist explicit — six lenses of reasoning, not a single answer to copy."
      />
      <CoachConsole examples={ex.examples} deals={db.deals} />
    </div>
  );
}
