/** Claim, command, result — including the results that hurt.
 *
 *  Every judge has been lied to by a leaderboard today. Marking your own losing rows is
 *  the highest-trust move available, so the arms that beat us are in the same table at the
 *  same weight, and the row that beat us carries a marker rather than a footnote.
 *
 *  Every number below regenerates from the command printed beside it. */

interface Row {
  label: string;
  cells: (string | number)[];
  note?: "beats-us" | "ours" | "exploit";
}

interface Claim {
  claim: string;
  command: string;
  columns: string[];
  rows: Row[];
  verdicts: string[];
}

const CLAIMS: Claim[] = [
  {
    claim: "Twenty thousand agents cost the diversity of their situations, not their population.",
    command: "python scripts/prove_swarm.py --agents 20000",
    columns: ["", "value"],
    rows: [
      { label: "agents invoked", cells: ["20,000"] },
      { label: "distinct situations", cells: ["1,964"] },
      { label: "model calls made", cells: ["1,964"], note: "ours" },
      { label: "paid for twice", cells: ["0"], note: "ours" },
      { label: "cost incurred", cells: ["$1.9394"] },
      { label: "cost at one call per agent", cells: ["$19.7495"] },
    ],
    verdicts: [
      "The swarm made exactly one call per distinct situation and not one more, so collapse and the structural ceiling agree at 10.2×.",
      "v1 made 222 calls for 192 situations and blamed retries. The larger cause was concurrent misses; single-flight closed it, and at twenty thousand agents the gap is now zero rather than smaller.",
    ],
  },
  {
    claim: "Collapse is fidelity-preserving.",
    command: "python -m bench.fidelity --cohorts 40 --per-cohort 15",
    columns: ["arm", "sat·weighted", "sat·blind", "p95 wait", "calls"],
    rows: [
      { label: "B4 collapsed", cells: ["108.3", "80.0", "31.0h", "40"], note: "ours" },
      { label: "B4t + tie-break", cells: ["100.6", "87.4", "31.0h", "40"] },
      { label: "B5 uncollapsed", cells: ["124.4", "105.1", "23.5h", "600"], note: "beats-us" },
    ],
    verdicts: [
      "WITHDRAWN. Collapse costs about 13% of tier-weighted satisfaction, replicated across three independent runs, and loses on equity and worst-case wait too.",
      "The mechanism is visible in the rank correlation, −0.04 on urgency: every member of a cohort gets the same score, so the allocator has nothing to order them by.",
      "Escalating the worst-agreeing 30% of cohorts recovers 85% of the loss at 5.2× cost against 15.0× for not collapsing at all.",
    ],
  },
  {
    claim: "The model earns its place over a control built to beat it.",
    command: "python scripts/verify_extraction.py --model 200",
    columns: ["extractor", "urgency", "party", "exact", "mean"],
    rows: [
      { label: "keyword (free)", cells: ["45.0%", "55.5%", "12.0%", "60.1%"] },
      { label: "gemini-3.5-flash", cells: ["79.5%", "97.5%", "54.5%", "87.0%"], note: "ours" },
      { label: "gemma-4-26b (answered)", cells: ["86.1%", "97.0%", "57.6%", "88.5%"], note: "beats-us" },
    ],
    verdicts: [
      "A regex cannot infer that “she can’t manage stairs” means assistance. On unbounded input the model reads 26.9 points better than the control.",
      "Gemma is not less accurate — it is less reliable. It fails to finish 35 of 200, and that is what puts it behind overall.",
    ],
  },
  {
    claim: "The allocator’s scoring is sound.",
    command: "python -m bench.run --agents 4000",
    columns: ["arm", "sat·tier", "sat·blind", "sat·soul"],
    rows: [
      { label: "B1 first-come", cells: ["3,875.7", "2,038.7", "9,660.0"] },
      { label: "B2 rules, zero LLM", cells: ["4,509.5", "1,554.3", "11,156.7"], note: "beats-us" },
      { label: "B3 value packing", cells: ["5,497.8", "2,634.5", "7,156.8"], note: "exploit" },
    ],
    verdicts: [
      "B3 was called a greedy upper bound and led both per-booking metrics. It was exploiting the scorer: satisfaction summed once per booking while seats are consumed per soul, so it seated solos and moved fewer people home.",
      "Counting per soul reverses it — B3 lands 25.9% below first-come. The arm is kept, renamed to what it is.",
    ],
  },
];

export function Claims() {
  return (
    <div className="claims">
      {CLAIMS.map((c) => (
        <article key={c.claim} className="claim reveal">
          <p className="eyebrow">Claim</p>
          <h3 className="claim-head display">{c.claim}</h3>
          <p className="claim-cmd data">{c.command}</p>

          <div className="claim-table-wrap">
            <table className="claim-table">
              <thead>
                <tr>{c.columns.map((h) => <th key={h} scope="col">{h}</th>)}</tr>
              </thead>
              <tbody>
                {c.rows.map((r) => (
                  <tr key={r.label} data-note={r.note}>
                    <th scope="row">
                      {r.label}
                      {r.note === "beats-us" && <span className="claim-flag"> ← beats us</span>}
                      {r.note === "exploit" && <span className="claim-flag"> ← exploits the metric</span>}
                    </th>
                    {r.cells.map((cell, i) => <td key={i} className="data">{cell}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <ul className="claim-verdicts">
            {c.verdicts.map((v) => <li key={v}>{v}</li>)}
          </ul>
        </article>
      ))}
    </div>
  );
}
