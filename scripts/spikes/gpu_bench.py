"""Time Laya on GPU vs CPU in the .venv-gpu environment."""
from __future__ import annotations
import inspect, statistics, sys, time, traceback

MODEL = "convaiinnovations/laya-multilingual"
Q = {"damage_likelihood": {"type": "choice", "instructions": "Read `report`. How likely is serious crop damage on this farm?", "criteria": {
    "high": "severe hail and the farm is very close to the storm core", "medium": "moderate hail at a middle distance",
    "low": "light hail and the farm is far from the storm core"}}}
REPORTS = [f"Hail intensity at this village was {i}. The farm is {k} km from the storm core. Crop: wheat, close to harvest."
           for i, k in (("severe", 2), ("moderate", 7), ("light", 13))] * 10

def bench(agent, label):
    agent.predict({"report": REPORTS[0]}, Q)
    ms = []
    for r in REPORTS:
        t0 = time.perf_counter(); agent.predict({"report": r}, Q); ms.append((time.perf_counter() - t0) * 1000)
    print(f"{label}: median {statistics.median(ms):.0f} ms, total for 30 = {sum(ms) / 1000:.2f} s -> 340 farms about {sum(ms) / 30 * 340 / 1000:.0f} s")

def main():
    import torch, laya
    print("torch", torch.__version__, "cuda available:", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")
    print("laya.load signature:", inspect.signature(laya.load))
    agent = None
    for kwargs in ({"device": "cuda"}, {}):
        try:
            agent = laya.load(MODEL, **kwargs); print("loaded with", kwargs or "defaults"); break
        except TypeError as e:
            print("load", kwargs, "->", e)
    dev = "?"
    try:
        params = [p for m in vars(agent).values() if hasattr(m, "parameters") for p in m.parameters()]
        if params: dev = str(params[0].device)
    except Exception: pass
    print("model device:", dev, "| agent attrs:", [a for a in dir(agent) if not a.startswith("_")][:25])
    if torch.cuda.is_available() and "cuda" not in dev:
        moved = False
        for name in ("to", "cuda"):
            fn = getattr(agent, name, None)
            if fn:
                try:
                    fn("cuda") if name == "to" else fn(); moved = True; print("moved with agent." + name); break
                except Exception as e: print("agent." + name, "failed:", e)
        if not moved:
            for k, m in vars(agent).items():
                if hasattr(m, "to") and hasattr(m, "parameters"):
                    try: m.to("cuda"); moved = True; print("moved submodule", k)
                    except Exception as e: print("submodule", k, "failed:", e)
    bench(agent, "Laya timing in this environment")

if __name__ == "__main__":
    try: main()
    except Exception: traceback.print_exc(file=sys.stdout); print("GPU BENCH FAILED")
