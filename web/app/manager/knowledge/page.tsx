import { api } from "@/lib/api";
import { PageHeader } from "@/components/site/page-header";
import { KnowledgeExplorer } from "@/components/knowledge/knowledge-explorer";

export const dynamic = "force-dynamic";

export default async function ManagerKnowledgePage() {
  const [{ data: pr, live }, { data: it }, { data: src }] = await Promise.all([
    api.principles(),
    api.items(),
    api.sources(),
  ]);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrowKey="nav.mknowledge"
        titleKey="knowledge.title"
        leadKey="knowledge.lead"
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
