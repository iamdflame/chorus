# Chorus v2 — Complete Rebuild Plan

**Goal:** convert Chorus from a project with a superb kernel and an indefensible thesis into the strongest submission in the All Things Agentic Hackathon.

**Judged against:** Innovation & Operational Utility 40% · Architectural Discipline & Tech Stack 30% · Demo & Production Readiness 30%.

---

# PART 0 — The strategic pivot

## 0.1 What the audit actually found

Restated bluntly, because the rebuild depends on accepting it:

| Finding | Severity |
|---|---|
| Zero-LLM rules scored **+101.6%** vs the LLM swarm's **+92.2%** — the model's marginal contribution is **−4.7%** | Fatal to the thesis |
| "192 distinct situations" = `tier(4) × urgency(4) × party(4) × constraints(3)` — arithmetic, not discovery | Fatal to the headline |
| Seat supply (2,888) is fully consumed by every strategy — the gain is purely distributional (tier reallocation) | Fatal to the utility claim |
| `swarm/allocate.py` and `swarm/runtime.py` — the two claim-bearing modules — have **zero tests** | Severe |
| `project_passenger` defaults to wall clock; no call site passes `now=`; durable replay decays over time | Severe |
| No single-flight lock — the saving degrades exactly as you parallelize | Severe |
| Declared Fortified Enterprise Fleet with **0 auth, 0 gateway, 0 OpenTelemetry** | Severe (wrong track) |
| `allow-unauthenticated` + `CORS *` + unbounded `agents` int + unauthenticated `/fork`,`/merge`,`/replay` | Severe |
| `max-instances 4` with in-memory per-instance state; Firestore coded but not deployed | Severe |
| README says 90× collapse, shipped log says 104.2× for the same run | Moderate |
| Decision-relevant fields (`has_hotel_entitlement`, destination/region, `is_misconnect`) dropped from the projection while the prompt asks about them | Moderate |

## 0.2 The reframe that wins

The most damaging finding contains the best product.

> **The better the collapse works, the less you need the model at all.**

Right now that is an unanswered indictment. In v2 it becomes the **central thesis**, stated first, measured continuously, and shipped as a product surface:

> **Chorus is an agent execution substrate that discovers where reasoning is actually needed — and proves it. Most "agent" workloads are lookup tables wearing a costume. Chorus finds the ones that aren't, pays only for those, and can show you the receipt.**

This is defensible, novel, and immune to the exact attack that destroyed v1, because the attack *is* the feature.

## 0.3 The two structural changes that make the model load-bearing

**Change 1 — unbounded input.** v1 fed the model 5 categorical fields. A 192-row table trivially replicates that. v2 ingests **free text, voice, and images** from entities. A lookup table cannot replicate a mapping from an unbounded input space. The model becomes genuinely necessary, and collapse still works because thousands of different sentences describe the same situation.

**Change 2 — honest claim.** Stop claiming "better than first-come." Claim instead:

> **Collapse is fidelity-preserving.** Chorus produces decisions statistically indistinguishable from running one uncollapsed model call per entity, at ~1/100th the cost.

That is measurable, falsifiable, and true if the engineering is right. It survives every baseline a judge can throw at it.

## 0.4 Prize targeting

| Prize | Fit after rebuild |
|---|---|
| **Grand Prize $50k** | Primary target |
| **Fortified Enterprise Fleet $20k** | Primary — but only after Part 5 is genuinely built |
| **Best Architectural Design $5k** | Very strong — the kernel is already best-in-field |
| **Best Multimodal UX $5k** | Strong after Part 7 |
| **Individual/Hobbyist $10k** | Eligible (solo author) |
| Startup Excellence $20k | Only if incorporated w/ corporate email |

Track note: Fortified Enterprise Fleet is the most crowded track (129 of 684 declared it). Collaborative Partner has only 66 for identical money. But Chorus is not a collaborative partner, and the enterprise infrastructure is its genuine strength. **Stay in FEF, but actually satisfy its bullet list** (Part 5) instead of declaring it and shipping none of it.

