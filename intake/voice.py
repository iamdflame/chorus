"""Speech in, the same typed situation out.

The thesis this project rests on is that the *input* is unbounded and the *reasoning* is
not. Text was the first proof of that. Voice is the harder one, and it is harder in a way
that matters: a traveller speaking at an airport gives you disfluency, background noise,
self-correction and things a keyboard would have tidied away. If the projection survives
that, the airlock is not a property of well-formed prose.

Two things are worth saying plainly about what this does and does not demonstrate.

**The audio is synthesised, not recorded.** `speak()` uses Gemini TTS to produce genuine
audio, and `listen()` genuinely hears it — the model is doing real speech understanding on
real waveform data, not reading a transcript we handed it. But TTS speech is cleaner than a
phone call from a departure hall, so this measures that the pipeline works end to end, not
that it is robust to a crying child six feet away.

**Nothing about collapse changes.** Voice is another way of arriving at a `Projection`, and
a projection derived from speech addresses identically to one derived from text. That is the
claim the verification checks, and it is the only reason adding a modality is interesting
rather than decorative: a traveller who speaks joins the same cohort as one who typed, and
shares the same thought at no extra cost.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
TTS_MODEL = "gemini-3.1-flash-tts-preview"
LISTEN_MODEL = "gemini-3.5-flash"

# Gemini TTS returns headerless little-endian PCM. The rate is announced in the mime type
# rather than assumed, because a wrong sample rate produces audio that plays at the wrong
# speed and is then blamed on the model.
_RATE = re.compile(r"rate=(\d+)")


@dataclass
class Utterance:
    """Synthesised speech, as a playable WAV."""

    wav: bytes
    sample_rate: int
    said: str

    @property
    def seconds(self) -> float:
        # 16-bit mono.
        return max(len(self.wav) - 44, 0) / (2 * self.sample_rate)


def _post(model: str, body: dict, *, api_key: str, timeout: float) -> dict:
    request = urllib.request.Request(
        f"{ENDPOINT}/{model}:generateContent?key={api_key}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap raw PCM in a WAV container so the bytes are a file anyone can play."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm)
    return buffer.getvalue()


def speak(text: str, *, voice: str = "Kore", api_key: str | None = None,
          timeout: float = 180.0) -> Utterance | None:
    """Synthesise a traveller saying something. Returns None on failure, never raises."""
    key = api_key or os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        return None
    try:
        got = _post(TTS_MODEL, {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
                },
            },
        }, api_key=key, timeout=timeout)
    except (urllib.error.HTTPError, Exception):  # noqa: BLE001
        return None

    parts = got.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    for part in parts:
        blob = part.get("inlineData")
        if not blob:
            continue
        mime = blob.get("mimeType", "")
        found = _RATE.search(mime)
        rate = int(found.group(1)) if found else 24_000
        pcm = base64.b64decode(blob["data"])
        return Utterance(wav=to_wav(pcm, rate), sample_rate=rate, said=text)
    return None


def listen(wav: bytes, instruction: str, *, api_key: str | None = None,
           timeout: float = 180.0) -> dict | None:
    """Hand audio to the model and get a typed answer back.

    The audio is sent as data, not as a transcript. Transcribing first and then extracting
    would be a different and weaker system: it would throw away everything the waveform
    carries that the words do not, and it would hide a transcription error as an
    extraction error.
    """
    key = api_key or os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        return None
    try:
        got = _post(LISTEN_MODEL, {
            "contents": [{"parts": [
                {"text": instruction},
                {"inlineData": {"mimeType": "audio/wav",
                                "data": base64.b64encode(wav).decode("ascii")}},
            ]}],
            "generationConfig": {"temperature": 0, "response_mime_type": "application/json"},
        }, api_key=key, timeout=timeout)
    except Exception:  # noqa: BLE001 - a failed modality is a data point
        return None

    for part in got.get("candidates", [{}])[0].get("content", {}).get("parts", []):
        text = part.get("text")
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None
