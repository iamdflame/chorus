import { useEffect, useState } from "react";
import { api, type Registry as RegistryData } from "../../api";
import { LINKS } from "../links";

/** Governance, on the Plate.
 *
 *  An enterprise cannot approve what it cannot enumerate. Every agent publishes a card
 *  whose version is derived from its own definition — edit a prompt and the version moves
 *  on its own, with nobody remembering to bump it — and each card states the fields its
 *  agent is permitted to see, which tests/test_projection_leakage.py checks is actually
 *  true of the projection rather than merely written down. */
export function Registry() {
  const [data, setData] = useState<RegistryData | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    api.registry().then((d) => alive && setData(d)).catch(() => alive && setError(true));
    return () => { alive = false; };
  }, []);

  return (
    <div className="page">
      <section className="shell prose-head">
        <p className="eyebrow">Registry</p>
        <h1 className="display h1" style={{ maxWidth: "18ch" }}>
          An enterprise cannot approve what it cannot enumerate.
        </h1>
        <p className="lede">
          Every agent publishes a card whose version is the hash of its own definition —
          instruction, model, generation config, tool allowlist. Edit a prompt and the
          version moves on its own, because nobody remembers to bump one by hand.
        </p>
      </section>

      <section className="section">
        <div className="shell">
          {error && <p className="muted">Registry unreachable.</p>}
          {!data && !error && <p className="muted">Reading the registry…</p>}

          {data && (
            <>
              <p className="faint policy-count">
                {data.count} agents published · versions derived from content
              </p>
              <div className="cards">
                {data.agents.map((a) => (
                  <article key={a.id} className="card">
                    <header className="card-head">
                      <span className="data card-id">{a.id}</span>
                      <span className="data card-ver">v{a.version}</span>
                    </header>
                    <p className="card-summary">{a.summary}</p>

                    <dl className="card-meta">
                      <div><dt>model</dt><dd className="data">{a.model}</dd></div>
                      {a.generation?.thinking_level && (
                        <div>
                          <dt>thinking</dt>
                          <dd className="data">{a.generation.thinking_level}</dd>
                        </div>
                      )}
                      <div><dt>status</dt><dd className="data">{a.status}</dd></div>
                      <div>
                        <dt>tools</dt>
                        <dd className="data">
                          {a.tools.length ? a.tools.map((t) => t.name).join(", ") : "none"}
                        </dd>
                      </div>
                    </dl>

                    <div className="card-policy">
                      <p className="card-policy-head">Permitted to see</p>
                      <p className="data card-sees">{a.data_policy.sees.join(" · ")}</p>
                      <p className="card-policy-head">Never sees</p>
                      <p className="data card-never">{a.data_policy.never_sees.join(" · ")}</p>
                    </div>
                  </article>
                ))}
              </div>

              <div className="ceiling" style={{ marginTop: "2.5rem" }}>
                <p>
                  <strong>Coverage gaps are declared, not hidden.</strong> A capability with
                  no published agent escalates to a human rather than being routed to
                  whichever agent looked closest. An honest gap is cheaper than a confident
                  wrong answer, and a registry that always has a match is a registry that is
                  guessing.
                </p>
                <p className="muted">
                  Identity is enforced by IAM rather than by prompt. One service account per
                  agent role, and the allocator holds no model access at all — a model there
                  is unreachable rather than merely unused.{" "}
                  <a href={LINKS.repo} target="_blank" rel="noreferrer">
                    scripts/verify_controls.sh
                  </a>{" "}
                  attempts the forbidden action from each identity and reports the denial,
                  including two probes that must be <em>allowed</em>: an identity that can do
                  nothing proves only that it is broken.
                </p>
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
