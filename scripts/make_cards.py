"""Render the video's title cards as 1920x1080 PNGs.

Built from the product's own design tokens rather than a template, so the cards and the
console are visibly the same object — the Instrument's warm graphite, Google Sans Flex on
the display axes, Google Sans Code for anything numeric, and the incandescent/reflected
pair carrying paid against free exactly as it does in the field.

Rendered from HTML through a headless browser because that is the only way to get the
variable-font axes right. A card set drawn in an image editor would use a static instance
and the roundedness axis would silently do nothing, which is the same trap the fonts
themselves sprang earlier.

    python scripts/make_cards.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "media" / "cards"
FONTS = ROOT / "console" / "public" / "fonts"

# Cards are deliberately sparse. A card competing with the voiceover for attention wastes
# both; each one holds a single idea for the seconds the narrator needs it.
CARDS: list[dict[str, str]] = [
    {
        "name": "01-scenario",
        "kicker": "02:14 · ORD · FIELD CLOSED",
        "headline": "20,000 people need to be somewhere else.",
        "figure": "2,888",
        "figure_label": "seats still moving",
        "foot": "One duty manager decides who gets them.",
    },
    {
        "name": "02-title",
        "kicker": "CHORUS",
        "headline": "One agent each. Computed once.",
        "figure": "10.2×",
        "figure_label": "collapse, measured on a live 20,000-agent run",
        "foot": "Twenty thousand agents. Two thousand thoughts.",
    },
    {
        "name": "03-amplification",
        "kicker": "THE CONSEQUENCE NOBODY WROTE UP",
        "headline": "Collapse amplifies injection by exactly the collapse ratio.",
        "figure": "128",
        "figure_label": "entities reached by one compromised call",
        "foot": "One injection is not one compromised agent.",
        "tone": "breach",
    },
    {
        "name": "04-close",
        "kicker": "CHORUS",
        "headline": "Priced by the diversity of their situations, not their population.",
        "figure": "$1.94",
        "figure_label": "against $19.75 at one call per agent",
        "foot": "Every number regenerates from one command — including the ones that don't flatter us.",
    },
]

# Lower thirds: small, bottom-left, for dropping over live screen capture.
LOWER: list[dict[str, str]] = [
    {"name": "lt-paid", "label": "PAID", "text": "a model call — computed", "tone": "filament"},
    {"name": "lt-free", "label": "FREE", "text": "served from the store", "tone": "reflect"},
    {"name": "lt-terminal", "label": "LIVE", "text": "unedited terminal, no cuts", "tone": "filament"},
    {"name": "lt-losing", "label": "OUR LOSING ROW", "text": "rules with no model beat us here", "tone": "reflect"},
    {"name": "lt-cloud", "label": "GOOGLE CLOUD", "text": "Cloud Run · Vertex AI · Firestore · Cloud Trace", "tone": "filament"},
]

SHELL = """
<style>
  @font-face {{ font-family:"GSF"; src:url("{flex}") format("woff2");
                font-weight:1 1000; font-stretch:25% 151%; }}
  @font-face {{ font-family:"GSC"; src:url("{code}") format("woff2");
                font-weight:300 800; }}
  :root {{
    --housing:#15161B; --chassis:#1E2027; --rule:#2C2F38;
    --filament:#FF9D4D; --reflect:#A8D5E5; --breach:#FF5470;
    --text-hi:#ECEDF0; --text:#B9BEC9; --text-lo:#8C929E; --text-faint:#5D626D;
  }}
  * {{ box-sizing:border-box; margin:0; }}
  body {{ width:1920px; height:1080px; background:var(--housing);
          font-family:"GSF",sans-serif; overflow:hidden; }}
  {extra}
