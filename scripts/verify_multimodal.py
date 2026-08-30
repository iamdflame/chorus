"""Three ways in, one thought out.

Adding modalities is decorative unless they land in the same place. The claim worth testing
is not "we support voice" — it is that **collapse is modality-independent**: a traveller who
speaks joins the same cohort as one who typed the same thing, addresses identically, and
shares the same thought at no extra cost. If that holds, voice and vision cost nothing on
the reasoning side and the whole unbounded-input thesis widens from text to anything.

Each modality is asked for what only it can supply, which is the same division of labour the
rest of the system uses:

    text     what only the traveller knows — urgency, party, constraints
    speech   the same, spoken: disfluency, self-correction, no keyboard to tidy it up
    a photo  what the airline already knows — PNR, flight, tier, bags. Inferring these
             from prose is the mistake that escalated 23 travellers in 24.

Two limits, stated rather than discovered. The speech is synthesised, so it is cleaner than
a phone call from a departure hall; the model does real speech understanding on real
waveform data, but this measures the pipeline, not robustness to noise. And the passes are
rendered, then deliberately degraded — skewed, unevenly lit, JPEG-compressed — because
reading a pristine PNG would measure the renderer.

    python scripts/verify_multimodal.py --sample 8
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))

from extract.gemma_arm import PROMPT as TERSE_PROMPT
from extract.runner import extract_many
from intake.corpus import load_corpus
from intake.vision import boarding_pass, photograph, read_pass
from intake.voice import listen, speak
from kernel.clock import FIXED
from swarm.canonical import Projection, bind, project_passenger
from swarm.scenario import build_scenario

VOICE_PROMPT = TERSE_PROMPT.replace(
    "Message: {text}", "The traveller's message is the attached audio recording."
).replace("Classify this traveller message.", "Classify this traveller's spoken message.")

VOCAB = {
    "tier": ("basic", "silver", "gold", "platinum"),
    "urgency": ("critical", "urgent", "same_day", "flexible"),
    "party": ("solo", "pair", "family", "group"),
    "constraints": ("assisted", "checked_bags", "unencumbered"),
}
SPOKEN = ("urgency", "party", "constraints")


def as_projection(fields: dict, record: dict) -> Projection | None:
    """Build a projection from extracted fields, refusing anything out of vocabulary."""
    for name, allowed in VOCAB.items():
        if fields.get(name) not in allowed:
            return None
    from swarm.canonical import haul_band

    return Projection(
        role="passenger",
        tier=record["tier"],
        urgency=fields["urgency"],
        party=fields["party"],
        constraints=fields["constraints"],
        haul=haul_band(record["region"]),
        hotel_entitled=bool(record["has_hotel_entitlement"]),
        misconnect=bool(record["is_misconnect"]),
    )


async def main(sample: int) -> int:
    corpus = load_corpus()
    scenario = build_scenario(passengers=20_000)
    by_id = {p.id: asdict(p) for p in scenario.passengers}
    messages = [m for m in corpus if m.passenger_id in by_id][:sample]
    if not messages:
        print("\n  No corpus. Run scripts/build_corpus.py first.\n")
        return 1

    print(f"\n  Three modalities, {len(messages)} travellers\n")

    # -- text ------------------------------------------------------------------
    run = await extract_many(messages, concurrency=4, dedupe=False)
    text_keys: dict[str, str] = {}
    for m in messages:
        got = run.results[m.id]
        p = as_projection(got.projection.to_dict(), by_id[m.passenger_id])
        if p:
            text_keys[m.id] = p.key()
    print(f"  [1] text     {len(text_keys)}/{len(messages)} produced a valid situation")

    # -- speech ----------------------------------------------------------------
    voice_keys: dict[str, str] = {}
    spoken_ok = 0
    audio_seconds = 0.0
    for i, m in enumerate(messages, 1):
        print(f"\r  [2] speech   synthesising and listening {i}/{len(messages)}",
              end="", flush=True)
        utterance = await asyncio.to_thread(speak, m.text)
        if utterance is None:
            continue
        audio_seconds += utterance.seconds
        heard = await asyncio.to_thread(listen, utterance.wav, VOICE_PROMPT)
        if not heard:
            continue
        spoken_ok += 1
        p = as_projection(heard, by_id[m.passenger_id])
        if p:
            voice_keys[m.id] = p.key()
    print(f"\r  [2] speech   {spoken_ok}/{len(messages)} heard, "
          f"{audio_seconds:.0f}s of audio synthesised and understood      ")

    # -- vision ----------------------------------------------------------------
    read_fields = 0
    read_total = 0
    vision_ok = 0
    for i, m in enumerate(messages, 1):
        record = by_id[m.passenger_id]
        print(f"\r  [3] vision   reading pass {i}/{len(messages)}", end="", flush=True)
        photo = photograph(boarding_pass(record), seed=i)
        got = await asyncio.to_thread(read_pass, photo)
        if not got:
            continue
        vision_ok += 1
        truth = {
            "flight": record["original_flight"],
            "destination": record["destination"],
            "tier": record["tier"],
            "checked_bags": record["checked_bags"],
        }
        for field, want in truth.items():
            read_total += 1
            have = got.get(field)
            if field == "checked_bags":
                read_fields += str(have) == str(want)
            else:
                read_fields += str(have).strip().lower() == str(want).strip().lower()
    print(f"\r  [3] vision   {vision_ok}/{len(messages)} passes read, "
          f"{read_fields}/{read_total} fields correct from a degraded photo   ")

    # -- the claim -------------------------------------------------------------
    both = [m.id for m in messages if m.id in text_keys and m.id in voice_keys]
    same = sum(1 for i in both if text_keys[i] == voice_keys[i])
    spoken_same = 0
    for i in both:
        t = text_keys[i].split("|")
        v = voice_keys[i].split("|")
        # Fields 3,4,5 are urgency, party, constraints — the ones speech supplies.
        spoken_same += t[3:6] == v[3:6]

    print(f"\n  Same cohort from text and from speech   "
          f"{100 * same / len(both) if both else 0:>6.1f}%   ({same}/{len(both)})")
    print(f"  Agreement on the spoken fields alone    "
          f"{100 * spoken_same / len(both) if both else 0:>6.1f}%   "
          f"({spoken_same}/{len(both)})")

    # The conclusion has to follow the measurement rather than precede it. An earlier
    # version of this script printed the confident version unconditionally, which would
    # have announced modality independence over a 71% agreement rate.
    rate = same / len(both) if both else 0.0
    print()
    if rate >= 0.9:
        print(f"  A traveller who speaks joins the same cohort as one who typed, so voice")
        print(f"  costs nothing on the reasoning side: they share the thought that cohort")
        print(f"  already had. The unbounded input widens; the bounded lattice does not.")
    else:
        print(f"  Collapse is only partly modality-independent on this sample. A spoken")
        print(f"  message reaches the same cohort as the typed one {100 * rate:.0f}% of the "
              f"time,")
        print(f"  so {len(both) - same} of {len(both)} travellers would be reasoned about "
              f"in a different bucket")
        print(f"  depending on how they got in touch. Where they diverge is recorded in")
        print(f"  data/multimodal.json; the disagreements are on the spoken fields, which")
        print(f"  is where speech and prose genuinely carry different amounts of signal.")
    print()

    out = Path("data/multimodal.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "sample": len(messages),
        "text_valid": len(text_keys),
        "speech_heard": spoken_ok,
        "audio_seconds": round(audio_seconds, 1),
        "vision_read": vision_ok,
        "vision_fields_correct": read_fields,
        "vision_fields_total": read_total,
        "same_cohort": same,
        "compared": len(both),
        "spoken_fields_agree": spoken_same,
        "divergences": [
            {"message": i, "text": text_keys[i], "voice": voice_keys[i]}
            for i in both if text_keys[i] != voice_keys[i]
        ],
    }, indent=2))
    print(f"  Written to {out}\n")
    return 0 if both else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=8)
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(args.sample)))
