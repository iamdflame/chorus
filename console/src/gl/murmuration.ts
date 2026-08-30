/** The swarm, drawn as what it actually is: cohorts, not individuals.
 *
 *  Twenty thousand agents, but only ~192 distinct situations — so the rendering unit is
 *  the cohort, which is also the semantic unit. A cohort is the set of agents whose
 *  reasoning is provably identical, and it lights up in unison because it thinks in
 *  unison. Watching three hundred and sixty-eight points ignite together on a single
 *  model call is the claim made visible.
 *
 *  Cohorts as display objects rather than 20,000 individual sprites: the animation is
 *  per-cohort by construction, so 192 containers with static geometry beat a particle
 *  system that has to touch every point every frame — which matters on modest hardware. */

import { Application, Container, Graphics } from "pixi.js";
import { gsap } from "gsap";

const C = {
  ground: 0x07080a,
  // Bright enough to read as a population rather than as noise. The whole claim is
  // that you can SEE twenty thousand agents, so an idle cohort must be visible before
  // anything happens to it.
  idle: 0x39424f,
  cell: 0x11141a,
  thinking: 0xffffff,
  thought: 0x5ef0c8,
  shared: 0x2f8f7c,
  label: 0x565c69,
};

export interface Cohort {
  key: string;
  size: number;
  label: string;
}

interface CohortView {
  key: string;
  container: Container;
  dots: Graphics;
  size: number;
  state: { glow: number; tint: number };
  status: "idle" | "thinking" | "thought" | "shared";
}

/** Deterministic PRNG so a cohort's cloud looks identical on every load — a layout that
 *  reshuffles between runs makes two screenshots incomparable. */
function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
}

export class Murmuration {
  private app = new Application();
  private stage = new Container();
  private views = new Map<string, CohortView>();
  private host!: HTMLElement;
  private ready = false;
  private destroyed = false;

  async mount(host: HTMLElement): Promise<void> {
    this.host = host;
    await this.app.init({
      background: C.ground,
      antialias: true,
      resizeTo: host,
      resolution: Math.min(window.devicePixelRatio ?? 1, 2),
      autoDensity: true,
    });
    if (this.destroyed) {
      this.app.destroy(true, { children: true });
      return;
    }
    this.ready = true;
    host.appendChild(this.app.canvas);
    this.app.stage.addChild(this.stage);
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    if (this.ready) this.app.destroy(true, { children: true });
  }

  /** Squarified treemap: rows of cells whose areas are proportional to cohort size,
   *  chosen to keep each cell near square. Classic Bruls/Huizing/van Wijk. */
  private static tile(
    sizes: number[], x: number, y: number, w: number, h: number,
  ): { x: number; y: number; w: number; h: number }[] {
    const out: { x: number; y: number; w: number; h: number }[] = [];
    const total = sizes.reduce((a, b) => a + b, 0) || 1;
    let remaining = sizes.map((s) => (s / total) * w * h);
    let i = 0;
    let [cx, cy, cw, ch] = [x, y, w, h];

    const worst = (row: number[], side: number): number => {
      const sum = row.reduce((a, b) => a + b, 0);
      const max = Math.max(...row);
      const min = Math.min(...row);
      const s2 = side * side;
      const sum2 = sum * sum;
      return Math.max((s2 * max) / sum2, sum2 / (s2 * min));
    };

    while (i < remaining.length) {
      const vertical = cw >= ch;
      const side = vertical ? ch : cw;
      const row: number[] = [remaining[i]];
      let j = i + 1;
      while (j < remaining.length &&
             worst(row.concat(remaining[j]), side) <= worst(row, side)) {
        row.push(remaining[j]);
        j += 1;
      }
      const rowSum = row.reduce((a, b) => a + b, 0);
      const thickness = rowSum / side;
      let offset = 0;
      for (const area of row) {
        const length = area / thickness;
        if (vertical) {
          out.push({ x: cx, y: cy + offset, w: thickness, h: length });
        } else {
          out.push({ x: cx + offset, y: cy, w: length, h: thickness });
        }
        offset += length;
      }
      if (vertical) { cx += thickness; cw -= thickness; }
      else { cy += thickness; ch -= thickness; }
      i = j;
    }
    return out;
  }

