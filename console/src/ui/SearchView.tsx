import { useMemo } from "react";

export interface SearchCandidate {
  id: string;
  generation: number;
  text: string;
  rationale: string;
  parent_id: string | null;
  outcome: {
    total_cost_usd: number;
    wrongful_refunds_usd: number;
    missed_valid_usd: number;
    escalations: number;
    refunds_issued: number;
    compute_usd: number;
  } | null;
  error: string | null;
}

interface Props {
  baseline: SearchCandidate | null;
  candidates: SearchCandidate[];
  generations: number;
  running: boolean;
  winner: SearchCandidate | null;
  onAdopt: (c: SearchCandidate) => void;
}

const W = 1000;
const H = 460;
const PAD = { top: 34, right: 40, bottom: 44, left: 78 };

const usd = (n: number) =>
  `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** The search, drawn as a cost landscape.
 *
 *  Cost increases upward and the production policy is a dashed line across the frame, so
 *  "below the line" means "cheaper than what you run today" without needing a legend.
 *  Each point is one complete execution of the fleet against the same real disputes;
 *  edges run from a policy to the variants it inspired. Convergence is visible as the
 *  cloud descending, which is the only progress indicator the search needs. */
export function SearchView({ baseline, candidates, generations, running, winner, onAdopt }: Props) {
  const scored = useMemo(
    () => candidates.filter((c) => c.outcome && !c.error),
    [candidates],
  );

  const { x, y, maxCost, minCost } = useMemo(() => {
    const costs = [
      ...scored.map((c) => c.outcome!.total_cost_usd),
      baseline?.outcome?.total_cost_usd ?? 0,
    ];
    const hi = Math.max(...costs, 1) * 1.08;
    const lo = Math.min(...costs, 0) * 0.92;
    const span = Math.max(hi - lo, 1);
    return {
      minCost: lo,
      maxCost: hi,
      x: (gen: number) =>
        PAD.left + (gen / Math.max(generations, 1)) * (W - PAD.left - PAD.right),
      y: (cost: number) =>
        PAD.top + (1 - (cost - lo) / span) * (H - PAD.top - PAD.bottom),
    };
  }, [scored, baseline, generations]);

  const byId = useMemo(
    () => new Map([...(baseline ? [baseline] : []), ...scored].map((c) => [c.id, c])),
    [scored, baseline],
  );

  const baseCost = baseline?.outcome?.total_cost_usd ?? null;
  const improvement =
    baseCost !== null && winner?.outcome ? baseCost - winner.outcome.total_cost_usd : 0;

  return (
    <div className="search-view">
      <svg viewBox={`0 0 ${W} ${H}`} className="search-plot" role="img"
           aria-label="policy cost landscape">
        {/* cost gridlines */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const cost = minCost + (maxCost - minCost) * t;
          return (
            <g key={t}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(cost)} y2={y(cost)}
                    stroke="#16181d" strokeWidth={1} />
              <text x={PAD.left - 10} y={y(cost) + 3} textAnchor="end"
                    className="axis-label">{usd(cost)}</text>
            </g>
          );
        })}

        {/* generation ticks */}
        {Array.from({ length: generations + 1 }, (_, g) => (
          <text key={g} x={x(g)} y={H - 18} textAnchor="middle" className="axis-label">
            {g === 0 ? "production" : `gen ${g}`}
          </text>
        ))}

        {/* the line to beat */}
        {baseCost !== null && (
          <>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(baseCost)} y2={y(baseCost)}
                  stroke="#ff5c5c" strokeWidth={1} strokeDasharray="3 4" opacity={0.75} />
            <text x={W - PAD.right} y={y(baseCost) - 8} textAnchor="end"
                  className="axis-note">current production policy · {usd(baseCost)}</text>
          </>
        )}

        {/* lineage */}
        {scored.map((c) => {
          const parent = c.parent_id ? byId.get(c.parent_id) : null;
          if (!parent?.outcome) return null;
          return (
            <line key={`e-${c.id}`}
                  x1={x(parent.generation)} y1={y(parent.outcome.total_cost_usd)}
                  x2={x(c.generation)} y2={y(c.outcome!.total_cost_usd)}
                  stroke="#232833" strokeWidth={1} />
          );
        })}

        {/* candidates */}
        {scored.map((c) => {
          const cost = c.outcome!.total_cost_usd;
          const better = baseCost !== null && cost < baseCost;
          const isWinner = winner?.id === c.id;
          return (
            <g key={c.id}>
              {isWinner && (
                <circle cx={x(c.generation)} cy={y(cost)} r={13} fill="none"
                        stroke="#5ef0c8" strokeWidth={1.2} opacity={0.9}>
                  <animate attributeName="r" values="10;16;10" dur="2.4s"
                           repeatCount="indefinite" />
                </circle>
              )}
              <circle cx={x(c.generation)} cy={y(cost)} r={better ? 6 : 4.5}
                      fill={better ? "#5ef0c8" : "#4b5160"}
                      opacity={better ? 0.95 : 0.65} />
            </g>
          );
        })}

        {baseline?.outcome && (
          <circle cx={x(0)} cy={y(baseline.outcome.total_cost_usd)} r={6}
                  fill="#ff5c5c" opacity={0.9} />
        )}
      </svg>

      <aside className="search-panel">
        <h2>Policy search</h2>
        <p className="search-blurb">
          Every point is one full execution of the six-agent fleet against the same real
          disputes. Irreversible actions are staged, never dispatched — which is what
          makes searching production history possible at all.
        </p>

        <dl className="kv">
          <dt>evaluated</dt><dd>{scored.length}</dd>
          <dt>production</dt><dd>{baseCost !== null ? usd(baseCost) : "—"}</dd>
          <dt>best found</dt>
          <dd>{winner?.outcome ? usd(winner.outcome.total_cost_usd) : "—"}</dd>
          <dt>improvement</dt>
          <dd data-tone={improvement > 0 ? "good" : undefined}>
            {improvement > 0 ? `−${usd(improvement)}` : "—"}
          </dd>
        </dl>

        {winner && winner.outcome && (
          <>
            <h2 style={{ marginTop: 20 }}>Winning clause</h2>
            <blockquote className="clause">{winner.text}</blockquote>
            {winner.rationale && <p className="rationale">{winner.rationale}</p>}
            <button className="action" data-variant="primary" disabled={running}
                    onClick={() => onAdopt(winner)}>
              adopt into production
            </button>
          </>
        )}
      </aside>
    </div>
  );
}
