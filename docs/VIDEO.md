# Demo video — 4:00 maximum

Judges evaluate only the first four minutes. Deployment proof is a scored requirement, so
it gets its own beat rather than being mentioned in passing.

Record at 1600x900 or larger. Unedited screen capture with voiceover — the rules reward
"unedited, live execution", and cutting between takes reads as hiding something.

---

## 0:00 – 0:28 · The problem

> "Reasoning now costs less than a database query. Gemini 3.5 Flash is about a dollar
> thirty per million tokens. So in principle every entity in your system could have its
> own agent — one per customer, per machine, per passenger — running for weeks.
>
> Nobody builds that. Because twenty thousand agents means twenty thousand model calls,
> and that is both unaffordable and rate-limited into uselessness."

**On screen:** the scenario line — ORD closed, 20,367 travellers, 2,888 seats.

---

## 0:28 – 0:50 · The claim

> "Unless identical reasoning is computed once.
>
> This is Chorus. Twenty thousand agents. Two thousand thoughts."

**On screen:** the Chorus console, idle, the treemap of cohorts filling the frame.

---

## 0:50 – 2:20 · The demo

Click **wake 20,000**.

> "Every one of these is a real, independent agent with its own ADK session. Nothing in
> the runtime groups them — none of them knows the others exist.
>
> Each cloud is a cohort: agents whose situations are genuinely equivalent. Watch what
> happens when one of them reaches the model."

**Let it run.** Point at a large cohort igniting.

> "That flash is one model call. Three hundred and sixty-eight agents just shared it —
> not because I grouped them, but because they computed the same content address and
> collided in the store.
>
> An agent reasons over a canonical projection of itself: tier, urgency, party size,
> constraints. Never its name, never its destination. Two stranded platinum passengers
> travelling alone who both need to move within four hours face the same decision. Their
> names differ. Their reasoning does not."

**Let the counters climb.** Land on the footer numbers.

> "Twenty thousand agents. Two hundred and twenty-two model calls. Twenty-one cents.
> The same run with one call per agent would have cost nineteen dollars twenty-five."

---

## 2:20 – 2:50 · Why it saturates

**On screen:** the saturation table from the README.

> "The part that matters isn't the ratio, it's the shape. Five hundred agents need a
> hundred and twenty-eight thoughts. Eight thousand need a hundred and eighty-seven.
> Twenty thousand need a hundred and ninety-two.
>
> Twelve thousand extra agents cost five more thoughts. The curve is flat — because cost
> is bounded by the diversity of situations, not by population. A million agents costs
> roughly what twenty thousand does."

---

## 2:50 – 3:20 · That it actually works

**On screen:** the allocation comparison.

> "Cheap is half of it. These agents state what they'd accept — a downgrade, a split
> party, a nearby airport — and a deterministic allocator turns that into a recovery plan.
>
> Against the first-come-first-served fallback airlines actually use: same seats, same
> passengers, ninety-two percent better weighted satisfaction, because the scarce seats go
> to the people who said they most needed them."

---

## 3:20 – 3:50 · Running on Google Cloud

**This beat is scored. Show, do not narrate.**

1. Browser address bar on the live URL: `https://chorus-512017284899.us-central1.run.app`
2. `GET /health` in a tab — `"deployment":"chorus"`, `"region":"us-central1"`
3. Cloud Run console: the **chorus** service, green, revision and region visible
4. Cloud Run **Logs** tab, live requests scrolling
5. Firestore console: the `lightcone` collection with effect documents

> "Backend on Cloud Run. Gemini 3.5 Flash through Vertex AI, authenticating as the
> service account the container runs as. Timeline in Firestore, keyed by content address.
> Agents built on ADK — one plugin intercepts every model call, which is what makes the
> sharing possible at all."

---

## 3:50 – 4:00 · Close

> "Chorus. One agent per entity, for the price of the situations they're actually in."

---

## Checklist before recording

- [ ] `./infra/deploy.sh <project> us-central1` green, including both smoke tests
- [ ] Cloud Run and Firestore consoles open in tabs, already signed in
- [ ] Console at 1600x900+, dark room, browser chrome minimal
- [ ] Say "Gemini 3.5 Flash", "Vertex AI", "ADK", "Cloud Run" and "Firestore" out loud —
      judges are checking the required stack
- [ ] Under 4:00. Anything after is not watched.
