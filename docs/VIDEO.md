# Chorus — Demo Strategy and Script v2

> **Making it:** [`PRODUCTION.md`](PRODUCTION.md) has the step-by-step for ElevenLabs and
> CapCut Pro. Cards are rendered in [`media/cards/`](media/cards/) —
> `python scripts/make_cards.py` regenerates them.
>
> **Length:** 566 spoken words. At ElevenLabs speed **1.05** that is ~3:47 including the
> silent beats. At speed 1.0 it runs 4:02, which is over the cap.

---

# PART 0 — What the rules actually say

I pulled the official rules. Several things change the strategy.

## 0.1 Scoring maths

Each criterion scores **1–5**, averaged. Bonuses stack on top. **Maximum final score is 6.**

That means bonus contributions are worth **1.0 out of 6 — 16.7% of the maximum score:**

| Bonus | Max points | Chorus status |
|---|---|---|
| Public content (blog/podcast/video) | 0.2 | Written, **not published** |
| Social post with `#AllThingsAgenticHackathon` | 0.2 | Not done |
| Each additional Google AI model (Gemma, Veo, Lyria…) | 0.2 each, **0.6 cap** | Gemma only = 0.2 |

**You are leaving up to 0.6 points on the table** — more than a full grade band on any single criterion. Publishing the blog and posting to LinkedIn is roughly an hour of work for 0.4. That is the highest points-per-hour available anywhere in this project.

The content must include language stating it was created for this hackathon, and must be public, not unlisted.

## 0.2 The Demo criterion, verbatim

> **The Proof of Action:** Does the video show an **unedited, live execution** of the agent performing its task (via **terminal logs, database updates, or UI changes**)?
> **The Documentation:** …Is there **visual proof of Google Cloud deployment** in the video?

Three named evidence forms. **Hit all three** — terminal, database, UI — rather than one. Almost every competitor will show UI only.

## 0.3 Two FEF criteria the current script ignores

> **Innovation:** Did they build this for an **"Unlikely Hero"** outside of standard corporate roles?

> **Architecture:** Is the inter-agent routing logic **failure-tolerant** (e.g. how does the system recover if a worker agent **loops or returns a hallucination**)?

Neither appears in the current script. Both are explicit, named scoring language. Fix both.

---

# PART 1 — What is wrong with the current script

`docs/VIDEO.md` is well written and well paced. It is also a **v1 script for a v2 project**, and one beat is now actively dangerous.

## 1.1 The fatal beat — 2:50–3:20

The script says:

> *"…ninety-two percent better weighted satisfaction…"*

**Your own repo now contradicts this.** Commit `8af8492` — *"the arm beating everything was exploiting the scorer"* — found that satisfaction was summed per booking while seats are consumed per soul, so a party of six scored the same as one person in one seat. The corrected bench prints:

```
B2  rules, zero LLM    tier-weighted  +31.3%   tier-blind  -28.9%
B3  value packing      tier-weighted  +73.4%   per-soul    -23.7%
```

Saying "+92%" on camera while the repository prints a contradiction is the worst possible failure mode. Judges score Documentation and Demo together; a judge who opens the repo after watching finds the discrepancy, and **every other number you said becomes suspect.**

This is not a small edit. It is the beat that has to be replaced.

## 1.2 Mixed v1 and v2 numbers throughout

- 0:28 says *"Two thousand thoughts"* (v2) but 0:50–2:20 says *"two hundred and twenty-two model calls"* (v1)
- The saturation beat uses 128 / 187 / **192** — the old ceiling. The projection is richer now; the concurrency proof reports **428 distinct situations** and the lattice ceiling is 2,304.

Any judge cross-checking one number against the README finds drift.

## 1.3 The saturation beat argues your weakest point

2:20–2:50 spends thirty seconds on *"the curve is flat."* That is precisely the "you are dividing by a constant" attack, delivered by you, unprompted, as though it were the insight. **Cut it or own it** — see 2.4.

## 1.4 It demos none of the last twelve hours

Missing entirely: the Necessity Ledger, injection amplification and containment, multimodal intake, fidelity measurement, identity and gateway proofs, Cloud Trace, memory, Gemma. The script demos the v1 collapse and nothing else. **The differentiators are all absent.**

## 1.5 Dead weight at 3:20–3:50

Thirty seconds of clicking through consoles proves deployment but carries no argument. It can do both jobs at once — see 2.5.

---

# PART 2 — Demo strategy

## 2.1 Principle: the demo is an experiment, not a tour

