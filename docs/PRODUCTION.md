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
| `terminal/armor.mp4` | verify_armor, real run, 7s | Beat 5, after card 03 |
| `terminal/bench.mp4` | six arms, real run, 4s | Beat 4 |
| `terminal/collapse.mp4` | saturation, real run, 30s | spare — cut in if a beat runs short |
| `terminal/memory.mp4` | memory across 90 days, 5s | spare |

The five `lt-` files have **transparent backgrounds**, so they sit on top of your screen
recording without a box around them.

---

# PART A — Record the screen

**Three of the five clips are already made.** The terminal proofs in
[`media/terminal/`](media/terminal/) are real recordings: each command was executed in a
real pseudo-terminal, every line stamped with the moment it actually appeared, and replayed
at exactly that speed. Nothing was typed for effect and no output was invented.

| Already made | Length | Shows |
| --- | --- | --- |
| `armor.mp4` | 7s | `PASS every containment property holds` |
| `bench.mp4` | 4s | Six arms, including the row that beats us |
| `collapse.mp4` | 30s | Saturation against the 2,304 ceiling |
| `memory.mp4` | 5s | 90 days of simulated time |

Regenerate any of them with `python scripts/record_terminal.py armor` — they re-run the
real command, so the numbers are whatever is true that day.

**You record two clips: the console, and the cloud tour.**

---

## A0. The one setting that will ruin your take

The console asks for **20,000 agents**. The deployed server caps an unauthenticated caller
at **300** — so if you record against the live URL without preparing, the counters will say
300 while you narrate twenty thousand, and a judge reading the screen catches it.

**Record the console clip against a local server**, started like this:

```bash
cd /home/dflame/Pictures/all_things
CHORUS_PUBLIC_CEILING=20000 .venv/bin/python -m uvicorn api.main:app --port 8000
```

Then open `http://localhost:8000/console`. The address bar showing `localhost` is fine —
the *cloud tour* clip is what proves deployment, and it uses the real `.run.app` URL.

If you do record against the live URL anyway, the console will now tell you: it prints
*"capped to 300 agents"* on screen. **If you see that line, stop and re-record.**

---

## A1. Prepare the machine — 10 minutes

1. **Do Not Disturb on.** Windows: `Win + N` → Focus assist. Mac: Control Centre → Focus.
2. Close Slack, mail, anything that pops.
3. Unplug the second monitor, or move everything to one screen.
4. **Screen resolution 1920×1080.** If your screen is bigger, set the recorder to capture a
   1920×1080 region rather than downscaling — downscaled text goes mushy.
5. Battery: plugged in. Some laptops throttle the GPU on battery and the field stutters.

## A2. Prepare the browser

1. Use a **fresh browser window** — not your daily one.
2. **Hide the bookmarks bar**: `Ctrl+Shift+B` (Mac: `Cmd+Shift+B`).
3. Zoom **100%** exactly: `Ctrl+0`.
4. Press **F11** for full screen when recording the console. This removes tabs and address
   bar, so the field fills the frame.
   *Exception:* for the cloud tour you WANT the address bar visible. Leave F11 off there.
5. Open exactly these tabs, in this order, and sign in to each **now**:

   | # | Tab |
   |---|---|
   | 1 | `http://localhost:8000/console` |
   | 2 | `https://chorus-512017284899.us-central1.run.app` |
   | 3 | `https://chorus-512017284899.us-central1.run.app/health` |
   | 4 | Cloud Run console → the `chorus` service |
   | 5 | Cloud Trace → trace list, filtered to today |
   | 6 | Firestore → Data → the `lightcone` collection |

6. On tabs 4–6, **dismiss every banner and tooltip now.** Google consoles love popping a
   "what's new" card the moment you start recording.

## A3. Set up the recorder (OBS)

1. Install OBS Studio. Open it.
2. **Settings → Video**: Base resolution `1920×1080`, Output resolution `1920×1080`,
   FPS `60`.
3. **Settings → Output** → Output Mode `Advanced` → Recording tab:
   - Type: `Standard`
   - Format: `MP4`
   - Encoder: `x264` (or hardware if offered)
   - Rate control: `CRF`, CRF `18`
4. **Settings → Audio**: set Desktop Audio to **Disabled** and Mic to **Disabled**. You are
   recording picture only — the voice comes from ElevenLabs.
5. Back on the main window, under **Sources** click `+` → **Display Capture** → OK.
6. Click **Start Recording** to test for 5 seconds, stop, and **watch it back**. Check:
   text is sharp, no cursor trails, no dropped frames.