---

# PART 1 — The new architecture

## 1.1 Five-stage pipeline with a justified boundary at every step

```
[1] INTAKE          unbounded    free text / voice / image  →  per entity
[2] EXTRACTION      MODEL        text → structured situation + confidence
[3] COLLAPSE        KERNEL       identical situations share one thought
[4] ELICITATION     MODEL        situation → preferences (collapsible)
[5] ALLOCATION      DETERMINISTIC min-cost flow — no model, ever
[6] RENDERING       DETERMINISTIC shared reasoning + private identity → per-entity explanation
```

The defensibility comes from being able to justify each boundary out loud:

- **[2] must be a model** — input is unbounded natural language. No table can do it.
- **[4] may be a model but is collapsible** — input is bounded, so this is where the kernel earns its money.
- **[5] must not be a model** — allocation under hard constraints is what deterministic optimization is *for*, and an LLM is both more expensive and worse at it.
- **[6] must not be a model** — it is templating over already-computed reasoning.

That single diagram answers "where does the AI actually go?", which is the question judges use to separate real systems from chatbots with extra steps.

## 1.2 Repository layout

```
chorus/
├── kernel/                  # KEEP — the crown jewel, hardened in Part 2
│   ├── effect.py            # content-addressed effects
│   ├── interposer.py        # ADK plugin, + single-flight (NEW)
│   ├── store.py
│   ├── firestore_store.py   # NOW ACTUALLY DEPLOYED
│   ├── clock.py             # NEW — injectable clock, kills wall-clock nondeterminism
│   ├── singleflight.py      # NEW — in-process + cross-instance lease
│   ├── branch.py  dag.py  quarantine.py  snapshot.py
│   └── otel.py              # NEW — effects → OpenTelemetry spans
├── intake/                  # NEW — unbounded input
│   ├── text.py  voice.py  vision.py
│   └── armor.py             # Model Armor screening BEFORE projection
├── extract/                 # NEW — stage [2]
│   ├── situation.py         # text → Projection + confidence + evidence spans
│   └── schema.py
├── swarm/
│   ├── canonical.py         # richer projection, versioned, clock-injected
│   ├── runtime.py           # + single-flight, + session hygiene
│   ├── allocate.py          # REPLACED by optimizer/flow.py
│   └── scenario.py          # fixed epoch, no datetime.now()
├── optimizer/
│   └── flow.py              # NEW — min-cost flow allocator
├── distill/                 # NEW — the headline feature
│   ├── policy.py            # collapse → deterministic policy table w/ provenance
│   ├── shadow.py            # sample the model, compare to table, detect drift
│   └── ledger.py            # "reasoning necessity" metric
├── governance/              # NEW — Part 5, the FEF requirements
│   ├── registry.py  identity.py  gateway.py  memory.py
├── bench/                   # NEW — Part 6
│   ├── baselines.py         # B0..B5
│   ├── metrics.py           # tier-blind + tier-weighted + equity
│   └── run.py
├── api/  console/  infra/  docs/  tests/  scripts/
```

---

# PART 2 — Fix the kernel (keep everything good, close every hole)

The kernel is genuinely the best code in the hackathon. Do not rewrite it. Harden it.

## 2.1 Kill wall-clock nondeterminism

**Problem:** `project_passenger(now=None)` falls back to `datetime.now()`; no call site passes `now=`. `build_scenario` sets `scheduled_departure = datetime.now() + offset`. Replay decays across days.

**Fix:**

```python
# kernel/clock.py
from dataclasses import dataclass

@dataclass(frozen=True)
class Clock:
    """Time is an input, never an ambient fact."""
    epoch: float                      # unix seconds, recorded in the run manifest
    def now(self) -> datetime: ...

class RecordedClock(Clock):
    """Reads become CLOCK effects so a replay reproduces them exactly."""
```