</style>
{body}
"""

CARD_CSS = """
  .card { height:1080px; padding:120px 140px; display:flex; flex-direction:column;
          justify-content:center; position:relative; }
  /* The cohort field, as the product draws it: clusters rather than a lattice, weighted
     to the right so the type has the left two-thirds and the frame is not half empty.
     The cards sit inside the world the demo is about rather than in front of it. */
  .grain { position:absolute; inset:0; opacity:0.9;
           background-image:
             radial-gradient(circle at 1.2px 1.2px,#4A525F 1.2px,transparent 0),
             radial-gradient(circle at 1px 1px,#39404C 1px,transparent 0);
           background-size:23px 23px, 41px 41px;
           background-position:0 0, 11px 7px;
           -webkit-mask-image:
             radial-gradient(circle at 78% 32%,#000 0%,transparent 26%),
             radial-gradient(circle at 88% 62%,#000 0%,transparent 20%),
             radial-gradient(circle at 66% 74%,#000 0%,transparent 17%),
             radial-gradient(circle at 92% 16%,#000 0%,transparent 13%),
             radial-gradient(circle at 71% 12%,#000 0%,transparent 11%);
           -webkit-mask-composite:source-over; }
  /* One cohort lit, because that is the whole idea and a still frame should carry it. */
  .lit { position:absolute; inset:0; opacity:0.85;
         background-image:radial-gradient(circle at 1.4px 1.4px,#FF9D4D 1.4px,transparent 0);
         background-size:23px 23px;
         -webkit-mask-image:radial-gradient(circle at 78% 32%,#000 0%,transparent 12%); }
  .card[data-tone="breach"] .lit {
         background-image:radial-gradient(circle at 1.4px 1.4px,#FF5470 1.4px,transparent 0);
         -webkit-mask-image:radial-gradient(circle at 78% 32%,#000 0%,transparent 22%); }
  .inner { position:relative; }
  .kicker { font-family:"GSC",monospace; font-size:22px; letter-spacing:0.24em;
            color:var(--text-faint); margin-bottom:44px; }
  .headline { font-variation-settings:"wght" 620,"wdth" 88,"ROND" 0;
              font-size:78px; line-height:1.06; letter-spacing:-0.02em;
              color:var(--text-hi); max-width:19ch; }
  .figure { font-family:"GSC",monospace; font-variation-settings:"wght" 300;
            font-size:190px; line-height:0.9; letter-spacing:-0.05em;
            color:var(--filament); margin-top:64px; font-variant-numeric:tabular-nums; }
  .figure.breach { color:var(--breach); }
  .figure-label { font-family:"GSC",monospace; font-size:22px; letter-spacing:0.14em;
                  text-transform:uppercase; color:var(--text-faint); margin-top:14px; }
  .foot { margin-top:70px; padding-top:30px; border-top:1px solid var(--rule);
          font-size:30px; color:var(--text-lo); max-width:46ch; line-height:1.45; }
"""

LOWER_CSS = """
  body { background:transparent; height:220px; width:1920px; }
  .lt { display:inline-flex; align-items:center; gap:22px; margin:60px 0 0 110px;
        padding:22px 34px; background:rgba(21,22,27,0.94); border:1px solid var(--rule);
        border-left:4px solid var(--filament); border-radius:3px;
        backdrop-filter:blur(10px); }
  .lt[data-tone="reflect"] { border-left-color:var(--reflect); }
  .lt-label { font-family:"GSC",monospace; font-size:22px; letter-spacing:0.18em;
              color:var(--filament); }
  .lt[data-tone="reflect"] .lt-label { color:var(--reflect); }
  .lt-text { font-size:30px; color:var(--text-hi);
             font-variation-settings:"wght" 480,"wdth" 96,"ROND" 0; }
"""


def card_html(card: dict[str, str], flex: str, code: str) -> str:
    tone = " breach" if card.get("tone") == "breach" else ""
    tone_attr = card.get("tone", "")
    body = f"""
    <div class="card" data-tone="{tone_attr}">
      <div class="grain"></div>
      <div class="lit"></div>
      <div class="inner">
        <div class="kicker">{card['kicker']}</div>
        <h1 class="headline">{card['headline']}</h1>
        <div class="figure{tone}">{card['figure']}</div>
        <div class="figure-label">{card['figure_label']}</div>
        <p class="foot">{card['foot']}</p>
      </div>
    </div>"""
    return SHELL.format(flex=flex, code=code, extra=CARD_CSS, body=body)


def lower_html(lt: dict[str, str], flex: str, code: str) -> str:
    body = f"""
    <div class="lt" data-tone="{lt['tone']}">
      <span class="lt-label">{lt['label']}</span>
      <span class="lt-text">{lt['text']}</span>
    </div>"""
    return SHELL.format(flex=flex, code=code, extra=LOWER_CSS, body=body)


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("\n  playwright is a dev dependency: pip install -r requirements-dev.txt\n")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    flex = (FONTS / "GoogleSansFlex.woff2").as_uri()
    code = (FONTS / "GoogleSansCode.woff2").as_uri()
    made: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        page = browser.new_page(viewport={"width": 1920, "height": 1080},
                                device_scale_factor=1)
        for card in CARDS:
            page.set_content(card_html(card, flex, code))
            page.wait_for_timeout(700)          # let the variable font settle
            path = OUT / f"{card['name']}.png"
            page.screenshot(path=str(path))
            made.append(path.name)
        page.close()

        # Lower thirds keep their alpha, so they can sit over live capture.
        page = browser.new_page(viewport={"width": 1920, "height": 220})
        for lt in LOWER:
            page.set_content(lower_html(lt, flex, code))
            page.wait_for_timeout(500)
            path = OUT / f"{lt['name']}.png"
            page.screenshot(path=str(path), omit_background=True)
            made.append(path.name)
        page.close()
        browser.close()

    print(f"\n  {len(made)} assets in docs/media/cards/\n")
    for name in made:
        size = (OUT / name).stat().st_size // 1024
        print(f"    {name:<24} {size:>4} KB")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
