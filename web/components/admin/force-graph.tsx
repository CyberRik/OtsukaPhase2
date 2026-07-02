"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import type { GraphLink, GraphNode } from "@/lib/admin-types";

// react-force-graph-2d is WebGL/canvas + window-dependent → client-only, no SSR.
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

export interface FGNode extends GraphNode {
  color?: string;
  val?: number;
  highlight?: boolean;
}

export function ForceGraphView({
  nodes,
  links,
  height = 560,
  onNodeClick,
  highlightIds,
}: {
  nodes: FGNode[];
  links: GraphLink[];
  height?: number;
  onNodeClick?: (node: FGNode) => void;
  highlightIds?: Set<string>;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setWidth(e.contentRect.width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const FG = ForceGraph2D as any;

  return (
    <div ref={wrapRef} className="overflow-hidden rounded-lg border border-border bg-[#0b1020]" style={{ height }}>
      <FG
        graphData={{ nodes, links }}
        width={width}
        height={height}
        backgroundColor="#0b1020"
        nodeId="id"
        nodeVal={(n: FGNode) => Math.max(1, (n.val ?? n.degree ?? 1))}
        nodeColor={(n: FGNode) => {
          if (highlightIds && highlightIds.size > 0) {
            return highlightIds.has(n.id) ? (n.color ?? "#ffffff") : "rgba(120,130,160,0.25)";
          }
          return n.color ?? "#8892b0";
        }}
        nodeLabel={(n: FGNode) => `${n.label} · ${n.kind}${n.outcome ? ` · ${n.outcome}` : ""}`}
        linkColor={() => "rgba(120,130,160,0.18)"}
        linkWidth={0.5}
        linkDirectionalParticles={0}
        cooldownTicks={120}
        onNodeClick={(n: FGNode) => onNodeClick?.(n)}
        nodeCanvasObjectMode={() => "after"}
        nodeCanvasObject={(node: FGNode & { x: number; y: number }, ctx: CanvasRenderingContext2D, scale: number) => {
          // label the higher-degree / highlighted nodes only, so it stays legible
          const show = (node.degree ?? 0) > 12 || (highlightIds?.has(node.id) ?? false);
          if (!show || scale < 1.2) return;
          const label = node.label;
          ctx.font = `${11 / scale}px Inter, sans-serif`;
          ctx.fillStyle = "rgba(230,235,245,0.9)";
          ctx.textAlign = "center";
          ctx.fillText(label, node.x, node.y + 8 / scale);
        }}
      />
    </div>
  );
}
