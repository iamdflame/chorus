# Chorus — Frontend Redesign, Complete Plan

---

# PART 0 — What the field actually looks like

I measured the frontend of all 172 repos I cloned. This is the competitive reality:

| Library | Repos using it |
|---|---|
| tailwindcss | **37** |
| next | **33** |
| lucide-react | **33** |
| framer-motion | 6 |
| gsap | 3 |
| recharts | 3 |
| pixi.js | **2** (one is Chorus) |
| three | 1 |
| reactflow | 1 |
| **d3** | **0** |
| **@xyflow/react, cytoscape, sigma, vis-network, visx, konva, @react-three/fiber** | **0** |

## 0.1 Three conclusions

**The field is monolithic.** Next + Tailwind + shadcn/radix + lucide is the entire hackathon. Those are the same defaults every AI coding assistant emits, so ~35 projects will look like siblings on the judging screen. Visual differentiation is essentially free right now.

**Nobody can draw a graph.** Zero repos have any graph-rendering library. Not one. The single most visually distinctive thing available in this hackathon — a causal DAG of 20,000 agent invocations — is a category no competitor is equipped to enter.

**Chorus is already off the template stack.** Its console runs **PixiJS 8 + GSAP + Vite**, no Tailwind, no shadcn, no lucide. That is GPU-accelerated 2D WebGL and a professional animation engine. It is the right stack and it is nearly unique here. **Keep it.**

And the observability-tooling research says the same thing from the other direction: Langfuse's agent graph view is still beta, and Datadog's decision-graph is singled out as *"one of the best implementations"* precisely because so few exist. Rendering a true causal DAG at scale is an unsolved UI problem. Chorus's signature is an unsolved UI problem rendered well.

## 0.2 What has to change

The current palette is `#10131a` near-black with `#5ef0c8` acid mint. That is textbook AI-generated default styling — near-black plus one bright acid accent is one of the three looks that machine-generated design reliably converges on. It is the one thing about the current console that reads as templated, and it is the first thing to go.

Current console is only 1,691 lines across 3 pages (Home, Mechanism, Evidence) plus one Console view. There is a lot to build.

---

# PART 1 — Design direction

## 1.1 Ground it in the subject

**Subject:** an execution substrate that records every boundary an agent crosses, addresses it by its entire causal history, and can replay or fork time.
**Audience:** Google engineers judging, then enterprise architects.
**The console's single job:** make visible the instant 20,000 agents collapse into ~200 thoughts — and let someone verify it.

The vernacular of this subject is *physics*: light cones, causality, propagation, emission, measurement, provenance, instruments.

## 1.2 The direction: **Event Display**

A light cone is a physics object, so borrow the visual language of the instruments that record physics. **Particle-detector event displays** (ATLAS, CMS) render millions of tracks radiating from a collision vertex — dense, beautiful, and *literally the same visual problem* Chorus has. For the archival side, **astronomical plate photography**: the permanent, measurable record.

This is derived from the subject rather than selected from a moodboard, which is what makes it defensible when a judge asks why it looks like this.

## 1.3 The signature structure: Plate and Instrument

Chorus is two things at once, so the interface is two places:

- **The Plate** *(light)* — the permanent record. Evidence, ledger, provenance, receipts. Archival grey-white, like photographic paper or an observatory logbook. Still, precise, typographic.
- **The Instrument** *(dark)* — the live detector. The console, the running swarm, the DAG. Warm graphite, emissive, in motion.

**This is not a theme toggle. It is a place you travel between.** Moving from `/evidence` into `/console` is a lighting change: the plate dims, the housing warms, the instrument powers on. That transition is a signature moment and it encodes something true — you are stepping from the record into the apparatus.

## 1.4 Palette — derived from emission, not from defaults

The core semantic in Chorus is **paid vs free**. Red/green is both the obvious default and hostile to the ~8% of male judges with a colour-vision deficiency. Use the physics instead:

> A thought that was **computed** *emits* light. A thought that was **reused** is lit by another's.

**Incandescent vs reflected.** Warm vs cool, separated in luminance as well as hue, and reinforced by shape (filled disc vs open ring) so colour is never the only channel.

