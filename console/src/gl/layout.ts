/** Positioning the causal graph.
 *
 *  Time runs left to right, agents occupy horizontal lanes. Reading the graph then costs
 *  nothing: horizontal distance is elapsed work, vertical position is who did it, and a
 *  causal edge that climbs between lanes is a handoff. A force-directed layout would look
 *  more organic and say much less. */

import type { GraphEdge, GraphNode } from "../api";

export interface Placed extends GraphNode {
  x: number;
  y: number;
  lane: number;
  r: number;
}

export interface Layout {
  nodes: Placed[];
  byId: Map<string, Placed>;
  edges: GraphEdge[];
  lanes: { agent: string; y: number }[];
  width: number;
  height: number;
}

const TOP = 56;
const BOTTOM = 40;
const LEFT = 132;
const RIGHT = 48;

/** Radius carries weight — a node that cost more is physically larger. Log-scaled so a
 *  single expensive reasoning step does not swamp everything around it. */
function radius(node: GraphNode): number {
  if (node.kind === "agent_enter") return 2.2;
  if (node.kind === "delegation") return 4.2;
  const weight = Math.log10(1 + node.tokens) / 4;
  return 3 + Math.min(weight, 1) * 5.5;
}

export function layout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  agents: string[],
  width: number,
  height: number,
): Layout {
  const usableW = Math.max(width - LEFT - RIGHT, 10);
  const usableH = Math.max(height - TOP - BOTTOM, 10);
  const laneH = usableH / Math.max(agents.length, 1);

  const laneOf = new Map(agents.map((a, i) => [a, i]));
  const lanes = agents.map((agent, i) => ({
    agent,
    y: TOP + laneH * i + laneH / 2,
  }));

  const seqs = nodes.map((n) => n.seq);
  const min = Math.min(...seqs, 0);
  const max = Math.max(...seqs, min + 1);
  const span = Math.max(max - min, 1);

  // Effects sharing a lane and a sequence position would overlap exactly; nudge them
  // apart deterministically so the same graph always draws identically.
  const seen = new Map<string, number>();

  const placed: Placed[] = nodes.map((node) => {
    const lane = laneOf.get(node.agent) ?? 0;
    const key = `${lane}:${node.seq}`;
    const collisions = seen.get(key) ?? 0;
    seen.set(key, collisions + 1);

    return {
      ...node,
      lane,
      x: LEFT + ((node.seq - min) / span) * usableW,
      y: TOP + laneH * lane + laneH / 2 + (collisions % 2 ? 1 : -1) * Math.ceil(collisions / 2) * 9,
      r: radius(node),
    };
  });

  return {
    nodes: placed,
    byId: new Map(placed.map((p) => [p.id, p])),
    edges: edges.filter((e) => e.source !== e.target),
    lanes,
    width,
    height,
  };
}

/** Breadth-first depth from a root, following causal edges forward.
 *  Drives the ignition: the cone lights up in causal order rather than all at once,
 *  so what the eye follows is the propagation itself. */
export function depthsFrom(root: string, edges: GraphEdge[]): Map<string, number> {
  const children = new Map<string, string[]>();
  for (const e of edges) {
    const list = children.get(e.source);
    if (list) list.push(e.target);
    else children.set(e.source, [e.target]);
  }
  const depth = new Map<string, number>([[root, 0]]);
  let frontier = [root];
  let d = 0;
  while (frontier.length) {
    d += 1;
    const next: string[] = [];
    for (const id of frontier) {
      for (const child of children.get(id) ?? []) {
        if (!depth.has(child)) {
          depth.set(child, d);
          next.push(child);
        }
      }
    }
    frontier = next;
  }
  return depth;
}
