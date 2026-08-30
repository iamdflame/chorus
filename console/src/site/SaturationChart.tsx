const DATA = [
  { agents: 500, thoughts: 128 },
  { agents: 1000, thoughts: 149 },
  { agents: 2000, thoughts: 170 },
  { agents: 4000, thoughts: 183 },
  { agents: 8000, thoughts: 187 },
  { agents: 20000, thoughts: 192 },
];

const W = 1000;
const H = 420;
const PAD = { top: 40, right: 132, bottom: 54, left: 74 };

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
  const maxY = 220;

  const x = (agents: number) =>
    PAD.left + ((Math.log10(agents) - minX) / (maxX - minX)) * (W - PAD.left - PAD.right);
  const y = (thoughts: number) =>
    PAD.top + (1 - thoughts / maxY) * (H - PAD.top - PAD.bottom);

  const curve = DATA.map((d, i) => `${i ? "L" : "M"}${x(d.agents)},${y(d.thoughts)}`).join(" ");
  const area = `${curve} L${x(20000)},${y(0)} L${x(500)},${y(0)} Z`;

  return (
    <figure className="chart reveal-late">
      <svg viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label="Distinct thoughts saturate near 192 as agent count grows to 20,000">
        <defs>
          <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#5ef0c8" stopOpacity="0.16" />
            <stop offset="100%" stopColor="#5ef0c8" stopOpacity="0" />
          </linearGradient>
        </defs>

        {[0, 50, 100, 150, 200].map((v) => (
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

        <line x1={x(20000)} x2={W - PAD.right + 26} y1={y(192)} y2={y(192)} className="chart-callout" />
        <text x={W - PAD.right + 34} y={y(192) - 6} className="chart-label accent">192 thoughts</text>
        <text x={W - PAD.right + 34} y={y(192) + 14} className="chart-label">20,000 agents</text>
      </svg>
      <figcaption>
        Distinct situations are bounded by the product of the buckets — tier, urgency,
        party size, constraints — so the curve flattens where the population does not.
        One thought per agent is not drawn here: at twenty thousand it would sit a
        hundred times above the top of this frame. It costs <b>$19.25</b> against
        <b>$0.21</b>.
      </figcaption>
    </figure>
  );
}
