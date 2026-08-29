/** The worldline renderer.
 *
 *  Draws the causal graph and, more importantly, animates the one thing worth watching:
 *  selecting an effect ignites its forward lightcone, and the light travels *along causal
 *  edges in causal order* rather than appearing all at once. That propagation is the
 *  product's whole claim made visible — this decision, and everything it caused.
 *
 *  Rendered with Pixi because the graph runs to thousands of nodes; drawn into two
 *  Graphics objects (edges, nodes) rebuilt only when state is dirty, because rebuilding
 *  per frame on modest hardware is what turns a smooth idea into a slideshow. */

import { Application, Container, Graphics, Text, TextStyle } from "pixi.js";
import { gsap } from "gsap";
import { depthsFrom, layout, type Layout, type Placed } from "./layout";
import type { GraphEdge, GraphNode } from "../api";

const C = {
  ground: 0x07080a,
  rule: 0x16181d,
  laneText: 0x565c69,
  inherited: 0x2b313c,
  executed: 0x5ef0c8,
  model: 0x7b8496,
  staged: 0xf5a524,
  irreversible: 0xff5c5c,
  delegation: 0x8b7bff,
  edge: 0x1b1f27,
  edgeHot: 0x5ef0c8,
};

interface NodeState {
  glow: number;   // 0..1 ignition
  dim: number;    // 0..1 pushed out of focus
  pulse: number;  // 0..1 transient flash when re-executed live
}

export class Worldline {
  private app = new Application();
  private stage = new Container();
  private edgeLayer = new Graphics();
  private nodeLayer = new Graphics();
  private laneLayer = new Container();
  private host!: HTMLElement;

  private view: Layout | null = null;
  private state = new Map<string, NodeState>();
  private cone = new Set<string>();
  private root: string | null = null;
  private dirty = true;
  private hovered: string | null = null;

  onSelect: (node: GraphNode | null) => void = () => {};
  onHover: (node: GraphNode | null) => void = () => {};

  async mount(host: HTMLElement): Promise<void> {
    this.host = host;
    await this.app.init({
      background: C.ground,
      antialias: true,
      resizeTo: host,
      resolution: Math.min(window.devicePixelRatio ?? 1, 2),
      autoDensity: true,
    });
    host.appendChild(this.app.canvas);

    this.stage.addChild(this.edgeLayer, this.nodeLayer, this.laneLayer);
    this.app.stage.addChild(this.stage);

    this.app.canvas.addEventListener("pointermove", this.handleMove);
    this.app.canvas.addEventListener("click", this.handleClick);
    this.app.canvas.addEventListener("pointerleave", () => {
      this.hovered = null;
      this.onHover(null);
      this.dirty = true;
    });

    this.app.ticker.add(() => {
      if (this.dirty) {
        this.draw();
        this.dirty = false;
      }
    });
    window.addEventListener("resize", this.handleResize);
  }

  destroy(): void {
    window.removeEventListener("resize", this.handleResize);
    this.app.destroy(true, { children: true });
  }

  private handleResize = () => {
    if (!this.view) return;
    this.setGraph(this.view.nodes, this.view.edges, this.view.lanes.map((l) => l.agent));
  };

  setGraph(nodes: GraphNode[], edges: GraphEdge[], agents: string[]): void {
    const w = this.host.clientWidth || 1200;
    const h = this.host.clientHeight || 700;
    this.view = layout(nodes, edges, agents, w, h);
    for (const node of this.view.nodes) {
      if (!this.state.has(node.id)) {
        this.state.set(node.id, { glow: 0, dim: 0, pulse: 0 });
      }
    }
    this.drawLanes();
    this.dirty = true;
  }

  /** Ignite the forward lightcone of one effect.
   *
   *  Everything outside the cone dims first, so the eye is already prepared when the
   *  light starts travelling; the cone then lights up in breadth-first order with a
   *  per-depth stagger, which is what makes causality legible as motion. */
  ignite(rootId: string, forward: string[]): void {
    if (!this.view) return;
    this.root = rootId;
    this.cone = new Set([rootId, ...forward]);

    const depths = depthsFrom(rootId, this.view.edges);
    gsap.killTweensOf([...this.state.values()]);

    for (const node of this.view.nodes) {
      const st = this.state.get(node.id)!;
      const inCone = this.cone.has(node.id);
      gsap.to(st, {
        dim: inCone ? 0 : 0.82,
        duration: 0.32,
        ease: "power2.out",
        onUpdate: () => { this.dirty = true; },
      });
      gsap.to(st, {
        glow: inCone ? 1 : 0,
        duration: inCone ? 0.42 : 0.2,
        delay: inCone ? 0.12 + (depths.get(node.id) ?? 0) * 0.055 : 0,
        ease: "power3.out",
        onUpdate: () => { this.dirty = true; },
      });
    }
  }

