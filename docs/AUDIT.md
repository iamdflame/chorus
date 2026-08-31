# Self-audit, and what closed each finding

A hostile technical audit was run against v1 of this project. It found four things it
labelled fatal or severe. **All four are closed**, and this document exists so that can be
checked rather than taken on trust: each row names the commit that closed it and the test
that stops it reopening.

The plan document those findings came from is deliberately not in the repository. It is
written in the present tense with no dates, so a reader browsing the file list would find
a document by this team calling this project "fatal to the thesis" with no way to tell it
had been acted on. This is the same content, in the past tense, with receipts.

---

## Fatal — the model's marginal contribution was negative

> *"Zero-LLM rules scored +101.6% against the swarm's +92.2%. The model's marginal
> contribution is −4.7%."*

**True, and worse than reported.** Reproduced here, the rules arm scored **+31.3%
tier-weighted** — and **−28.9% tier-blind**. It was not creating value, it was
redistributing it toward the tiers the metric happened to weight. Under flat tiers *both*
arms lost to first-come.

**What closed it.** The input became unbounded free text in eight languages, where a rule
table cannot follow. Measured against a control built in good faith to beat it, the model
reads **+26.9 points** better on mean field accuracy and gets **5× more situations entirely
right** — because no regex infers that *"she can't manage stairs"* means assistance.

`scripts/verify_extraction.py` · `tests/test_extraction.py` · README "Does the model earn
its place?"

## Fatal — "192 distinct situations" was arithmetic, not discovery

> *"tier(4) × urgency(4) × party(4) × constraints(3) = 192. That is a ceiling you chose,
> not a property you found."*

**Correct.** Any finite bucketing saturates. Worse, the v1 projection omitted haul, hotel
entitlement and misconnect *while the prompt asked about them* — so a traveller to London
and one to Dallas shared reasoning about whether a nearby airport would do.

**What closed it.** The lattice is now **2,304 cells** and the ceiling is stated up front
rather than discovered. Correcting the false sharing took collapse from **104× to 10.2×**
at twenty thousand agents: the old number was a wrong projection, not a better result.
Saturation is now demonstrated where it is actually interesting — 200,000 agents occupy
2,296 of 2,304 cells, after which cost stops growing entirely.

`scripts/verify_collapse.py` · `tests/test_projection_leakage.py` · README "Saturation is
structural"

## Fatal — the utility gain was purely distributional

> *"Seat supply is fully consumed by every strategy. The gain is distributional."*

**True, and the claim was withdrawn.** The +92% was measuring tier redistribution against
the metric it was scored on.

**What closed it.** Three metrics are now published side by side — tier-weighted,
tier-blind and **per-soul** — and the third one found a further problem nobody had raised:
satisfaction was summed per *booking* while seats are consumed per *soul*, so an arm that
seated solo travellers scored 42% higher while moving **fewer people home**. That arm was
labelled a "greedy upper bound"; it was exploiting the scorer, and it is now named for what
it is.

`bench/metrics.py` · `tests/test_bench.py` · README "The arm that was beating everything
was exploiting the scorer"

## Severe — Fortified Enterprise Fleet declared with none of its controls

> *"0 auth, 0 gateway, 0 OpenTelemetry."*

**True at the time.** All three now exist, along with the rest of the track's named
components.

| control | where | pinned by |
| --- | --- | --- |
| Auth | fail-closed, constant-time bearer gate on every mutating endpoint | `tests/test_api_security.py` |
| Gateway | denials recorded as **effects** — replayable and diffable | `tests/test_gateway.py` |
| OpenTelemetry | 39,996 spans exported to Cloud Trace, causal parents as span links | `tests/test_otel.py` |
| Identity | one service account per agent role; the allocator has no model access | `scripts/verify_controls.sh` |
| Model Armor | `sanitizeUserPrompt` as layer 0 | `tests/test_armor.py` |
| Memory Bank | cross-session profiles that feed the projection, not the prompt | `tests/test_memory.py` |
| Registry | content-derived agent versions | `tests/test_registry.py` |

---

## Found afterwards, by measuring rather than intending

These were not in the original audit. They are here because they are the reason to believe
the numbers that remain.

| finding | how it was caught |
| --- | --- |
| **A README row claimed exponential backoff that did not exist.** | Grepping the tree for `backoff\|jitter\|retry` and finding nothing. Now implemented at the single model boundary, with a test that a retry re-derives the **same** causal address — otherwise the store records two thoughts where the fleet had one and the collapse ratio inflates under exactly the load where it matters. |
| **Two scripts were not using the mechanism this project is about.** | `Mode.RECORD` never consults the effect store. The fidelity and necessity runs paid full price for answers already held: 1,748 calls where 880 distinct situations existed. |
| **A drift rate with no noise floor is not a measurement.** | The first Necessity Ledger reported 29.63%. Asking the model the same question twice showed it disagrees with itself 0 times in 27 — which is what makes the corrected figure trustworthy. |
| **Collapse is lossy.** | The plan predicted `B4 ≈ B5`. Measured three times, collapse costs **13%** of tier-weighted satisfaction. Published as a withdrawn claim rather than quietly dropped. |
| **Google Fonts served an axis-pinned static instance.** | It rendered correctly and silently ignored every `font-variation-settings`. Caught with fontTools. |
| **Model Armor blocks 3.35% of genuine travellers**, and the ones it blocks are the distressed. | Screening the 2,000-message benign corpus. It now flags for review rather than blocking. |
| **A Gemma comparison nearly published a false finding.** | It scored 26.7% on urgency, below a regex. That was our prompt, not the model: given one line of band definition it scores 80.8%. |

---

## What is still open

Listed because a closed-findings document with nothing open is a document nobody checked.

- **No asynchronous background execution.** A 20,000-agent run is a request-response today.
  It should be a queued job with the DAG as its checkpoint, and the track names this
  explicitly.
- **`swarm/allocate.py` has property tests but the allocator is not formally verified.**
- **A second scenario has not been run.** The kernel carries no domain knowledge and ADK
  appears in one file, but that is an argument, not a demonstration.
- **The console lacks the time scrubber and fork-diff.** The kernel supports both and the
  API exposes them; only the UI is missing. Marked *partial* on `/architecture`.
