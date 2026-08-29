# Lightcone

**Your agent fleet rewrites itself, and proves the rewrite was better — by re-running your
actual history, not a benchmark.**

Point Lightcone at what your agents really did last month. It searches the space of
policies they *could* have followed, executes each candidate with the real fleet against
the real disputes, and hands you the version that would have cost you least — with the
counterfactual as evidence. Then you adopt it into production.

Nobody optimises agents against production history today, and the reason is not cost. It
is catastrophe: re-running a live fleet a thousand times would send a thousand real
emails and issue a thousand real refunds. Lightcone makes the experiment ordinary.

---

## The three properties that make it possible

Each is verified by a test in this repository, not asserted.

**1. Execution is deterministic and replayable.** Every crossing of the agent/world
boundary — model call, tool call, delegation — is content-addressed by its *entire causal
history*:

```
address = H(kind, agent, [parent addresses], request)
```

Because a parent's address is itself a hash of its own history, a change anywhere upstream
changes every address downstream. Cache invalidation is free: a perturbed run misses the
store exactly where it genuinely diverges and hits everywhere else. This is the
content-addressed derivation trick Nix and Bazel use for builds, applied to agent
execution.

> Measured on the real six-agent fleet: replay reproduced **82 of 82** boundary crossings,
> reached the model **0 times**, cost **$0.0000**, and reproduced the causal root hash
> exactly.

**2. Forking is O(1).** A branch is a reference, not a copy — `(parent, fork_at_seq,
overlay)`. Forking a timeline writes one small record and copies nothing, so exploring
thousands of alternatives is tractable.

> Measured: a fork of a 99-effect timeline stores **0** effects.

**3. Irreversible actions are quarantined.** Tools are classified by what they do to the
world. Reversible ones re-execute against branch-isolated state; ones with no honest
compensator — sending mail, moving money, paging a human — are *staged*: never dispatched,
but recorded with the exact arguments the agent chose. The agent's reasoning is unchanged,
so the counterfactual stays faithful; the blast radius stops at the process boundary.

> Measured: a counterfactual staged **6** irreversible actions and issued **0** real
> refunds while production issued 4 totalling $314.30.

An unregistered tool defaults to *irreversible*, so a forgotten classification produces a
visibly staged action rather than an unintended side effect. This caught a real bug during
development: ADK's built-in `transfer_to_agent` was unclassified and got quarantined,
severing delegation on every branch.

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
| Gemini 3.5+ | `gemini-3.5-flash` for all six agents, the policy proposer, and embeddings |
| Google agent framework | **ADK** (`google-adk` 2.8) — `BasePlugin` interposition, `SequentialAgent`, runtime `transfer_to_agent` |
| Google Cloud infrastructure | **Firestore** (native mode) as the durable effect store |

`thinking_level` is set per agent rather than left at Gemini 3.5 Flash's `medium` default:
the policy decision that moves money gets `high`, record lookups get `low`. Per-agent
context caching is enabled because every delegation swaps the system instruction and
re-sends the prompt uncached, which was most of the bill.

---

## Spin up

Requires Python 3.11+, Node 20+, and a Gemini API key.

```bash
git clone <this repo> && cd lightcone

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