- `EffectKind.CLOCK` already exists in the enum — **use it.** Every clock read becomes a recorded effect.
- `project_passenger(passenger, *, clock)` — make `clock` a **required keyword**, no default. The type checker then finds every call site for you.
- `build_scenario(*, epoch: float, seed: int)` — no `datetime.now()` anywhere.
- Record `epoch` in the branch manifest and print it in every proof.

**CI gate:** run the same scenario twice with the wall clock shifted +30 days (`faketime` or a monkeypatched clock) and assert **identical root hash**. This is a test v1 would have failed.

## 2.2 Single-flight — stop the thundering herd

**Problem:** lookup happens in `before_model_callback`; concurrent agents in one cohort all miss and all call the model. The saving degrades exactly as you parallelize. This is very likely a co-cause of the unexplained 222-vs-192 gap.

**Fix, two layers:**

```python
# kernel/singleflight.py
class SingleFlight:
    """One in-flight execution per address. Everyone else awaits the winner."""
    def __init__(self): self._inflight: dict[str, asyncio.Future] = {}

    async def do(self, address: str, fn):
        if (fut := self._inflight.get(address)) is not None:
            return await fut, True                 # coalesced — count separately
        fut = asyncio.get_running_loop().create_future()
        self._inflight[address] = fut
        try:
            result = await fn(); fut.set_result(result); return result, False
        except Exception as e:
            fut.set_exception(e); raise
        finally:
            self._inflight.pop(address, None)
```

- **Cross-instance:** a Firestore transactional lease on `leases/{address}` with a TTL. Loser polls the store for the winner's write.
- **Report a new metric:** `coalesced` — calls suppressed by single-flight. This turns a bug fix into a demonstrable number.
- **Then re-run the 20,000 swarm.** The measured call count should drop from 222 toward 192, and you can say *why* the residual exists instead of guessing.

## 2.3 Close the `default=repr` hole

`canonical_json(default=repr)` embeds memory addresses for non-JSON objects, so the docstring's "stable across processes and machines" is false on that path.

**Fix:** raise on unserialisable input in strict mode; keep the degrade-to-miss behaviour only behind an explicit flag, and **count** those events (`unstable_payloads` metric). Silent degradation is what destroys a collapse ratio in production.

## 2.4 Widen the digest

128-bit is fine mathematically, but this is a cache where a collision returns a **wrong answer**, not a miss. Move to 32 bytes (256-bit) and truncate only for display. Cost is negligible; the "collision = wrong answer" objection disappears permanently.

## 2.5 Harden causal-edge detection

Substring containment with a 16-char floor can forge false parents on structured JSON (`{"accept_downgrade": true` recurs constantly).

**Fix:** register producers by **content hash of the emitted payload**, and detect edges by hash membership rather than substring scan. Keep a substring fallback for prose, gated and counted. Bonus: removes the O(producers × haystack) scan on every crossing.

## 2.6 Fix `_pending` key collision

`self._pending[f"model:{agent}"]` collides when one agent name has two concurrent model calls in flight. Key it by the **effect address** instead, which is already unique.

## 2.7 Stop swallowing failures

```python
except Exception as exc:
    metrics.errors.append(...)
    return                      # BUG: agents_invoked never incremented
```

Failed entities vanish from the denominator and silently drop out of allocation. **Fix:** count `agents_failed` explicitly, surface it in every report, and make the proof scripts **fail** if `agents_failed > 0.5%`.

## 2.8 Session and object hygiene

- `InMemorySessionService` accumulates 20,000 sessions, never deleted → delete after each invocation.
- A `Runner`/`App` is constructed per invocation → build once per role, reuse.
- Both matter for the "20,000 agents" claim to survive a memory-profiler question.

---

# PART 3 — Make the model load-bearing (the thesis fix)

## 3.1 Unbounded intake

Replace the 5-field synthetic record with real unstructured input per entity:

