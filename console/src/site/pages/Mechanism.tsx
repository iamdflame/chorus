import { AddressDemo } from "../AddressDemo";
import { Link } from "../router";

const STEPS = [
  {
    n: "01",
    title: "Project the situation, not the identity",
    body: "An agent is given only what determines its decision — loyalty tier, urgency band, party size, constraints — bucketed deliberately coarse. Name, destination and flight number are absent, because they decide which seat you are matched to, never what kind of itinerary you would accept. Every extra distinction multiplies cost, and a distinction that does not change the decision buys nothing.",
    code: "passenger | platinum | critical | solo | checked_bags",
  },
  {
    n: "02",
    title: "Address the call by its whole causal history",
    body: "Every model call is content-addressed. The role is the agent name rather than the individual, the request is the projection, and the causal parents include a round anchor so agents reasoning about the same world state share it. Two agents whose situations are genuinely equivalent compute the same address.",
    code: "address = H(kind, role, [causal parents], canonical request)",
  },
  {
    n: "03",
    title: "Let them collide",
    body: "Nothing in the runtime groups agents. Each is invoked independently with its own ADK session, unaware the others exist. The second agent to reach a given address is served from the store and never touches the model. The sharing is discovered, not assumed — which is why it holds for structure nobody anticipated.",
    code: "20,000 invocations → 1,964 model calls → 17,964 served from the store",
  },
];

export function Mechanism() {
  return (
    <div className="page">
      <section className="shell prose-head">
        <p className="eyebrow">Mechanism</p>
        <h1 className="display h2" style={{ maxWidth: "17ch" }}>
          A naive cache would be <em>wrong</em> here.
        </h1>
        <p className="lede">
          Sharing reasoning between agents is only sound if a collision genuinely means
          “these are the same computation”, not “these look similar”. Three properties
          make that true, and all three are enforced by the kernel rather than by
          convention.
        </p>
      </section>

      <section className="section">
        <div className="shell">
          <div className="steps">
            {STEPS.map((step) => (
              <article className="step reveal" key={step.n}>
                <span className="step-n">{step.n}</span>
                <div>
                  <h3 className="display h3">{step.title}</h3>
                  <p className="lede">{step.body}</p>
                  <code>{step.code}</code>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section">
        <div className="shell">
          <p className="eyebrow reveal">The split that keeps it honest</p>
          <h2 className="display h2 reveal" style={{ maxWidth: "16ch" }}>
            Reasoning is shared. <em>Acting is not.</em>
          </h2>
          <div className="two-up reveal-late">
            <p className="lede">
              <strong>Reasoning</strong> is a function of a situation — what would someone
              in this position accept. Thousands of agents share it, because thousands of
              agents are in the same position.
            </p>
            <p className="lede">
              <strong>Matching</strong> depends on identity and live inventory, so it is
              individual by nature. It never reaches a model at all: allocation under hard
              constraints is what deterministic code is good at, and a model would be both
              more expensive and worse.
            </p>
          </div>
        </div>
      </section>

      <section className="section closer">
        <div className="shell">
          <h2 className="display h2" style={{ maxWidth: "15ch" }}>
            Watch a cohort <em>share a thought</em>.
          </h2>
          <div className="hero-actions" style={{ marginTop: 34 }}>
            <Link to="/console" className="btn">Open the console <span className="arrow">→</span></Link>
            <Link to="/evidence" className="btn" data-variant="ghost">See the numbers</Link>
          </div>
        </div>
      </section>
    
      <section className="section">
        <div className="shell">
          <p className="eyebrow reveal">The address, live</p>
          <h2 className="display h2 reveal" style={{ maxWidth: "18ch" }}>
            Change a field. Watch the bucket move.
          </h2>
          <p className="lede reveal" style={{ marginBottom: "2rem" }}>
            Two travellers with different names, different bags and different departure
            times. Whether they share a thought depends on nothing except whether their
            projections land in the same cell.
          </p>
          <div className="reveal"><AddressDemo /></div>
        </div>
      </section>

      <section className="section">
        <div className="shell">
          <p className="eyebrow reveal">Cardinality</p>
          <h2 className="display h2 reveal" style={{ maxWidth: "20ch" }}>
            Saturation is arithmetic, not discovery.
          </h2>
          <div className="ceiling reveal">
            <p>
              The projection lattice has <strong>2,304 cells</strong>: 4 tiers × 4
              urgencies × 4 party sizes × 3 constraints × 3 hauls × 2 hotel × 2 misconnect.
              Collapse is bounded above by that number <strong>by construction</strong> —
              any bucketing scheme saturates, and publishing the ceiling is cheaper than
              having it discovered.
            </p>
            <p className="muted">
              So the interesting question is not whether it saturates. It is whether the
              bucketing is <em>lossless</em> — and on this workload it is not. Collapsed
              reasoning costs about 13% of tier-weighted satisfaction against reasoning per
              traveller, replicated across three runs. That measurement, and what recovers
              85% of it, is on the evidence page.
            </p>
          </div>
        </div>
      </section>
</div>
  );
}
