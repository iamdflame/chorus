# Making the video — ElevenLabs, then CapCut Pro

Every step spelled out. Nothing assumed.

The script is in [`VIDEO.md`](VIDEO.md), Part 3. The cards are in
[`media/cards/`](media/cards/). Regenerate them any time with
`python scripts/make_cards.py`.

**Target: 3 minutes 50 seconds. Hard cap: 4 minutes.** The judges stop watching at 4:00.

---

## What you have already

| File | What it is | Where it goes |
| --- | --- | --- |
| `01-scenario.png` | 2am, 2,888 seats | Beat 1, opening |
| `02-title.png` | Chorus, 10.2× | Beat 2 |
| `03-amplification.png` | Collapse amplifies injection | Beat 5, before the terminal |
| `04-close.png` | $1.94 against $19.75 | Beat 8, the end |
| `lt-paid.png` | "PAID — a model call" | Over the field, when orange first flashes |
| `lt-free.png` | "FREE — served from the store" | Over the field, when blue spreads |
| `lt-terminal.png` | "LIVE — unedited terminal" | When a terminal is on screen |
| `lt-losing.png` | "OUR LOSING ROW" | Over the bench table |
| `lt-cloud.png` | The Google Cloud stack names | Over the console tour |

The five `lt-` files have **transparent backgrounds**, so they sit on top of your screen
recording without a box around them.

---

# PART A — Record the screen first

Do this **before** the voiceover. You will fit the voice to the picture, not the other way
round.

### A1. Set up

1. Close every app you do not need. Turn off notifications — **Do Not Disturb on**.
2. Open these in browser tabs, already signed in, in this order:
   - `https://chorus-512017284899.us-central1.run.app` (the console)
   - the same URL + `/ledger`
   - Cloud Run console → the `chorus` service
   - Cloud Trace → trace list
   - Firestore console → the `lightcone` collection
3. Open a terminal. Make the font **big** — 18pt or more. You want it readable on a phone.
4. Screen recorder at **1920×1080, 60fps**. On Windows use OBS; on Mac, QuickTime or OBS.

### A2. Record five separate clips

Do **not** try to record it all in one go. Record five, and CapCut joins them.

| Clip | What you record | Roughly |
| --- | --- | --- |
| **1 — collapse** | The console. Click *Watch it collapse*. Let it run to the end. | 60s |
| **2 — bench** | Terminal: `python -m bench.run --agents 8000`. Let the table print. | 30s |
| **3 — armor** | Terminal: `python scripts/verify_armor.py`. Let `PASS` appear, wait 3s. | 30s |
| **4 — ledger** | The `/ledger` page. Scroll slowly from the big % down to the drift rows. | 25s |
| **5 — cloud** | Address bar → `/health` → Cloud Run → Cloud Trace → Firestore. Slow. | 35s |

**Rules while recording:**

- Move the mouse **slowly**. Fast cursor movement looks panicked on video.
- On clip 1, after clicking, **do not touch anything for 3 seconds.**
- On clips 2 and 3, let the final line sit on screen for **3 full seconds** before stopping.
- If you fumble, **do not stop** — just do that clip again. You will pick the best take.

### A3. Write down the real numbers

While clip 1 is finishing, **write down what the counters actually say**: model calls, cost,
served free. You will read those exact numbers in the voiceover. The script has them in
`[brackets]` for this reason. **Never say a number you did not see on screen that day.**

---

# PART B — The voiceover in ElevenLabs

### B1. Get set up

1. Go to **elevenlabs.io** and sign in.
2. Click **Text to Speech** in the left sidebar.

### B2. Choose the voice

Click the voice dropdown. Pick a **calm, low, unhurried** voice. Good defaults:

- **Adam** — steady, neutral, slightly deep
- **Daniel** — British, measured
- **Charlotte** — calm, clear

Avoid anything described as *energetic*, *upbeat* or *narration trailer*. This script is
someone explaining a system carefully, not selling one.

### B3. The settings that matter

Open **Settings** under the voice picker and set:

| Setting | Value | Why |
| --- | --- | --- |
| **Model** | Eleven Multilingual v2 | Best quality for long narration |
| **Speed** | **1.05** | At 1.0 the script runs 4:02. At 1.05 it lands ~3:47. **This is the setting that keeps you under the cap.** |
| **Stability** | 50% | Lower wanders; higher goes flat |
| **Similarity** | 75% | |
| **Style exaggeration** | 0% | Any higher sounds like an advert |
| **Speaker boost** | On | |

### B4. Record it in eight pieces, not one

Open `VIDEO.md` and find Part 3. Each beat has its words in a `>` quote block.

**Do one beat at a time.** Paste the words of beat 1 into the box, click **Generate**,
click **Download**. Name it `vo-1.mp3`. Then beat 2 → `vo-2.mp3`. And so on to `vo-8.mp3`.

Eight small files are far easier to line up in CapCut than one long one. If beat 5 sounds
wrong you regenerate thirty seconds, not four minutes.

### B5. Two things to fix in the text before you paste

**Numbers.** Replace every `[bracket]` with what you wrote down in step A3, **spelled out as
words**. ElevenLabs reads digits inconsistently.

