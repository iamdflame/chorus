/** Typed client for the Lightcone API. Same origin in production; proxied in dev. */

export interface Branch {
  id: string;
  name: string;
  parent_id: string | null;
  fork_at_seq: number | null;
  perturbation: Record<string, unknown> | null;
  effects: number;
  own_effects: number;
  is_primary: boolean;
}

export interface GraphNode {
  id: string;
  seq: number;
  agent: string;
  kind: string;
  determinism: string;
  inherited: boolean;
  quarantined: boolean;
  cost_usd: number;
  tokens: number;
  wall_ms: number;
  label: string;
}

export interface GraphEdge { source: string; target: string; }

export interface Graph {
  branch: Branch;
  nodes: GraphNode[];
  edges: GraphEdge[];
  agents: string[];
  stats: Record<string, unknown>;
}


export interface AgentCard {
  id: string;
  version: string;
  role: string;
  summary: string;
  status: string;
  model: string;
  generation?: { thinking_level?: string; temperature?: number };
  tools: { name: string; determinism?: string; reversible?: boolean }[];
  data_policy: { sees: string[]; never_sees: string[] };
  delegates_to?: string[];
}

export interface Registry {
  registry: string;
  count: number;
  agents: AgentCard[];
  reversibility_classes?: Record<string, string>;
}

export interface Provenance {
  effect_id: string | null;
  model: string;
  derived_at: string;
  served: number;
}

export interface PolicyRow {
  key: string;
  answer: Record<string, unknown>;
  provenance: Provenance;
  confirmations: number;
  disagreements: number;
  invalidated: boolean;
}

export interface PolicyList {
  available: boolean;
  reason?: string;
  version?: string;
  ceiling?: number;
  populated?: number;
  matched?: number;
  rows?: PolicyRow[];
}

export type PolicyCell = PolicyRow & { available: boolean; version: string };

export interface Shadow {
  sampled: number;
  answered: number;
  confirmed: number;
  drifted: number;
  failed: number;
  drift_rate: number;
  drift_interval_95: [number, number];
  events: { key: string; fields: string[] }[];
}

export interface Necessity {
  available: boolean;
  reason?: string;
  ledger?: {
    period: string;
    decisions: number;
    served_from_table: number;
    served_from_model: number;
    model_calls_made: number;
    table_share: number;
    cost_usd: number;
    projected_naive_cost_usd: number;
    shadow: Shadow | null;
  };
  policy?: { version: string; populated: number; ceiling: number; occupancy: number };
  noise_floor?: { compared: number; disagreed: number; rate: number };
}


async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${detail.slice(0, 300)}`);
  }
  return res.json() as Promise<T>;
}

export interface SearchCandidateDTO {
  id: string;
  generation: number;
  text: string;
  rationale: string;
  parent_id: string | null;
  outcome: {
    total_cost_usd: number;
    wrongful_refunds_usd: number;
    missed_valid_usd: number;
    escalations: number;
    refunds_issued: number;
    compute_usd: number;
  } | null;
  error: string | null;
}

export const api = {
  branches: () => json<Branch[]>("/api/branches"),
  cohorts: (agents = 20000) =>
    json<{ agents: number; cohorts: { key: string; size: number; label: string }[];
           scenario: Record<string, number> }>(`/api/swarm/cohorts?agents=${agents}`),
  graph: (branch: string) => json<Graph>(`/api/branches/${branch}/graph`),
  /** The Necessity Ledger from the last recorded run. Returns `available: false`
   *  rather than zeros when no run exists — a necessity of 0% from a measurement
   *  that never happened is the most reassuring number here and the least true. */
  necessity: () => json<Necessity>("/api/necessity"),
  registry: () => json<Registry>("/api/registry"),
  policy: (q = "", limit = 60) =>
    json<PolicyList>(`/api/policy?limit=${limit}&q=${encodeURIComponent(q)}`),
  policyCell: (cell: string) =>
    json<PolicyCell>(`/api/policy/${encodeURIComponent(cell)}`),
};

/** Shared SSE reader. Both replay and search stream over POST, which EventSource
 *  cannot do, so frames are parsed by hand. */
async function readEvents(
  res: Response,
  onEvent: (event: Record<string, any>) => void,
): Promise<void> {
  if (!res.ok || !res.body) throw new Error(`stream failed: ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.trim();
      if (line.startsWith("data:")) {
        try { onEvent(JSON.parse(line.slice(5).trim())); } catch { /* partial frame */ }
      }
    }
  }
}

/** Stream a swarm run: one event per cohort as it resolves, distinguishing cohorts that
 *  reached the model from those served by the store. */
export async function streamSwarm(
  body: { agents?: number; concurrency?: number },
  onEvent: (event: Record<string, any>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/swarm", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  await readEvents(res, onEvent);
}
