"""Start the 72 Ghante backend processes and stop them all on Ctrl+C.

    python scripts/dev.py                 # everything that is built
    python scripts/dev.py --only orchestrator,portal
    python scripts/dev.py --no-s1         # skip the decision service (it loads large models)
    python scripts/dev.py --voice         # also start the voice worker (needs .venv-voice and the LiveKit keys; uses LiveKit minutes only during calls)
    python scripts/dev.py --list
"""
from __future__ import annotations

import argparse
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# name, port, module, built in phase
PROCESSES = [
    ("orchestrator", 8000, "apps.orchestrator.main", 1),
    ("portal", 8090, "apps.portal.main", 1),
    ("mcp-weather", 8101, "mcp_servers.weather", 1),
    ("mcp-registry", 8102, "mcp_servers.registry", 1),
    ("mcp-mandi", 8103, "mcp_servers.mandi", 1),
    ("s1", 8200, "apps.s1.main", 1),
    ("filer", 8300, "apps.filer.main", 3),
    ("voice", None, "apps.voice.agent", 2),
]


def module_exists(module: str) -> bool:
    return (ROOT / (module.replace(".", "/") + ".py")).exists()


def pump(name: str, proc: subprocess.Popen, log_path: pathlib.Path) -> None:
    with open(log_path, "a", encoding="utf-8") as log:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            log.write(line + "\n")
            log.flush()
            print(f"[{name:<12}] {line}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma-separated process names")
    ap.add_argument("--no-s1", action="store_true")
    ap.add_argument("--voice", action="store_true", help="also start the voice worker from .venv-voice")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    only = {n.strip() for n in args.only.split(",") if n.strip()}
    if args.list:
        for name, port, module, phase in PROCESSES:
            print(f"  {name:<14} {str(port or '-'):<6} python -m {module:<26} {'built' if module_exists(module) else f'not built yet (Phase {phase})'}")
        print("  web            8000   served by the orchestrator at / and /farmer    " + ("built" if (ROOT / "apps/web/index.html").exists() else "not built yet"))
        return 0

    from ghante_shared import config

    config.ensure_dirs()
    env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONPATH=str(ROOT))
    procs: list[tuple[str, subprocess.Popen]] = []
    for name, port, module, _phase in PROCESSES:
        if only and name not in only:
            continue
        if (args.no_s1 and name == "s1") or (name == "voice" and not (args.voice or "voice" in only)) or not module_exists(module):
            continue
        python = sys.executable
        if name == "voice":  # LiveKit packages live in their own environment
            candidates = [ROOT / ".venv-voice" / "Scripts" / "python.exe", ROOT / ".venv-voice" / "bin" / "python"]
            found = next((c for c in candidates if c.exists()), None)
            if found is None:
                print("[dev         ] voice not started: .venv-voice is missing", flush=True)
                continue
            python = str(found)
        if name == "filer":  # Playwright and browser-use live in the browser environment
            candidates = [ROOT / ".venv-browser" / "Scripts" / "python.exe", ROOT / ".venv-browser" / "bin" / "python"]
            found = next((c for c in candidates if c.exists()), None)
            if found is not None:
                python = str(found)
            else:
                print("[dev         ] filer: .venv-browser is missing, starting it with this Python (it needs Playwright)", flush=True)
        cmd = [python, "-m", module] + (["dev"] if name == "voice" else [])
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        procs.append((name, proc))
        threading.Thread(target=pump, args=(name, proc, config.LOG_DIR / f"{name}.log"), daemon=True).start()
        print(f"[dev         ] started {name}" + (f" on port {port}" if port else ""), flush=True)
    if not procs:
        print("nothing to start")
        return 1
    print("[dev         ] all started. Check with: python scripts/smoke.py   Stop with Ctrl+C.", flush=True)

    def stop(*_):
        raise KeyboardInterrupt

    for sig in (signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
        if sig is not None:
            signal.signal(sig, stop)
    try:
        while True:
            time.sleep(1)
            for name, proc in procs:
                if proc.poll() is not None:
                    print(f"[dev         ] {name} stopped with code {proc.returncode}. See logs/{name}.log", flush=True)
                    procs.remove((name, proc))
            if not procs:
                return 1
    except KeyboardInterrupt:
        print("\n[dev         ] stopping...", flush=True)
    finally:
        for _, proc in procs:
            proc.terminate()
        for _, proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