```css
/* THE INSTRUMENT — dark */
--housing:      #15161B;  /* warm graphite; photographic, not neon-black */
--chassis:      #1E2027;  /* raised surfaces, panels */
--rule:         #2C2F38;  /* hairlines */
--filament:     #FF9D4D;  /* PAID — computed, incandescent (sodium lamp) */
--filament-hot: #FFC48A;  /* ignition peak */
--reflect:      #A8D5E5;  /* FREE — reused, reflected light */
--counterfact:  #B69CF7;  /* quarantined / "would have happened" */
--breach:       #FF5470;  /* denied, blocked, poisoned — used ONCE per screen */
--text-hi:      #ECEDF0;
--text-lo:      #8C929E;

/* THE PLATE — light */
--plate:        #E9EAE5;  /* archival grey-white, faint green cast — NOT cream */
--plate-deep:   #DCDDD6;
--ink:          #14151A;
--filament-ink: #C2611A;  /* accents darkened for AA on light */
--reflect-ink:  #2C6B85;
```

Note the deliberate avoidance: `#E9EAE5` has a green-grey cast like archival board, specifically *not* the warm cream (`#F4F1EA`) that AI design defaults to. And `#15161B` is a warm graphite, not the blue-black of the current build.

**Contrast:** every text pairing meets WCAG AA; the primary readouts meet AAA. `--filament` and `--reflect` are never the sole carrier of meaning.

## 1.5 Typography — use Google's own new fonts

This is the "Google will love it" move, and **nobody in the field is doing it.**

- **Display + UI: Google Sans Flex.** Google open-sourced its brand font with **six variable axes** — weight, width, optical size, slant, grade, and roundedness. Treat the axes as design tokens.
- **Data + numerals: Google Sans Code.** Google's open-source monospace (SIL OFL, `MONO` + `wght` 300–800 axes). Every hash, cost, count and address.

**The expressive device — axis shift as voice.** Roundedness (`ROND`) carries the Plate/Instrument duality:

```css
/* Instrument: technical, tight, no softness */
--type-instrument: "Google Sans Flex";
  font-variation-settings: "wght" 600, "wdth" 85, "ROND" 0, "GRAD" 100;

/* Plate: human, wider, slightly softened */
--type-plate: "Google Sans Flex";
  font-variation-settings: "wght" 500, "wdth" 100, "ROND" 45, "GRAD" 0;

/* Readouts */
--type-data: "Google Sans Code";
  font-variation-settings: "wght" 450, "MONO" 1;
  font-variant-numeric: tabular-nums;   /* non-negotiable for live counters */
```

The same typeface speaks in two registers depending on where you are. That is a genuine use of variable technology rather than decoration, and it is the kind of detail a Google design reviewer notices immediately.

**Scale** — a 1.25 minor third for UI, with one deliberate break: the hero collapse number ignores the scale entirely at `clamp(4rem, 14vw, 11rem)`. One number is allowed to be enormous. Nothing else is.

## 1.6 The signature element

**The Collapse.** Twenty thousand particles enter. About two hundred ignite. The rest catch reflected light and never burn.

Spend all boldness here. Every other surface stays quiet, dense, and typographic. If a component does not serve the collapse or the evidence, cut it.

---

# PART 2 — Motion system

## 2.1 Principles

Google's Material 3 Expressive research — 46 studies, 18,000+ participants — found expressive motion let users locate key elements **up to four times faster**, and equalised detection speed across age groups. So motion here is functional, not garnish. Two Expressive properties matter most:

- **Spring physics, not easing curves.** Everything settles; nothing linearly interpolates.
- **Interruptible and retargetable.** A user who scrubs mid-animation retargets it in flight. Nothing blocks input waiting for a transition to finish.

## 2.2 Tokens

```css
--spring-snap:    380 stiffness / 30 damping;  /* buttons, toggles, chips */
--spring-settle:  180 / 24;                    /* panels, drawers, page enter */
--spring-drift:   90 / 18;                     /* ambient field, camera */
--dur-ignite:     140ms;                       /* a thought is paid for */
--dur-reflect:    90ms;                        /* a thought is reused */
--dur-place:      420ms;                       /* Plate <-> Instrument */
```

