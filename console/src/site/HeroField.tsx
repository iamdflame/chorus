import { useEffect, useRef } from "react";

/** The hero is the product.
 *
 *  A field of agents grouped into cohorts. Every so often one cohort reaches the model —
 *  it flashes white — and the rest of that cohort inherits the thought a beat later,
 *  settling to the accent. So the page's first impression is literally the mechanism it
 *  is about to explain, rather than an abstract gradient standing in for one.
 *
 *  Canvas 2D with fillRect rather than WebGL or arcs: a few thousand axis-aligned rects
 *  is the cheapest thing a browser can draw, and this has to stay at sixty frames on
 *  modest hardware while the rest of the page animates. */

interface Agent {
  x: number;
  y: number;
  cohort: number;
  phase: number;
  drift: number;
}

const COHORTS = 52;
const PER_COHORT = 78;
const IGNITE_EVERY = 1500; // ms

export function HeroField() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let agents: Agent[] = [];
    let centres: { x: number; y: number }[] = [];
    // Per-cohort brightness: 0 idle, 1 just-thought. Animated, not recomputed.
    const heat = new Float32Array(COHORTS);
    const inherited = new Float32Array(COHORTS);
    let dpr = 1;
    let width = 0;
    let height = 0;

    const layout = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      const rect = canvas.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // Cohorts sit on a loose grid, then are jittered: a perfect lattice reads as a
      // table, and pure randomness reads as noise. The population has structure.
      const cols = Math.ceil(Math.sqrt(COHORTS * (width / Math.max(height, 1))));
      const rows = Math.ceil(COHORTS / cols);
      centres = [];
      agents = [];
      let seed = 9;
      const rand = () => {
        seed = (seed * 1664525 + 1013904223) >>> 0;
        return seed / 0xffffffff;
      };

      for (let c = 0; c < COHORTS; c += 1) {
        const col = c % cols;
        const row = Math.floor(c / cols);
        const cx = ((col + 0.5) / cols) * width + (rand() - 0.5) * (width / cols) * 0.55;
        const cy = ((row + 0.5) / rows) * height + (rand() - 0.5) * (height / rows) * 0.55;
        centres.push({ x: cx, y: cy });

        const spread = Math.min(width / cols, height / rows) * (0.22 + rand() * 0.2);
        for (let i = 0; i < PER_COHORT; i += 1) {
          const angle = rand() * Math.PI * 2;
          const radius = Math.sqrt(rand()) * spread;
          agents.push({
            x: cx + Math.cos(angle) * radius,
            y: cy + Math.sin(angle) * radius,
            cohort: c,
            phase: rand() * Math.PI * 2,
            drift: 0.35 + rand() * 0.5,
          });
        }
      }
    };

    layout();
    const onResize = () => layout();
    window.addEventListener("resize", onResize);

    let last = performance.now();
    let sinceIgnite = 0;
    let raf = 0;

    const frame = (now: number) => {
      const dt = Math.min(now - last, 64);
      last = now;
      sinceIgnite += dt;

      if (!reduced && sinceIgnite > IGNITE_EVERY) {
        sinceIgnite = 0;
        const c = Math.floor(Math.random() * COHORTS);
        heat[c] = 1;
        inherited[c] = 1;
      }

      // Decay: the flash is brief, the inherited glow lingers. The asymmetry is the
      // point — thinking is rare and fast, sharing is broad and slow.
      for (let c = 0; c < COHORTS; c += 1) {
        heat[c] *= Math.exp(-dt / 220);
        inherited[c] *= Math.exp(-dt / 1400);
      }

      ctx.clearRect(0, 0, width, height);
      const t = now / 1000;

      for (let i = 0; i < agents.length; i += 1) {
        const a = agents[i];
        const wobble = Math.sin(t * a.drift + a.phase) * 1.6;
        const h = heat[a.cohort];
        const s = inherited[a.cohort];

        // Three states, and the colour is never the only thing that separates them:
        // an unlit agent is a dim neutral speck, a reflected one takes the cool cast of
        // light it did not pay for, and an ignited one goes incandescent AND grows. Size
        // and hue move together so the field still reads without colour discrimination.
        //
        //   latent    #4A5566   waiting
        //   reflect   #A8D5E5   served from the store, free
        //   filament  #FF9D4D   a model call, and money leaving
        let r = 0x5c, g = 0x67, b = 0x7a, alpha = 0.8;
        if (s > 0.01) {
          alpha = 0.8 + s * 0.2;
          r = Math.round(0x5c + (0xa8 - 0x5c) * s);
          g = Math.round(0x67 + (0xd5 - 0x67) * s);
          b = Math.round(0x7a + (0xe5 - 0x7a) * s);
        }
        if (h > 0.02) {
          // Ignition ramps through the hot filament rather than through white: this is
          // the only moment anything in the interface flashes, and it flashes exactly
          // when money is spent, so the visual budget maps to the financial one.
          const k = Math.min(h * 1.15, 1);
          r = Math.round(r + (0xff - r) * k);
          g = Math.round(g + (0xc4 - g) * k);
          b = Math.round(b + (0x8a - b) * k);
          alpha = Math.min(alpha + h * 0.55, 1);
        }

        ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
        const size = 1.5 + s * 0.5 + h * 2.4;
        ctx.fillRect(a.x - size / 2, a.y + wobble - size / 2, size, size);
      }

      raf = requestAnimationFrame(frame);
    };

    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  return <canvas ref={ref} className="hero-field" aria-hidden="true" />;
}
