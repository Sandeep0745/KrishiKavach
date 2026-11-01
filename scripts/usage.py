"""Show how much of each limited free allowance has been used (NFR-14).

    python scripts/usage.py

Allowances are the figures found on 6-7 Oct 2026 (context/TechDecisions.md §9). Check each provider's console for the real balance.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ghante_shared import usage  # noqa: E402

ALLOWANCES = {
    ("sarvam", "tts_chars"): (33000, "characters, if the whole Rs 100 credit goes to speech"),
    ("deepgram", "stt_seconds"): (1_500_000, "seconds, rough value of the $200 credit"),
    ("groq", "llm_requests"): (1000, "requests per day per model"),
    ("groq", "llm_tokens"): (200_000, "tokens per day per model"),
    ("livekit", "agent_minutes"): (1000, "minutes per month"),
}


def main() -> int:
    data = usage.read()
    if not data:
        print("No usage recorded yet (logs/usage.json is empty).")
        return 0
    print(f"{'provider':<10} {'metric':<16} {'used':>12}   allowance")
    for provider in sorted(data):
        for metric, used in sorted(data[provider].items()):
            limit = ALLOWANCES.get((provider, metric))
            note = f"{used / limit[0] * 100:5.1f}% of {limit[0]:,} {limit[1]}" if limit else "local, no limit" if provider in ("head", "laya", "mock", "piper") else "-"
            print(f"{provider:<10} {metric:<16} {used:>12,.0f}   {note}")
    print("\nDaily limits reset every day; this file adds up everything since the last reset (python scripts/reset.py --logs).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