- **Text:** SMS / WhatsApp / web form free text. *"Stuck at ORD, my mum is 84 and in a wheelchair, we have to be in Boston before Sunday for a funeral, I'll take literally anything."*
- **Voice:** a spoken message, transcribed and reasoned over.
- **Image:** photo of a boarding pass / bag tag → extract flight, PNR, bag count.

Generate a corpus of ~20,000 messages with wide linguistic variety (multiple languages, typos, ambiguity, contradictions, missing info). Ship the generator **and** a 500-message human-reviewed gold set.

## 3.2 Extraction with confidence and evidence

```python
class ExtractedSituation(BaseModel):
    projection: Projection
    confidence: float                 # 0..1, per field
    evidence: dict[str, str]          # which span of the message supports each field
    unresolved: list[str]             # what the model could not determine
    clarifying_question: str | None   # if a field is critical and missing
```

Three things this buys you:

1. **Evidence spans** make extraction auditable — a judge can see *why* a passenger was bucketed `assisted`.
2. **`unresolved` + `clarifying_question`** is a genuine Collaborative-Partner behaviour and a fallback track if you ever want it.
3. **Confidence** drives the escalation policy in 3.4.

## 3.3 Richer, versioned projection — and stop dropping load-bearing fields

Fix the false sharing the audit found. The prompt asks about hotels, nearby airports and misconnects; the projection must therefore carry them:

```python
@dataclass(frozen=True, slots=True)
class Projection:
    schema_version: str          # NEW — part of the address; bump = clean invalidation
    role: str
    tier: str                    # 4
    urgency: str                 # 4
    party: str                   # 4
    constraints: str             # 3
    haul: str                    # NEW  short / long / intercontinental  (3)
    hotel_entitled: bool         # NEW  (2)
    misconnect: bool             # NEW  (2)
    accompanied_minor: bool      # NEW  (2)
```

New ceiling: `4×4×4×3×3×2×2×2` = **2,304**. State this ceiling **explicitly in the README** — owning it is what kills the "your collapse is just division by a constant" attack:

> The projection lattice has 2,304 cells. Collapse is bounded above by that number **by construction, not by discovery** — any bucketing saturates. The interesting question is not whether it saturates but **whether the bucketing is lossless**, which Part 6 measures directly.

That paragraph alone converts the audit's most quotable finding into evidence of authorial rigour.

## 3.4 Escalation — pay for reasoning exactly where it is needed

```
confidence high  AND  policy table has this cell   →  0 model calls  (table)
confidence high  AND  cell is novel                →  1 model call, then cached
confidence low   OR   contradictory evidence       →  per-entity model call, no collapse
critical field missing                             →  clarifying question to the human
```

The escalation rate is now a **live product metric**, not a hidden implementation detail.

---

# PART 4 — Distillation, drift, and the Necessity Ledger

This is the headline feature and it does not exist in any competitor I reviewed.

## 4.1 Distill

After a run, compile every `(projection → preference)` pair into a deterministic policy table. Each row carries provenance: the effect IDs that produced it, the model version, the timestamp, and the number of entities it has served.

```
POLICY v7  ·  2,304 cells  ·  1,891 populated  ·  derived from 1,891 model calls
row  platinum|critical|solo|assisted|long|hotel:Y|mis:Y|minor:N
     → {max_wait_hours: 4, accept_downgrade: true, urgency_score: 96}
     provenance: effect 4a91c… · gemini-3.5-flash · served 1,204 entities
```

## 4.2 Shadow-sample and detect drift

On a configurable slice of traffic (say 2%), call the model **even when the table has an answer**, and compare.

- Agreement → increment the row's confidence, log a free confirmation.
- Disagreement → **invalidate that row**, re-derive, and emit a drift event.

This solves a real production problem nobody else in the field addresses: **a cached agent decision silently going stale when the model, the policy or the world changes.**

## 4.3 The Necessity Ledger

A live dashboard panel and a CLI report answering: *is the model earning its cost?*

