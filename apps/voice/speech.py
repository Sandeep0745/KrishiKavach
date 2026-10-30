"""The audio cache (SystemDesign §10.3a, FR-21). Pure Python: text in, 16-bit PCM in WAV files out.

Speech is cached one sentence at a time. A scripted line is the same words on every call, so after the cache is built it costs
no speech-synthesis request; a sentence the LLM wrote is synthesised once and then also comes from the cache if it is said again.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import wave
from collections.abc import Iterator

from ghante_shared import config

# A sentence ends at . ? or ! followed by a space or the end of the text, so "1.8 hectares" stays one sentence.
_SPLIT = re.compile(r".*?[.?!।]+[\"'”’)]*(?:\s+|$)", re.DOTALL)
# While text is still arriving, a full stop at the very end may be a decimal point ("1." then "8"): wait for the space.
_SPLIT_DONE = re.compile(r".*?[.?!।]+[\"'”’)]*\s+", re.DOTALL)


def clean(segment: str) -> str:
    return re.sub(r"\s+", " ", segment).strip()


def split_segments(text: str) -> list[str]:
    """Sentences of a text, in order. A trailing piece without sentence punctuation is kept as its own segment."""
    out, pos = [], 0
    for m in _SPLIT.finditer(text):
        out.append(clean(m.group(0)))
        pos = m.end()
    tail = clean(text[pos:])
    if tail:
        out.append(tail)
    return [s for s in out if s and any(ch.isalnum() for ch in s)]


def take_complete(buffer: str) -> tuple[list[str], str]:
    """From text that is still arriving: the sentences that are finished, and the unfinished rest."""
    done, pos = [], 0
    for m in _SPLIT_DONE.finditer(buffer):
        done.append(clean(m.group(0)))
        pos = m.end()
    return [s for s in done if s and any(ch.isalnum() for ch in s)], buffer[pos:]


class SpeechCache:
    def __init__(self, root: pathlib.Path | None = None, *, provider: str = "sarvam", model: str = "bulbul:v3", voice: str = "simran", language: str = "en-IN") -> None:
        self.provider, self.model, self.voice = provider, model, voice
        self.language = language
        self.dir = (root or config.VAR_DIR / "tts_cache") / f"{provider}-{voice}"

    def path(self, segment: str) -> pathlib.Path:
        identity = f"{self.provider}|{self.model}|{self.voice}|{clean(segment)}"
        if self.language != "en-IN":  # preserve existing English cached files
            identity = f"{self.language}|{identity}"
        key = hashlib.sha1(identity.encode("utf-8")).hexdigest()
        return self.dir / f"{key}.wav"

    def has(self, segment: str) -> bool:
        return self.path(segment).exists()

    def load(self, segment: str) -> tuple[bytes, int, int] | None:
        """(PCM bytes, sample rate, channels) or None."""
        path = self.path(segment)
        try:
            with wave.open(str(path), "rb") as f:
                if f.getsampwidth() != 2:
                    return None
                return f.readframes(f.getnframes()), f.getframerate(), f.getnchannels()
        except (OSError, wave.Error, EOFError):
            return None

    def save(self, segment: str, pcm: bytes, sample_rate: int, channels: int = 1) -> pathlib.Path:
        path = self.path(segment)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        with wave.open(str(tmp), "wb") as f:
            f.setnchannels(channels)
            f.setsampwidth(2)
            f.setframerate(sample_rate)
            f.writeframes(pcm)
        tmp.replace(path)
        return path

    def missing(self, texts: list[str]) -> list[str]:
        """Sentences of these texts that are not in the cache yet, without repeats, in order."""
        seen, out = set(), []
        for text in texts:
            for segment in split_segments(text):
                if segment not in seen and not self.has(segment):
                    seen.add(segment)
                    out.append(segment)
        return out


def chunks(pcm: bytes, sample_rate: int, channels: int = 1, ms: int = 100) -> Iterator[bytes]:
    """Cut PCM into pieces of `ms` milliseconds (the last one may be shorter)."""
    step = max(1, int(sample_rate * ms / 1000)) * 2 * channels
    for start in range(0, len(pcm), step):
        yield pcm[start:start + step]


def duration_s(pcm: bytes, sample_rate: int, channels: int = 1) -> float:
    return len(pcm) / (2 * channels * sample_rate) if sample_rate else 0.0
