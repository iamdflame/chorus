import { useEffect, useState } from "react";
import { api, type Necessity } from "../api";

/** The Necessity Ledger, as a CFO would read it.
 *
 *  Every agent project asserts its model is essential. Almost none can produce the number,
 *  because measuring it honestly means running the model against your own cache and
 *  publishing how often it agreed. This panel is that number, and it is deliberately
 *  capable of being unflattering: if most of the workload turns out to be a lookup table,
 *  the panel says so in the largest type on the page. */

const pct = (n: number) => `${(100 * n).toFixed(1)}%`;
const num = (n: number) => n.toLocaleString();
const usd = (n: number) => `$${n.toFixed(n < 10 ? 4 : 2)}`;

export function Ledger() {
  const [data, setData] = useState<Necessity | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .necessity()
      .then((d) => alive && setData(d))
      .catch(() => alive && setData({ available: false, reason: "unreachable" }));
    return () => {
      alive = false;
    };
  }, []);

  if (!data) return <p className="muted">Reading the ledger…</p>;

  if (!data.available || !data.ledger) {
    // Never zeros. A necessity of 0% from a run that never happened is the most
    // reassuring number this panel could show and the least true.
    return (
      <p className="muted">
        No run recorded — <code>scripts/necessity.py</code> writes this.{" "}
        {data.reason}
      </p>
    );
  }

  const l = data.ledger;
  const s = l.shadow;
  const noise = data.noise_floor;
  const measured = s && s.answered > 0;
  const adjusted =
    measured && noise ? Math.max(0, s.drift_rate - noise.rate) : null;

  return (
    <div className="ledger">
      <div className="ledger-head">
        <span className="mono muted">NECESSITY LEDGER</span>
        <span className="mono muted">{l.period}</span>
      </div>

      <div className="ledger-hero">
        {measured ? (
          <>
            <div className="ledger-figure">{pct(adjusted ?? s.drift_rate)}</div>
            <p className="ledger-caption">
              of this workload is where the model is <strong>load-bearing</strong>.
              The other {pct(1 - (adjusted ?? s.drift_rate))} is a lookup table, and
              it is served as one.
            </p>
          </>
        ) : (
          <>
            <div className="ledger-figure muted">not measured</div>
            <p className="ledger-caption">
              No shadow samples were taken, so nothing is known about whether the
              table is still right. <strong>This is not 0%.</strong>
            </p>
          </>
        )}
      </div>

      <dl className="ledger-grid">
        <div>
          <dt>decisions served</dt>
          <dd>{num(l.decisions)}</dd>
        </div>
        <div>
          <dt>answered free from the table</dt>
          <dd>
            {num(l.served_from_table)} <span className="muted">{pct(l.table_share)}</span>
          </dd>
        </div>
        <div>
          <dt>model calls actually paid for</dt>
          <dd>{num(l.model_calls_made)}</dd>
        </div>
        <div>
          <dt>cost</dt>
          <dd>{usd(l.cost_usd)}</dd>
        </div>
        <div>
          <dt>cost without the kernel</dt>
          <dd>
            {usd(l.projected_naive_cost_usd)} <span className="muted">projected</span>
          </dd>
        </div>
        {data.policy && (
          <div>
            <dt>policy</dt>
            <dd className="mono">
              v{data.policy.version}
              <span className="muted">
                {num(data.policy.populated)} of {num(data.policy.ceiling)} cells
                populated
              </span>
            </dd>
          </div>
        )}
      </dl>

      {measured && (
        <div className="ledger-proof">
          <p>
            <strong>How much of that is real.</strong> The model was re-asked{" "}
            {s.answered} questions it had already answered and disagreed with the
            stored answer {s.drifted} times. It was then asked{" "}
            {noise ? noise.compared : 0} questions <em>twice</em> to see how often it
            disagrees with itself: {noise ? noise.disagreed : 0} times
            {noise && noise.rate === 0 ? ", so none of the drift is noise" : ""}.
          </p>
          <p className="muted">
            95% interval {pct(s.drift_interval_95[0])}–{pct(s.drift_interval_95[1])} on{" "}
            {s.answered} samples. A direction, not a decimal.
          </p>
          {s.events.length > 0 && (
            <ul className="ledger-drift">
              {s.events.slice(0, 4).map((e) => (
                <li key={e.key}>
                  <code>{e.key.replace(/^v2\|passenger\|/, "")}</code>
                  <span className="muted"> moved on {e.fields.join(", ")}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
