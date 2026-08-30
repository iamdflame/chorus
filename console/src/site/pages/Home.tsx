import { HeroField } from "../HeroField";
import { Link } from "../router";
import { Counter } from "../Counter";
import { SaturationChart } from "../SaturationChart";

const PILLARS = [
  {
    n: "01",
    title: "One agent per entity",
    body: "Not a fleet processing a queue. Every passenger, every crew member, every aircraft gets its own agent with its own situation and its own interests.",
  },
  {
    n: "02",
    title: "Reasoning is shared",
    body: "An agent reasons over a canonical projection of itself. Two agents whose situations are genuinely equivalent compute the same address and share a single thought.",
  },
  {
    n: "03",
    title: "Acting stays private",
    body: "Which seat a specific passenger gets depends on identity and live inventory, so it never reaches a model at all. Deterministic allocation over shared preferences.",
  },
];

export function Home() {
  return (
    <>
      <section className="hero">
        <HeroField />
        <div className="shell hero-inner">
          <p className="eyebrow">All Things Agentic · Fortified Enterprise Fleet</p>
          <h1 className="display h1">
            Twenty thousand agents.<br />
            <em>Two thousand thoughts.</em>
          </h1>
          <p className="lede hero-lede">
            Reasoning now costs less than a database query, so every entity in a system
            could have its own permanent agent. Nobody builds that — twenty thousand
            agents means twenty thousand model calls. <strong>Unless identical reasoning
            is computed once.</strong>
          </p>
          <div className="hero-actions">
            <Link to="/console" className="btn">
              Wake the swarm <span className="arrow">→</span>
            </Link>
            <Link to="/mechanism" className="btn" data-variant="ghost">
              How it works
            </Link>
          </div>

          <dl className="hero-stats stagger">
            {[
              { k: "agents", v: 20000, suffix: "" },
              { k: "model calls", v: 1964, suffix: "" },
              { k: "cost", v: 1.9394, prefix: "$", dp: 4 },
              { k: "collapse", v: 10.2, suffix: "×", dp: 1 },
            ].map((stat, i) => (
              <div key={stat.k} style={{ "--i": i } as React.CSSProperties}>
                <dd className="fig">
                  {stat.prefix ?? ""}
                  <Counter to={stat.v} dp={stat.dp ?? 0} />
                  {stat.suffix ?? ""}
                </dd>
                <dt>{stat.k}</dt>
              </div>
            ))}
          </dl>
        </div>
        <div className="hero-fade" aria-hidden="true" />
      </section>

      <section className="section" id="problem">
        <div className="shell">
          <p className="eyebrow reveal">The wall everyone hits</p>
          <h2 className="display h2 reveal" style={{ maxWidth: "18ch" }}>
            A swarm is priced by its <em>population</em>. It should be priced by its
            <em> variety</em>.
          </h2>
          <div className="two-up reveal-late">
            <p className="lede">
              Give twenty thousand travellers their own agent and you have twenty thousand
              model calls — unaffordable, rate-limited, and mostly redundant. Most of those
              agents are not thinking different thoughts.
            </p>
            <p className="lede">
              Two stranded platinum passengers, both travelling alone, both needing to move
              within four hours, both with a checked bag, face the <strong>same decision</strong>.
              Their names differ. Their reasoning does not.
            </p>
          </div>
        </div>
      </section>

      <section className="section" id="pillars">
        <div className="shell">
          <div className="pillars stagger">
            {PILLARS.map((pillar, i) => (
              <article key={pillar.n} style={{ "--i": i } as React.CSSProperties}>
                <span className="pillar-n">{pillar.n}</span>
                <h3 className="display h3">{pillar.title}</h3>
                <p className="lede">{pillar.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section" id="saturation">
        <div className="shell">
          <p className="eyebrow reveal">Measured, not modelled</p>
          <h2 className="display h2 reveal" style={{ maxWidth: "16ch" }}>
            Thought count <em>saturates</em>. Agent count does not.
          </h2>
          <p className="lede reveal" style={{ marginTop: 22 }}>
            Five hundred agents need a hundred and twenty-eight distinct thoughts. Twenty
            thousand need a hundred and ninety-two. <strong>Twelve thousand extra agents
            cost five more thoughts.</strong>
          </p>
          <SaturationChart />
        </div>
      </section>

      <section className="section" id="works">
        <div className="shell">
          <p className="eyebrow reveal">And it produces a better answer</p>
          <h2 className="display h2 reveal" style={{ maxWidth: "17ch" }}>
            Same seats. Same passengers. <em>Better recovery.</em>
          </h2>
          <div className="compare reveal-late">
            <table>
              <thead>
                <tr><th /><th>First come</th><th>Chorus</th><th /></tr>
              </thead>
              <tbody>
                <tr><td>souls seated</td><td className="fig">2,888</td><td className="fig">2,888</td><td className="flat">saturated</td></tr>
                <tr className="hot"><td>weighted satisfaction</td><td className="fig">1,131.3</td><td className="fig">2,173.9</td><td className="up">+92%</td></tr>
                <tr><td>mean wait (hours)</td><td className="fig">17.12</td><td className="fig">16.76</td><td className="up">−0.36</td></tr>
              </tbody>
            </table>
            <p className="lede compare-note">
              Souls seated is deliberately not the headline. With 2,888 seats against
              20,367 souls the seat budget binds, so every competent allocator fills every
              seat and that number saturates. Under a fixed budget the question is not how
              many people move — it is <strong>which</strong>.
            </p>
          </div>
        </div>
      </section>

      <section className="section closer">
        <div className="shell">
          <h2 className="display h2" style={{ maxWidth: "15ch" }}>
            See twenty thousand agents think <em>two hundred times</em>.
          </h2>
          <div className="hero-actions" style={{ marginTop: 34 }}>
            <Link to="/console" className="btn">
              Open the console <span className="arrow">→</span>
            </Link>
            <Link to="/evidence" className="btn" data-variant="ghost">
              Read the evidence
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
