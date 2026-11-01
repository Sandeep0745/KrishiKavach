"""Phase 0 spike: try to run Laya on the laptop's NVIDIA GPU. Run with the base Python 3.12; creates .venv-gpu."""
from __future__ import annotations
import os, pathlib, subprocess, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[2]
VENV_PY = ROOT / ".venv-gpu" / "Scripts" / "python.exe"

def run(cmd, timeout=3000):
    print(">", " ".join(str(c) for c in cmd), flush=True)
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    tail = (p.stdout + p.stderr).strip().splitlines()[-6:]
    for line in tail: print("   ", line[:200])
    return p.returncode

def main():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"], capture_output=True, text=True, timeout=30)
        print("GPU:", out.stdout.strip() or out.stderr.strip()[:200])
        if out.returncode != 0 or not out.stdout.strip():
            print("No usable NVIDIA GPU found. GPU SKIPPED"); return
    except Exception as e:
        print("nvidia-smi not available:", e, "GPU SKIPPED"); return
    if not VENV_PY.exists():
        if run(["uv", "venv", ".venv-gpu", "--python", sys.executable]) != 0: print("GPU FAILED (venv)"); return
    ok = False
    for tag in ("cu130", "cu129", "cu128", "cu126", "cu124"):
        t0 = time.time()
        rc = run(["uv", "pip", "install", "--python", str(VENV_PY), "torch", "--index-url", f"https://download.pytorch.org/whl/{tag}"])
        if rc == 0:
            print(f"torch from {tag} installed in {time.time() - t0:.0f} s"); ok = True; break
    if not ok: print("GPU FAILED (no CUDA torch build could be installed)"); return
    if run(["uv", "pip", "install", "--python", str(VENV_PY), "laya"]) != 0: print("GPU FAILED (laya)"); return
    env = dict(os.environ, HF_HUB_DISABLE_SYMLINKS_WARNING="1", PYTHONUTF8="1")
    p = subprocess.run([str(VENV_PY), str(ROOT / "scripts" / "spikes" / "gpu_bench.py")], cwd=ROOT, capture_output=True, text=True, timeout=1200, env=env, encoding="utf-8", errors="replace")
    print(p.stdout[-4000:])
    if p.returncode != 0: print("stderr tail:", p.stderr[-800:])

if __name__ == "__main__":
    main(); print("D DONE")