## 2.3 The four motions that matter

**Ignition** *(a model call happens)* — particle scales 1 → 1.8 → 1.0 on `--spring-snap`, colour ramps `--filament-hot` → `--filament`, a 1px ring expands and dissipates over 400ms. This is the only time anything in the UI flashes. **It flashes exactly when money is spent**, so the visual budget maps to the financial one.

**Reflection** *(a cache hit)* — particle fades from neutral to `--reflect` over `--dur-reflect` with no scale change and no ring. Free things are quiet. After a few seconds of watching, a viewer understands the economics without reading a single label. That is the whole demo.

**Propagation** *(fork a branch)* — the forward lightcone illuminates outward from the perturbed node, hop by hop, at ~40ms per causal generation. Everything outside the cone desaturates to 15% opacity. **The blast radius draws itself.**

**Place change** *(Plate ↔ Instrument)* — 420ms. Background crossfades, hairlines invert, `ROND` animates 45 → 0, and the instrument's ambient field fades up from zero. One transition, used consistently, never decorative.

## 2.4 Honesty constraint

**Particle motion is bound to real data rates.** If 222 calls happen, 222 particles ignite — not "roughly two hundred, spread prettily." If a run takes 361 seconds, the replay control says so. A judge who suspects the animation is a scripted cartoon will discount everything else on the page, so the visualization must be a *readout*, not a video.

Ship a visible **`LIVE` / `REPLAY` / `SCRUBBED`** state chip at all times so nobody has to wonder which they are watching.

## 2.5 Reduced motion

`prefers-reduced-motion: reduce` is respected completely: particles render to their **final state instantly**, ignition becomes a static colour, propagation becomes an immediate highlight of the lightcone set. The information is identical; only the theatre is removed. Never a blank screen.

---

# PART 3 — Every page

## 3.1 `/` — The Field

The hero is the thesis. Do not open with a headline about a thesis; open with the thesis running.

```
┌──────────────────────────────────────────────────────────────┐
│  CHORUS                        mechanism  console  evidence  │
│                                                              │
│        · ·  ·   ·· ·  ·· ·   · ·· ·  · · ·  ·· ·  ·          │
│      ·  ·· ●·  · ·  ●  ·· · ·  · ●  ·· ·   · ·  ●· ·         │   ← live field
│        ·· ·  ·· ·  · ·· ·  ·● ·  · ·  ·· ·  · ·· ·           │
│                                                              │
│              20,000 agents.  192 thoughts.                   │
│                                                              │
│                        104×                                  │   ← scale break
│                                                              │
│     Every entity gets its own agent. Identical reasoning     │
│     is computed once. We measure how much of it was          │
│     needed at all — right now, 1.98%.                        │
│                                                              │
│     [ Watch it collapse ]   [ Read the evidence ]            │
│                                                              │
│  ─────────────────────────────────────────────────────────   │
│   $0.2137 spent    $19.2539 avoided    222 calls    0 errors │   ← live strip
└──────────────────────────────────────────────────────────────┘
```

- Field renders immediately from a **recorded run** — no cold start, no spinner, no API dependency. It is running before the page finishes settling.
- Particles drift on `--spring-drift`. Occasional ignition keeps it alive without becoming a screensaver.
- The number `104×` is the one scale break in the entire design system.
- Copy states the *honest* claim (necessity is 1.98%), not a boast. Judges have seen a hundred boasts today.
- On mobile: ~2,000 particles instead of 20,000, same visual grammar, and the number label says so.

## 3.2 `/mechanism` — How the address works

The one page that must teach, so it is **interactive rather than illustrated**.

An editable request card. Change any field and watch the address recompute live, character by character, in Google Sans Code. Then the payoff: two cards side by side.

```
   PASSENGER A                      PASSENGER B
   name    Aisha Kwarteng           name    Tom Reilly
   tier    platinum                 tier    platinum
   urgency critical                 urgency critical
   party   solo                     party   solo
   ─────────────────────            ─────────────────────
   address 4a91c7e2…                address 4a91c7e2…
                    ↓                       ↓
              ┌──────────────────────────────────┐
              │  SAME ADDRESS → ONE THOUGHT      │
              │  A paid $0.00096                 │
              │  B paid $0                       │
              └──────────────────────────────────┘
```