Most submissions will narrate a UI. The rules reward **live execution**. Chorus has twelve `verify_*.py` scripts that print PASS or fail loudly. **Nobody else in this hackathon can run a proof on camera.** That is the single biggest available differentiator and the current script uses none of them.

Run at least two in a visible terminal. A judge watching `verify_armor.py` print `PASS every containment property holds` is watching unedited live execution of a security claim. That is worth more than any amount of narration.

## 2.2 Principle: three evidence forms, not one

| Form | Beat |
|---|---|
| **UI changes** | The collapse field igniting; the incident propagation |
| **Terminal logs** | `verify_armor.py`, `bench.run` printing the table live |
| **Database updates** | Firestore console, `lightcone` collection, documents appearing |

## 2.3 Principle: name the unlikely hero

Do not open on "airlines." Open on **the person on shift**. One duty manager at 2am with 20,367 stranded travellers and 2,888 seats. Agents work for that person. This directly answers the "Unlikely Hero" scoring language and it makes the friction concrete in eight seconds.

## 2.4 Principle: own the ceiling instead of hiding it

Replace the saturation beat with one sentence that defuses the attack rather than inviting it:

> "The lattice has 2,304 cells, so collapse is bounded by construction — every bucketing scheme saturates. The interesting question isn't whether it saturates, it's whether it's **lossless**. So we measured that."

Then cut straight to fidelity. You have converted your weakest thirty seconds into your most credible ten.

## 2.5 Principle: make the Google Cloud beat carry an argument

Cloud Trace showing the causal DAG as spans satisfies **three** things at once: visual proof of deployment (Demo), the FEF Observability requirement (Innovation), and the architecture explanation (Architecture). Same thirty seconds, triple duty.

## 2.6 Principle: show a failure

The architecture criterion names loops and hallucinations explicitly. Show an extraction returning low confidence and **escalating instead of guessing**, or a malformed response being quarantined. Ten seconds. Almost nobody will show their system failing correctly, and it is exactly what the rubric asks for.

---

# PART 3 — The script

**3:50 target, 4:00 hard cap. 545 spoken words at ~150 wpm. Unedited screen capture,
1600×900 minimum, English subtitles uploaded separately.**

Numbers in `[brackets]` are read off the screen on the day. Never from memory.

---

### 0:00 – 0:22 · The friction, through a person  ·  *card 01*

> "Two in the morning at O'Hare. Weather has closed the field. Twenty thousand people need
> to be somewhere else, and there are two thousand eight hundred and eighty-eight seats
> still moving.
>
> One duty manager decides who gets them. Today that's first-come-first-served — because
> there's no time to ask twenty thousand people what they need."

**On screen:** card 01, then hold. No logo animation.

---

### 0:22 – 0:38 · The twist  ·  *card 02*

> "Reasoning is cheap enough now to give every one of them their own agent. Nobody does
> it, because twenty thousand agents means twenty thousand model calls.
>
> Unless the identical reasoning is only computed once. That's Chorus."

**On screen:** card 02 → cut to the console, idle, cohorts visible.

---

### 0:38 – 1:35 · The collapse, live  ·  *Proof of Action — UI*

Click **wake 20,000**. **Say nothing for three seconds.** Let it land.

> "Every point is a real ADK agent with its own session. Nothing groups them — none of them
> knows the others exist.
>
> Orange is a model call: computed, and paid for. Blue is an agent that found the answer
> already in the store and paid nothing.
>
> That flash was one call, and a hundred and twenty-eight agents just shared it — not
> because I grouped them, but because they independently computed the same content address
> and collided.
>
> Each reasons over a bucketed projection of its situation. Never its name. Two stranded
> platinum passengers travelling alone, both needing to move within four hours, face the
> same decision. Their names differ. Their reasoning doesn't."

**Land on the footer counters and read them off the screen.**

> "Twenty thousand agents. [1,964] model calls. [One dollar ninety-four]. One call per
> agent would have been nineteen seventy-five."

---

### 1:35 – 2:05 · Is it the same answer?  ·  *the honest claim*

> "Cheap is easy. The question is whether collapse changes the answer.
>
> The lattice has two thousand three hundred and four cells, so this saturates by
> construction. That's arithmetic, not a discovery."

**On screen:** `python -m bench.run --agents 8000` running live.

> "Six arms, scored identically. And look — hand-written rules with no model at all beat us
> on tier-weighted satisfaction. We ship that row because it's true.
>
> It's also why the next two things exist."

---

### 2:05 – 2:42 · The attack  ·  *Proof of Action — terminal*  ·  *card 03*

