"""Piper: a free English voice that runs on the laptop with no network and no limit (TechDecisions §2, the last speech fallback).

Checked on the team laptop with piper-tts 1.8.0: 2.9 s of speech is produced in 0.35 s on the CPU. It sounds more robotic than
Sarvam, so it is used for sentences that are not in the audio cache while CREDIT_SAVER=1, and whenever Sarvam cannot be reached.

Get the voice once:  .venv-voice\\Scripts\\python.exe -m piper.download_voices en_US-lessac-medium --data-dir var\\piper
"""
from __future__ import annotations

import threading

from ghante_shared import config

VOICE = config.env("PIPER_VOICE", "en_US-lessac-medium") or "en_US-lessac-medium"
FOLDER = config.VAR_DIR / "piper"
_lock = threading.Lock()
_voice = None


def model_path():
    return FOLDER / f"{VOICE}.onnx"


def available() -> tuple[bool, str]:
    try:
        import piper  # noqa: F401
    except ImportError:
        return False, "piper-tts is not installed"
    if not model_path().exists():
        return False, f"voice file missing: {model_path().name}"
    return True, "ready"


def synth(text: str) -> tuple[bytes, int]:
    """(16-bit mono PCM, sample rate). Blocking: call it from a worker thread."""
    global _voice
    with _lock:
        if _voice is None:
            from piper import PiperVoice

            _voice = PiperVoice.load(str(model_path()))
        pcm, rate = bytearray(), _voice.config.sample_rate
        for chunk in _voice.synthesize(text):
            pcm.extend(chunk.audio_int16_bytes)
            rate = chunk.sample_rate
        return bytes(pcm), rate
