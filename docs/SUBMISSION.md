# Devpost submission — paste-ready

**Category:** The Fortified Enterprise Fleet
**Hosted URL:** https://chorus-512017284899.us-central1.run.app
**Repository:** https://github.com/iamdflame/chorus

---

## What it does

A hub closes. **20,367 people are stranded, 2,888 seats exist**, and one duty manager at
two in the morning has to decide who flies while the queue is not getting shorter.

Chorus gives every stranded traveller their own agent — a real, independent ADK agent that
reasons about their situation — and charges for the **diversity of those situations, not
their population**. Twenty thousand agents cost 1,964 model calls and $1.94, because two
travellers in genuinely identical circumstances are asking the same question, and the
second one is served the first one's answer from a content-addressed store.

The duty manager gets every traveller reasoned about, inside the window where a seat still
exists, and can explain afterwards why a particular family was routed the way they were.

## How it works

Every boundary an agent crosses — model call, tool call, delegation — is intercepted at
the ADK plugin boundary and recorded as an **effect addressed by its entire causal
history**: `H(kind, role, causal parents, request)`. Two agents that arrive at the same
question from the same position produce the same address, so the second is free.

Five stages, and the boundary at each is defensible:

| stage | cost | why |
| --- | --- | --- |
| intake | unbounded | free text, speech, or a photographed boarding pass |
| extraction | **model**, per message | unbounded input; no table can follow it |
| collapse | kernel, free | identical situations share one thought |
| elicitation | **model**, per situation | the input is a bounded lattice — where the kernel earns its keep |
| allocation | deterministic | a model here would be dearer and worse, so the allocator identity cannot reach one |

## Technologies

**Gemini 3.5 Flash** (Vertex AI, `global` endpoint) for extraction and elicitation ·
**Gemma 4** as an independent second reader · **Gemini TTS + audio understanding** for
voice intake · **Gemini vision** for boarding passes · **`gemini-embedding-001`** ·
**Google ADK 2.8** (`BasePlugin` interposition — the only file that knows ADK exists) ·
**Cloud Run** · **Firestore** (the live service boots on it; `/health` reports which store
is serving) · **Cloud Trace** (39,996 spans) · **Model Armor** · **Secret Manager** ·
**Cloud Tasks** · **Terraform**.

## Data sources

A generated 2,000-message corpus across **8 languages**, written *from* known situations so
ground truth exists by construction — which is what makes the extraction result measurable
rather than asserted. No personal data. The disruption scenario is synthetic; the execution
over it is entirely real.

## Findings and learnings

Most of what we learned came from measurements that went against us. All of it is in the
repository with the commands that reproduce it.

**A twelve-line rule table beat our LLM swarm.** An audit found the model's marginal
contribution was negative. Reproduced, the rules arm scored **+31.3% tier-weighted — and
−28.9% tier-blind**. It was not creating value, it was redistributing it toward the tiers
the metric happened to weight. We rebuilt the input as unbounded free text, where no table
can follow, and the model now reads **26.9 points better** than a control built to beat it.

**We withdrew our headline claim.** The plan predicted collapsed reasoning would match
per-traveller reasoning. Measured three times, **collapse costs about 13%** of tier-weighted
satisfaction. It is published as a withdrawn claim, with the mechanism (a cohort shares one
urgency score, so the allocator cannot rank inside it) and the fix that recovers 85% of it
at a third of the cost.

**Our best-performing baseline was exploiting our own scorer.** Satisfaction was summed per
*booking* while seats are consumed per *soul*, so an arm that seated solo travellers scored
42% higher while moving **fewer people home**. Found by asking why an arm labelled an upper
bound was winning by so much.

**Collapse amplifies prompt injection by exactly the collapse ratio** — one injection
compromises everyone sharing a projection, not one agent. The defence is structural: no
attacker-controlled byte participates in a shared address, so cache poisoning is
*unaddressable* rather than filtered. The corollary generalises: **any design that admits
free text into shared reasoning either loses collapse entirely or becomes poisonable.**

**Model Armor blocks 3.35% of genuine travellers, and they are the distressed ones** —
*"everything is melting down here at the gate"*. Semantic jailbreak detection reads panic as
manipulation. In irregular operations those are the people who most need to get through, so
a match flags for review rather than blocking.

**A drift rate without a noise floor is not a measurement.** Our first Necessity Ledger read
29.63%. Asking the model the same question twice showed it disagrees with itself 0 times in
27 — which is what makes the corrected figure trustworthy.

Full account, including four findings a hostile audit made and how each was closed:
[`docs/AUDIT.md`](docs/AUDIT.md).

## Try it — three commands, no cloud account

```bash
git clone https://github.com/iamdflame/chorus && cd chorus
pip install -r requirements.txt
python -m pytest tests/ -q                 # 362 tests
python scripts/verify_collapse.py          # saturation, offline
python scripts/verify_armor.py             # containment, offline
```

Every number in the README carries the command that regenerates it, and the one figure that
is a projection says so.

---

### Before submitting — checklist

- [ ] Architecture diagram attached (`docs/ARCHITECTURE.md`, includes Gemini → interposer → store → Firestore and the Cloud Tasks path)
- [ ] Video ≤ 4:00 uploaded and public (`docs/VIDEO.md` has the beat-by-beat script)
- [ ] Hosted URL loads for a signed-out visitor
- [ ] Repo public
- [ ] Blog post published with the "created for the All Things Agentic hackathon" line (`docs/blog/cache-poisoning-in-collapsed-agent-fleets.md`)
- [ ] Social post with `#AllThingsAgenticHackathon`
- [ ] Gemma integration named explicitly in the submission text (bonus)
