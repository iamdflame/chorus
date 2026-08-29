import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamReplay, streamSearch, streamSwarm, type Branch, type Diff, type Graph, type GraphNode, type Lightcone } from "./api";
import { Worldline } from "./gl/worldline";
import { SearchView, type SearchCandidate } from "./ui/SearchView";
import { Murmuration, type Cohort } from "./gl/murmuration";

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

  const [mode, setMode] = useState<"swarm" | "worldline" | "search">("swarm");
  const swarmRef = useRef<HTMLDivElement>(null);
  const murmurRef = useRef<Murmuration | null>(null);
  const [swarmStats, setSwarmStats] = useState<Record<string, number> | null>(null);
  const [searchBaseline, setSearchBaseline] = useState<SearchCandidate | null>(null);
  const [searchCandidates, setSearchCandidates] = useState<SearchCandidate[]>([]);
  const [searchWinner, setSearchWinner] = useState<SearchCandidate | null>(null);
  // Fixed for now; the search is real model traffic and the API key is rate limited.
  const generations = 2;

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

  useEffect(() => {
    const murmur = new Murmuration();
    murmurRef.current = murmur;
    void (async () => {
      if (swarmRef.current) await murmur.mount(swarmRef.current);
    })();
    return () => { murmur.destroy(); murmurRef.current = null; };
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

  async function runSwarm(agents: number) {
    setBusy(true);
    setMode("swarm");
    setSwarmStats(null);
    murmurRef.current?.reset();
    setLog(`waking ${agents.toLocaleString()} agents…`);
    try {
      await streamSwarm({ agents, concurrency: 6 }, (event) => {
        if (event.event === "swarm_start") {
          murmurRef.current?.setCohorts(event.cohorts as Cohort[]);
          setLog(
            `${event.agents.toLocaleString()} agents · ${event.cohorts.length} distinct situations · ` +
            `${event.scenario.souls_on_board.toLocaleString()} souls for ${event.scenario.seats_available.toLocaleString()} seats`,
          );
        } else if (event.event === "progress") {
          if (event.cohort) {
            if (event.thought) murmurRef.current?.think(event.cohort);
            else murmurRef.current?.share(event.cohort);
          }
          setSwarmStats(event as Record<string, number>);
          setLog(
            `${event.done.toLocaleString()}/${event.total.toLocaleString()} agents · ` +
            (event.model_calls === 0
              ? `every thought already recorded — replayed for $0.00`
              : `${event.model_calls} thoughts · ${event.cache_hits.toLocaleString()} shared · ${usd(event.cost_usd)}`),
          );
        } else if (event.event === "swarm_done") {
          setSwarmStats(event.metrics as Record<string, number>);
          const m = event.metrics;
          setLog(
            `${m.agents_invoked.toLocaleString()} agents reasoned for ${usd(m.cost_usd)} — ` +
            `${m.collapse}x fewer thoughts than agents (naive: ${usd(m.naive_cost_usd)})`,
          );
        }
      });
    } catch (e) {
      setLog(`swarm: ${(e as Error).message}`);
    } finally { setBusy(false); }
  }

  async function runSearch() {
    setBusy(true);
    setMode("search");
    setSearchBaseline(null);
    setSearchCandidates([]);
    setSearchWinner(null);
    setLog("searching policy space against recorded history…");
    try {
      await streamSearch({ generations, population: 3 }, (event) => {
        if (event.event === "baseline") {
          setSearchBaseline(event.candidate);
          setLog(`production policy costs $${event.candidate.outcome.total_cost_usd.toFixed(2)} on this history — searching for better`);
        } else if (event.event === "generation_start") {
          setLog(`generation ${event.generation}: ${event.candidates.length} proposals from gemini-3.5-flash`);
        } else if (event.event === "evaluated") {
          setSearchCandidates((prev) => [...prev, event.candidate]);
          const o = event.candidate.outcome;
          if (o) {
            const delta = event.baseline_cost - o.total_cost_usd;
            setLog(
              `${event.candidate.id} · ${usd(o.total_cost_usd)} (${delta > 0 ? "−" : "+"}${usd(Math.abs(delta))}) · ` +
              `${event.running.evaluations} evaluations · ${event.running.replay_hits} crossings reused · ` +
              `${usd(event.running.compute_usd)} compute`,
            );
          }
        } else if (event.event === "search_done") {
          setSearchWinner(event.winner);
          setLog(
            event.improvement_usd > 0
              ? `search complete · found a policy worth ${usd(event.improvement_usd)} on this history across ${event.evaluations} full fleet evaluations`
              : `search complete · no candidate beat production across ${event.evaluations} evaluations`,
          );
        }
      });
      await loadBranches();
    } catch (e) {
      setLog(`search: ${(e as Error).message}`);
    } finally { setBusy(false); }
  }

  async function adopt(candidate: SearchCandidate) {
    try {
      await api.adopt("POL-REFUND-CEILING", candidate.text);
      setLog("adopted into production · the fleet now runs the policy it proved");
      await loadGraph(active);
    } catch (e) {
      setLog(`adopt: ${(e as Error).message}`);
    }
  }

  const activeBranch = branches.find((b) => b.id === active);
  const stats = (graph?.stats ?? {}) as Record<string, number>;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="wordmark">CHO<span>RUS</span></div>
        <div className="tagline">
          {mode === "swarm"
            ? "twenty thousand agents · two hundred thoughts"
            : "shared cognition for agent swarms"}
        </div>
        <div className="spacer" />
        <nav className="rail">
          {mode !== "swarm" && branches.map((b) => (
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
        <div className="mode-rail">
          <button className="branch-chip" data-active={mode === "swarm"}
                  onClick={() => setMode("swarm")}>swarm</button>
          <button className="branch-chip" data-active={mode === "worldline"}
                  onClick={() => setMode("worldline")}>worldline</button>
          <button className="branch-chip" data-active={mode === "search"}
                  onClick={() => setMode("search")}>search</button>
        </div>
        <button className="action" data-variant={mode === "swarm" ? "primary" : undefined}
                onClick={() => runSwarm(20000)} disabled={busy}>
          {busy && mode === "swarm" ? "thinking" : "wake 20,000"}
        </button>
        {mode !== "swarm" && (
          <>
            <button className="action" onClick={forkAndTighten} disabled={busy}>
              fork
            </button>
            <button className="action" onClick={replay} disabled={busy}>
              replay
            </button>
            <button className="action" data-variant="primary" onClick={runSearch}
                    disabled={busy}>
              {busy ? "searching" : "optimise fleet"}
            </button>
          </>
        )}
      </header>

      <div className="swarm-stage" ref={swarmRef} data-visible={mode === "swarm"} />
      <main className="stage" ref={stageRef} data-visible={mode !== "swarm"}>
        {mode === "search" && (
          <SearchView
            baseline={searchBaseline}
            candidates={searchCandidates}
            generations={generations}
            running={busy}
            winner={searchWinner}
            onAdopt={adopt}
          />
        )}
        {mode === "worldline" && graph && graph.nodes.length === 0 && (
          <div className="empty">
            <strong>No recorded history on this timeline</strong>
            <span>Run scripts/verify_fleet_replay.py to record one, then reload.</span>
          </div>
        )}

        {mode === "worldline" && selected && (
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
          {mode === "swarm" && swarmStats ? (
            <>
              <div className="metric">
                <span className="metric-label">agents</span>
                <span className="metric-value">{(swarmStats.agents_invoked ?? 0).toLocaleString()}</span>
              </div>
              <div className="metric">
                <span className="metric-label">
                  {swarmStats.model_calls === 0 ? "thoughts · replayed" : "thoughts"}
                </span>
                <span className="metric-value" data-tone="accent">
                  {swarmStats.model_calls ?? 0}
                </span>
              </div>
              <div className="metric">
                <span className="metric-label">cost</span>
                <span className="metric-value">{usd(swarmStats.cost_usd ?? 0)}</span>
              </div>
              <div className="metric">
                <span className="metric-label">collapse</span>
                <span className="metric-value" data-tone="accent">{swarmStats.collapse ?? 0}x</span>
              </div>
            </>
          ) : (
          <>
          <div className="metric">
            <span className="metric-label">effects</span>
            <span className="metric-value">{stats.effects ?? 0}</span>
          </div>
          <div className="metric">
            <span className="metric-label">reused</span>
            <span className="metric-value" data-tone="accent">{stats.replayed ?? 0}</span>
          </div>
          </>
          )}
          {searchWinner?.outcome && searchBaseline?.outcome && (
            <div className="metric">
              <span className="metric-label">found</span>
              <span className="metric-value" data-tone="accent">
                −{usd(searchBaseline.outcome.total_cost_usd - searchWinner.outcome.total_cost_usd)}
              </span>
            </div>
          )}
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
          {mode === "swarm" ? (
            <>
              <span><i style={{ background: "#1c2029" }} />not yet woken</span>
              <span><i style={{ background: "#ffffff" }} />reached the model</span>
              <span><i style={{ background: "#2f8f7c" }} />shared a thought</span>
              <span>each cloud is one cohort · area = population</span>
            </>
          ) : (
            <>
              <span><i style={{ background: "#5ef0c8" }} />executed here</span>
              <span><i style={{ background: "#2f8f7c" }} />reasoning</span>
              <span><i style={{ background: "#232833" }} />inherited</span>
              <span><i style={{ background: "#8b7bff" }} />delegation</span>
              <span><i style={{ background: "#ff5c5c" }} />irreversible</span>
            </>
          )}
        </div>
      </footer>
    </div>
  );
}
