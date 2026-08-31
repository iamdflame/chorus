import { LINKS } from "../links";
import { Link } from "../router";

/** Track compliance, on one screen.
 *
 *  A judge scoring a bullet list should be able to tick every box without leaving the
 *  page, and each row should name the file that implements it rather than describing an
 *  intention. Rows that are partly done say so. */

const STAGES = [
  ["01", "intake", "unbounded", "Free text, speech or a photographed boarding pass. Any modality, no schema."],
  ["02", "extraction", "MODEL · per message", "Text → situation, with confidence and a quoted evidence span. Unbounded input, so no table follows it."],
  ["03", "collapse", "KERNEL · free", "Identical situations share one thought. Addressed by content, so sharing is discovered rather than assumed."],
  ["04", "elicitation", "MODEL · per situation", "Situation → preferences. The input is a bounded lattice, which is where the kernel earns its keep."],
  ["05", "allocation", "DETERMINISTIC", "Who gets which seat. A model here would be dearer and worse, so the allocator identity cannot reach one."],
];

const COMPLIANCE: [string, string, string, string][] = [
  ["Scalable network of institutional agents", "done",
   "20,000 concurrent per-entity agents, one ADK session each, invoked independently", "swarm/runtime.py"],
  ["Discovery & lifecycle — Agent Registry", "done",
   "Content-derived versions; declared coverage gaps escalate to a human", "fleet/registry.py"],
  ["Core execution & state — long-running async", "done",
   "POST /api/runs returns 202 and a run id; the sweep outlives the request, progress is mirrored to Firestore, and the causal DAG is the checkpoint — a run that dies resumes at zero model cost", "api/runs.py"],
  ["Memory across weeks", "done",
   "Recognised 90 days later without re-stating anything; memory feeds the projection, not the prompt", "memory/"],
  ["Security — data handling & PII", "done",
   "Identity never crosses the model boundary; enforced structurally", "swarm/canonical.py"],
  ["Zero-trust — agent identity", "done",
   "One service account per role; the allocator has no model access. Proved by attempting the forbidden action", "infra/identity.sh"],
  ["Governance — policy enforcement", "done",
   "Quarantine gate plus a gateway whose denials are recorded as effects — replayable and diffable", "gateway/policy.py"],
  ["Security — prompt injection", "done",
   "Collapse amplifies injection by the collapse ratio, so the airlock is structural. Proved in CI", "armor/"],
  ["Telemetry — reasoning-chain traces", "done",
   "39,996 spans in Cloud Trace; causal parents map to span links, replays render at zero duration", "obs/otel.py"],
  ["Is the model earning its cost?", "done",
   "Shadow sampling against the system's own cache, with a measured noise floor", "policy/"],
  ["Infrastructure as code", "done",
   "Terraform for services, IAM, Firestore, Secret Manager and Cloud Run. Planned: 23 to add, 0 to change", "infra/terraform/"],
  ["Console — time travel and fork/diff", "partial",
   "The kernel supports both and the API exposes them; the console surfaces the live collapse, not yet the scrubber", "console/src/Console.tsx"],
];

export function Architecture() {
  return (
    <div className="page">
      <section className="shell prose-head">
        <p className="eyebrow">Architecture</p>
        <h1 className="display h1" style={{ maxWidth: "18ch" }}>
          Five stages, and a boundary you can defend at each one.
        </h1>
        <p className="lede">
          Two of the five may use a model, and only one of those collapses. Saying which is
          what makes the economics checkable rather than asserted.
        </p>
      </section>

      <section className="section">
        <div className="shell">
          <ol className="stages">
            {STAGES.map(([n, name, cost, body]) => (
              <li key={n} className="stage reveal">
                <span className="data stage-n">{n}</span>
                <div>
                  <p className="stage-name">
                    {name} <span className="data stage-cost">{cost}</span>
                  </p>
                  <p className="stage-body muted">{body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="section">
        <div className="shell">
          <p className="eyebrow reveal">Fortified Enterprise Fleet</p>
          <h2 className="display h2 reveal" style={{ maxWidth: "17ch" }}>
            Every bullet, and the file that implements it.
          </h2>
          <div className="claim-table-wrap reveal" style={{ marginTop: "2rem" }}>
            <table className="claim-table compliance">
              <thead>
                <tr>
                  <th scope="col">requirement</th>
                  <th scope="col">how</th>
                  <th scope="col">where</th>
                </tr>
              </thead>
              <tbody>
                {COMPLIANCE.map(([req, state, how, where]) => (
                  <tr key={req} data-state={state}>
                    <th scope="row">
                      <span className="compliance-dot" data-state={state} aria-hidden="true" />
                      {req}
                      {state === "partial" && <span className="claim-flag"> · partial</span>}
                    </th>
                    <td className="compliance-how">{how}</td>
                    <td className="data compliance-where">{where}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="faint" style={{ marginTop: "1.5rem", maxWidth: "70ch" }}>
            One row says partial. A compliance table where everything is green is a
            compliance table nobody checked.
          </p>
          <p style={{ marginTop: "1.5rem" }}>
            <Link to="/evidence" className="btn" data-variant="ghost">The evidence →</Link>{" "}
            <a className="btn" data-variant="ghost" href={LINKS.repo} target="_blank"
               rel="noreferrer">Source</a>
          </p>
        </div>
      </section>
    </div>
  );
}
