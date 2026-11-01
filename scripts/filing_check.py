"""Check the claim pipeline and the Filer with the real models, on spare ports and a temporary data folder (Testing T3-04 to T3-06).

    .venv\\Scripts\\python.exe scripts\\filing_check.py                  # pipeline once, 3 browser-agent filings, the timeout drill
    .venv\\Scripts\\python.exe scripts\\filing_check.py --agent-runs 5   # the full T3-04 count
    .venv\\Scripts\\python.exe scripts\\filing_check.py --visible        # show the browser window while it works

The browser agent uses the free-tier LLM in BROWSER_LLM_CHAIN; runs are spaced so the per-minute limit is not what fails.
Nothing here touches a running demo: it uses ports 18000 and up, and the only site opened is the sandbox portal on this computer.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests import _util as u  # noqa: E402
from tests.test_phase3 import HERO_FORM, HERO_META, HERO_SLOTS, PHOTO  # noqa: E402

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)


def note(text: str) -> None:
    print(f"      {text}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-runs", type=int, default=3)
    ap.add_argument("--gap", type=float, default=65.0, help="seconds between browser-agent runs (one filing uses about a minute's free token allowance)")
    ap.add_argument("--visible", action="store_true")
    ap.add_argument("--mock-s1", action="store_true", help="use the test decision provider instead of the real models")
    args = ap.parse_args()

    ok, why = u.filer_can_run()
    print(f"Filer environment: {u.filer_python()}")
    if not ok:
        print(f"FAIL  the Filer cannot run: {why}")
        return 1
    print(f"Browser: {why}")
    env = {"FILING_MODE": "auto", "CREDIT_SAVER": "0", "FILER_HEADLESS": "0" if args.visible else "1", "FILER_FIELD_DELAY_MS": "150" if args.visible else "0",
           "PIPELINE_WAIT_S": "170"}
    if args.mock_s1:
        env.update(S1_CHAIN_TEXT="mock", S1_CHAIN_REPORT="mock")
    s = u.Services("orchestrator", "portal", "weather", "registry", "mandi", "s1", "filer", **env)
    api = lambda method, path, payload=None, timeout=200: u.call(method, u.url("orchestrator", path), payload, timeout=timeout)  # noqa: E731
    filer = lambda body, timeout=200: u.call("POST", u.url("filer", "/file"), body, timeout=timeout)  # noqa: E731
    try:
        health = u.call("GET", u.url("filer", "/health"))[1]
        engine = api("GET", "/health")[1].get("pipeline_engine")
        print(f"Pipeline engine: {engine}. Browser agent: {health['agent']['detail']}, models {health['agent']['models']}.")
        agent_usable = health["agent"]["usable"]

        # ---- 1. the decision model's second opinion, warmed up first (the first call loads the model) ----
        t0 = time.time()
        state = {"peril": "hailstorm", "damage_pct": 70, "edge_label": "hail_damage", "edge_confidence": 0.8, "hail": True, "precipitation_mm": 27.8,
                 "wind_gust_kmh": 85, "distance_from_plot_m": 120, "minutes_from_storm": 0}
        status, v = u.call("POST", u.url("s1", "/decide"), {"decision": "VERIFY", "state": state}, timeout=900)
        check("VERIFY answers for the hero's evidence", status == 200 and isinstance(v.get("answers", {}).get("evidence_consistent", {}).get("value"), bool),
              f"provider {v.get('provider')}, value {v.get('answers', {}).get('evidence_consistent', {}).get('value')}, "
              f"confidence {v.get('answers', {}).get('evidence_consistent', {}).get('confidence')}, first call {time.time() - t0:.0f} s" if status == 200 else str(v)[:200])

        # ---- 2. the whole pipeline for the hero, filing mode auto ----
        case = api("POST", "/api/cases", {"farmer_id": "F0001"})[1]
        for st in ("QUEUED", "CALLING", "IN_CALL", "EVIDENCE"):
            api("POST", f"/api/cases/{case['id']}/status", {"status": st})
        api("PATCH", f"/api/cases/{case['id']}/slots", dict(HERO_SLOTS))
        code, _, body = u.post_form(u.url("orchestrator", f"/api/cases/{case['id']}/evidence"), {"meta": json.dumps(HERO_META)}, {"photo": ("crop.jpg", PHOTO, "image/jpeg")})
        api("POST", f"/api/cases/{case['id']}/status", {"status": "PROCESSING", "reason": "photo and consent"})
        t0 = time.time()
        status, out = api("POST", f"/api/cases/{case['id']}/pipeline/run", {})
        took = time.time() - t0
        check("pipeline files the hero's report", status == 200 and out.get("status") == "FILED" and str(out.get("claim_ref", "")).startswith("FCS-"),
              f"{out.get('claim_ref')}, filed by {out.get('filing_mode')}, {took:.1f} s, verdict {out.get('verdict')}" if status == 200 else str(out)[:300])
        if status == 200 and out.get("status") != "FILED":
            note(f"status {out.get('status')}, reasons {out.get('reasons')}, failed {out.get('failed')}")
        time.sleep(1)
        events = s.events()
        for e in events:
            if e["type"] == "s1.decision" and e["data"]["decision"] == "VERIFY" and e["case_id"] == case["id"]:
                a = e["data"]["answers"]["evidence_consistent"]
                note(f"VERIFY on the call: {e['data']['provider']} said {a['value']} with confidence {a['confidence']} in {e['data']['latency_ms']} ms")
            if e["type"] == "fallback.used":
                note(f"fallback: {e['data']}")
            if e["type"] == "agent.finished" and e["case_id"] == case["id"]:
                note(f"{e['agent']}: {e['data']['summary']} [{e['data']['seconds']} s]")
        if out.get("claim_ref"):
            record = u.call("GET", u.url("portal", f"/api/claims/{out['claim_ref']}"))[1]
            differ = [k for k, v2 in HERO_FORM.items() if str(record.get(k)) != v2]
            check("the portal's record equals the form", not differ and record.get("has_photo") is True, f"differs in {differ}" if differ else "all fields and the photo")

        # ---- 3. T3-04: the browser agent, several times ----
        photo = pathlib.Path(s.tmp) / "crop.jpg"
        photo.write_bytes(PHOTO)
        form = {**HERO_FORM, "remarks": "Reported by phone by an automated assistant on the farmer's behalf, with consent. Weather record: hail, 27.8 mm rain."}
        good, seconds, llm = 0, [], []
        if not agent_usable:
            check("browser agent is usable", False, health["agent"]["detail"])
        for n in range(1, args.agent_runs + 1 if agent_usable else 1):
            time.sleep(args.gap)  # also after the pipeline run above, which used the agent too
            t0 = time.time()
            status, r = filer({"case_id": "case_0001", "form": form, "photo_path": str(photo), "mode": "agent"})
            took = time.time() - t0
            fine = status == 200 and not r.get("mismatches")
            good += 1 if fine else 0
            if status == 200:
                seconds.append(took)
                llm.append(r.get("llm_steps", 0))
                print(f"AGENT RUN {n}: {'correct' if fine else 'WRONG VALUES in ' + str(r.get('mismatches'))}, {r['claim_ref']}, {took:.0f} s, {r.get('llm_steps')} LLM calls, {r.get('steps')} actions", flush=True)
            else:
                print(f"AGENT RUN {n}: failed after {took:.0f} s: {str(r.get('error') if isinstance(r, dict) else r)[:300]}", flush=True)
        if agent_usable and args.agent_runs:
            need = max(1, round(args.agent_runs * 0.8))
            check(f"T3-04 browser agent: {good} of {args.agent_runs} correct (bar: {need})", good >= need,
                  f"median {statistics.median(seconds):.0f} s, slowest {max(seconds):.0f} s, LLM calls {llm}" if seconds else "no run finished")
            if seconds:
                check("T3-04 time and LLM-call limits", max(seconds) <= 75 and max(llm) <= 12, f"limits: 75 s and 12 calls; got {max(seconds):.0f} s and {max(llm)}")

        # ---- 4. T3-05 scripted, and T3-06 the automatic fallback with a 5-second limit ----
        t0 = time.time()
        status, r = filer({"case_id": "case_0001", "form": form, "photo_path": str(photo), "mode": "scripted"})
        check("T3-05 scripted fill", status == 200 and not r.get("mismatches") and time.time() - t0 <= 15, f"{time.time() - t0:.1f} s, {r.get('steps')} steps" if status == 200 else str(r)[:200])
        if agent_usable:
            time.sleep(args.gap)
            s.stop("filer")
            s.env["FILING_TIMEOUT_S"] = "5"
            s.start("filer")
            mark = len(s.events())
            t0 = time.time()
            status, r = filer({"case_id": "case_0001", "form": form, "photo_path": str(photo), "mode": "auto"})
            time.sleep(1)
            fell = [e["data"] for e in s.events()[mark:] if e["type"] == "fallback.used" and e["data"].get("component") == "filer"]
            check("T3-06 agent cut off at 5 s, scripted fill finishes the same form", status == 200 and r.get("mode_used") == "scripted" and not r.get("mismatches") and bool(fell),
                  f"{r.get('claim_ref')}, {time.time() - t0:.0f} s, reason: {r.get('fallback_reason')}" if status == 200 else str(r)[:300])
        total = u.call("GET", u.url("portal", "/api/claims/count"))[1]["claims"]
        note(f"reports in the sandbox portal after this check: {total}")
    except Exception as e:  # noqa: BLE001
        check("filing check ran to the end", False, f"{type(e).__name__}: {str(e)[:300]}")
    finally:
        s.close()
        for name in ("filer", "orchestrator"):
            log = (s.logs / f"{name}.log").read_text(encoding="utf-8", errors="replace").strip()
            if log and failures:
                print(f"---- last lines of the {name} log ----\n{log[-1800:]}")
    print(f"\nFILING CHECK {'PASSED' if failures == 0 else f'FAILED ({failures})'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
