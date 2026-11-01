"""Phase 3 measurement: which free models can fill the three-page form through the browser agent, how long it takes and how
many tokens it uses (the free tier counts tokens per minute for each model).

    .venv\\Scripts\\python.exe scripts\\spikes\\agent_timing.py                      # try the likely Groq models, then the working ones in rotation
    .venv\\Scripts\\python.exe scripts\\spikes\\agent_timing.py "groq:a,groq:b"      # one filing with exactly this chain

One filing per chain, with a long time limit; the Filer's own log lines are printed (one per LLM answer, with the time).
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ghante_shared import config  # noqa: E402
from tests import _util as u  # noqa: E402
from tests.test_phase3 import HERO_FORM, PHOTO  # noqa: E402

WANTED = ["gpt-oss-120b", "kimi-k2", "llama-4", "llama-3.3-70b", "qwen"]  # substrings, in order of preference


def groq_models() -> list[str]:
    """Model ids this key can use. The key itself is never printed."""
    req = urllib.request.Request("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {config.env('GROQ_API_KEY')}", "User-Agent": "ghante72"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return sorted(m["id"] for m in json.loads(r.read().decode("utf-8")).get("data", []))
    except Exception as e:  # noqa: BLE001
        print(f"could not list Groq models: {type(e).__name__}")
        return []


def main() -> None:
    chains = sys.argv[1:]
    auto = not chains
    if auto:
        ids = groq_models()
        print("Groq models for this key:", ", ".join(ids))
        picked = []
        for want in WANTED:
            match = next((i for i in ids if want in i and "guard" not in i and "whisper" not in i and "tts" not in i), None)
            if match and match not in picked:
                picked.append(match)
        chains = [f"groq:{m}" for m in picked] or ["groq:openai/gpt-oss-120b"]
    s = u.Services("portal", "filer", FILING_TIMEOUT_S="200", BROWSER_LLM_CHAIN=chains[0])
    photo = pathlib.Path(s.tmp) / "crop.jpg"
    photo.write_bytes(PHOTO)
    form = {**HERO_FORM, "remarks": "Reported by phone by an automated assistant on the farmer's behalf, with consent. Weather record: hail, 27.8 mm rain."}
    log = s.logs / "filer.log"
    good: list[tuple[float, str]] = []

    def one(chain: str, first: bool) -> None:
        if not first:
            time.sleep(15)
            s.stop("filer")
            s.env["BROWSER_LLM_CHAIN"] = chain
            s.start("filer")
        before = len(log.read_text(encoding="utf-8", errors="replace"))
        t0 = time.time()
        status, r = u.call("POST", u.url("filer", "/file"), {"case_id": "case_0001", "form": form, "photo_path": str(photo), "mode": "agent"}, timeout=300)
        took = time.time() - t0
        ok = status == 200 and not r.get("mismatches")
        print(f"\n==== {chain}: {'CORRECT' if ok else 'not filed correctly'}, HTTP {status}, {took:.0f} s: {str(r)[:300]}", flush=True)
        if ok and "," not in chain:
            good.append((took, chain))
        text = log.read_text(encoding="utf-8", errors="replace")[before:]
        keep = [line for line in text.splitlines() if "[filer]" in line or "rror" in line or "429" in line or "WARNING" in line]
        print("\n".join(line[:240] for line in keep[:40]), flush=True)

    try:
        for n, chain in enumerate(chains):
            one(chain, n == 0)
        if auto and len(good) >= 2:
            good.sort()
            rotation = ",".join(c for _, c in good[:3])
            print(f"\n#### the working models in rotation, one page each, twice: {rotation}")
            one(rotation, False)
            one(rotation, False)
    finally:
        s.close()


if __name__ == "__main__":
    main()
