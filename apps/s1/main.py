"""Decision service (SystemDesign §8). Port 8200. One endpoint for all System One decisions.

Run:  python -m apps.s1.main
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import json
import threading
import time

import uvicorn
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ghante_shared import config, http, usage

from . import decisions
from .providers import REGISTRY

_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="s1")
# How long each provider may take before the next one in the chain is tried (milliseconds).
# Measured on the team laptop (CPU): head about 20 ms, Laya 170-400 ms, Groq fallback 0.8-2.5 s.
# Override one with S1_TIMEOUT_MS_<PROVIDER>, for example S1_TIMEOUT_MS_LAYA=2500.
TIMEOUT_MS = {"head": 500, "laya": 2000, "llm": 8000, "mock": 1000}
_sim_cache: dict[str, dict] = {}


def decide_sync(decision: str, state: dict, case_id: str | None = None, sim: bool = False, live: bool | None = None) -> dict:
    if decision not in decisions.KIND:
        raise ValueError(f"unknown decision: {decision}. Use one of {sorted(decisions.KIND)}")
    cache_key = None
    if sim and config.env("S1_SIM_CACHE", "1") != "0":
        # Simulated farmers only. The key is what the model actually reads: for a report decision that is the rendered report,
        # so two cases whose reports are word-for-word the same are computed once and the repeat is shown as "cached".
        cache_key = decision + "|" + (decisions.render_report(decision, state) if decisions.KIND[decision] == "report"
                                      else json.dumps(state, sort_keys=True, ensure_ascii=False))
        if cache_key in _sim_cache:
            out = {**_sim_cache[cache_key], "cached": True, "latency_ms": 0}
            _emit(out, case_id, live)
            return out
    failed: list[dict] = []
    for name in decisions.chain_for(decision):
        provider = REGISTRY.get(name)
        if provider is None:
            failed.append({"provider": name, "reason": "unknown provider"})
            continue
        ok, reason = provider.available()
        if not ok:
            failed.append({"provider": name, "reason": reason})
            continue
        timeout_s = config.env_int(f"S1_TIMEOUT_MS_{name.upper()}", TIMEOUT_MS.get(name, 2000)) / 1000
        t0 = time.perf_counter()
        future = _pool.submit(provider.decide, decision, state)
        try:
            # the first call of a local model includes loading it, so it gets a long allowance
            first_use = "first use" in reason
            answers = future.result(timeout=max(timeout_s, 600) if first_use else timeout_s)
        except concurrent.futures.TimeoutError:
            failed.append({"provider": name, "reason": f"slower than {int(timeout_s * 1000)} ms"})
            continue
        except Exception as e:  # provider error: try the next one
            failed.append({"provider": name, "reason": f"{type(e).__name__}: {str(e)[:120]}"})
            continue
        out = {"decision": decision, "answers": answers, "provider": name, "model": provider.MODEL,
               "latency_ms": round((time.perf_counter() - t0) * 1000), "fallback_from": failed[0]["provider"] if failed else None,
               "fallback_reason": failed[0]["reason"] if failed else None, "cached": False}
        usage.add(name, "s1_decisions")
        if cache_key:
            _sim_cache[cache_key] = out
        _emit(out, case_id, live)
        if failed:
            http.post_event(config.ORCH_URL, "fallback.used", {"component": "s1", "from": failed[0]["provider"], "to": name,
                                                             "reason": failed[0]["reason"]}, case_id=case_id)
        return out
    raise RuntimeError("no provider could answer: " + "; ".join(f"{f['provider']}: {f['reason']}" for f in failed))


def _emit(out: dict, case_id: str | None, live: bool | None) -> None:
    agent = {"TRIAGE": "dispatcher", "ROUTE": "intake", "PERIL": "intake", "VERIFY": "eligibility"}[out["decision"]]
    data = {k: out[k] for k in ("decision", "answers", "provider", "model", "latency_ms", "fallback_from", "cached")}
    http.post_event(config.ORCH_URL, "s1.decision", data, case_id=case_id, agent=agent, live=live)


async def decide(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("state"), dict):
            raise ValueError('body must be {"decision": ..., "state": {...}}')
        out = await run_in_threadpool(decide_sync, str(body.get("decision", "")), body["state"], body.get("case_id"),
                                      bool(body.get("sim", False)), body.get("live"))
        return JSONResponse(out)
    except (ValueError, json.JSONDecodeError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=503)


async def reset(request: Request) -> JSONResponse:
    """A new scenario run starts with nothing remembered, so its decisions are computed (and timed) again."""
    n = len(_sim_cache)
    _sim_cache.clear()
    return JSONResponse({"ok": True, "forgotten": n})


async def health(request: Request) -> JSONResponse:
    providers = {}
    for name, p in REGISTRY.items():
        ok, reason = p.available()
        providers[name] = {"usable": ok, "detail": reason, "model": p.MODEL}
    return JSONResponse({"ok": True, "service": "s1", "providers": providers, "warmed": sorted(_warmed),
                         "chains": {d: decisions.chain_for(d) for d in decisions.KIND}})


# One made-up question per decision, answered once at start-up and never shown. A model's first answer is much slower than the
# next ones, and a decision that misses its allowance (the head has 500 ms) goes to the LLM instead, which answers differently.
WARM_UP = {"ROUTE": {"agent_question": "Was your crop damaged?", "expected": "yes_no", "utterance": "Yes, it was."},
           "PERIL": {"cause_text": "Hail fell", "crop_stage": "standing"},
           "TRIAGE": {"crop": "wheat", "crop_stage": "close to harvest", "hail_intensity": "severe", "distance_km": 1, "insured_area_ha": 1.0, "notes": ""}}
_warmed: set[str] = set()  # decisions whose first provider has answered once


def preload() -> None:
    """Load the local models now, in the background, and have each answer one made-up question, so the first decision of a live
    call is not the slow one. Turn off with S1_PRELOAD=0. Only the first usable provider of each chain is loaded."""
    seen: set[str] = set()
    for decision in decisions.KIND:
        for name in decisions.chain_for(decision):
            provider = REGISTRY.get(name)
            if provider is None or not provider.available()[0]:
                continue
            loader = getattr(provider, "_load", None)
            if loader is not None and name not in seen:
                seen.add(name)
                try:
                    loader()
                except Exception as e:  # noqa: BLE001 - the chain falls through at decision time
                    print(f"[s1] could not preload {name}: {type(e).__name__}: {str(e)[:120]}", flush=True)
                    break
            if loader is not None and decision in WARM_UP:
                try:
                    t0 = time.perf_counter()
                    provider.decide(decision, WARM_UP[decision])
                    _warmed.add(decision)
                    print(f"[s1] {decision} warmed on {name} in {round((time.perf_counter() - t0) * 1000)} ms", flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f"[s1] could not warm {decision} on {name}: {type(e).__name__}: {str(e)[:120]}", flush=True)
            break


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    if config.env("S1_PRELOAD", "1") != "0":
        threading.Thread(target=preload, name="s1-preload", daemon=True).start()
    yield


app = Starlette(lifespan=lifespan, routes=[Route("/decide", decide, methods=["POST"]), Route("/reset", reset, methods=["POST"]), Route("/health", health)])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=config.port_of(config.S1_URL, 8200), log_level="warning")