Change one field on B and both addresses visibly diverge. **Understanding arrives in about four seconds**, which is faster than any paragraph could manage.

Below: a **cardinality panel** that owns the audit finding rather than hiding from it.

> The projection lattice has **2,304 cells**. Collapse is bounded above by that number **by construction, not by discovery** — any bucketing scheme saturates. The real question is whether the bucketing is *lossless*, which the evidence page measures directly. `[ See the measurement → ]`

A live slider from 500 → 200,000 agents shows the curve flattening onto its ceiling. Publishing your own ceiling is the strongest credibility move available, and it defuses the single most obvious attack.

## 3.3 `/console` — The Instrument *(the centrepiece)*

```
┌────────────────────────────────────────────────────────────────────┐
│ ● LIVE   branch: primary        epoch 2026-08-30T00:00:00Z         │
├──────────────┬─────────────────────────────────────┬───────────────┤
│  COHORTS     │                                     │  EFFECT       │
│              │                                     │               │
│ ●platinum    │         [ CAUSAL FIELD ]            │ 4a91c7e2…     │
│  critical    │                                     │ MODEL_CALL    │
│  solo   1204 │      20,000 nodes, WebGL            │ passenger_ag  │
│              │      force-directed, GPU            │               │
│ ○gold        │                                     │ parents  2    │
│  urgent  882 │                                     │ tokens   412/ │
│              │                                     │ cost  $0.0009 │
│ ○basic       │                                     │ replayed  no  │
│  flexible    │                                     │               │
│         3140 │                                     │ [lightcone →] │
├──────────────┴─────────────────────────────────────┴───────────────┤
│ ◀━━━━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━▶  │
│ t=0                        seq 8,412 / 20,222                      │
├────────────────────────────────────────────────────────────────────┤
│ paid 222   free 19,778   coalesced 41   $0.2137 / $19.2539  361.5s │
└────────────────────────────────────────────────────────────────────┘
```

**The causal field.** PixiJS, GPU instanced sprites, one draw call for all 20,000 nodes. Force-directed layout precomputed in a Web Worker so the main thread never blocks. Level-of-detail: beyond ~5,000 visible nodes, render cohort *aggregates* and expand on zoom.

**The time scrubber.** Drag through the effect log. The field rewinds. This is the feature nobody else has, because nobody else records causally-addressed effects — **the product's architecture is what makes the UI possible**, and that is worth saying out loud in the demo.

**Fork and diff.** Right-click any effect → *Fork from here*. A second branch spawns; only the forward lightcone re-executes and ignites. Everything outside dims. Then a side-by-side diff with a cost delta.

**Inspector.** Full effect record — address, content id, causal parents (clickable), request, response, tokens, cost, replay flag, quarantine flag. Every hash is copyable. **A judge must be able to verify a claim from the UI in one click.**

## 3.4 `/ledger` — The Necessity Ledger

The headline feature deserves a dedicated page, and it should look like an audited financial statement, not a dashboard. **Plate lighting.**

```
   NECESSITY LEDGER                          30 days to 2026-08-30

   decisions served                                    1,204,882
     from policy table                    1,197,441       99.38%
     model calls                                7,441        0.62%

   shadow samples                                        24,097
     model agreed with table                   23,619       98.02%
     model DISAGREED → invalidated                478        1.98%
   ─────────────────────────────────────────────────────────────
   REASONING NECESSITY                                    1.98%

   98.02% of this workload is a lookup table.
   The 1.98% is where the model is load-bearing,
   and it is the only part you paid full price for.

   cost this period                                      $14.02
   cost without the kernel                            $2,271.19
```

- Right-aligned tabular figures in Google Sans Code. Hairline rules. No cards, no gradients, no chart junk.
- One sparkline: necessity over time. If it trends up, the world is drifting and the model is earning more of its keep — that is a genuinely useful signal.
- Each disagreement is a clickable row → the invalidated policy cell → its provenance chain.

