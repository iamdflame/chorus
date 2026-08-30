import { Counter } from "../Counter";
import { SaturationChart } from "../SaturationChart";
import { LINKS } from "../links";
import { Link } from "../router";

const FACTS = [
  { v: 20000, dp: 0, label: "agents invoked", tone: undefined },
  { v: 222, dp: 0, label: "model calls made", tone: "accent" },
  { v: 19778, dp: 0, label: "served from the store", tone: undefined },
  { v: 0.2137, dp: 4, prefix: "$", label: "cost incurred", tone: "accent" },
  { v: 19.2539, dp: 4, prefix: "$", label: "cost at one call per agent", tone: undefined },
  { v: 361.5, dp: 1, suffix: "s", label: "wall clock", tone: undefined },
];

export function Evidence() {
  return (
    <div className="page">
      <section className="shell prose-head">
        <p className="eyebrow">Evidence</p>
        <h1 className="display h2" style={{ maxWidth: "18ch" }}>
          Every number here came out of a <em>run</em>, not a model of one.
        </h1>
        <p className="lede">
          Executed against live <strong>gemini-3.5-flash</strong> through Vertex AI, with
          real ADK sessions, real tool dispatch and real recorded effects. The proof
          scripts are in the repository and reproduce these figures.
        </p>
      </section>

      <section className="section">
        <div className="shell">
          <p className="eyebrow reveal">One run · 20,000 agents</p>
          <dl className="facts stagger">
            {FACTS.map((fact, i) => (
              <div className="fact" key={fact.label} data-tone={fact.tone}
                   style={{ "--i": i } as React.CSSProperties}>
                <dd className="fig">
                  {fact.prefix ?? ""}
                  <Counter to={fact.v} dp={fact.dp} />
                  {fact.suffix ?? ""}
                </dd>
                <dt>{fact.label}</dt>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section className="section">
        <div className="shell">
          <p className="eyebrow reveal">Saturation</p>
          <h2 className="display h2 reveal" style={{ maxWidth: "16ch" }}>
            The curve <em>flattens</em>. That is the whole result.
          </h2>
          <SaturationChart />
        </div>
      </section>

      <section className="section">
        <div className="shell">
          <p className="eyebrow reveal">Honest limits</p>
          <h2 className="display h2 reveal" style={{ maxWidth: "16ch" }}>
            What is synthetic, and what is not.
          </h2>
          <div className="two-up reveal-late">
            <p className="lede">
              The scenario is <strong>generated</strong>: 20,000 passengers, 320 crew and
              46 departures from a fixed seed, so a run is reproducible and two runs are
              comparable.
            </p>
            <p className="lede">
              The execution over it is <strong>entirely real</strong>. Every model call,
              every ADK session, every recorded effect and every figure on this site
              traces to something that actually ran.
            </p>
          </div>
        </div>
      </section>

      <section className="section closer">
        <div className="shell">
          <h2 className="display h2" style={{ maxWidth: "15ch" }}>
            Run it yourself.
          </h2>
          <div className="hero-actions" style={{ marginTop: 34 }}>
            <Link to="/console" className="btn">Open the console <span className="arrow">→</span></Link>
            <a className="btn" data-variant="ghost" href={LINKS.repo} target="_blank" rel="noreferrer">
              Read the source
            </a>
          </div>
        </div>
      </section>
    </div>
  );
}