## A4. Clip 1 — the collapse *(the most important 60 seconds in the video)*

**Before you press record:**

- Local server running with `CHORUS_PUBLIC_CEILING=20000`
- Tab 1 open at `/console`, **F11 full screen**
- Page fully loaded — the cohort field is visible and still
- Mouse parked at the **bottom right corner**, out of the way

**Record:**

1. Press **Start Recording**. Wait **2 seconds** doing nothing.
2. Move the mouse **slowly** to the `Wake the swarm` button. Two seconds of travel, not a
   flick.
3. Click once.
4. **Take your hands off the keyboard and mouse. Count to five out loud, silently.** This
   is the shot. The field ignites and spreads and you must not be moving the cursor
   through it.
5. Let it run to completion. It takes roughly 40–60 seconds. **Do not touch anything.**
6. When the footer counters stop changing, wait **4 more seconds**, then stop recording.

**What a good take looks like:**

- Orange flashes appear scattered, not all at once
- Blue spreads outward from each flash
- The footer counters climb and settle
- The cursor is nowhere near the middle of the frame

**Re-record if:** you see *"capped to 300 agents"*, the cursor crosses the field, or you
clicked twice.

**Write these down** the moment it finishes — you will speak them in the voiceover:

```
model calls    ______     served free   ______
cost           ______     collapse      ______
```

## A5. Clip 2 — the ledger

1. Tab 1 → navigate to `http://localhost:8000/ledger`. Still full screen.
2. Start recording. Wait 2 seconds.
3. **Scroll slowly** — about one screen every four seconds — from the big percentage down
   past the cost rows to the drift rows at the bottom.
4. Stop at the bottom, wait 3 seconds, stop recording.

Use the **scroll wheel one notch at a time**, or press the down arrow. Trackpad flicks
produce a blur that reads as sloppy.

## A6. Clip 3 — the cloud tour *(this is the deployment proof — do not rush it)*

**F11 OFF for this one.** The address bar is the evidence.

Record all five in **one continuous take**, pausing 3–4 seconds on each:

1. **Tab 2** — the live `.run.app` URL. Let the address bar be readable. Let the page load.
2. **Tab 3** — `/health`. Pause on the JSON. `"backend":"firestore"` and
   `"region":"us-central1"` must be legible.
3. **Tab 4** — Cloud Run console. The `chorus` service, green tick, region visible.
   Scroll down once to show the revision list.
4. **Tab 5** — Cloud Trace. Click into **one trace** so the span tree opens.
5. **Tab 6** — Firestore. Click the `lightcone` collection, then click **one document** so
   the effect fields show.

**Switch tabs with `Ctrl+Tab`, not by clicking.** Clicking makes the cursor jump and looks
frantic.

Total: about 35 seconds. If it runs to 45, that is fine — you will trim it.

## A7. Do it three times

Record each clip **three times**. Not because you will fumble — because the third take is
always calmer than the first, and calm is what this video needs.

Name them as you go: `collapse-1.mp4`, `collapse-2.mp4`, `collapse-3.mp4`. Watch all three
back before choosing. Pick on **cursor discipline and pacing**, not on whether you feel it
went well.

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
| vo-4 | `terminal/bench.mp4` — already made |
| vo-5 | `03-amplification.png`, then `terminal/armor.mp4` — already made |
| vo-6 | **clip 2** — the ledger |
| vo-7 | **clip 3** — the cloud tour |
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
3. `lt-losing.png` over `bench.mp4`, once the table is fully printed. About 4 seconds.
4. `lt-terminal.png` over `armor.mp4` at the start. About 3 seconds.
5. `lt-cloud.png` over clip 3 (the cloud tour) at the start. About 4 seconds.

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

**A beat runs short and the picture ends before the voice.** Cut in `terminal/collapse.mp4`
or `terminal/memory.mp4` — that is what they are there for.

**Someone asks whether the terminal clips are real.** They are recordings of the commands
actually running: executed in a real pseudo-terminal, each line stamped with the moment it
appeared, replayed at that exact speed. The colours and the font are the product's, and a
long idle gap is shortened so nobody watches nothing happen. Both are presentation; the
text and its timing are the record. `scripts/record_terminal.py` regenerates them, and it
re-runs the real command each time.

**A number changed since you recorded.** Re-record just that clip and regenerate just that
one `vo-*.mp3`. This is exactly why they are separate files.
