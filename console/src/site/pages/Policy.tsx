import { useEffect, useState } from "react";
import { api, type PolicyList, type PolicyRow } from "../../api";
import { Link, useParam } from "../router";

/** Deep-linkable provenance. Every number elsewhere should be able to reach here.
 *
 *  A dashboard shows you a figure. An audited system lets you click it and see the effect
 *  that produced it, the model that answered, when, how many entities have been served
 *  that answer, and whether drift has since invalidated it. That difference is the whole
 *  reason the policy carries provenance rather than just values. */

function Answer({ answer }: { answer: Record<string, unknown> }) {
  return (
    <dl className="policy-answer">
      {Object.entries(answer).map(([k, v]) => (
        <div key={k}>
          <dt>{k.replace(/_/g, " ")}</dt>
          <dd className="data">{typeof v === "boolean" ? (v ? "yes" : "no") : String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

function Cell({ cell }: { cell: string }) {
  const [row, setRow] = useState<PolicyRow | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.policyCell(cell)
      .then((r) => alive && setRow(r))
      .catch((e) => alive && setError(String(e).slice(0, 140)));
    return () => { alive = false; };
  }, [cell]);

  if (error) return <p className="muted">No such cell. {error}</p>;
  if (!row) return <p className="muted">Reading provenance…</p>;

  const facets = row.key.split("|").slice(2);
  const seen = row.confirmations + row.disagreements;

  return (
    <>
      <div className="policy-facets">
        {facets.map((f) => <span key={f} className="policy-facet data">{f}</span>)}
      </div>

      {row.invalidated && (
        <p className="policy-flag">
          Invalidated by drift. This answer is no longer served — the next request for this
          situation pays for a fresh one. The row is kept rather than deleted, because an
          auditor has to be able to see what was served and to whom.
        </p>
      )}

      <h3 className="h3" style={{ marginTop: "1.5rem" }}>The answer</h3>
      <Answer answer={row.answer} />

      <h3 className="h3" style={{ marginTop: "2rem" }}>Where it came from</h3>
      <dl className="policy-prov">
        <div>
          <dt>derived by</dt>
          <dd className="data">{row.provenance.model}</dd>
        </div>
        <div>
          <dt>effect address</dt>
          <dd className="data policy-hash">{row.provenance.effect_id ?? "—"}</dd>
        </div>
        <div>
          <dt>derived at</dt>
          <dd className="data">{row.provenance.derived_at.slice(0, 19).replace("T", " ")}</dd>
        </div>
        <div>
          <dt>entities served</dt>
          <dd className="data">{row.provenance.served.toLocaleString()}</dd>
        </div>
        <div>
          <dt>shadow samples</dt>
          <dd className="data">{seen === 0 ? "never sampled" : seen}</dd>
        </div>
        <div>
          <dt>trust</dt>
          <dd className="data">
            {seen === 0
              ? "unknown"
              : `${((100 * row.confirmations) / seen).toFixed(0)}%`}
          </dd>
        </div>
      </dl>

      {seen === 0 && (
        <p className="faint" style={{ maxWidth: "70ch" }}>
          An unsampled row reports unknown trust, never full trust. A row that has never
          been checked is not a row that has been found correct, and reporting it as one
          would be the single most dishonest number this page could produce.
        </p>
      )}

      <p style={{ marginTop: "2rem" }}>
        <Link to="/policy" className="btn" data-variant="ghost">← All cells</Link>{" "}
        <Link to="/ledger" className="btn" data-variant="ghost">The ledger →</Link>
      </p>
    </>
  );
}

function Index() {
  const [data, setData] = useState<PolicyList | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    let alive = true;
    api.policy(q, 40).then((d) => alive && setData(d)).catch(() => alive && setData({ available: false }));
    return () => { alive = false; };
  }, [q]);

  return (
    <>
      <label className="policy-search">
        <span className="eyebrow">Filter</span>
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="platinum, misconnect, assisted…" />
      </label>

      {!data ? <p className="muted">Reading the policy…</p>
        : !data.available ? (
          <p className="muted">
            No policy distilled yet — <code>scripts/necessity.py</code> writes this.
          </p>
        ) : (
          <>
            <p className="faint policy-count">
              v{data.version} · {data.populated?.toLocaleString()} of{" "}
              {data.ceiling?.toLocaleString()} cells populated ·{" "}
              {data.matched?.toLocaleString()} matching, most-served first
            </p>
            <div className="policy-rows">
              {data.rows?.map((r) => (
                <Link key={r.key} to={`/policy/${encodeURIComponent(r.key)}`}
                      className="policy-row">
                  <span className="data policy-row-key">{r.key.split("|").slice(2).join(" · ")}</span>
                  <span className="data policy-row-served">
                    {r.provenance.served.toLocaleString()}
                  </span>
                  {r.invalidated && <span className="policy-row-flag">invalidated</span>}
                </Link>
              ))}
            </div>
          </>
        )}
    </>
  );
}

export function Policy() {
  const cell = useParam("/policy");
  return (
    <div className="page">
      <section className="shell prose-head">
        <p className="eyebrow">Provenance</p>
        <h1 className="display h1" style={{ maxWidth: "18ch" }}>
          {cell ? "One cell, and everything behind it." : "Every answer the fleet settled on."}
        </h1>
        <p className="lede">
          {cell
            ? "The effect that derived this answer, the model that produced it, how many entities have been served it, and whether drift has since taken it out of service."
            : "A distilled policy is only trustworthy if you can reach the reasoning behind any row of it in one click. These are real rows from a real distillation."}
        </p>
      </section>

      <section className="section">
        <div className="shell">{cell ? <Cell cell={cell} /> : <Index />}</div>
      </section>
    </div>
  );
}
