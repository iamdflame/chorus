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
  cell: 0x0d1015,
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

export interface CohortSummary {
  key: string;
  label: string;
  size: number;
  status: string;
  /** 0 at the left edge of the frame, 1 at the right. */
  xFraction: number;
}

interface CohortView {
  key: string;
  label: string;
  container: Container;
  dots: Graphics;
  backing: Graphics;
  size: number;
  cell: { x: number; y: number; w: number; h: number };
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
  private order: CohortView[] = [];
  private hovered: string | null = null;
  private selected: string | null = null;
  private overlay = new Graphics();
  private host!: HTMLElement;
  private ready = false;
  private destroyed = false;
  // Kept so the treemap can be recomputed when the stage changes size. Laying out once at
  // mount leaves the field clipped the moment anything reflows — the readout wrapping to
  // a second row on a narrow screen is enough to do it.
  private lastCohorts: Cohort[] = [];
  private observer: ResizeObserver | null = null;

  onHover: (cohort: CohortSummary | null) => void = () => {};
  onSelect: (cohort: CohortSummary | null) => void = () => {};

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
    this.app.stage.addChild(this.stage, this.overlay);

    let frame = 0;
    this.observer = new ResizeObserver(() => {
      // Coalesced: a resize fires many times per drag, and re-tiling 192 cohorts on each
      // one would drop frames for no benefit.
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (this.lastCohorts.length) this.setCohorts(this.lastCohorts);
      });
    });
    this.observer.observe(host);

    this.app.canvas.addEventListener("pointermove", this.handleMove);
    this.app.canvas.addEventListener("pointerleave", this.handleLeave);
    this.app.canvas.addEventListener("click", this.handleClick);
  }

  private pick(clientX: number, clientY: number): CohortView | null {
    const rect = this.app.canvas.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    for (const view of this.order) {
      const c = view.cell;
      if (x >= c.x && x <= c.x + c.w && y >= c.y && y <= c.y + c.h) return view;
    }
    return null;
  }

  private summary(view: CohortView): CohortSummary {
    const width = this.host.clientWidth || 1;
    return {
      key: view.key,
      label: view.label,
      size: view.size,
      status: view.status,
      xFraction: (view.cell.x + view.cell.w / 2) / width,
    };
  }

  private handleMove = (event: PointerEvent) => {
    const hit = this.pick(event.clientX, event.clientY);
    const key = hit?.key ?? null;
    if (key === this.hovered) return;
    this.hovered = key;
    this.app.canvas.style.cursor = hit ? "pointer" : "default";
    this.onHover(hit ? this.summary(hit) : null);
    this.drawOverlay();
  };

  private handleLeave = () => {
    this.hovered = null;
    this.onHover(null);
    this.drawOverlay();
  };

  private handleClick = (event: MouseEvent) => {
    const hit = this.pick(event.clientX, event.clientY);
    this.selected = hit?.key ?? null;
    this.onSelect(hit ? this.summary(hit) : null);
    this.drawOverlay();
  };

  /** Hover and selection are drawn in a separate layer so pointing at a cohort never
   *  rebuilds its geometry — the field stays perfectly still under the cursor. */
  private drawOverlay(): void {
    this.overlay.clear();
    for (const key of [this.hovered, this.selected]) {
      if (!key) continue;
      const view = this.views.get(key);
      if (!view) continue;
      const c = view.cell;
      this.overlay
        .rect(c.x + 1, c.y + 1, Math.max(c.w - 2, 1), Math.max(c.h - 2, 1))
        .stroke({
          color: key === this.selected ? 0x5ef0c8 : 0x8f9aad,
          width: key === this.selected ? 1.4 : 1,
          alpha: key === this.selected ? 1 : 0.55,
        });
    }
  }

  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    this.observer?.disconnect();
    this.observer = null;
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
    const previous = new Map([...this.views].map(([key, view]) => [key, view.status]));
    this.stage.removeChildren();
    this.views.clear();
    this.order = [];
    this.lastCohorts = cohorts;
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
      // A gap between cells rather than a shared edge: touching rectangles read as a
      // table, and this is a population, not a spreadsheet.
      const gap = 3;
      const inner = {
        x: cell.x + gap,
        y: cell.y + gap,
        w: Math.max(cell.w - gap * 2, 2),
        h: Math.max(cell.h - gap * 2, 2),
      };
      const backing = new Graphics();
      backing
        .rect(inner.x, inner.y, inner.w, inner.h)
        .fill({ color: C.cell, alpha: 0.55 });
      const dots = new Graphics();
      const random = rng(index * 7919 + 13);

      // Fill the cell rather than a circle inscribed in it: the treemap already encodes
      // area, so a cloud that fills its cell reads as its true share of the population.
      const cx = inner.x + inner.w / 2;
      const cy = inner.y + inner.h / 2;
      const rx = Math.max(inner.w / 2 - 2, 1.5);
      const ry = Math.max(inner.h / 2 - 2, 1.5);
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
      const carried = previous.get(cohort.key);
      dots.fill({ color: C.idle, alpha: 1 });
      if (carried === "thought" || carried === "thinking") {
        dots.tint = C.thought;
      } else if (carried === "shared") {
        dots.tint = C.shared;
      }

      container.addChild(backing, dots);
      this.stage.addChild(container);
      const view: CohortView = {
        key: cohort.key,
        label: cohort.label,
        container,
        dots,
        backing,
        size: cohort.size,
        cell: inner,
        status: previous.get(cohort.key) ?? "idle",
      };
      this.views.set(cohort.key, view);
      this.order.push(view);
    });

    this.hovered = null;
    this.selected = null;
    this.overlay.clear();
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
