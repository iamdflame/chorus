"""A photograph of a boarding pass, read into the half of the projection the airline owns.

The modality split here is not decorative, it follows the division of labour the rest of the
system already uses:

    speech and text   what only the traveller knows — urgency, who is with them, what
                      they will accept. A boarding pass cannot tell you that a funeral is
                      on Tuesday.
    a boarding pass   what the airline already knows — tier, flight, bag count, PNR. Asking
                      a model to *infer* these from prose is waste twice over: it pays for
                      a guess, then escalates when the guess is unsure. That exact mistake
                      escalated 23 travellers in 24 before it was found.

So vision does not compete with text. It supplies the record-sourced fields for a traveller
who has no booking reference to hand but does have the pass in their pocket, which is the
ordinary case at a rebooking desk.

The passes rendered here are synthetic and say so. They are generated from real scenario
records so the ground truth is known by construction — the same discipline the text corpus
uses — and the model genuinely reads pixels rather than being handed the fields back.
"""

from __future__ import annotations

import base64
import io
import json
import os
import urllib.request
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
MODEL = "gemini-3.5-flash"

INSTRUCTION = """You are reading a photograph of an airline boarding pass.

Return ONLY a JSON object with exactly these keys, reading them off the pass:
  pnr           the six-character booking reference
  flight        the flight number
  destination   the three-letter arrival airport code
  tier          the loyalty tier printed on the pass: basic|silver|gold|platinum
  checked_bags  the number of checked bags, as an integer

If a field is not legible on the pass, use null. Do not guess."""

# Reading is the only job. What the traveller wants is not on the pass and is not asked for.
FIELDS = ("pnr", "flight", "destination", "tier", "checked_bags")


def _font(size: int, bold: bool = False):
    """A real font if the system has one, the bitmap default if not.

    Falling back matters: with the default font every pass renders in one tiny size, which
    would quietly turn a vision benchmark into a test of whether the model can read 6px
    text.
    """
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def boarding_pass(record: dict[str, Any], *, pnr: str | None = None) -> bytes:
    """Render a pass for a scenario passenger. Returns PNG bytes."""
    W, H = 1000, 420
    img = Image.new("RGB", (W, H), (247, 246, 243))
    d = ImageDraw.Draw(img)

    ink = (26, 28, 32)
    faint = (128, 132, 140)
    rule = (206, 204, 199)

    booking = pnr or record["id"].replace("PAX-", "")[:6].upper().rjust(6, "K")

    d.rectangle([0, 0, W, 92], fill=(26, 28, 32))
    d.text((36, 30), "UNITED", font=_font(34, bold=True), fill=(247, 246, 243))
    d.text((W - 300, 38), "BOARDING PASS", font=_font(20), fill=(180, 182, 188))

    # The tear-off stub, because a real pass has one and a model that has only ever seen
    # clean rectangles is being tested on something easier than reality.
    d.line([(W - 250, 92), (W - 250, H)], fill=rule, width=2)
    for y in range(100, H, 18):
        d.line([(W - 250, y), (W - 250, y + 8)], fill=(247, 246, 243), width=3)

    def field(x: int, y: int, label: str, value: str, size: int = 30) -> None:
        d.text((x, y), label.upper(), font=_font(14), fill=faint)
        d.text((x, y + 22), value, font=_font(size, bold=True), fill=ink)

    field(36, 128, "passenger", str(record.get("name", "TRAVELLER")).upper()[:22], 26)
    field(36, 210, "booking ref", booking)
    field(300, 210, "flight", str(record["original_flight"]))
    field(520, 210, "to", str(record["destination"]), 44)
    field(36, 300, "tier", str(record["tier"]).upper(), 26)
    field(300, 300, "checked bags", str(record.get("checked_bags", 0)), 26)
    field(520, 300, "departs", str(record["scheduled_departure"])[11:16], 26)

    field(W - 226, 128, "flight", str(record["original_flight"]), 24)
    field(W - 226, 210, "to", str(record["destination"]), 30)
    field(W - 226, 300, "ref", booking, 22)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def read_pass(png: bytes, *, api_key: str | None = None,
              timeout: float = 120.0) -> dict[str, Any] | None:
    """Read a boarding pass photograph. Returns None on failure, never raises."""
    key = api_key or os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        return None
    body = {
        "contents": [{"parts": [
            {"text": INSTRUCTION},
            {"inlineData": {"mimeType": "image/png",
                            "data": base64.b64encode(png).decode("ascii")}},
        ]}],
        "generationConfig": {"temperature": 0, "response_mime_type": "application/json"},
    }
    request = urllib.request.Request(
        f"{ENDPOINT}/{MODEL}:generateContent?key={key}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            got = json.loads(response.read())
    except Exception:  # noqa: BLE001 - a failed read is a data point
        return None

    for part in got.get("candidates", [{}])[0].get("content", {}).get("parts", []):
        text = part.get("text")
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def photograph(png: bytes, *, seed: int = 0) -> bytes:
    """Degrade a clean render into something closer to a photograph.

    Reading a pristine 1000x420 PNG is not the task. A traveller at a rebooking desk holds
    a creased pass at an angle under bad light and photographs it with a phone that then
    compresses the result. Testing only the clean render would measure the renderer.

    The degradations are deliberately mild — a few degrees of rotation, a perspective
    nudge, uneven lighting, sensor noise and JPEG compression. Enough to stop this being a
    test of pristine input; not so much that a failure says more about the abuse than the
    model.
    """
    import random

    rng = random.Random(seed)
    img = Image.open(io.BytesIO(png)).convert("RGB")
    w, h = img.size

    # A slight perspective, as if held rather than scanned.
    skew = rng.uniform(0.01, 0.03)
    img = img.transform(
        (w, h), Image.QUAD,
        (int(w * skew), 0, int(w * skew * 0.4), h, w - int(w * skew * 0.6), h,
         w - int(w * skew), 0),
        Image.BICUBIC, fillcolor=(232, 231, 228),
    )
    img = img.rotate(rng.uniform(-2.5, 2.5), resample=Image.BICUBIC,
                     fillcolor=(232, 231, 228), expand=False)

    # Uneven light across the surface.
    gradient = Image.linear_gradient("L").resize((w, h)).rotate(rng.uniform(0, 360))
    img = Image.composite(img, Image.blend(img, Image.new("RGB", (w, h), (255, 255, 255)),
                                           0.18), gradient)

    # Sensor noise, then the compression a phone applies on the way out.
    pixels = img.load()
    for _ in range(int(w * h * 0.02)):
        x, y = rng.randrange(w), rng.randrange(h)
        r, g, b = pixels[x, y]
        n = rng.randint(-18, 18)
        pixels[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)),
                        max(0, min(255, b + n)))

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=rng.randint(58, 74))
    return out.getvalue()
