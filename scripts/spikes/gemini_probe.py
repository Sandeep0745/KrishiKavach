r"""Which Gemini models answer the call's extraction question on this free key? (Phase 5, drill D4.)

    .venv\Scripts\python.exe scripts\spikes\gemini_probe.py
    .venv\Scripts\python.exe scripts\spikes\gemini_probe.py --write run\reports\gemini-working.txt   # also note the fastest one

Drill D4 found that with Groq unusable the next LLM, gemini-3.8-flash, answered 429 (quota). This lists the Flash and Gemma models
the key can see and asks each the same extraction the voice agent asks, a few seconds apart. Prints the model, whether a usable
answer came back and how long it took; never the key. About one free request per model.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apps.voice import extract, lines, prompts  # noqa: E402
from ghante_shared import config  # noqa: E402


def listed_models(key: str) -> list[str]:
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", headers={"x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    names = []
    for m in data.get("models", []):
        name = m.get("name", "").split("/")[-1]
        if "generateContent" in (m.get("supportedGenerationMethods") or []) and ("flash" in name or "gemma" in name):
            if not any(bad in name for bad in ("image", "tts", "audio", "live", "embedding", "thinking-exp")):
                names.append(name)
    return names


def main() -> int:
    key = config.env("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY is not set in .env")
        return 1
    try:
        names = listed_models(key)
    except urllib.error.HTTPError as e:
        print(f"listing the models failed: HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
        return 1
    print(f"{len(names)} Flash and Gemma models listed: {', '.join(names)}", flush=True)
    call = lines.CallContext(case_id="case_0001", farmer_id="F0001", name_en="Ramlal Verma", name_hi="रामलाल वर्मा", village_en="Khajuriya Kalan",
                             crop_en="wheat", khasra="214", is_hero=True, slots={}, storm_started_at="2026-03-12T15:30:00+05:30")
    user = prompts.extract_user(call, step="CAUSE", question="नुकसान किस वजह से हुआ?", utterance="ओले गिरे थे, गेहूँ पूरा बिछ गया।", known={})
    working = []
    for name in names[:12]:
        t0 = time.perf_counter()
        try:
            data, _ = extract._request("gemini", name, prompts.EXTRACT_SYSTEM, user)
            ms = round((time.perf_counter() - t0) * 1000)
            slots = data.get("slots") if isinstance(data, dict) else None
            ok = isinstance(slots, dict) and bool(slots.get("cause_text"))
            print(f"{'OK  ' if ok else 'ODD '} {name}: {ms} ms, {json.dumps(slots, ensure_ascii=False)[:120]}", flush=True)
            if ok:
                working.append((name, ms))
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {name}: {round((time.perf_counter() - t0) * 1000)} ms, {type(e).__name__}: {str(e)[:170]}", flush=True)
        time.sleep(5)
    print(f"\nWORKING: {', '.join(f'{n} ({ms} ms)' for n, ms in working) or 'none'}")
    if len(sys.argv) > 2 and sys.argv[1] == "--write":  # the fastest working model, for the task that runs drill D4 with it
        pathlib.Path(sys.argv[2]).write_text(min(working, key=lambda w: w[1])[0] if working else "", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