> "Collapse has a security consequence nobody has written up. If one agent's reasoning is
> shared by a thousand, one prompt injection isn't one compromised agent. It's a thousand.
> Collapse amplifies injection by exactly the collapse ratio."

**On screen:** card 03, then `python scripts/verify_armor.py` live.

> "An attacker can join a cohort. They cannot steer one — no attacker-controlled byte ever
> reaches a shared address. Containment quarantined the compromised cohort while the
> healthy one kept serving.
>
> The causal graph already knows the blast radius, because the forward lightcone *is* the
> blast radius."

**Hold on `PASS  every containment property holds` for a beat.**

---

### 2:42 – 3:19 · When it doesn't know, and what it cost

> "When extraction isn't confident, the agent doesn't guess — it escalates, or asks."

**On screen:** the Necessity Ledger on `/ledger`.

> "And this is the number I'd want if I were funding it. [Eighty-eight] percent of decisions
> came from a distilled policy table, free. We shadow-sample the model against that table —
> checking it agrees with itself first, so the drift we measure is real.
>
> Most of this workload is a lookup table wearing a costume. The rest is where the model is
> load-bearing, and that's the only part we paid for."

---

### 3:19 – 3:50 · Running on Google Cloud  ·  *required — show, don't narrate*

**Do all five, in this order. Say the stack names out loud.**

1. Address bar on the live `.run.app` URL
2. `GET /health` → `"backend":"firestore"`, `"region":"us-central1"`
3. **Cloud Run console** — service green, revision and region visible
4. **Cloud Trace** — the causal DAG as spans
5. **Firestore console** — the `lightcone` collection, documents by content address

> "Cloud Run. Gemini 3.5 Flash through Vertex AI. Firestore, keyed by content address — and
> health reports which store is live, so that claim is checkable. Agents on ADK: one plugin
> intercepts every model call, which is what makes sharing possible at all. Gemma is a
> second reader.
>
> And the effect log exports as OpenTelemetry, so the causal chain is inspectable in Cloud
> Trace, not just our own console."

---

### 3:50 – 4:00 · Close  ·  *card 04*

> "One agent per entity, priced by the diversity of their situations rather than their
> population — and a continuous measurement of how much of that reasoning was needed at all.
>
> Every number in this video regenerates from one command. Including the ones that don't
> flatter us."

**On screen:** card 04, hold to black.

---

# PART 4 — Production checklist

**Before recording**
- [ ] **Redeploy.** The live URL is currently serving a pre-15:12 build. Everything in this script is absent from it.
- [ ] Re-run `bench.run` and `prove_swarm` the same day; **read the numbers off screen**, never from memory
- [ ] Confirm no beat states a figure the repo contradicts — especially anything resembling "+92%"
- [ ] Cloud Run, Cloud Trace, Firestore consoles open in tabs, already signed in
- [ ] Terminal font large enough to read at 720p; light-on-dark, high contrast
- [ ] Console at 1600×900+, browser chrome minimal, notifications off, dark room

**Recording**
- [ ] One take. Unedited is explicitly rewarded; cuts read as hiding something
- [ ] Say aloud: **Gemini 3.5 Flash · Vertex AI · ADK · Cloud Run · Firestore · Gemma · OpenTelemetry**
- [ ] Do not talk over the first three seconds of the collapse. Let it land
- [ ] Record three times, keep the best. Rehearse to 3:45 so you land under 4:00

**After**
- [ ] YouTube, **public** (not unlisted), English subtitles uploaded
- [ ] **Publish the blog** — it exists at `docs/blog/cache-poisoning-in-collapsed-agent-fleets.md` and is worth 0.2. Include the required "created for this hackathon" line
- [ ] **Post to LinkedIn/X** with `#AllThingsAgenticHackathon` — 0.2
- [ ] Consider one more honest Google model integration — 0.2 each up to 0.6. **Only if genuinely called in code.** A competitor advertised Veo, Lyria and Imagen whose only code matches were variables named `veOrders` and `veOffer`; that fails verification instantly

---

# PART 5 — Why this beats the field

Almost every one of the 684 submissions will narrate a UI tour for four minutes. This script instead:

- Opens on a **person**, not an architecture
- Runs **two live proofs in a terminal** that print PASS
- Shows **its own losing benchmark row** on camera
- Demonstrates a **novel security finding** with live containment
- Ends on a number that **measures its own necessity**
- Satisfies **terminal + database + UI** rather than one of the three
- Makes the Google Cloud beat carry the observability requirement simultaneously

The thing judges remember from four minutes is one image. Make it the moment twenty thousand points go blue for free — and the moment an injection stops at one cohort.