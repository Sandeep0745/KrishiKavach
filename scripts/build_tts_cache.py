r"""Build the audio cache: synthesise every scripted line once, sentence by sentence, in the demo voice (SystemDesign §10.3a).

    .venv-voice\Scripts\python.exe scripts\build_tts_cache.py --dry-run     show what is missing and how many characters it costs
    .venv-voice\Scripts\python.exe scripts\build_tts_cache.py               synthesise what is missing (uses the free Sarvam credit)

Sentences already in var/tts_cache are skipped, so running it again costs nothing. Rebuild only when a line's wording changes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps.voice import lines, speech, words  # noqa: E402
from ghante_shared import config, usage  # noqa: E402

# Read-back combinations worth having ready: (peril, HH:MM, percent). The script of Testing.md 9.2 is the first one.
READBACKS = [("hailstorm", "15:30", 70), ("hailstorm", "15:30", 50), ("hailstorm", "15:30", 100), ("hailstorm", "15:00", 70)]


def hero_context() -> lines.CallContext:
    farmers = json.loads((config.SEED_DIR / "farmers.json").read_text(encoding="utf-8"))
    villages = {v["id"]: v for v in json.loads((config.SEED_DIR / "villages.json").read_text(encoding="utf-8"))}
    storm = json.loads(config.SCENARIO_PATH.read_text(encoding="utf-8"))["storm"]
    f = next(x for x in farmers if x["is_hero"])
    return lines.CallContext(case_id="case_" + f["id"][1:], farmer_id=f["id"], name_en=f["name"], village_en=villages[f["village_id"]]["name"],
                             crop_en=f["policy"]["crop"], khasra=str(f["policy"]["khasra_no"]), is_hero=True, storm_started_at=storm["started_at"])


def all_texts(call: lines.CallContext) -> list[str]:
    texts = []
    for key in lines.LINES:
        if key == "consent":
            for peril, hhmm, pct in READBACKS:
                hh, mm = hhmm.split(":")
                texts.append(lines.render(key, call, peril=words.PERIL_EN[peril], time=words.clock(int(hh), int(mm)), pct=str(pct), peril_code=peril, loss_datetime=f"2026-03-12T{hhmm}:00+05:30"))
        elif key == "reference":
            # the sentence with the reference number is different on every call and is synthesised live; the rest is fixed
            texts.append(lines.render(key, call, ref_spoken="").replace("Your reference number is .", ""))
        else:
            texts.append(lines.render(key, call))
    return texts


async def synthesise(cache: speech.SpeechCache, segments: list[str], voice: str) -> int:
    import aiohttp
    from livekit.plugins import sarvam

    done = 0
    async with aiohttp.ClientSession() as http_session:
        tts = sarvam.TTS(target_language_code=cache.language, model=cache.model, speaker=voice, http_session=http_session)
        for n, segment in enumerate(segments, start=1):
            t0 = time.perf_counter()
            pcm, rate, channels = bytearray(), 0, 1
            try:
                async with tts.synthesize(segment) as stream:
                    async for ev in stream:
                        pcm.extend(bytes(ev.frame.data))
                        rate, channels = ev.frame.sample_rate, ev.frame.num_channels
            except Exception as e:  # noqa: BLE001
                print(f"  {n:>2}/{len(segments)} FAILED {type(e).__name__}: {str(e)[:160]}", flush=True)
                continue
            if not pcm or not rate:
                print(f"  {n:>2}/{len(segments)} FAILED: no audio returned", flush=True)
                continue
            cache.save(segment, bytes(pcm), rate, channels)
            usage.add("sarvam", "tts_chars", len(segment))
            done += 1
            print(f"  {n:>2}/{len(segments)} {speech.duration_s(bytes(pcm), rate, channels):4.1f} s of audio in {time.perf_counter() - t0:4.1f} s, "
                  f"{rate} Hz, {len(segment):>3} characters", flush=True)
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-chars", type=int, default=4000, help="refuse to synthesise more than this in one run")
    ap.add_argument("--language", choices=("hi-IN", "en-IN", "ml-IN", "ta-IN"), default="hi-IN")
    args = ap.parse_args()
    voice = (config.env("TTS_VOICE", "simran") or "simran").lower()
    cache = speech.SpeechCache(provider="sarvam", model="bulbul:v3", voice=voice, language=args.language)
    call = hero_context()
    call.language = args.language
    texts = all_texts(call)
    total_segments = []
    for text in texts:
        for s in speech.split_segments(text):
            if s not in total_segments:
                total_segments.append(s)
    missing = cache.missing(texts)
    chars = sum(len(s) for s in missing)
    print(f"voice {voice}; {len(lines.LINES)} scripted lines = {len(total_segments)} different sentences; {len(total_segments) - len(missing)} already cached; "
          f"{len(missing)} to synthesise = {chars} characters (about Rs {chars * 30 / 10000:.1f} of the Rs 100 free credit)")
    if args.dry_run or not missing:
        return 0
    if chars > args.max_chars:
        print(f"that is more than --max-chars {args.max_chars}; nothing was synthesised")
        return 1
    if not config.env("SARVAM_API_KEY"):
        print("SARVAM_API_KEY is empty in .env; nothing was synthesised")
        return 1
    done = asyncio.run(synthesise(cache, missing, voice))
    left = cache.missing(texts)
    print(f"synthesised {done} sentences; {len(left)} still missing; cache folder: {cache.dir}")
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