This page is the answer to "does the LLM add anything?", computed continuously instead of asserted. No competitor has anything like it.

## 3.5 `/evidence` — Claim, command, result

Plate lighting. Every claim, the command that regenerates it, and the result — **including the results that hurt.**

```
   CLAIM   Collapse is fidelity-preserving.
   RUN     python scripts/bench.py --all --agents 8000
   RESULT

   ┌──────────────────────────────────────────────────────────┐
   │ baseline           tier-blind  tier-wtd  souls   cost    │
   │ B0 random               412.7     504.1   2,888  $0      │
   │ B1 first-come         1,004.2   1,131.3   2,888  $0      │
   │ B2 rules, zero LLM    1,988.4   2,281.1   2,888  $0   ←  │
   │ B3 flow optimum       2,140.9   2,402.7   2,888  $0      │
   │ B4 Chorus             1,996.1   2,173.9   2,888  $0.21   │
   │ B5 per-entity LLM     2,001.3   2,180.4   2,888  $19.25  │
   └──────────────────────────────────────────────────────────┘

   B4 vs B5 agreement                                   99.6%
   B4 vs B5 cost                                          1.1%

   → Collapse is lossless. It is not what makes the decision good.
   → B2 beats us on this workload. We ship that number because
     it is true, and because it is why the Ledger exists.
```

Marking your own losing row with `←` is the single highest-trust move available in this hackathon. Every judge has been lied to by a leaderboard today.

Also on this page: **What we did not solve** — known-lossy cohorts, residual duplicate-call rate, offline-proof limits.

## 3.6 `/incident` — Blast radius *(the security page)*

Instrument lighting. `--breach` appears here and **nowhere else in the product**, which is why it lands.

The novel finding, stated plainly:

> In a collapsed fleet, one successful prompt injection does not compromise one agent. It compromises every entity sharing that projection. **Collapse amplifies injection by the collapse ratio.**

Interactive, three states:

1. **Armed off.** Inject a poisoned message. Watch it enter a populous cohort, cache, and propagate `--breach` across 1,204 entities in about two seconds. Genuinely alarming to watch.
2. **Armed on.** Model Armor intercepts pre-projection. One node flags. Nothing propagates. Counter reads `contained: 1 / affected: 0`.
3. **Post-hoc.** Flag an already-cached address; the forward lightcone illuminates and every affected entity is enumerated and exportable as CSV.

**This is the 45 seconds of the demo video people will remember.**

## 3.7 `/intake` — Multimodal front door

Three tabs, all live: **Speak · Photograph · Write.**

- Voice: waveform in `--reflect`, live transcript, then the extracted `Projection` assembling field by field with **evidence spans highlighted back in the original text**. Watching structure crystallise out of speech is the most persuasive possible argument that the model is load-bearing.
- Photo: drop a boarding pass, watch PNR/flight/bags extract with bounding boxes.
- Text: paste anything, including other languages. Show a Twi, Spanish, and English message **collapsing into the same cohort** — that single frame proves unbounded input and bounded reasoning simultaneously.

Confidence bars per field. Low confidence visibly routes to per-entity escalation; a missing critical field produces a clarifying question.

## 3.8 `/registry` — Governance

Plate lighting. Agent versions as content hashes, capability discovery, deprecation state, and the deliberate coverage gaps (declared capabilities with **no** published agent, so those escalate to a human). Each row links to the IAM identity and the `verify_controls.sh` result — including the checks that expect ALLOWED, since an identity that can do nothing only proves it is broken.

## 3.9 `/architecture` — Track compliance

The five-stage pipeline diagram, then a compliance table mapping every Fortified Enterprise Fleet requirement to the file that implements it and a live status dot. Judges scoring a track bullet list should be able to tick every box from one screen.

## 3.10 `/policy/:cell` — Deep-linkable provenance

One policy cell: its inputs, its output, the effect IDs that derived it, the model version, how many entities it has served, its shadow-agreement history, and whether it is currently invalidated. **Every number elsewhere in the product links here.** Provenance you can reach in one click is what separates an audited system from a dashboard.

---

# PART 4 — Components and technical build

