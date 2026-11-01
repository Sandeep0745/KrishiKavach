"""Can the free local voice (Piper) run on this laptop? Prints what the installed package offers and tries one Hindi sentence.

    .venv-voice\\Scripts\\python.exe scripts\\spikes\\piper_probe.py
"""
from __future__ import annotations

import inspect
import pathlib
import subprocess
import sys
import time
import wave

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
VOICE = "hi_IN-pratham-medium"
FOLDER = ROOT / "var" / "piper"

try:
    import importlib.metadata as md

    import piper
    print("piper-tts", md.version("piper-tts"))
    print("module:", [n for n in dir(piper) if not n.startswith("_")])
    from piper import PiperVoice
    print("PiperVoice.load", inspect.signature(PiperVoice.load))
    print("PiperVoice.synthesize", inspect.signature(PiperVoice.synthesize))
    for name in ("synthesize_wav", "synthesize_stream_raw", "synthesize_raw"):
        if hasattr(PiperVoice, name):
            print(f"PiperVoice.{name}", inspect.signature(getattr(PiperVoice, name)))
except Exception as e:  # noqa: BLE001
    print(f"PIPER NOT USABLE: {type(e).__name__}: {str(e)[:200]}")
    sys.exit(0)

FOLDER.mkdir(parents=True, exist_ok=True)
model = FOLDER / f"{VOICE}.onnx"
if not model.exists():
    print("downloading the voice", VOICE, "...")
    r = subprocess.run([sys.executable, "-m", "piper.download_voices", VOICE, "--data-dir", str(FOLDER)], capture_output=True, text=True)
    print("download exit code", r.returncode, (r.stdout + r.stderr)[-400:])
if not model.exists():
    print("VOICE FILE MISSING: download failed")
    sys.exit(0)
try:
    t0 = time.perf_counter()
    voice = PiperVoice.load(str(model))
    print(f"voice loaded in {time.perf_counter() - t0:.1f} s; sample rate {voice.config.sample_rate}")
    text = "नमस्ते, क्या मेरी बात रामलाल जी से हो रही है?"
    out = FOLDER / "probe.wav"
    t0 = time.perf_counter()
    first = None
    pcm = bytearray()
    rate = voice.config.sample_rate
    for chunk in voice.synthesize(text):
        if first is None:
            first = time.perf_counter() - t0
            print("chunk attributes:", [n for n in dir(chunk) if not n.startswith("_")])
        pcm.extend(chunk.audio_int16_bytes)
        rate = chunk.sample_rate
    with wave.open(str(out), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(bytes(pcm))
    print(f"PIPER OK: {len(pcm) / 2 / rate:.1f} s of audio in {time.perf_counter() - t0:.2f} s (first audio after {first:.2f} s), saved {out}")
except Exception as e:  # noqa: BLE001
    print(f"PIPER SYNTHESIS FAILED: {type(e).__name__}: {str(e)[:300]}")
