/** The Chorus mark.
 *
 *  One bright centre surrounded by six dim satellites: many agents, one thought. It is
 *  the product's own structure — a cohort — reduced until it still reads at sixteen
 *  pixels, which is the only size a mark really has to survive.
 *
 *  Drawn from circles rather than a glyph or a wordmark lockup so it shares the visual
 *  vocabulary of the hero field and the console: everything in this product is made of
 *  many small marks. */

const SATELLITES = [
  [19.5, 12], [15.75, 5.5], [8.25, 5.5],
  [4.5, 12], [8.25, 18.5], [15.75, 18.5],
] as const;

export function Mark({ size = 22, animated = true }: { size?: number; animated?: boolean }) {
  return (
    <svg
      className="mark-glyph"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      data-animated={animated}
    >
      {SATELLITES.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r="1.85" className="mark-satellite"
                style={{ "--i": i } as React.CSSProperties} />
      ))}
      <circle cx="12" cy="12" r="3.3" className="mark-core" />
    </svg>
  );
}
