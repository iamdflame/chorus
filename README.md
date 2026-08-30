# Chorus

**Twenty thousand agents. Two hundred thoughts.**

[![proofs](https://github.com/iamdflame/chorus/actions/workflows/ci.yml/badge.svg)](https://github.com/iamdflame/chorus/actions/workflows/ci.yml)

**Live:** https://chorus-512017284899.us-central1.run.app
**Source:** https://github.com/iamdflame/chorus
**Track:** The Fortified Enterprise Fleet

Reasoning now costs less than a database query, so every entity in a system can have its
own permanent agent — one per passenger, per machine, per account, running for weeks and
negotiating with the others. Nobody builds that, because twenty thousand agents means
twenty thousand model calls.

Unless identical reasoning is computed once.

Chorus gives each entity a real, independent agent, and discovers that most of them are
thinking the same thought. Measured on a live scenario:

Reproduce any row: `python scripts/verify_collapse.py`

| agents | distinct situations | collapse |
|---|---|---|
| 500 | 128 | 3.9x |
| 1,000 | 149 | 6.7x |
| 4,000 | 183 | 21.9x |
| 8,000 | 187 | 42.8x |
| 20,000 | **192** | **104x** |

Thought count **saturates** while agent count grows without bound. Adding twelve thousand
agents costs five more distinct situations. **The cost of a swarm is bounded by the
diversity of its situations, not by its size** — which is what makes per-entity agents
economically possible for the first time.

Run end to end against live `gemini-3.5-flash` — `python scripts/prove_swarm.py --agents 20000`:

| | |
|---|---|
| agents invoked | **20,000** |
| model calls actually made | **222** |
| served from the store | **19,778** |
| cost incurred | **$0.2137** |
| collapse | **90x** |

The measured 222 exceeds the 192 distinct situations because a handful of agents take a
second turn before returning valid JSON — those are genuinely different requests at a
different causal position, so they correctly miss. The number reported is what was really
spent, not the projection.

---

## Track: The Fortified Enterprise Fleet

> *"Build a scalable network of institutional agents… demonstrate how agents are cataloged
> for cross-department use, how they safely maintain context across weeks of asynchronous
> operations, and how they interact with production data without violating enterprise
> compliance, data sovereignty, or security policies."*

| Track component | In Chorus | Verify |
|---|---|---|
| **Agent Registry** — publishing, versioning, discovering | `fleet/registry.py`. Versions are **content-derived**: a hash of instruction, model, generation settings, tools and role, so editing a prompt moves the version on its own. A hand-maintained number is a promise someone eventually forgets to keep. | `GET /api/registry` · `pytest tests/test_registry.py` |
| **Model Armor** — block PII leaks | The canonical projection is the guardrail. An agent receives bucketed situation only; name, id, email, order and destination never reach a model. Deterministic, not probabilistic — a rule cannot have an off day. | `python scripts/verify_collapse.py` asserts a renamed passenger projects identically |
| **Agent Gateway** — unified routing and policy enforcement | Every model call and tool call in the system routes through one ADK `BasePlugin`. Nothing reaches a model or the world without passing the quarantine gate. | `kernel/interposer.py` |
| **Memory Bank** — persistent, secure cross-session context | Firestore effect store, keyed by content address, holding a 21-day recorded history. Replay resolves through it across sessions and across branches. | `pytest tests/test_firestore.py` (needs a project) |
| **Agent Identity** — zero-trust access | The container authenticates as its own service account with `aiplatform.user` and `datastore.user` only. No key is baked into the image or passed on the command line. | `infra/deploy.sh` |
| **Agent Runtime** — long-running async execution | `swarm/runtime.py` drives 20,000 independent ADK invocations under a concurrency gate, streaming progress over SSE. | `python scripts/prove_swarm.py --agents 20000` |
| **Agent Observability** — reasoning-chain traces | Every crossing is recorded as a causal effect with explicit parents, so a reasoning chain is a queryable DAG rather than a log. *OpenTelemetry export is not yet wired — see Honest limits.* | `kernel/dag.py` |

---

## How it works

An agent reasons over a **canonical projection** of itself — the decision-relevant
features only, bucketed, never its identity. Two stranded platinum passengers, both
travelling alone, both needing to move within four hours, both with a checked bag, face
the same decision. Their names differ. Their reasoning does not.

Because the kernel addresses every model call by its full causal history:

```
address = H(kind, role, [causal parents], canonical request)
```

two agents whose situations are genuinely equivalent compute the **same address**, and the
second is served from the store instead of the model.

**Nothing in the runtime groups agents.** Each is invoked independently, with its own ADK
session, unaware the others exist. The sharing is *discovered* by collision in a
content-addressed store — not assumed by a `GROUP BY`. That distinction is the whole
point: hand-grouping would make the same number of API calls and prove nothing, and it
would break the moment two situations were equivalent in a way nobody anticipated.

The split that keeps it sound:

| | | |
|---|---|---|
| **reasoning** | shared | what would someone in this situation accept |
| **matching** | private | which specific seat this specific passenger gets |

Matching depends on identity and live inventory, so it is individual by nature and never
reaches a model at all — it is deterministic allocation over the shared preferences,
scored against the first-come-first-served fallback airlines actually use.

---

## The scenario

A hub closure at ORD, with deliberate scarcity: **20,367 souls, 2,888 seats, a deficit of
17,479.** An allocation problem where everyone fits is not an allocation problem. Everyone
has been stranded at an airport, so the stakes need no explanation — and irregular
operations is a genuinely unsolved combinatorial problem airlines lose hundreds of
millions a year to.

---

## Does the reasoning actually help?

Cheap is half the claim. The other half is whether twenty thousand agents stating what
they would accept produces a better recovery than the queue-order fallback airlines
actually use. Measured on 8,000 agents:

| | first come | swarm | |
|---|---|---|---|
| souls seated | 2,888 | 2,888 | — |
| **weighted satisfaction** | 1,131.3 | **2,173.9** | **+92%** |
| mean wait (hours) | 17.12 | **16.76** | −0.36 |
| parties kept together | — | 8 split of 1,095 | |

**Souls seated is deliberately not the headline.** With 2,888 seats against 20,367 souls
the seat budget is the binding constraint, so every competent allocator fills every seat
and that metric saturates at an identical number — it cannot tell a good plan from a bad
one. Under a fixed budget the question is not how many people move but *which*: the swarm
prioritises by self-assessed urgency weighted by tier rather than by arrival order, and
the proof script fails if it does not beat the queue on that measure.

---

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full diagram and data flow.

```
optimizer/   policy search · Gemini proposes, forks evaluate, dollars decide
    |
api/         FastAPI on Cloud Run · SSE streams every search and replay event
    |
fleet/       6 ADK agents · triage -> policy -> resolver -> comms, with runtime delegation
    |
kernel/      the engine: content-addressed effects, causal DAG, O(1) branching,
             ADK interposition, quarantine gate
    |
world/       MVCC over a branch tree: time travel, branch isolation, conflicting merges
    |
Firestore    durable timeline, keyed by content address
```

`kernel/` is framework-agnostic and dependency-light. ADK appears in exactly one file
(`kernel/interposer.py`), and Google Cloud in exactly one (`kernel/firestore_store.py`),
so the determinism proof runs offline in CI against an in-memory reference — and the
Firestore backend is validated by *behaving identically to it*, including agreeing on the
causal root hash.

### Required technologies

| Requirement | Used |
|---|---|
| Gemini 3.5+ | `gemini-3.5-flash` for every agent and the policy proposer, via Vertex AI. Retrieval embeddings use `gemini-embedding-001` — Flash does not emit embeddings |
| Google agent framework | **ADK** (`google-adk` 2.8) — `BasePlugin` interposition, `SequentialAgent`, runtime `transfer_to_agent` |
| Google Cloud infrastructure | **Firestore** (native mode) as the durable effect store |

`thinking_level` is set per agent rather than left at Gemini 3.5 Flash's `medium` default:
the policy decision that moves money gets `high`, record lookups get `low`. Per-agent
context caching is enabled because every delegation swaps the system instruction and
re-sends the prompt uncached, which was most of the bill.

---

## Deployed

Running on Cloud Run at
[chorus-512017284899.us-central1.run.app](https://chorus-512017284899.us-central1.run.app),
with Gemini 3.5 Flash through Vertex AI and the timeline in Firestore. The container
authenticates as the service account it runs as, so no key is baked into the image.

```bash
./infra/deploy.sh YOUR_PROJECT_ID us-central1
```

The script enables the services, creates the Firestore database, grants the runtime
service account `aiplatform.user` and `datastore.user`, builds the container and then
smoke-tests the deployment — that the console bundle is really in the image, and that a
real swarm completes through Vertex. `/health` alone proves only that the process booted;
a missing `COPY` still serves a healthy process that fails on the first real request.

Verified on the live deployment: 300 agents, 122 model calls, 178 served from the store,
300 preferences produced, 0 errors.

---

## Spin up

Requires Python 3.11+, Node 20+, and a Gemini API key.

```bash
git clone https://github.com/iamdflame/chorus && cd chorus

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

echo "GOOGLE_API_KEY=your-key-here" > .env      # https://aistudio.google.com/apikey
```

**Run the proofs** (no cloud account needed for the first one):

```bash
# Offline: the kernel property, using a counting instrument to prove 0 model calls
.venv/bin/python scripts/verify_determinism.py

# Live: the same proof on the real six-agent fleet against gemini-3.5-flash
.venv/bin/python scripts/verify_fleet_replay.py --disputes 3

# The product: search policy space against recorded history
.venv/bin/python scripts/optimize_policy.py --generations 2 --population 3
```

**Run the console:**

```bash
.venv/bin/python -m uvicorn api.main:app --port 8080     # API + console
cd console && npm install && npm run build               # build the front end
open http://127.0.0.1:8080
```

**Tests:**

```bash
.venv/bin/python -m pytest tests/ -q                     # 47 tests, offline
GOOGLE_CLOUD_PROJECT=your-project .venv/bin/python -m pytest tests/ -q   # + live Firestore
```

**Firestore backend** (optional; the API defaults to a JSON snapshot):

```bash
gcloud services enable firestore.googleapis.com --project=YOUR_PROJECT
gcloud firestore databases create --location=nam5 --project=YOUR_PROJECT
export GOOGLE_CLOUD_PROJECT=YOUR_PROJECT
```

---

## The console

Two views over the same recorded history.

**Worldline** — the causal graph. Time runs left to right, agents occupy lanes, and an
edge climbing between lanes is a handoff. Selecting an effect ignites its forward
lightcone: the light travels along causal edges in breadth-first order, so causality reads
as motion. Everything outside the cone dims away.

**Search** — a cost landscape. Production is a dashed line across the frame; every point
is one complete execution of the fleet against the same real disputes. Below the line is
cheaper than what you run today.

---

## What is honest about this

- The seeded history is synthetic (120 disputes over 21 days, deterministically
  generated). The *execution* over it is entirely real: real Gemini calls, real tool
  dispatch, real embeddings, real recorded effects. Every number in the console traces to
  a recorded effect.
- Search scale is bounded by API rate limits, not by the design. The architecture
  parallelises across candidates; the concurrency ceiling is the key's, not the kernel's.
- Cloud Run deployment requires billing on the GCP project. Firestore, Pub/Sub and Vertex
  AI do not, and Firestore is live and tested here.
- Replay fidelity depends on interposing on *every* non-deterministic boundary. Tool
  ordering under concurrent fan-out is not automatically deterministic; effects are
  sequenced by causal position rather than wall clock, and the DAG comparison is
  order-insensitive.
- **Agent Observability is partial.** Reasoning chains are recorded as a causal DAG with
  explicit parents and are queryable, but they are not yet exported in OpenTelemetry
  format to Cloud Trace. The track names OTel specifically; this is the largest remaining
  gap and it is a format gap rather than a capability one.
- Pub/Sub is a declared dependency and the dispute fleet fans out over it, but the 20,000
  agent swarm runs in-process under a concurrency gate rather than across workers.
- The dispute fleet and the policy optimiser predate the swarm. Their kernel, storage and
  quarantine are shared and exercised by the same tests, but the console only surfaces the
  swarm — the rest is reachable through the API and the proof scripts.
