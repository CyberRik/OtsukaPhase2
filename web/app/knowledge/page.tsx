import { api } from "@/lib/api";
import { PageHeader } from "@/components/site/page-header";
import { KnowledgeExplorer } from "@/components/knowledge/knowledge-explorer";

export const dynamic = "force-dynamic";

export default async function KnowledgePage() {
  const [{ data: pr, live }, { data: it }, { data: src }] = await Promise.all([
    api.principles(),
    api.items(),
    api.sources(),
  ]);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Knowledge Explorer · ナレッジ・エクスプローラー"
        title="From a senior's sentence to a teachable principle."
        lead="Two interviews, eleven validated principles, four approved coaching items — and a verbatim citation behind every one. This is the audit trail that makes 'no invented expertise' a fact, not a claim."
      />
      <KnowledgeExplorer
        principles={pr.principles}
        items={it.items}
        sources={src.sources}
        live={live}
      />
    </div>
  );
}
