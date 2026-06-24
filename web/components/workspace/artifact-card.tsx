"use client";

// Workspace artifact dispatcher — renders any Artifact by kind. The single
// place a thread turns a typed Artifact into a pinned card. Phase 1 implements
// `review`; `account_brief` and `research` render a minimal placeholder until
// Phase 3 ports their dedicated renderers.

import type { Artifact } from "@/lib/artifacts";
import { ReviewCard } from "./cards/review-card";

import { AccountCard } from "./cards/account-card";
import { ResearchCard } from "./cards/research-card";

export function ArtifactCard({ artifact }: { artifact: Artifact }) {
  switch (artifact.kind) {
    case "review":
      return <ReviewCard artifact={artifact} />;
    case "account_brief":
      return <AccountCard artifact={artifact} />;
    case "research":
      return <ResearchCard artifact={artifact} />;
    default:
      return null;
  }
}