  clearCone(): void {
    this.root = null;
    this.cone.clear();
    for (const st of this.state.values()) {
      gsap.to(st, {
        glow: 0, dim: 0, duration: 0.28, ease: "power2.out",
        onUpdate: () => { this.dirty = true; },
      });
    }
  }

  /** Flash a node that just re-executed during a live replay. */
  pulse(ids: string[]): void {
    for (const id of ids) {
      const st = this.state.get(id);
      if (!st) continue;
      st.pulse = 1;
      gsap.to(st, { pulse: 0, duration: 1.1, ease: "power2.out",
        onUpdate: () => { this.dirty = true; } });
    }
  }

  // -- drawing --------------------------------------------------------------

  private drawLanes(): void {
    this.laneLayer.removeChildren();
    if (!this.view) return;
    const style = new TextStyle({
      fill: C.laneText, fontSize: 10, fontFamily: "JetBrains Mono, monospace",
      letterSpacing: 1.6,
    });
    for (const lane of this.view.lanes) {
      const label = new Text({ text: lane.agent.toUpperCase(), style });
      label.x = 20;
      label.y = lane.y - 6;
      this.laneLayer.addChild(label);
    }
  }

  private colourOf(node: Placed, st: NodeState): number {
    if (node.quarantined) return C.staged;
    if (node.determinism === "external_irreversible") return C.irreversible;
    if (node.kind === "delegation") return C.delegation;
    if (st.glow > 0.02) return C.executed;
    if (node.inherited) return C.inherited;
    if (node.kind === "model_call") return C.model;
    return C.executed;
  }

  private draw(): void {
    if (!this.view) return;
    const { byId, edges, nodes, lanes, width } = this.view;

    // lane guides
    this.edgeLayer.clear();
    for (const lane of lanes) {
      this.edgeLayer.moveTo(120, lane.y).lineTo(width - 24, lane.y)
        .stroke({ color: C.rule, width: 1, alpha: 0.55 });
    }

    // causal edges
    for (const edge of edges) {
      const a = byId.get(edge.source);
      const b = byId.get(edge.target);
      if (!a || !b) continue;
      const sa = this.state.get(a.id)!;
      const sb = this.state.get(b.id)!;
      const hot = Math.min(sa.glow, sb.glow);
      const dim = Math.max(sa.dim, sb.dim);

      const mid = (a.x + b.x) / 2;
      this.edgeLayer
        .moveTo(a.x, a.y)
        .bezierCurveTo(mid, a.y, mid, b.y, b.x, b.y)
        .stroke({
          color: hot > 0.05 ? C.edgeHot : C.edge,
          width: hot > 0.05 ? 1 + hot * 1.1 : 1,
          alpha: (hot > 0.05 ? 0.28 + hot * 0.62 : 0.9) * (1 - dim * 0.85),
        });
    }

    // nodes
    this.nodeLayer.clear();
    for (const node of nodes) {
      const st = this.state.get(node.id)!;
      const colour = this.colourOf(node, st);
      const alpha = (node.inherited && st.glow < 0.02 ? 0.5 : 1) * (1 - st.dim * 0.8);
      const r = node.r * (1 + st.glow * 0.5 + st.pulse * 0.8);

      if (st.glow > 0.02 || st.pulse > 0.02) {
        const halo = Math.max(st.glow, st.pulse);
        this.nodeLayer.circle(node.x, node.y, r + 7 * halo)
          .fill({ color: colour, alpha: 0.1 * halo });
        this.nodeLayer.circle(node.x, node.y, r + 3 * halo)
          .fill({ color: colour, alpha: 0.18 * halo });
      }

      this.nodeLayer.circle(node.x, node.y, r).fill({ color: colour, alpha });

      if (node.id === this.root) {
        this.nodeLayer.circle(node.x, node.y, r + 5)
          .stroke({ color: C.executed, width: 1.4, alpha: 0.95 });
      }
      if (node.id === this.hovered) {
        this.nodeLayer.circle(node.x, node.y, r + 4)
          .stroke({ color: 0xe6eaf1, width: 1, alpha: 0.75 });
      }
    }
  }

  // -- interaction ----------------------------------------------------------

  private pick(clientX: number, clientY: number): Placed | null {
    if (!this.view) return null;
    const rect = this.app.canvas.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    let best: Placed | null = null;
    let bestDist = 15 * 15;
    for (const node of this.view.nodes) {
      const dx = node.x - x;
      const dy = node.y - y;
      const dist = dx * dx + dy * dy;
      if (dist < bestDist) {
        bestDist = dist;
        best = node;
      }
    }
    return best;
  }

  private handleMove = (event: PointerEvent) => {
    const hit = this.pick(event.clientX, event.clientY);
    const id = hit?.id ?? null;
    if (id !== this.hovered) {
      this.hovered = id;
      this.app.canvas.style.cursor = hit ? "pointer" : "default";
      this.onHover(hit);
      this.dirty = true;
    }
  };

  private handleClick = (event: MouseEvent) => {
    const hit = this.pick(event.clientX, event.clientY);
    this.onSelect(hit);
  };
}
