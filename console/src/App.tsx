import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamReplay, type Branch, type Diff, type Graph, type GraphNode, type Lightcone } from "./api";
import { Worldline } from "./gl/worldline";

const CEILING_CLAUSE = "POL-REFUND-CEILING";
const TIGHTENED =
  "Disputes with a claimed amount at or below USD 50.00 may be auto-approved for full " +
  "refund without human review, provided the customer has fewer than three prior " +
  "disputes. Amounts above the ceiling must be escalated.";

const usd = (n: number) =>
  `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** Per-effect costs are fractions of a cent; rounding them to two places renders every
 *  reasoning step as "$0.00" and destroys the comparison. */
const micro = (n: number) =>
  n === 0 ? "—" : n < 0.01 ? `$${n.toFixed(4)}` : usd(n);

export function App() {
  const stageRef = useRef<HTMLDivElement>(null);
  const worldRef = useRef<Worldline | null>(null);

  const [branches, setBranches] = useState<Branch[]>([]);
  const [active, setActive] = useState("primary");
  const [graph, setGraph] = useState<Graph | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [cone, setCone] = useState<Lightcone | null>(null);
  const [diff, setDiff] = useState<Diff | null>(null);
  const [log, setLog] = useState("");
  const [busy, setBusy] = useState(false);

  // Mount the renderer once. Pixi owns its canvas; React only owns the chrome around it.
  useEffect(() => {
    const world = new Worldline();
    worldRef.current = world;
    void (async () => {
      if (stageRef.current) await world.mount(stageRef.current);
    })();
    // Single teardown path; Worldline.destroy is idempotent and handles the case where
    // mount() is still awaiting init().
    return () => { world.destroy(); worldRef.current = null; };
  }, []);

  const loadBranches = useCallback(async () => {
    try { setBranches(await api.branches()); }
    catch (e) { setLog(`branches: ${(e as Error).message}`); }
  }, []);

  const loadGraph = useCallback(async (branch: string) => {
    try {
      const g = await api.graph(branch);
      setGraph(g);
      worldRef.current?.setGraph(g.nodes, g.edges, g.agents);
      worldRef.current?.clearCone();
      setSelected(null);
      setCone(null);
    } catch (e) {
      setLog(`graph: ${(e as Error).message}`);
    }
  }, []);

  useEffect(() => { void loadBranches(); }, [loadBranches]);
  useEffect(() => { void loadGraph(active); }, [active, loadGraph]);

  // Selecting an effect asks the server for its cone, then ignites it.
  useEffect(() => {
    const world = worldRef.current;
    if (!world) return;
    world.onSelect = (node) => {
      if (!node) { world.clearCone(); setSelected(null); setCone(null); return; }
      setSelected(node);
      api.lightcone(active, node.id)
        .then((lc) => { setCone(lc); world.ignite(node.id, lc.forward); })
        .catch((e) => setLog(`lightcone: ${(e as Error).message}`));
    };
  }, [active]);

  async function forkAndTighten() {
    setBusy(true);
    try {
      const seq = graph?.nodes.at(-1)?.seq ?? 0;
      const branch = await api.fork("primary", {
        name: "tighter-ceiling",
        at_seq: seq,
        perturbation: { clause: CEILING_CLAUSE, from: "USD 500.00", to: "USD 50.00" },
      });
      await api.editPolicy(branch.id, CEILING_CLAUSE, TIGHTENED);
      await loadBranches();
      setActive(branch.id);
      setLog(`forked ${branch.name} · refund ceiling 500 → 50`);
    } catch (e) {
      setLog(`fork: ${(e as Error).message}`);
    } finally { setBusy(false); }
  }

  async function replay() {
    setBusy(true);
    setLog("replaying…");
    try {
      await streamReplay(active, { limit: 6 }, (event) => {
        if (event.event === "dispute") {
          const r = event.running;
          setLog(
            `${event.index}/${event.total} ${event.dispute_id} · reused ${r.hits} · ` +
            `re-executed ${r.executed} · paid ${usd(r.cost_usd)} · avoided ${usd(r.cost_avoided_usd)}` +
            (r.quarantined ? ` · ${r.quarantined} staged` : ""),
          );
        } else if (event.event === "done") {
          setLog(`replay complete · root ${String(event.root_hash).slice(0, 16)}`);
        } else if (event.event === "error") {
          setLog(`${event.dispute_id}: ${event.error}`);
        }
      });
      await loadGraph(active);
      await loadBranches();
      if (active !== "primary") setDiff(await api.diff("primary", active));
    } catch (e) {
      setLog(`replay: ${(e as Error).message}`);
    } finally { setBusy(false); }
  }

  // Which half of the timeline the selection sits in, so the panel can move out of the
  // cone's way rather than occluding it.
  const seqs = graph?.nodes.map((n) => n.seq) ?? [];
  const selectionIsLate =
    selected !== null && seqs.length > 0
      ? (selected.seq - Math.min(...seqs)) / Math.max(Math.max(...seqs) - Math.min(...seqs), 1) > 0.55
      : false;

  const activeBranch = branches.find((b) => b.id === active);
  const stats = (graph?.stats ?? {}) as Record<string, number>;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="wordmark">LIGHT<span>CONE</span></div>
        <div className="tagline">version control for agent reality</div>
        <div className="spacer" />
        <nav className="rail">
          {branches.map((b) => (
            <button
              key={b.id}
              className="branch-chip"
              data-active={b.id === active}
              data-primary={b.is_primary}
              onClick={() => setActive(b.id)}
            >
              {b.name}
              {b.fork_at_seq !== null ? ` @${b.fork_at_seq}` : ""}
            </button>
          ))}
        </nav>
        <button className="action" onClick={forkAndTighten} disabled={busy}>
          fork · tighten ceiling
        </button>
        <button className="action" data-variant="primary" onClick={replay} disabled={busy}>
          {busy ? "working" : "replay"}
        </button>
      </header>

      <main className="stage" ref={stageRef}>
        {graph && graph.nodes.length === 0 && (
          <div className="empty">
            <strong>No recorded history on this timeline</strong>
            <span>Run scripts/verify_fleet_replay.py to record one, then reload.</span>
          </div>
        )}

        {selected && (
          <aside className="inspector" data-side={selectionIsLate ? "left" : "right"}>
            <h2>Effect</h2>
            <dl className="kv">
              <dt>address</dt><dd>{selected.id.slice(0, 20)}</dd>
              <dt>agent</dt><dd>{selected.agent}</dd>
              <dt>kind</dt><dd>{selected.label}</dd>
              <dt>class</dt><dd>{selected.determinism.replace(/_/g, " ")}</dd>
              <dt>seq</dt><dd>{selected.seq}</dd>
              <dt>tokens</dt><dd>{selected.tokens || "—"}</dd>
              <dt>cost</dt><dd>{micro(selected.cost_usd)}</dd>
              <dt>origin</dt><dd>{selected.inherited ? "inherited" : "executed here"}</dd>
            </dl>

            {cone && (
              <div className="cone-banner">
                <span className="cone-count">{cone.forward_count}</span>
                effects downstream across {cone.agents_touched.length} agent
                {cone.agents_touched.length === 1 ? "" : "s"}
                {cone.irreversible_downstream.length > 0 && (
                  <>
                    <h2 style={{ marginTop: 16 }}>Irreversible in cone</h2>
                    {cone.irreversible_downstream.slice(0, 6).map((a) => (
                      <div className="staged-item" key={a.id}>{a.action}</div>
                    ))}
                  </>
                )}
              </div>
            )}
          </aside>
        )}
      </main>

      <footer className="footer">
        <div className="readout">
          <div className="metric">
            <span className="metric-label">effects</span>
            <span className="metric-value">{stats.effects ?? 0}</span>
          </div>
          <div className="metric">
            <span className="metric-label">reused</span>
            <span className="metric-value" data-tone="accent">{stats.replayed ?? 0}</span>
          </div>
          {diff && (
            <>
              <div className="metric">
                <span className="metric-label">refund delta</span>
                <span className="metric-value" data-tone={diff.money.delta_refund_usd < 0 ? "accent" : "danger"}>
                  {usd(diff.money.delta_refund_usd)}
                </span>
              </div>
              <div className="metric">
                <span className="metric-label">staged</span>
                <span className="metric-value" data-tone="staged">{diff.staged_count}</span>
              </div>
            </>
          )}
        </div>

        <div className="log">{log ? <b>{log}</b> : `${activeBranch?.name ?? ""} · click an effect to compute its lightcone`}</div>

        <div className="legend">
          <span><i style={{ background: "#5ef0c8" }} />executed here</span>
          <span><i style={{ background: "#2f8f7c" }} />reasoning</span>
          <span><i style={{ background: "#232833" }} />inherited</span>
          <span><i style={{ background: "#8b7bff" }} />delegation</span>
          <span><i style={{ background: "#f5a524" }} />staged</span>
          <span><i style={{ background: "#ff5c5c" }} />irreversible</span>
        </div>
      </footer>
    </div>
  );
}