- Type `one thousand nine hundred and sixty-four` — not `1,964`
- Type `one dollar ninety-four` — not `$1.94`
- Type `ten point two times` — not `10.2×`

**Pauses.** Where you want a beat of silence, type `...` on its own. Example:

```
That flash was one call... and a hundred and twenty-eight agents just shared it.
```

### B6. Listen back once

Play each file. You are checking one thing: **does it sound like a person explaining
something, or like an advert?** If it sounds like an advert, drop Style to 0 and Stability
to 45 and regenerate.

---

# PART C — Editing in CapCut Pro

### C1. Start the project

1. Open CapCut → **New Project**.
2. Top right, click the resolution setting. Set **1920×1080** and **60fps**.
3. Bottom left, click **Import**. Bring in:
   - your 5 screen recordings
   - your 8 `vo-*.mp3` files
   - all 9 PNGs from `docs/media/cards/`

### C2. Lay the voice down first

This is the trick that makes everything else easy. **The voice is the skeleton.**

1. Drag `vo-1.mp3` to the **audio track** at position 0:00.
2. Drag `vo-2.mp3` immediately after it. Then 3, 4, 5, 6, 7, 8 — end to end, no gaps.
3. Look at the total length at the end of the audio track. **It must be under 3:55.**
   If it is over, go back to ElevenLabs and raise Speed to 1.1.

### C3. Put pictures over the voice

Now drag video **above** the audio, matching each beat.

| While you hear | Put this on the video track |
| --- | --- |
| vo-1 | `01-scenario.png` |
| vo-2 | `02-title.png` for the first half, then cut to **clip 1** (console, idle) |
| vo-3 | **clip 1** — the collapse running |
| vo-4 | **clip 2** — the bench table |
| vo-5 | `03-amplification.png`, then **clip 3** — verify_armor |
| vo-6 | **clip 4** — the ledger |
| vo-7 | **clip 5** — the cloud tour |
| vo-8 | `04-close.png` |

**To make a still image last longer:** click it on the timeline, then drag its right edge.

**To trim a clip:** click it, drag the edge inwards. To cut out a middle chunk, put the
playhead where you want the cut and press **Ctrl+B** (Windows) or **Cmd+B** (Mac), then
click the piece you do not want and press **Delete**.

### C4. Drop in the lower thirds

These are the transparent PNGs. They go on a track **above** the video.

1. Drag `lt-paid.png` onto the timeline above clip 1, at the moment the **first orange
   flash** happens. Make it about **3 seconds** long.
2. `lt-free.png` right after it, when blue starts spreading. About 3 seconds.
3. `lt-losing.png` over clip 2, when the bench table is fully printed. About 4 seconds.
4. `lt-terminal.png` over clip 3 at the start. About 3 seconds.
5. `lt-cloud.png` over clip 5 at the start. About 4 seconds.

They are already positioned bottom-left, so **do not move or resize them**.

Give each one a soft entrance: click it → **Animation** → **In** → **Fade** → set to 0.3s.
Then **Out** → **Fade** → 0.3s.

### C5. Transitions — use almost none

The rules reward *unedited*. Fancy transitions read as hiding something.

- Between a card and a clip: **Fade**, 0.3 seconds. That is it.
- Between two clips: **no transition at all**. A hard cut is honest.
- **Never** use zoom, spin, glitch, or anything in the "Trending" tab.

### C6. Music — optional, and quiet if at all

If you add any: pick something ambient with no drums, and set its volume to **−28dB**. You
should barely notice it. If you can hum along, it is too loud. **No music at all is a
perfectly good choice** and several strong technical demos do exactly that.

### C7. Captions

1. Click **Text** → **Auto captions** → **Generate**.
2. **Read every line.** Auto-captions mangle technical words. Fix at minimum:
   *Gemini, Gemma, Vertex, Firestore, ADK, OpenTelemetry, Chorus, cohort, lattice.*
3. Style: white text, black outline, bottom centre. Nothing decorative.

### C8. Export

1. Click **Export** top right.
2. Resolution **1080p**, frame rate **60**, bitrate **Higher**, format **MP4**.
3. Check the duration one last time. **Under 4:00.**

---

# PART D — Before you publish

- [ ] Watch it once **with the sound off**. Does the picture alone tell the story?
- [ ] Watch it once **on your phone**. Is the terminal text readable?
- [ ] Every number you say matches what is on screen at that moment
- [ ] Nothing in it resembles the withdrawn "+92%" claim
- [ ] Upload to YouTube as **Public** — not Unlisted. Unlisted can fail the rules check
- [ ] Upload the caption file separately
- [ ] Title: `Chorus — 20,000 agents, 2,000 thoughts | All Things Agentic`
- [ ] Description: first line is the friction, then the repo and live URLs

---

## If something goes wrong

**The voice sounds robotic.** Stability 45, Style 0, and add `...` for breathing.

**It is over 4 minutes.** ElevenLabs Speed to 1.1 and regenerate. Do not cut a beat — every
one earns a scoring criterion.

**The collapse clip is too long.** Cut the *middle*, not the start or the end. The first
three seconds and the final counters are the whole point.

**A number changed since you recorded.** Re-record just that clip and regenerate just that
one `vo-*.mp3`. This is exactly why they are separate files.
