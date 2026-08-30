// Measured, not drawn. Regenerate with scripts/verify_collapse.py.
//
// The domain runs to 200,000 because that is where the argument actually lands: the
// lattice is 2,304 cells and at 200,000 agents 2,296 of them are occupied, so past that
// point cost stops growing entirely and collapse rises linearly with population forever.
// Stopping at 20,000 showed a curve still visibly climbing, which is the weaker claim.
const DATA = [
  { agents: 500, thoughts: 377 },
  { agents: 2000, thoughts: 942 },
  { agents: 8000, thoughts: 1599 },
  { agents: 20000, thoughts: 1965 },
  { agents: 50000, thoughts: 2172 },
  { agents: 100000, thoughts: 2269 },
  { agents: 200000, thoughts: 2296 },
];

// The arithmetic ceiling: 4 tiers x 4 urgencies x 4 parties x 3 constraints x 3 hauls
// x 2 hotel x 2 misconnect. Drawn, because a saturation curve without its asymptote
// invites the reader to wonder whether it keeps climbing off the right of the frame.
const CEILING = 2304;

const W = 1000;
const H = 420;
const PAD = { top: 40, right: 196, bottom: 54, left: 84 };

/** The saturation curve.
 *
 *  Agents are plotted on a log axis because the interesting range spans two orders of
 *  magnitude; on a linear axis the first four points collapse into the origin and the
 *  shape — the whole argument — disappears.
 *
 *  One thought per agent is deliberately not plotted: at this scale it sits above the
 *  frame across the whole domain, so it renders as a line escaping the figure rather than
 *  as a comparison. It belongs in the caption, as a number. */
export function SaturationChart() {
  const xs = DATA.map((d) => Math.log10(d.agents));
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const maxY = 2600;

  const x = (agents: number) =>
    PAD.left + ((Math.log10(agents) - minX) / (maxX - minX)) * (W - PAD.left - PAD.right);
  const y = (thoughts: number) =>
    PAD.top + (1 - thoughts / maxY) * (H - PAD.top - PAD.bottom);

  const curve = DATA.map((d, i) => `${i ? "L" : "M"}${x(d.agents)},${y(d.thoughts)}`).join(" ");
  const area = `${curve} L${x(200000)},${y(0)} L${x(500)},${y(0)} Z`;

  return (
    <figure className="chart reveal-late">
      <svg viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label="Distinct thoughts saturate at 2,296 of a possible 2,304 as agent count grows to 200,000">
        <defs>
          <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#5ef0c8" stopOpacity="0.16" />
            <stop offset="100%" stopColor="#5ef0c8" stopOpacity="0" />
          </linearGradient>
        </defs>

        {[0, 500, 1000, 1500, 2000, 2500].map((v) => (
          <g key={v}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} className="chart-grid" />
            <text x={PAD.left - 14} y={y(v) + 4} className="chart-tick" textAnchor="end">{v}</text>
          </g>
        ))}

        {DATA.map((d) => (
          <text key={d.agents} x={x(d.agents)} y={H - 20} className="chart-tick" textAnchor="middle">
            {d.agents >= 1000 ? `${d.agents / 1000}k` : d.agents}
          </text>
        ))}

        <path d={area} fill="url(#fill)" className="chart-area" />
        <path d={curve} className="chart-line" />

        {DATA.map((d) => (
          <g key={d.agents}>
            <circle cx={x(d.agents)} cy={y(d.thoughts)} r="5" className="chart-dot" />
            <text x={x(d.agents)} y={y(d.thoughts) - 16} className="chart-value" textAnchor="middle">
              {d.thoughts}
            </text>
          </g>
        ))}

        <line x1={PAD.left} x2={W - PAD.right + 26} y1={y(CEILING)} y2={y(CEILING)}
              className="chart-grid" strokeDasharray="5 5" />
        <text x={W - PAD.right + 34} y={y(CEILING) - 6} className="chart-label">
          2,304 ceiling
        </text>

        <line x1={x(200000)} x2={W - PAD.right + 26} y1={y(2296)} y2={y(2296)} className="chart-callout" />
        <text x={W - PAD.right + 34} y={y(2296) + 14} className="chart-label accent">2,296 thoughts</text>
        <text x={W - PAD.right + 34} y={y(2296) + 34} className="chart-label">200,000 agents</text>
      </svg>
      <figcaption>
        Distinct situations are bounded by the product of the buckets — tier, urgency,
        party size, constraints, haul, hotel entitlement, misconnect — so the curve
        flattens where the population does not. Doubling from a hundred thousand agents
        to two hundred thousand costs <b>twenty-seven</b> more thoughts, and the lattice
        is then full: past that point every further agent is free. One thought per agent
        is not drawn, because at twenty thousand it would sit ten times above this frame
        — <b>$19.75</b> against the <b>$1.94</b> actually spent.
      </figcaption>
    </figure>
  );
}