```
NECESSITY LEDGER            last 30 days
────────────────────────────────────────────────────
decisions served                        1,204,882
  from policy table (free)              1,197,441   99.38%
  model calls                               7,441    0.62%
shadow samples                             24,097
  model agreed with table                  23,ْ619   98.02%
  model DISAGREED  → rows invalidated         478    1.98%
────────────────────────────────────────────────────
REASONING NECESSITY                                 1.98%
  → 98.02% of this workload is a lookup table.
  → The 1.98% is where the model is load-bearing,
    and it is the only part you paid full price for.
cost this period                            $14.02
cost without the kernel                  $2,271.19
```

Two reasons this is devastating in a good way:

1. It is the **honest** answer to "does the LLM add anything?" — the system measures it continuously instead of asserting it.
2. It is a genuinely useful enterprise artifact. Every CFO funding an agent programme wants exactly this number and nobody can currently produce it.

**Ship the ablation as a product surface, not a defensive footnote.**

---

# PART 5 — Actually satisfy the Fortified Enterprise Fleet bullets

v1 declared this track and shipped none of it. Each bullet below is an explicit track requirement; build all of them.

## 5.1 Agent Registry (Discovery & Lifecycle)

You already have the hard part: **content addressing.** An agent's registry version *is* the hash of its definition (instruction + model + config + tool allowlist).

- `POST /api/registry/publish` — version derived, never assigned.
- `GET /api/registry?capability=…` — discovery by declared capability.
- Deprecation and pinning; a branch records which agent versions it ran.
- **Steal the best idea in the field:** NAV Sentinel deliberately ships *declared capabilities with no published agent*, so those requests escalate to a human instead of being routed to whichever agent looked closest. Do the same and say so — honest coverage gaps read as maturity.

## 5.2 Agent Identity (zero-trust)

- One **service account per agent role**, not one per app.
- Workload Identity Federation; no keys on disk.
- Tool allowlist enforced by IAM, not by prompt.
- **Prove it the way Remediation Zero does:** ship `scripts/verify_controls.sh` that *attempts the forbidden action* from the extractor's identity and reports the denial. Include at least two checks that expect ALLOWED — an identity that can do nothing proves only that it is broken.

## 5.3 Agent Gateway

Every inter-agent and agent-to-tool call routes through a policy-enforcing gateway. Denials are **structured events in the effect log**, never silent. Because denials are effects, they are content-addressed, replayable, and diffable across branches — a genuinely novel property.

## 5.4 Model Armor — and the security contribution that could headline the whole submission

With free-text intake this stops being box-ticking and becomes existential. And there is a **novel vulnerability class here that I have not seen described anywhere**:

> ### Cache poisoning in a collapsed agent fleet
> In a collapsed fleet, one successful prompt injection does not compromise one agent — it compromises **every entity that shares that projection**. A single malicious passenger message that lands in a populous cohort can be served, from cache, to thousands of entities. **Collapse amplifies injection by the collapse ratio.**

Defence, layered:

1. **Screen before projection.** Model Armor on every ingested message, pre-extraction.
2. **Structural containment.** Extraction returns *only* a typed `Projection`; free text never reaches the elicitation prompt. The schema is the airlock.
3. **Poison quarantine.** If an address is later flagged, invalidate it and every descendant — and here the causal DAG does the work for free, because the forward lightcone *is* the blast radius.
4. **Blast-radius report.** `GET /api/incident/{effect_id}/blast-radius` → exactly which entities consumed a poisoned thought.

Then **demo the attack and the containment on camera.** Inject, show it amplify with defences off, turn them on, show it contained, then show the blast-radius report naming every affected entity. That is the single most memorable 45 seconds available to any team in this hackathon.

Write it up as the bonus-points blog post (Part 10). It is genuinely publishable.

## 5.5 Agent Observability — the elegant one

**The causal DAG is already a distributed trace.** Map it directly:

