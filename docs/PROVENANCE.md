# Provenance

**This repository's history runs from 29 to 31 August 2026 — 83 commits across three days.**
That is dense enough to be worth explaining before anyone has to wonder,
so here is the straight account.

## What happened

The project was built in a single extended session against the All Things Agentic brief,
working from a written plan rather than from an existing codebase. There is no earlier
private repository being laundered into a fresh history, and no code here was written by
anyone else. The commit timestamps are real; the density is what it looks like.

That density is the honest reason to be sceptical of a submission, so the rest of this
document is the evidence that would be hard to fabricate.

## v1, and the audit that ended it

An earlier version of this system existed inside the same session and was substantially
rebuilt. It is worth describing because the rebuild is the most useful thing about the
project.

v1 collapsed **104×** at twenty thousand agents over a **192-cell** lattice, and claimed
+92% utility over a first-come baseline. Then a hostile technical audit found the thing
that mattered:

> A twelve-line, zero-LLM rule table beat the LLM swarm.

That was correct. Reproduced here, the rules arm scored **+31.3% tier-weighted** against
the swarm — and the follow-up was worse than the finding: under a tier-blind metric the
same rules scored **−28.9%**. They were not creating value, they were redistributing it
toward the tiers the metric happened to weight. Both arms lost to first-come once the
tiers were flattened.

Everything after that is a response to that audit:

| what changed | why |
| --- | --- |
| Input became unbounded free text in 8 languages | A rule table cannot follow language. A regex cannot infer that "she can't manage stairs" means assistance. |
| The lattice went 192 → **2,304** cells | v1's projection omitted haul, hotel entitlement and misconnect while the prompt asked about them. Omitting load-bearing fields collapses beautifully and answers the wrong question. |
| Collapse fell 104× → **10.2×** | The correction cost 90% of the headline number. The old number was a wrong projection, not a better result. |
| The headline became the **blend**, not the best stage | Extraction is per-message and cannot collapse. Quoting only the collapsible stage is how v1 overclaimed. |
| +92% utility was **withdrawn** | It was measuring tier redistribution against the metric it was scored on. |
| Collapse was measured for **fidelity** | It is not lossless: it costs about 13% of tier-weighted satisfaction, replicated across three runs. |

## Things found by measuring rather than by intending

These are in the git history with the commits that made them, and they are the reason to
believe the numbers elsewhere:

- **The bench arm beating everything was exploiting the scorer.** Satisfaction was summed
  per *booking* while seats are consumed per *soul*, so an arm that seated solo travellers
  scored 42% higher while moving *fewer people home*. Found by asking why an arm labelled
  an upper bound was winning by so much.
- **Two scripts were not using the mechanism this project is about.** `Mode.RECORD` never
  consults the effect store, so the fidelity and necessity runs paid full price for answers
  already held. The symptom was silent: 1,748 calls where 880 distinct situations existed.
- **A drift rate with no noise floor is not a measurement.** The first Necessity Ledger
  reported 29.63% necessity. Asking the model the same question twice showed it disagrees
  with itself 0 times in 27 — which is what makes the corrected number trustworthy.
- **Google Fonts served an axis-pinned static instance.** It rendered correctly and
  silently ignored every `font-variation-settings` on the page. Caught with fontTools.
- **A Gemma comparison nearly published a false finding.** It scored 26.7% on urgency,
  below a regex. That was our prompt, not the model: given one line of band definition it
  scores 80.8%.
- **Model Armor blocks 3.35% of genuine travellers**, and the ones it blocks are the
  distressed. It flags rather than blocks here for that reason.

## How to check any of it

Every number in the README carries the command that regenerates it, and the proofs that
need no credentials run offline in CI:

```bash
python -m pytest tests/ -q          # 306 tests
python scripts/verify_determinism.py
python scripts/verify_collapse.py
python scripts/verify_armor.py
python scripts/verify_memory.py
python -m bench.run --agents 4000
```

The claims that cost money to reproduce are marked as such, and the one projected figure
on the README says it is projected.
