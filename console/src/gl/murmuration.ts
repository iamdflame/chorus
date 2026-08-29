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

import { Application, Container, Graphics, Text, TextStyle } from "pixi.js";
import { gsap } from "gsap";

const C = {
  ground: 0x07080a,
  idle: 0x1c2029,
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

  /** Lay the population out as clustered clouds, one per cohort, area proportional to
   *  cohort size so the eye reads population weight directly. */
  setCohorts(cohorts: Cohort[]): void {
    this.stage.removeChildren();
    this.views.clear();
    if (!cohorts.length) return;

    const w = this.host.clientWidth || 1200;
    const h = this.host.clientHeight || 700;
    const columns = Math.ceil(Math.sqrt(cohorts.length * (w / Math.max(h, 1))));
    const rows = Math.ceil(cohorts.length / columns);
    const cellW = w / columns;
    const cellH = h / rows;

    const largest = Math.max(...cohorts.map((c) => c.size), 1);

    cohorts.forEach((cohort, index) => {
      const col = index % columns;
      const row = Math.floor(index / columns);
      const cx = col * cellW + cellW / 2;
      const cy = row * cellH + cellH / 2;

      const container = new Container();
      const dots = new Graphics();
      const random = rng(index * 7919 + 13);

      // Radius follows sqrt of size so area, not radius, tracks population.
      const spread = Math.min(cellW, cellH) * 0.42 * Math.sqrt(cohort.size / largest);
      const drawn = Math.min(cohort.size, 260); // beyond this the cloud reads as solid
      for (let i = 0; i < drawn; i += 1) {
        const angle = random() * Math.PI * 2;
        const radius = Math.sqrt(random()) * spread;
        dots.circle(cx + Math.cos(angle) * radius, cy + Math.sin(angle) * radius, 1.5);
      }
      dots.fill({ color: C.idle, alpha: 0.9 });

      container.addChild(dots);
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