  /** Lay the population out as clustered clouds, one per cohort, area proportional to
   *  cohort size so the eye reads population weight directly. */
  setCohorts(cohorts: Cohort[]): void {
    this.stage.removeChildren();
    this.views.clear();
    if (!cohorts.length) return;

    const w = this.host.clientWidth || 1200;
    const h = this.host.clientHeight || 700;
    const pad = 18;

    const ordered = [...cohorts].sort((a, b) => b.size - a.size);
    const cells = Murmuration.tile(
      ordered.map((c) => c.size), pad, pad, w - pad * 2, h - pad * 2,
    );

    ordered.forEach((cohort, index) => {
      const cell = cells[index];
      if (!cell) return;
      const container = new Container();
      const backing = new Graphics();
      backing
        .rect(cell.x + 1, cell.y + 1, Math.max(cell.w - 2, 1), Math.max(cell.h - 2, 1))
        .fill({ color: C.cell, alpha: 0.9 });
      const dots = new Graphics();
      const random = rng(index * 7919 + 13);

      // Fill the cell rather than a circle inscribed in it: the treemap already encodes
      // area, so a cloud that fills its cell reads as its true share of the population.
      const cx = cell.x + cell.w / 2;
      const cy = cell.y + cell.h / 2;
      const rx = Math.max(cell.w / 2 - 3, 1.5);
      const ry = Math.max(cell.h / 2 - 3, 1.5);
      const drawn = Math.min(cohort.size, 300); // beyond this the cloud reads as solid
      // Floored so a cohort of four stays a visible mark rather than a sub-pixel smudge,
      // and capped so a cohort of hundreds reads as a population rather than as gravel —
      // the dots are agents, and an agent should never look like a boulder.
      const dotSize = Math.min(Math.max(Math.min(rx, ry) / 12, 1.1), 2.4);
      for (let i = 0; i < drawn; i += 1) {
        const angle = random() * Math.PI * 2;
        const radius = Math.sqrt(random());
        dots.circle(
          cx + Math.cos(angle) * radius * rx,
          cy + Math.sin(angle) * radius * ry,
          dotSize,
        );
      }
      dots.fill({ color: C.idle, alpha: 1 });

      container.addChild(backing, dots);
      this.stage.addChild(container);
      this.views.set(cohort.key, {
        key: cohort.key, container, dots, size: cohort.size,
        state: { glow: 0, tint: 0 }, status: "idle",
      });
    });
  }

  /** A cohort reached the model: one agent thought, and the whole cohort is about to
   *  inherit it. Drawn as a white flash so a real model call is visually distinct from
   *  the sharing that follows. */
  think(key: string): void {
    const view = this.views.get(key);
    if (!view) return;
    view.status = "thinking";
    view.dots.tint = C.thinking;
    gsap.killTweensOf(view.dots);
    gsap.fromTo(
      view.dots,
      { alpha: 1 },
      { alpha: 0.85, duration: 0.45, ease: "power2.out",
        onComplete: () => { view.dots.tint = C.thought; view.status = "thought"; } },
    );
    gsap.fromTo(view.container.scale, { x: 1, y: 1 },
      { x: 1.14, y: 1.14, duration: 0.22, yoyo: true, repeat: 1, ease: "power2.out" });
  }

  /** A cohort was served from the store — no model call. Settles to the dim shared
   *  colour, so the screen ends up mostly quiet: the point of the whole system. */
  share(key: string): void {
    const view = this.views.get(key);
    if (!view || view.status === "thinking") return;
    view.status = "shared";
    view.dots.tint = C.shared;
    gsap.fromTo(view.dots, { alpha: 0.35 }, { alpha: 0.75, duration: 0.6, ease: "power2.out" });
  }

  reset(): void {
    for (const view of this.views.values()) {
      gsap.killTweensOf(view.dots);
      view.dots.tint = C.idle;
      view.dots.alpha = 0.9;
      view.status = "idle";
    }
  }
}
