import { Ledger } from "../Ledger";
import { LINKS } from "../links";
import { Link } from "../router";

/** The Necessity Ledger, on the Plate.
 *
 *  This is the answer to "does the LLM add anything?", computed continuously instead of
 *  asserted, and it deserves a page rather than a panel. It is set like an audited
 *  statement rather than a dashboard: right-aligned tabular figures, hairline rules, no
 *  cards, no gradients, nothing that would look at home in a template.
 *
 *  It is also allowed to be unflattering. If most of the workload turns out to be a lookup
 *  table, the page says so in the largest type on it. */
export function LedgerPage() {
  return (
    <div className="page">
      <section className="shell prose-head">
        <p className="eyebrow">Necessity</p>
        <h1 className="display h1" style={{ maxWidth: "17ch" }}>
          Is the model earning its cost?
        </h1>
        <p className="lede">
          Every agent project asserts that its model is essential. Almost none can produce
          the number, because measuring it honestly means running the model against your
          own cache and publishing how often it agreed — and being willing to find out that
          most of the workload is a lookup table.
        </p>
      </section>

      <section className="section">
        <div className="shell">
          <Ledger />
        </div>
      </section>

      <section className="section">
        <div className="shell prose">
          <h2 className="display h2 reveal" style={{ maxWidth: "18ch" }}>
            Why a drift rate without a noise floor is not a measurement.
          </h2>
          <p className="reveal">
            Shadow sampling calls the model on a slice of traffic <em>even though the table
            has an answer</em>, and counts the disagreements. That number is worthless on
            its own. Temperature is zero, but batched serving is not bitwise deterministic,
            so some fraction of “the model disagrees with the table” is really the model
            disagreeing with itself for no reason at all.
          </p>
          <p className="reveal">
            So every sampled question is asked twice. On this run the model disagreed with
            itself <strong>0 times in 27</strong>, which is what makes the drift rate above
            trustworthy. Without that baseline the ledger would be reporting the model’s own
            variance as evidence that the model is needed — the most flattering possible way
            to be wrong.
          </p>
          <p className="reveal muted">
            The interval matters too. Nineteen answered samples do not measure a percentage
            to two decimal places, so the page prints the 95% interval beside the rate. It
            is a direction, not a decimal.
          </p>
          <p className="reveal">
            <Link to="/evidence" className="btn" data-variant="ghost">
              See what collapse costs →
            </Link>{" "}
            <a className="btn" data-variant="ghost" href={LINKS.repo} target="_blank"
               rel="noreferrer">
              scripts/necessity.py
            </a>
          </p>
        </div>
      </section>
    </div>
  );
}
