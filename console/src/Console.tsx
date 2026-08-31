import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamSwarm } from "./api";
import { Murmuration, type Cohort } from "./gl/murmuration";

/** The console does one thing.
 *
 *  It used to carry three modes — swarm, causal worldline, policy search — behind a mode
 *  rail. Two of them answered a question the product no longer asks, and a rail of modes
 *  is the fastest way to make a single idea feel like three unfinished ones. Depth now
 *  lives inside the one view: point at a cohort and you get its situation, its
 *  population, and the thought it shared. */

import type { CohortSummary } from "./gl/murmuration";

interface Stats {
  agents_invoked: number;
  model_calls: number;
  cache_hits: number;
  collapse: number;
  cost_usd: number;
  naive_cost_usd: number;
}

const usd = (n: number) => `$${n.toFixed(n < 1 ? 4 : 2)}`;
const num = (n: number) => n.toLocaleString();

/** "passenger|platinum|critical|solo|checked_bags" -> readable chips. */
function facets(key: string): string[] {
  return key.split("|").slice(1).map((f) => f.replace(/_/g, " "));
}

export function Console() {
  const stageRef = useRef<HTMLDivElement>(null);
  const murmurRef = useRef<Murmuration | null>(null);

  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [scenario, setScenario] = useState<Record<string, number> | null>(null);
  const [cohortCount, setCohortCount] = useState(0);
  const [stats, setStats] = useState<Stats | null>(null);
  const [selected, setSelected] = useState<CohortSummary | null>(null);
  const [hovered, setHovered] = useState<CohortSummary | null>(null);
  const [thoughts, setThoughts] = useState<Record<string, unknown>>({});
  const [note, setNote] = useState("");

  useEffect(() => {
    const murmur = new Murmuration();
    murmurRef.current = murmur;
    murmur.onHover = (c) => setHovered(c);
    murmur.onSelect = (c) => setSelected(c);

    void (async () => {
      if (!stageRef.current) return;
      await murmur.mount(stageRef.current);
      try {
        const { cohorts, scenario: s } = await api.cohorts(20000);
        murmur.setCohorts(cohorts as Cohort[]);
        setScenario(s);
        setCohortCount(cohorts.length);
        setReady(true);
      } catch (e) {
        setNote(`could not load the population: ${(e as Error).message}`);
      }
    })();

    return () => { murmur.destroy(); murmurRef.current = null; };
  }, []);

  const wake = useCallback(async () => {
    setBusy(true);
    setStats(null);
    setThoughts({});
    murmurRef.current?.reset();
    setNote("waking 20,000 agents…");
    try {
      await streamSwarm({ agents: 20000, concurrency: 8 }, (event) => {
        // The server caps an unauthenticated caller and says so in the opening frame.
        // Ignoring that would leave the counters reading 300 while the page still claims
        // twenty thousand — the interface contradicting itself in the one place a viewer
        // is reading numbers off the screen.
        if (event.event === "capped") {
          setNote(
            `capped to ${num(event.running as number)} agents — the public demo ceiling. ` +
            `A write token lifts it.`,
          );
        } else if (event.event === "progress") {
          if (event.cohort) {
            if (event.thought) murmurRef.current?.think(event.cohort);
            else murmurRef.current?.share(event.cohort);
            if (event.preference) {
              setThoughts((prev) => ({ ...prev, [event.cohort]: event.preference }));
            }
          }
          setStats(event as unknown as Stats);
          setNote("");
        } else if (event.event === "swarm_done") {
          setStats(event.metrics as Stats);
          const m = event.metrics;
          setNote(
            m.model_calls === 0
              ? "every thought was already recorded — replayed for $0.00"
              : `${num(m.agents_invoked)} agents reasoned ${m.model_calls} times for ${usd(m.cost_usd)}`,
          );
        }
      });
    } catch (e) {
      setNote(`swarm failed: ${(e as Error).message}`);
    } finally { setBusy(false); }
  }, []);

  const focus = selected ?? hovered;
  const thought = selected ? thoughts[selected.key] : undefined;

  return (
    <div className="cx">
      <div className="cx-bar">
        <p className="cx-scenario">
          {scenario ? (
            <>
              <b>{num(scenario.passengers)}</b> agents
              <i /> <b>{cohortCount}</b> distinct situations
              <i /> <b>{num(scenario.souls_on_board)}</b> souls for{" "}
              <b>{num(scenario.seats_available)}</b> seats
            </>
          ) : (
            "loading the population…"
          )}
        </p>
        <button className="btn" onClick={wake} disabled={busy || !ready}>
          {busy ? "thinking…" : "Wake the swarm"} <span className="arrow">→</span>
        </button>
      </div>

      <div className="cx-stage" ref={stageRef}>
        {focus && (
          <aside
            className="cx-card"
            data-pinned={Boolean(selected)}
            /* Sit opposite the cohort so the card never covers the cell it describes. */
            data-side={focus.xFraction > 0.5 ? "left" : "right"}
          >
            <h2>{selected ? "Cohort" : "Cohort · hover"}</h2>
            <div className="cx-facets">
              {facets(focus.key).map((f) => <span key={f}>{f}</span>)}
            </div>
            <dl className="cx-kv">
              <dt>agents</dt><dd>{num(focus.size)}</dd>
              <dt>status</dt>
              <dd data-status={focus.status}>
                {focus.status === "thinking" ? "reaching the model"
                  : focus.status === "thought" ? "reached the model"
                  : focus.status === "shared" ? "shared a thought"
                  : "not yet woken"}
              </dd>
            </dl>
            {thought ? (
              <>
                <h2>The thought they share</h2>
                <pre className="cx-thought">{JSON.stringify(thought, null, 2)}</pre>
                <p className="cx-foot">
                  Computed once. Inherited by all {num(focus.size)}.
                </p>
              </>
            ) : selected ? (
              <p className="cx-foot">Wake the swarm to see what this cohort decides.</p>
            ) : (
              <p className="cx-foot">Click to pin.</p>
            )}
          </aside>
        )}
      </div>

      <div className="cx-readout" data-run={Boolean(stats)}>
        {stats ? (
          <>
            <Metric label="agents" value={num(stats.agents_invoked)} />
            <Metric label="thoughts" value={String(stats.model_calls)} tone="accent" />
            <Metric label="shared" value={num(stats.cache_hits)} />
            <Metric label="cost" value={usd(stats.cost_usd)} tone="accent" />
            <Metric label="instead of" value={usd(stats.naive_cost_usd)} tone="muted" />
            {/* A fully replayed run has no collapse ratio: nothing was computed. */}
            <Metric
              label={stats.collapse ? "collapse" : "replayed"}
              value={stats.collapse ? `${stats.collapse}×` : "free"}
              tone="accent"
            />
          </>
        ) : (
          <>
            <Metric label="agents" value={scenario ? num(scenario.passengers) : "—"} />
            <Metric label="distinct situations" value={cohortCount ? String(cohortCount) : "—"} tone="accent" />
            <Metric label="souls" value={scenario ? num(scenario.souls_on_board) : "—"} />
            <Metric label="seats" value={scenario ? num(scenario.seats_available) : "—"} tone="muted" />
          </>
        )}
        <p className="cx-note">
          {note || (stats
            ? "Each cloud is one cohort. Area is population."
            : "Nothing has been woken yet. Each cloud is one cohort; area is population.")}
        </p>
      </div>
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="cx-metric">
      <span className="cx-metric-value fig" data-tone={tone}>{value}</span>
      <span className="cx-metric-label">{label}</span>
    </div>
  );
}
