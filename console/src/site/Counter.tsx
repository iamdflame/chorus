import { useEffect, useRef, useState } from "react";

/** Counts up once, when it first comes into view.
 *
 *  Deliberately eased rather than linear: a linear count reads as a loading spinner,
 *  an eased one reads as a value settling. Respects reduced-motion by simply showing
 *  the final number — the number is the content, the animation is not. */
export function Counter({ to, dp = 0, ms = 1500 }: { to: number; dp?: number; ms?: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [value, setValue] = useState(0);
  const done = useRef(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setValue(to);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries[0].isIntersecting || done.current) return;
        done.current = true;
        const start = performance.now();
        const tick = (now: number) => {
          const t = Math.min((now - start) / ms, 1);
          const eased = 1 - Math.pow(1 - t, 4);
          setValue(to * eased);
          if (t < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      },
      { threshold: 0.4 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [to, ms]);

  return (
    <span ref={ref}>
      {value.toLocaleString(undefined, {
        minimumFractionDigits: dp,
        maximumFractionDigits: dp,
      })}
    </span>
  );
}
