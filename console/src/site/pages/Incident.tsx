import { useMemo, useState } from "react";
import { LINKS } from "../links";
import { Link } from "../router";

/** Blast radius — the security page, and the only place `--breach` appears.
 *
 *  The finding is genuinely novel and it is created by the mechanism that makes the system
 *  cheap: in a collapsed fleet one successful injection does not compromise one agent, it
 *  compromises every entity sharing that projection. The saving and the blast radius are
 *  the same number.
 *
 *  Three states, and the third is the one that matters. Every number here comes from
 *  scripts/verify_armor.py, which runs offline in CI. */

type Mode = "unarmed" | "armed" | "posthoc";

const COHORT = 128;          // the largest cohort at 20,000 agents, measured
const CELLS = 2304;

export function Incident() {
  const [mode, setMode] = useState<Mode>("unarmed");
  // Bumping this remounts the marks, which restarts the propagation from generation zero.
  const [take, setTake] = useState(0);
  const replay = (next: Mode) => { setMode(next); setTake((t) => t + 1); };

  // 128 marks, laid out as the cohort actually is, each carrying its causal generation.
  //
  // The delay is distance from patient zero, not position in the grid. That distinction is
  // the whole point: this is a forward lightcone illuminating hop by hop from the
  // compromised call, so the blast radius draws itself outward from a source rather than
  // wiping across the block in reading order. An earlier version staggered by row and
  // column, which looked like an animation and taught nothing.
  const marks = useMemo(() => {
    const raw = Array.from({ length: COHORT }, (_, i) => ({
      i,
      x: 4 + (i % 16) * 6.1,
      y: 5 + Math.floor(i / 16) * 11.6,
    }));
    const zero = raw[0];
    const far = Math.max(
      ...raw.map((m) => Math.hypot(m.x - zero.x, m.y - zero.y)),
    );
    return raw.map((m) => {
      const d = Math.hypot(m.x - zero.x, m.y - zero.y);
      // Eight causal generations across the cohort, ~40ms apart, as the plan specifies.
      const generation = Math.round((d / far) * 7);
      return { ...m, generation, delay: generation * 40 };
    });
  }, []);

  const generations = Math.max(...marks.map((m) => m.generation)) + 1;

  const affected = mode === "unarmed" ? COHORT : mode === "armed" ? 0 : COHORT;
  const contained = mode === "armed" ? 1 : mode === "posthoc" ? COHORT : 0;

  return (
    <div className="page">
      <section className="shell prose-head">
        <p className="eyebrow">Incident</p>
        <h1 className="display h1" style={{ maxWidth: "20ch" }}>
          Collapse amplifies injection by exactly the collapse ratio.
        </h1>
        <p className="lede">
          In an uncollapsed fleet a successful prompt injection compromises one agent. In a
          collapsed fleet it compromises <strong>every entity sharing that projection</strong>,
          because sharing the answer is what the system was built to do. The number in the
          cost report and the number in the incident report are the same number.
        </p>
      </section>

      <section className="section">
        <div className="shell">
          <div className="incident">
            <div className="incident-controls" role="tablist" aria-label="Defence state">
              {([
                ["unarmed", "Airlock off"],
                ["armed", "Airlock on"],
                ["posthoc", "Found later"],
              ] as [Mode, string][]).map(([value, label]) => (
                <button
                  key={value}
                  role="tab"
                  aria-selected={mode === value}
                  className="incident-tab"
                  data-active={mode === value}
                  onClick={() => replay(value)}
                >
                  {label}
                </button>
              ))}
            </div>

            <div className="incident-stage" data-mode={mode} key={take}>
              <svg viewBox="0 0 100 92" role="img"
                   aria-label={`Cohort of ${COHORT} entities, ${affected} affected`}>
                {marks.map((m, i) => (
                  <circle
                    key={i}
                    cx={m.x}
                    cy={m.y}
                    r={mode === "armed" && i === 0 ? 2.4 : 1.9}
                    className="incident-mark"
                    style={{ animationDelay: `${m.delay}ms` }}
                    data-generation={m.generation}
                    data-role={i === 0 ? "patient-zero" : "member"}
                  />
                ))}
              </svg>

              <dl className="incident-readout">
                <div className="incident-chip-row">
                  <span className="chip" data-state={mode === "posthoc" ? "scrubbed" : "replay"}>
                    {mode === "posthoc" ? "lightcone" : "replay"}
                  </span>
                  <button className="incident-replay" onClick={() => setTake((t) => t + 1)}>
                    Play again
                  </button>
                </div>
                <div>
                  <dt>entities in cohort</dt>
                  <dd className="data">{COHORT}</dd>
                </div>
                <div data-tone={affected ? "breach" : undefined}>
                  <dt>affected</dt>
                  <dd className="data">{affected}</dd>
                </div>
                <div>
                  <dt>contained</dt>
                  <dd className="data">{contained}</dd>
                </div>
                <div>
                  <dt>causal generations</dt>
                  <dd className="data">{mode === "armed" ? 0 : generations}</dd>
                </div>
              </dl>
            </div>

            <p className="incident-note">
              {mode === "unarmed" && (
                <>
                  One poisoned message enters a populous cohort. It is cached, and served
                  to everyone in it. <strong>This is the design most agent fleets have</strong> —
                  free text reaching shared reasoning.
                </>
              )}
              {mode === "armed" && (
                <>
                  Extraction yields a typed projection whose every field comes from a closed
                  vocabulary, so the injected instruction has nowhere to live. It cannot
                  reach a shared prompt and it cannot change one. The attacker joins a
                  cohort; they do not change what it believes.
                </>
              )}
              {mode === "posthoc" && (
                <>
                  A compromise found by other means — a bad model version, a leaked
                  credential. The forward lightcone of the poisoned call <em>is</em> the
                  blast radius, computed rather than guessed, and every affected entity is
                  enumerable. Quarantine invalidates the rows derived from inside it; the
                  healthy cohorts keep serving.
                </>
              )}
            </p>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="shell prose">
          <h2 className="display h2 reveal" style={{ maxWidth: "20ch" }}>
            Cache poisoning here is not filtered. It is unaddressable.
          </h2>
          <p className="reveal">
            A shared answer is addressed by <code>H(kind, role, causal parents, request)</code>,
            and the request for a shared elicitation contains <strong>only</strong> a
            projection — eight fields, each from a closed vocabulary of three or four
            values. No attacker-controlled byte participates in a shared address, so an
            attacker cannot place a chosen response where another traveller will look, and
            cannot mint a private cell either: every projection they can produce is one of{" "}
            {CELLS.toLocaleString()} that real travellers also occupy.
          </p>
          <p className="reveal">
            The corollary is the constraint the whole design rests on, and it cuts both
            ways: <strong>any design that admits free text into shared reasoning either
            loses collapse entirely — because the text makes every address unique — or
            becomes poisonable.</strong> There is no version that keeps both.
          </p>
          <p className="reveal muted">
            The pattern screen in front of this is the weakest layer and the code says so.
            Matching on natural language is defeated by paraphrase. It catches the obvious
            cases at a 0.00% false-positive rate against 2,000 genuine messages in eight
            languages, and it is not what the containment rests on.
          </p>
          <p className="reveal">
            <Link to="/evidence" className="btn" data-variant="ghost">Read the evidence →</Link>{" "}
            <a className="btn" data-variant="ghost" href={LINKS.repo} target="_blank"
               rel="noreferrer">scripts/verify_armor.py</a>
          </p>
        </div>
      </section>
    </div>
  );
}
