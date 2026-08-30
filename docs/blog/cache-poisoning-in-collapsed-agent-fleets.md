# Cache poisoning in collapsed agent fleets

### How deduplicating agent reasoning amplifies prompt injection by exactly the ratio that makes it cheap

*Created for the All Things Agentic hackathon.*

---

Give twenty thousand entities their own agent and you get twenty thousand model calls. The
standard response is to stop giving them their own agent. A better one is to notice that
most of those agents are thinking the same thought, and to let them share it.

That is what our system does. Each traveller in a disrupted airline operation gets a real,
independent agent, and each agent reasons not about the traveller but about a **bucketed
projection** of their situation — loyalty tier, urgency, party size, constraints, haul,
hotel entitlement, misconnect status. Two travellers whose projections are identical are
asking the same question, so the second one is served the first one's answer from a
content-addressed store. Twenty thousand agents, 1,964 distinct thoughts, $1.94 instead of
$19.75.

This post is about the vulnerability that creates, which we have not seen described
anywhere, and about the defence — which turns out to be stronger than we expected, for a
reason that is worth the whole article.

## The attack

In an uncollapsed fleet, a successful prompt injection compromises one agent. The blast
radius is one entity, and every incident-response instinct the industry has developed is
calibrated for that.

In a collapsed fleet it is not one. If an attacker can get a malicious answer *recorded at
an address other entities will resolve*, then every entity sharing that projection is served
the poisoned thought — from cache, free, at machine speed, without any of them making a
model call that anyone could inspect.

> **Collapse amplifies injection by exactly the collapse ratio.** The number in the cost
> report and the number in the incident report are the same number.

In our largest cohort at twenty thousand travellers, that number is 128. The saving is the
attack surface. You cannot have one without the other by adding a filter, because they are
not two properties — they are one property, described twice.

## The defence that does not work

The obvious answer is to screen inbound messages for injection. We built that screen. It
catches the obvious cases, it has a 0.00% false-positive rate against 2,000 genuine
traveller messages in eight languages, and while writing it we found a real evasion of our
own first attempt: deleting zero-width characters is not enough, because an attacker using
them *as word separators* leaves one long token that a word-boundary pattern sails straight
past. We now screen every reading the tokeniser might produce.

None of that is the defence, and the module says so in its own docstring. Pattern matching
on natural language is defeated by paraphrase. Any claim that a regex list stops prompt
injection is a claim that should not survive contact with an adversary who is trying.

## The defence that does work, and why it is structural

A shared answer is addressed by

```
H(kind, agent_role, causal_parents, request_hash)
```

and the request for a shared elicitation contains **only a projection** — eight fields, each
drawn from a closed vocabulary of three or four values. There is no free-text field. There
is nowhere for an instruction to live.

So no attacker-controlled byte participates in a shared address. An attacker cannot place a
chosen response at an address another traveller will resolve, because they cannot influence
what that address *is*, and they cannot mint a private one either — every projection they
can produce is one of 2,304 cells that real travellers also occupy.

> **Cache poisoning here is not filtered. It is unaddressable.**

We verify this rather than assert it. `verify_armor.py` runs seven injections through the
extractor, checks that zero attacker-controlled substrings reach any shared prompt, and
checks that each attack lands on a lattice cell a real traveller also occupies and addresses
identically to them. It runs in CI, offline, on every push.

## The constraint this implies, which is the real result

Work the mechanism backwards and it generalises past our system:

> Any design that admits free text into shared reasoning either **loses collapse entirely** —
> because the text makes every address unique — or **becomes poisonable**. There is no
> version that keeps both.

This is a genuine fork in the road for anyone building agent fleets at scale, and it is not
obvious before you hit it. It says that "cache the agent's reasoning" and "give the agent
the user's message" are incompatible design decisions, and that the incompatibility is
structural rather than a matter of sanitisation quality.

We ran into the same wall from an unrelated direction while building cross-session memory.
The natural implementation — a returning traveller's history in their prompt — makes every
prompt unique and takes collapse to 1×. The fix was the same shape: memory feeds the
*projection*, not the prompt. It changes which cohort you join, never what that cohort
thinks. Two features, one constraint, discovered twice.

## What an attacker can still do

They can mislabel themselves. A crafted message can extract to a projection that is not
their true situation, landing them in a cohort they do not belong to. This is real, we
verify that it is possible, and its blast radius is exactly one: they join a cohort, they do
not change what it believes.

## When something does get compromised

The typed airlock covers the injection path. It does not cover a bad model version, a
leaked credential, or a tool that starts returning attacker-controlled data — and a
containment story that only handles the attack you designed for is not a containment story.

Here the architecture pays a dividend it was not built for. Every effect is addressed over
its full causal history, so the set of everything downstream of a compromised call is its
**forward lightcone** — computed, not estimated. Ask which entities consumed a poisoned
thought and it is a graph query returning an exact answer in milliseconds, not a forensic
exercise over logs where the honest answer is "probably these, we think".

Quarantine then invalidates every policy row derived from inside that radius, the policy
version changes, and healthy cohorts keep serving. The rows are invalidated rather than
deleted, because destroying the record of what was served, during incident response, is its
own failure.

The property that makes replay cheap is the property that makes containment exact. That was
not planned, and it is the nicest thing about the design.

## The numbers

```
[1] screen        7/7 obvious injections blocked
    false positives on 2,000 genuine messages: 0.00%
    (the weak layer, and it is not what the containment rests on)

[2] airlock       0 attacker-controlled bytes in any shared prompt
    7/7 attacks landed on a cell a real traveller also occupies,
    and addressed identically to them

[3] mislabelling  an attacker can move themselves between cohorts: yes
    blast radius of that attack: 1 (their own booking)

[4] containment   a compromised call reached 128 travellers
    cohorts quarantined: 1 of 2 — the healthy one keeps serving
```

Reproduce with `python scripts/verify_armor.py`. It needs no credentials.

## If you are building one of these

1. **Compute your amplification factor.** It is your collapse ratio. If you do not know it,
   you do not know your blast radius.
2. **Put a typed schema between untrusted input and shared reasoning**, and make the schema
   the airlock rather than a validation step. Closed vocabularies, no free-text passthrough.
3. **Test that the airlock holds**, in CI, with real injections — not that your screen
   catches them.
4. **Know which entities consumed which thought.** If that is a log-grep, your containment
   is a guess.
5. **Decide the fork deliberately.** Free text in shared reasoning, or collapse. Not both.

---

*Chorus is open source: [github.com/iamdflame/chorus](https://github.com/iamdflame/chorus).
Every number above regenerates from a command in the README, and the ones that are
projections rather than measurements say so.*
