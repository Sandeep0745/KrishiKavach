"""Smoke check for 72 Ghante (T0-5).

Standard library only. Prints which tools are installed, which keys are present
in .env (names only - values are never printed), and which local services answer.

    uv run python scripts/smoke.py
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent

TOOLS = [
    ("Git", ["git", "--version"], None),
    ("uv", ["uv", "--version"], None),
    ("Node.js (20+)", ["node", "--version"], 20),
    ("npm", ["npm", "--version"], None),
    ("cloudflared", ["cloudflared", "--version"], None),
    ("LiveKit CLI", ["lk", "--version"], None),
]

# (name, needed_for, required)
KEYS = [
    ("LIVEKIT_URL", "voice calls", True),
    ("LIVEKIT_API_KEY", "voice calls", True),
    ("LIVEKIT_API_SECRET", "voice calls", True),
    ("DEEPGRAM_API_KEY", "speech-to-text", True),
    ("SARVAM_API_KEY", "voice", True),
    ("GROQ_API_KEY", "conversation LLM", True),
    ("GEMINI_API_KEY", "browser agent LLM", True),
    ("JEV_API_KEY", "System One (optional, only if free)", False),
    ("DATA_GOV_API_KEY", "live mandi prices (optional)", False),
]

SERVICES = [
    ("orchestrator", "http://127.0.0.1:8000/health", 1),
    ("portal", "http://127.0.0.1:8090/health", 1),
    ("mcp weather", "http://127.0.0.1:8101/health", 1),
    ("mcp registry", "http://127.0.0.1:8102/health", 1),
    ("mcp mandi", "http://127.0.0.1:8103/health", 1),
    ("decision service", "http://127.0.0.1:8200/health", 1),
    ("filer", "http://127.0.0.1:8300/health", 1),
]


def read_env(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def tool_version(cmd: list[str]) -> str | None:
    exe = shutil.which(cmd[0])
    if exe is None:
        return None
    try:
        out = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr).strip().splitlines()
    return text[0] if text else "installed"


def major(version: str) -> int | None:
    m = re.search(r"(\d+)\.", version)
    return int(m.group(1)) if m else None


# The values the demo was tuned and measured with (context/Phase4Results.md). setup\7-start-everything.cmd sets the first three
# itself; any other way of starting reads them from .env.
DEMO_SETTINGS = [("MAX_PARALLEL_CALLS", "8", "with 6 the run ends the next morning with 55 hours left"),
                 ("S1_SIM_CACHE", "1", "with 0 the ranking cannot keep up and the run ends late"),
                 ("FILING_MODE", "auto", "scripted skips the browser agent"),
                 ("SIM_SPEED", "180", "the fleet was timed at 180"),
                 ("HERO_SIM", "0", "1 makes the hero a simulated farmer"),
                 ("WEATHER_MODE", "replay", "the scenario's storm is a replay"),
                 ("HERO_FLOW", "full", "short is the three-minute version")]


def get_json(opener, url: str):
    import json

    with opener.open(url, timeout=3) as r:
        return json.loads(r.read().decode("utf-8"))


def demo_readiness(env: dict[str, str], opener) -> int:
    """Settings in .env that differ from the demo values, and, when the services are running, whether they are ready to go on stage."""
    problems = 0
    print("\nDemo settings in .env (setup\\7-start-everything.cmd sets MAX_PARALLEL_CALLS, S1_SIM_CACHE and FILING_MODE itself)")
    for key, want, why in DEMO_SETTINGS:
        have = env.get(key, "")
        if key == "FILING_MODE" and not have:
            default = "scripted" if env.get("CREDIT_SAVER", "1") != "0" else "auto"
            state = "OK      " if default == want else "DIFFERS "
            print(f"  {state} {key} not set: {default} is used because CREDIT_SAVER={env.get('CREDIT_SAVER', '1')}" + ("" if default == want else f" ({why})"))
        elif have and have != want:
            print(f"  DIFFERS  {key}={have} (demo value {want}: {why})")
        else:
            print(f"  OK       {key}={have or '(not set: the built-in default ' + want + ' is used)'}")
    try:
        orch = get_json(opener, "http://127.0.0.1:8000/health")
    except Exception:
        print("\nOn-stage readiness: the services are not running (start them with setup\\7-start-everything.cmd)")
        return problems
    print("\nOn-stage readiness")
    rows = []
    rows.append(("scenario reset and not started", orch.get("scenario") == "idle" and orch.get("cases") == 0,
                 f"scenario {orch.get('scenario')}, {orch.get('cases')} cases: press Reset twice on the dashboard"))
    rows.append(("the farmer's phone is connected", (orch.get("hero_phones") or 0) > 0, "open /farmer on the phone and press the big button"))
    try:
        health = get_json(opener, "http://127.0.0.1:8200/health")
        s1, warmed = health["providers"], set(health.get("warmed", []))
        loaded = all(s1.get(p, {}).get("detail") == "ready" for p in ("head", "laya")) and {"ROUTE", "PERIL", "TRIAGE"} <= warmed
        rows.append(("decision models loaded and warmed", loaded, ", ".join(f"{p}: {s1.get(p, {}).get('detail')}" for p in ("head", "laya"))
                     + f"; warmed: {', '.join(sorted(warmed)) or 'none yet'} (wait a minute after starting)"))
    except Exception:
        rows.append(("decision service answers", False, "not running"))
    try:
        filer = get_json(opener, "http://127.0.0.1:8300/health")
        rows.append(("Filer window open", bool(filer.get("window_open")), f"browser {filer.get('browser')}"))
        rows.append(("browser agent usable", bool(filer.get("agent", {}).get("usable")), filer.get("agent", {}).get("detail", "")))
    except Exception:
        rows.append(("Filer answers", False, "not running: is .venv-browser installed?"))
    for name, ok, detail in rows:
        print(f"  {'OK      ' if ok else 'NOT YET '} {name}" + ("" if ok else f"  ({detail})"))
        problems += 0 if ok else 1
    return problems


def main() -> int:
    problems = 0
    print("72 Ghante smoke check\n")

    print("Tools")
    for name, cmd, min_major in TOOLS:
        v = tool_version(cmd)
        if v is None:
            print(f"  MISSING  {name}")
            problems += 1
        elif min_major and (major(v) or 0) < min_major:
            print(f"  TOO OLD  {name}: {v}")
            problems += 1
        else:
            print(f"  OK       {name}: {v}")
    py_ok = sys.version_info[:2] == (3, 12)
    print(f"  {'OK      ' if py_ok else 'WRONG   '} Python: {sys.version.split()[0]} (need 3.12)")
    problems += 0 if py_ok else 1

    print("\nKeys in .env (values are never shown)")
    env_path = ROOT / ".env"
    if not env_path.exists():
        print("  MISSING  .env file - copy .env.example to .env and fill it in")
        problems += 1
    env = read_env(env_path)
    for key, purpose, required in KEYS:
        if env.get(key):
            print(f"  SET      {key}  ({purpose})")
        elif required:
            print(f"  EMPTY    {key}  ({purpose})")
            problems += 1
        else:
            print(f"  -        {key}  ({purpose})")

    print("\nLocal services (start them with: python scripts/dev.py)")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for name, url, phase in SERVICES:
        try:
            with opener.open(url, timeout=2) as r:
                state = "UP      " if r.status == 200 else "ERROR   "
        except Exception:
            state = "down    "
        if state != "UP      ":
            problems += 1
        print(f"  {state} {name}" + ("" if phase == 1 else f"  (built in Phase {phase})"))

    problems += demo_readiness(env, opener)
    print(f"\n{'All required items are ready.' if problems == 0 else f'{problems} item(s) need attention.'}")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
