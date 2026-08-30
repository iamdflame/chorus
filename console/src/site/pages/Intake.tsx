import { useState } from "react";
import { LINKS } from "../links";
import { Link } from "../router";

/** The multimodal front door.
 *
 *  The point is not that three modalities are supported. It is that all three land in the
 *  same 2,304-cell lattice, so the unbounded input widens while the bounded reasoning does
 *  not. Every number here comes from scripts/verify_multimodal.py — including the one that
 *  is not flattering. */

type Mode = "speak" | "photograph" | "write";

const SPOKEN = {
  said:
    "Hi, um, our flight got cancelled. My mother is eighty-four and she really can’t " +
    "manage stairs at all. There’s two of us and we’ve got a checked bag. We have to get " +
    "to Boston by tomorrow morning if there’s any way.",
  fields: [
    ["urgency", "same_day", "we have to get to Boston by tomorrow morning"],
    ["party", "pair", "there’s two of us"],
    ["constraints", "assisted", "she really can’t manage stairs"],
  ],
};

/** Three languages, one cell. The single frame that proves unbounded input and bounded
 *  reasoning at the same time. */
const MULTILINGUAL = [
  ["English", "We’re two, travelling with my mother who uses a wheelchair. Tomorrow morning at the latest."],
  ["French", "Nous sommes deux, avec ma mère en fauteuil roulant. Demain matin au plus tard."],
  ["Twi", "Yɛyɛ baanu, me maame te wheelchair mu. Ɔkyena anɔpa akyi koraa."],
];

const CELL = "v2 | passenger | basic | same_day | pair | assisted | short | nohotel | origin";

export function Intake() {
  const [mode, setMode] = useState<Mode>("speak");

  return (
    <div className="page">
      <section className="shell prose-head">
        <p className="eyebrow">Intake</p>
        <h1 className="display h1" style={{ maxWidth: "19ch" }}>
          Speak it, photograph it, or type it.
        </h1>
        <p className="lede">
          A regex cannot infer that “she really can’t manage stairs” means assistance. That
          is why extraction needs a model — and why the input can be anything, as long as
          what comes out is typed.
        </p>
      </section>

      <section className="section">
        <div className="shell">
          <div className="incident">
            <div className="incident-controls" role="tablist" aria-label="Modality">
              {([["speak", "Speak"], ["photograph", "Photograph"], ["write", "Write"]] as
                [Mode, string][]).map(([value, label]) => (
                <button key={value} role="tab" aria-selected={mode === value}
                        className="incident-tab" data-active={mode === value}
                        onClick={() => setMode(value)}>
                  {label}
                </button>
              ))}
            </div>

            <div className="intake-body">
              {mode === "speak" && (
                <>
                  <p className="intake-said">“{SPOKEN.said}”</p>
                  <p className="faint intake-meta">
                    135 seconds of speech, synthesised with Gemini TTS and understood as
                    audio — not transcribed first. Transcribing would throw away everything
                    the waveform carries beyond the words, and would hide a transcription
                    error as an extraction error.
                  </p>
                  <dl className="intake-fields">
                    {SPOKEN.fields.map(([field, value, evidence]) => (
                      <div key={field}>
                        <dt>{field}</dt>
                        <dd className="data">{value}</dd>
                        <p className="intake-evidence">heard: “{evidence}”</p>
                      </div>
                    ))}
                  </dl>
                </>
              )}

              {mode === "photograph" && (
                <>
                  <p className="intake-said">
                    A boarding pass supplies what the airline already knows — PNR, flight,
                    tier, bags. Asking a model to infer those from prose is waste twice
                    over: it pays for a guess, then escalates when the guess is unsure.
                  </p>
                  <dl className="intake-fields">
                    {[["flight", "UA1235"], ["destination", "FRA"],
                      ["tier", "basic"], ["checked bags", "1"]].map(([f, v]) => (
                      <div key={f}>
                        <dt>{f}</dt>
                        <dd className="data">{v}</dd>
                      </div>
                    ))}
                  </dl>
                  <p className="faint intake-meta">
                    <strong>96 of 96 fields correct</strong> across 24 passes — and not from
                    clean renders. Each one is skewed, unevenly lit, noise-flecked and
                    JPEG-compressed first, because reading a pristine PNG measures the
                    renderer rather than the model.
                  </p>
                </>
              )}

              {mode === "write" && (
                <>
                  <ul className="intake-langs">
                    {MULTILINGUAL.map(([lang, text]) => (
                      <li key={lang}>
                        <span className="intake-lang data">{lang}</span>
                        <span>{text}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="intake-cell data">{CELL}</p>
                  <p className="faint intake-meta">
                    Three languages, one cell of the lattice — so they share one thought and
                    the second and third are free. The corpus is 2,000 messages across eight
                    languages, written from known situations so the ground truth exists by
                    construction.
                  </p>
                </>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="shell prose">
          <h2 className="display h2 reveal" style={{ maxWidth: "20ch" }}>
            And the number that is not flattering.
          </h2>
          <p className="reveal">
            A spoken message reaches the same cohort as the typed one{" "}
            <strong>82% of the time</strong>, not 100%. Four travellers in twenty-two would
            be reasoned about in a different bucket depending on how they got in touch.
          </p>
          <p className="reveal muted">
            All four disagreements are on ordinal fields, and three of the four are between
            neighbouring bands — <code>same_day</code> against <code>flexible</code>,{" "}
            <code>urgent</code> against <code>critical</code>. The modalities are not reading
            different situations; they are placing the same situation on either side of a
            boundary. Two further voice reads produced a value outside the closed vocabulary
            and were rejected rather than admitted, which is the airlock working.
          </p>
          <p className="reveal">
            <Link to="/evidence" className="btn" data-variant="ghost">Read the evidence →</Link>{" "}
            <a className="btn" data-variant="ghost" href={LINKS.repo} target="_blank"
               rel="noreferrer">scripts/verify_multimodal.py</a>
          </p>
        </div>
      </section>
    </div>
  );
}
