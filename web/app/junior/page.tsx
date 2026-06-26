import { api } from "@/lib/api";
import { HomeContent } from "@/components/junior/home-content";

export const dynamic = "force-dynamic";

export default async function JuniorHome() {
  const [{ data: p }, { data: it }, { data: gr }] = await Promise.all([
    api.principles(),
    api.items(),
    api.growth(),
  ]);

  return (
    <HomeContent
      principles={p.principles}
      counts={{
        pTotal: p.counts.total ?? 0,
        pPending: p.counts.pending ?? 0,
        iTotal: it.counts.total ?? 0,
        iDraft: it.counts.pending ?? 0,
        two: p.counts.two_source ?? 0,
      }}
      profile={gr.growth}
    />
  );
}
