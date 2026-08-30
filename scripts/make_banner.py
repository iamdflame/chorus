"""Generate the README banner from the real cohort layout.

Drawing an illustration of the product would be easy and would be a lie by degrees — the
shapes would be whatever looked good rather than whatever is true. This lays out the
actual 192 cohorts at their actual populations, using the same squarified treemap the
console uses, so the picture in the README is the thing the system computes.

    python scripts/make_banner.py
"""

from __future__ import annotations

import math
import os
import random
import sys
from dataclasses import asdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from kernel.clock import FIXED
from swarm.canonical import bind, collapse, project_passenger
from swarm.scenario import build_scenario

W, H = 1200, 420
PAD = 40
FIELD_X, FIELD_W = 596, 1200 - 596 - PAD

GROUND = "#06070a"
CELL = "#0d1015"
IDLE = "#39424f"
ACCENT = "#5ef0c8"
DEEP = "#2f8f7c"
INK = "#a3adbd"
FAINT = "#565c69"
BRIGHT = "#eef1f6"


def squarify(sizes, x, y, w, h):
    """Bruls/Huizing/van Wijk, same as the console's renderer."""
    out, total = [], sum(sizes) or 1
    areas = [(s / total) * w * h for s in sizes]
    i, cx, cy, cw, ch = 0, x, y, w, h

    def worst(row, side):
        s, mx, mn = sum(row), max(row), min(row)
        return max((side * side * mx) / (s * s), (s * s) / (side * side * mn))

    while i < len(areas):
        vertical = cw >= ch
        side = ch if vertical else cw
        row = [areas[i]]
        j = i + 1
        while j < len(areas) and worst(row + [areas[j]], side) <= worst(row, side):
            row.append(areas[j]); j += 1
        thickness = sum(row) / side
        off = 0.0
        for a in row:
            length = a / thickness
            out.append((cx, cy + off, thickness, length) if vertical
                       else (cx + off, cy, length, thickness))
            off += length
        if vertical: cx += thickness; cw -= thickness
        else:        cy += thickness; ch -= thickness
        i = j
    return out


def mark(cx: float, cy: float, r: float) -> str:
    """The Chorus mark: one bright centre, six dim satellites."""
    parts = []
    for k in range(6):
        a = math.radians(k * 60)
        parts.append(
            f'<circle cx="{cx + math.cos(a) * r:.1f}" cy="{cy + math.sin(a) * r:.1f}" '
            f'r="{r * 0.247:.2f}" fill="{IDLE}"/>'
        )
    parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r * 0.44:.2f}" fill="{ACCENT}"/>')
    return "".join(parts)


def main() -> int:
    scenario = build_scenario(passengers=20000)
    passengers = [asdict(p) for p in scenario.passengers]
    groups = collapse(passengers, bind(project_passenger, FIXED))
    cohorts = sorted((len(v) for v in groups.values()), reverse=True)

    cells = squarify(cohorts, FIELD_X, PAD, FIELD_W, H - PAD * 2)
    rng = random.Random(7)

    field = []
    # A handful of cohorts are lit, as they are mid-run: most of the field is inheriting.
    lit = {0, 3, 9, 22}
    for idx, ((x, y, w, h), size) in enumerate(zip(cells, cohorts)):
        gap = 1.6
        ix, iy = x + gap, y + gap
        iw, ih = max(w - gap * 2, 1), max(h - gap * 2, 1)
        colour = ACCENT if idx in lit else IDLE
        field.append(f'<rect x="{ix:.1f}" y="{iy:.1f}" width="{iw:.1f}" height="{ih:.1f}" '
                     f'fill="{CELL}"/>')
        drawn = min(size, 90)
        dot = max(min(iw, ih) / 13, 0.62)
        for _ in range(drawn):
            ang, rad = rng.random() * math.tau, math.sqrt(rng.random())
            px = ix + iw / 2 + math.cos(ang) * rad * (iw / 2 - dot)
            py = iy + ih / 2 + math.sin(ang) * rad * (ih / 2 - dot)
            field.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{dot:.2f}" '
                         f'fill="{colour}" opacity="{0.95 if idx in lit else 0.72}"/>')

    stats = [("20,000", "agents"), ("192", "thoughts"), ("$0.21", "cost"), ("104×", "collapse")]
    stat_svg = []
    for i, (value, label) in enumerate(stats):
        x = PAD + i * 132
        stat_svg.append(
            f'<text x="{x}" y="352" font-family="ui-monospace,monospace" font-size="30" '
            f'fill="{ACCENT if i in (1, 3) else BRIGHT}" letter-spacing="-1">{value}</text>'
            f'<text x="{x}" y="372" font-family="ui-monospace,monospace" font-size="9.5" '
            f'fill="{FAINT}" letter-spacing="2.4">{label.upper()}</text>'
        )

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Chorus — twenty thousand agents, two hundred thoughts">
  <rect width="{W}" height="{H}" fill="{GROUND}"/>
  <g opacity="0.5">{"".join(f'<line x1="{i}" y1="0" x2="{i}" y2="{H}" stroke="#171b22"/>' for i in range(0, W, 88))}</g>
  {mark(PAD + 15, 62, 15)}
  <text x="{PAD + 44}" y="69" font-family="ui-monospace,monospace" font-size="15" fill="{BRIGHT}" letter-spacing="7">CHORUS</text>
  <text x="{PAD}" y="150" font-family="Georgia,'Times New Roman',serif" font-size="52" fill="{BRIGHT}">Twenty thousand agents.</text>
  <text x="{PAD}" y="208" font-family="Georgia,'Times New Roman',serif" font-size="52" font-style="italic" fill="{ACCENT}">Two hundred thoughts.</text>
  <text x="{PAD}" y="252" font-family="ui-monospace,monospace" font-size="13" fill="{INK}">One agent per entity, priced by the diversity</text>
  <text x="{PAD}" y="273" font-family="ui-monospace,monospace" font-size="13" fill="{INK}">of their situations rather than their population.</text>
  <line x1="{PAD}" y1="306" x2="{PAD + 496}" y2="306" stroke="#232935"/>
  {"".join(stat_svg)}
  {"".join(field)}
</svg>'''

    out = os.path.join(ROOT, "docs/media/banner.svg")
    with open(out, "w") as fh:
        fh.write(svg)
    print(f"  cohorts drawn : {len(cohorts)} (largest {cohorts[0]:,}, smallest {cohorts[-1]})")
    print(f"  agents         : {sum(cohorts):,}")
    print(f"  written        : docs/media/banner.svg  ({len(svg) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
