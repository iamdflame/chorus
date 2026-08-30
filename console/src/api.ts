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

export interface Lightcone {
  root: string;
  forward: string[];
  backward: string[];
  forward_count: number;
  backward_count: number;
  agents_touched: string[];
  irreversible_downstream: { id: string; agent: string; action: string }[];
  cost_downstream_usd: number;
}

export interface Diff {
  left: string;
  right: string;
  causal: Record<string, number>;
  state_changes: Record<string, { left: unknown; right: unknown }>;
  money: {
    left: { refund_count: number; refund_total_usd: number; emails_sent: number; tickets_open: number };
    right: { refund_count: number; refund_total_usd: number; emails_sent: number; tickets_open: number };
    delta_refund_usd: number;
    delta_refund_count: number;
  };
  staged_actions: { id: string; agent: string; action: string }[];
  staged_count: number;
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
  effect: (branch: string, id: string) =>
    json<Record<string, unknown>>(`/api/branches/${branch}/effects/${id}`),
  lightcone: (branch: string, id: string) =>
    json<Lightcone>(`/api/branches/${branch}/effects/${id}/lightcone`),
  diff: (left: string, right: string) => json<Diff>(`/api/branches/${left}/diff/${right}`),
  world: (branch: string, collection: string, atSeq?: number) =>
    json<Record<string, any>>(
      `/api/branches/${branch}/world/${collection}` + (atSeq ? `?at_seq=${atSeq}` : ""),
    ),
  fork: (branch: string, body: { name: string; at_seq: number; perturbation?: unknown }) =>
    json<Branch>(`/api/branches/${branch}/fork`, { method: "POST", body: JSON.stringify(body) }),
  editPolicy: (branch: string, clause: string, text: string) =>
    json<Record<string, unknown>>(`/api/branches/${branch}/policies/${clause}`, {
      method: "PATCH",
      body: JSON.stringify({ text }),
    }),
  adopt: (clause_id: string, text: string) =>
    json<Record<string, unknown>>("/api/policies/adopt", {
      method: "POST",
      body: JSON.stringify({ clause_id, text }),
    }),
  merge: (branch: string, into = "primary", force = false) =>
    json<Record<string, unknown>>(`/api/branches/${branch}/merge`, {
      method: "POST",
      body: JSON.stringify({ into, force }),
    }),
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

/** Stream a policy search: candidates fork, replay against real history, and settle
 *  onto a cost frontier one at a time. */
export async function streamSearch(
  body: { dispute_ids?: string[]; generations?: number; population?: number },
  onEvent: (event: Record<string, any>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/search", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  await readEvents(res, onEvent);
}

/** Stream a replay. Server-Sent Events over POST, so it is read manually rather than
 *  with EventSource — the payload matters and EventSource cannot POST. */
export async function streamReplay(
  branch: string,
  body: { dispute_ids?: string[]; limit?: number },
  onEvent: (event: Record<string, any>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api/branches/${branch}/replay`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  await readEvents(res, onEvent);
}