## 4.1 Stack (keep what exists, add carefully)

```
vite + react 18 + typescript      keep
pixi.js 8                         keep — GPU field, 20k nodes
gsap 3                            keep — orchestrated sequences
+ @react-spring/web               ADD  — M3-style spring physics for UI
+ d3-force  (worker only)         ADD  — layout solver, never renders
+ comlink                         ADD  — clean worker boundary
NO tailwind · NO shadcn · NO lucide · NO next
```

Icons: draw ~14 custom 1px-stroke glyphs in the instrument idiom. lucide's presence in 33 competing repos makes it a tell.

Styling: plain CSS with custom properties and `@layer`. The token file is the design system.

## 4.2 Performance budget

| Metric | Target |
|---|---|
| First contentful paint | < 1.2s |
| Field first frame | < 400ms (recorded data, no API) |
| Sustained frame rate, 20k nodes | 60fps desktop / 30fps mobile |
| JS bundle, gzipped | < 220KB (Pixi is the bulk) |
| Fonts | 2 variable files, subset Latin, `font-display: swap` |

Layout runs in a Web Worker. Rendering uses instanced sprites and a single draw call. Level-of-detail above 5,000 visible nodes. Never block the main thread — a stuttering demo reads as a broken product.

## 4.3 Accessibility floor

Keyboard path through every interactive surface, with a visible 2px `--filament` focus ring. The causal field gets a **table equivalent** at `/console?view=table` — same data, screen-reader navigable, and genuinely faster for some tasks. All meaning carried by colour is duplicated in shape and label. `prefers-reduced-motion` fully honoured. AA contrast throughout, AAA on primary readouts.

## 4.4 Copy rules

Sentence case everywhere. Active voice. A control names exactly what happens: *Fork from here* → toast reads *Forked*. Errors say what broke and what to do, never apologise, never go vague. Empty states are invitations: an empty branch list reads *No forks yet. Right-click any effect to branch from it.* Numbers always carry units and always carry their command.

---

# PART 5 — Build sequence

**Phase 1 — Foundation.** Token file (both places), Google Sans Flex + Sans Code self-hosted and subset, spring system, Plate↔Instrument transition, nav, custom icon set. *Nothing else starts until the palette is off acid-mint.*

**Phase 2 — The signature.** Rebuild the field on Pixi 8 with instanced sprites, worker-side d3-force, LOD, ignition and reflection motions. Ship `/` alone if it is all that gets done — it is the whole thesis in one screen.

**Phase 3 — The instrument.** `/console`: cohort rail, inspector, time scrubber, fork-and-diff, lightcone propagation.

**Phase 4 — The evidence.** `/evidence` with all six baselines and the losing row marked, `/ledger`, `/policy/:cell`, `/mechanism` with the cardinality panel.

**Phase 5 — The set pieces.** `/incident` three-state attack demo, `/intake` voice + photo + multilingual collapse.

**Phase 6 — Compliance and polish.** `/registry`, `/architecture`, accessibility audit, performance pass, reduced-motion pass, mobile pass.

---

# PART 6 — Why this wins on the rubric

**Demo & Production Readiness (30%).** The field renders from recorded data in under 400ms with no cold start and no spinner. Every claim is one click from its provenance. The `LIVE / REPLAY / SCRUBBED` chip means a judge never wonders whether they are watching a cartoon.

**Architectural Discipline (30%).** The UI is only possible *because* of the kernel. Time-travel requires content-addressed effects. Blast radius requires the causal DAG. Nobody can copy this frontend without building the backend first — and that is the strongest possible argument that the architecture is real.

**Innovation & Operational Utility (40%).** The Necessity Ledger and the blast-radius view answer questions no other tool in this field can even ask.

**And for Google specifically:** Google Sans Flex and Google Sans Code used with their variable axes as real design tokens, Material 3 Expressive spring physics and size hierarchy applied to a non-Material product, effects exported as OpenTelemetry spans so the same causality is inspectable in Cloud Trace. It respects Google's design research without cosplaying as an Android app.

## The one-line design brief

> **A scientific instrument for watching reasoning collapse — and a paper record proving what it cost.**