| Chorus | OpenTelemetry |
|---|---|
| Effect | Span |
| `causal_parents` | Span links (true DAG, not just parent-child) |
| `branch_id` | Trace-level attribute |
| replay hit | Span event `replayed=true`, zero duration |
| quarantined effect | Span event `quarantined=true` |
| `cost_usd`, `tokens_in/out` | Span attributes |

Export to Cloud Trace. Now a judge opens the Google Cloud console and sees 20,000 agent invocations, 192 real thoughts, and the causal structure between them — **in Google's own tooling, not yours.** That is worth more than any custom dashboard, and it satisfies the track's OpenTelemetry requirement exactly.

## 5.6 Memory Bank

Use Vertex AI Agent Engine Memory Bank for genuine cross-session context: a returning passenger's stated constraints persist across disruptions. Demonstrate a session weeks apart in simulated time. This is an explicit track bullet.

---

# PART 6 — The evidence rig (this is what actually wins)

## 6.1 Six baselines, all reported, always

| ID | Baseline | Purpose |
|---|---|---|
| B0 | Random assignment | Floor |
| B1 | First-come-first-served | What airlines actually do (v1's only baseline) |
| B2 | **Hand-written rules, zero LLM** | **The control that destroyed v1 — ship it yourself** |
| B3 | Min-cost flow optimum given stated preferences | Ceiling given the preferences |
| B4 | **Chorus** (LLM extraction + collapse + optimizer) | The product |
| B5 | Per-entity LLM, no collapse | Fidelity reference and cost ceiling |

**The headline claim becomes `B4 ≈ B5` at 1/100th the cost**, with `B2` published in the same table so nobody can spring it on you. Publishing your own worst result is the strongest credibility move available.

## 6.2 Metrics that cannot be gamed

v1 reported one metric that its own allocator sorted by. Report a panel instead:

- Souls seated · bookings seated · stranded
- **Tier-weighted satisfaction** *and* **tier-blind satisfaction** (exposes the distributional effect the audit found rather than hiding it)
- Mean wait · **p95 wait** · **worst-case wait**
- **Gini coefficient over wait time** (equity)
- Parties kept intact · constraint violations · SLA breaches
- Cost, latency, model calls, coalesced calls, escalation rate

And say the quiet part out loud in the README:

> Seat supply is the binding constraint: **every strategy seats the same number of souls.** Chorus does not move more people — it changes *which* people, and the tier-weighted metric rewards that. We report tier-blind numbers alongside so the trade-off is visible rather than buried.

A judge who reads that trusts every other number on the page.

## 6.3 Fidelity measurement

- **Agreement rate** between B4 and B5 decisions, per cohort.
- **Outcome delta** distribution, not just the mean.
- **Where collapse is lossy** — publish the cohorts with the worst agreement and explain them. A known, quantified failure mode beats an unexamined success.

## 6.4 Reproducibility

Every number in the README carries the command that regenerates it, and CI regenerates all of them nightly and fails on drift. v1 had this instinct; v2 makes it total.

---

# PART 7 — Multimodal (targets Best Multimodal UX $5k)

## 7.1 Input

- **Voice intake** via Gemini audio — a passenger speaks; the system extracts, buckets, and responds. Demo this live.
- **Vision intake** — photo of a boarding pass → PNR, flight, bag count via Gemini vision.
- **Multilingual** — the corpus should include non-English messages collapsing into the same cohorts as English ones. Visually beautiful and makes the "unbounded input" point instantly.

## 7.2 The console

The single most visually striking thing available to this project: **20,000 agents collapsing into ~200 thoughts, live.**

- Force-directed causal DAG, streaming as the swarm runs.
- Cohorts light up on first thought (paid, red) then fill with cache hits (free, green).
- **Time-travel scrubber** across the branch history.
- **Fork-and-diff** view: change one policy, watch only the forward lightcone re-execute and light up.
- Cost counter ticking against the counterfactual "cost without the kernel."

## 7.3 Gemma (explicit bonus points)

Use **Gemma** as a cheap local triage classifier ahead of Gemini: it screens and routes obviously-simple messages, and Gemini handles the rest. Report the cost split. This is a *real* integration and earns the bonus honestly.

> **Warning, from the audit:** v1's neighbour `cymbal-agentic-suite` advertised Imagen 3, Veo 2 and Lyria while the only matches in its code were camelCase variables like `veOrders`. Do not claim a model you do not call. **Either ship a real Veo/Lyria integration or claim neither.** If you want Veo honestly: generate a short personalised recovery-explainer video for a stranded passenger. If that feels contrived, skip it — an unclaimed bonus costs far less than a claim that fails verification.

---

# PART 8 — Production and security

Every one of these is a direct audit finding:

| Fix | Detail |
|---|---|
| **Authentication** | Remove `--allow-unauthenticated`. Firebase Auth or IAP. Issue a scoped judge token, printed in the README. |
| **CORS** | Replace `allow_origins=["*"]` with the console origin. |
| **Input caps** | `agents: int = Field(2000, ge=1, le=50_000)`, `concurrency: int = Field(6, ge=1, le=64)`. |
| **Mutation endpoints** | `/fork`, `/merge`, `/replay`, `/policies/adopt` require auth + audit log. |
| **Rate limiting** | Per-token quotas. |
| **State** | Deploy `FirestoreStore` for real. Remove the `data/history.json` in-memory path from production. |
| **Multi-instance** | With Firestore-backed state, `max-instances 4` is finally safe. Add a test that runs two engines against one store and asserts convergence. |
| **Secrets** | Secret Manager, Workload Identity. Nothing in env vars. |
| **IaC** | **Terraform** for everything — project, services, IAM, Firestore, Pub/Sub, Cloud Run, Model Armor. `deploy.sh` is not infrastructure-as-code, and Best Architectural Design judges will look. |
| **Image** | Drop `playwright` from production requirements. |
| **DR** | Document RPO/RTO. Effects are content-addressed and immutable, so this is easy and impressive. |

---

# PART 9 — Repo, docs and the demo

## 9.1 README structure (claim → command → result)

```
1  One sentence: what it is
2  The thesis, including the 2,304 ceiling stated up front
3  For judges: four commands, zero cloud account
4  The claim table: B0–B5 side by side, tier-blind AND tier-weighted
5  The Necessity Ledger
6  The security finding (collapse amplifies injection) + containment
7  Architecture diagram
8  Every number + its regenerating command
9  What we did NOT solve  ← ship this section
10 Track compliance: each FEF bullet → the file that implements it
```

**Section 9 is not optional.** List the known-lossy cohorts, the residual duplicate-call rate, the escalation cost, the limits of the offline proof. Every strong project I audited that was trusted had a section like this; every one that got caught did not.

## 9.2 The offline proof — make it prove more

The audit's fair criticism: `CountingLlm` is deterministic by construction, so a deterministic fake replaying deterministically is close to tautological. Fix by adding to the offline suite:

- A **deliberately nondeterministic** instrument (seeded jitter) proving the *store*, not the model, is what makes replay exact.
- An **adversarial** instrument that attempts injection, proving containment offline.
- A **clock-shift** proof (Part 2.1) that fails on v1's code and passes on v2's.

Keep the "zero cloud account" promise. It is the best reproducibility affordance in the hackathon — just make it prove the interesting things.

## 9.3 The 4-minute video

| Time | Beat |
|---|---|
| 0:00–0:25 | The problem, concretely. A real passenger message on screen. |
| 0:25–1:00 | Voice/photo intake → extraction with visible evidence spans. |
| 1:00–1:50 | **The collapse, live.** 20,000 agents, ~200 thoughts, cost counter running against the counterfactual. |
| 1:50–2:20 | Fork a policy. Only the forward lightcone re-executes. Root hashes on screen. |
| 2:20–3:05 | **The attack.** Inject, amplify with defences off, contain with Model Armor on, show the blast-radius report. |
| 3:05–3:30 | **The Necessity Ledger** — "98% of this workload is a lookup table, and here is the 2% that isn't." |
| 3:30–3:50 | Google Cloud console: Cloud Run, Cloud Trace spans, Firestore. Proof it runs on GCP. |
| 3:50–4:00 | The B0–B5 table. |

Unedited, single take, live. Record it three times and keep the best.

---

# PART 10 — Bonus points

- **Blog post:** *"Cache poisoning in collapsed agent fleets: how deduplication amplifies prompt injection."* Genuinely novel, genuinely publishable, and it markets the project on its strongest and most original idea. Include the required line stating it was created for this hackathon.
- **Second post (optional):** *"We built an agent swarm, then proved 98% of it was a lookup table."* This is the intellectual-honesty story, and that story travels.
- **Social:** LinkedIn/X with `#AllThingsAgenticHackathon`, leading with the collapse visualization.
- **Gemma** integration (Part 7.3) — real, not claimed.

---

# PART 11 — Build sequence

**Phase 1 — Credibility (do first; nothing else matters if these are open)**
Clock injection + CI clock-shift gate · single-flight · tests for `allocate.py` and `runtime.py` · B0–B5 bench rig with B2 published · fix the 90×/104.2× inconsistency · state the 2,304 ceiling in the README.

**Phase 2 — Thesis**
Unbounded intake corpus + gold set · extraction with confidence/evidence · richer versioned projection · escalation policy · fidelity measurement (B4 vs B5).

**Phase 3 — Headline feature**
Policy distillation with provenance · shadow sampling · drift detection · Necessity Ledger UI + CLI.

**Phase 4 — Track compliance**
Registry · Identity + `verify_controls.sh` · Gateway with logged denials · Model Armor + poisoning demo + blast-radius API · OTel export to Cloud Trace · Memory Bank.

**Phase 5 — Production**
Auth · CORS · caps · Firestore-backed deployed state · multi-instance convergence test · Terraform · Secret Manager.

**Phase 6 — Presentation**
Console with live collapse + time-travel + fork-diff · voice/vision intake · Gemma · README rewrite · video · blog + social.

---

# PART 12 — What judges will attack, and your answer

| Attack | Answer |
|---|---|
| *"Your collapse is just division by a constant."* | Stated up front: the lattice is 2,304 cells and saturation is arithmetic. The claim is **losslessness**, measured as B4-vs-B5 agreement. |
| *"Rules would do this for free."* | B2 is in our own table. Rules cannot read free text, voice or images — that is why extraction is per-entity and why the Necessity Ledger measures exactly how much of the workload is genuinely reasoning. |
| *"The LLM adds nothing."* | We measure that continuously and publish it. On this workload it is 1.98%, and we only pay for that 1.98%. That is the product. |
| *"You just prioritise rich passengers."* | Tier-blind and tier-weighted metrics both published, plus Gini and worst-case wait. The trade-off is stated, not hidden. |
| *"Replay is trivial — you cached the bytes."* | Correct, and that is the point. The nondeterministic instrument proves the store is what makes it exact. The hard part is invalidation, which the lightcone does. |
| *"Does it really run on Google Cloud?"* | Cloud Trace spans, Cloud Run dashboard, Firestore documents — all on camera, all in Google's console. |
| *"Concurrency breaks your saving."* | It did. Single-flight fixes it, and `coalesced` is a reported metric. |
| *"Wrong track."* | Every FEF bullet maps to a named file in the README's compliance table. |

---

# The one-line pitch

> **Chorus gives every entity its own agent, makes that affordable by computing identical reasoning once, and — uniquely — proves how much of that reasoning was needed at all.**

The v1 kernel was already the best code in this hackathon. What it lacked was a claim that survived contact with a control. v2's claim is *built out of* the control.