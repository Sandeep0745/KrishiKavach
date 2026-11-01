r"""Fallback drills (Testing.md §8) that a machine can run: break one thing, check the system notices, says so, and recovers.

    .venv\Scripts\python.exe scripts\drills.py            # D1, D2, D4, D6, D7 with the real models and keys
    python scripts/drills.py --mock-s1                    # with the test decision provider (no models)

D1 the first decision provider is broken      -> the next one answers, marked as a fallback
D2 the browser agent is given 5 seconds       -> the scripted fill finishes the form, labelled
D4 the first LLM's key is wrong               -> another LLM answers the call's question, or the call asks again (reported)
D6 the Filer is killed while filing           -> the case is FAILED with a reason, the orchestrator stays up, filing again works
D7 the orchestrator is killed                 -> it comes back with the cases it had, and reset still works

D3 (wrong speech key), D5 (phone Wi-Fi off), D8 (laptop offline) and D9 (local voice only) need the microphone, the phone or
the network, and stay manual. It uses spare ports and a temporary data folder; a running demo is not disturbed.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests import _util as u  # noqa: E402
from tests.test_phase3 import HERO_META, HERO_SLOTS, PHOTO  # noqa: E402

results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)
    return bool(ok)


def api(method: str, path: str, payload: dict | None = None, timeout: float = 60):
    return u.call(method, u.url("orchestrator", path), payload, timeout=timeout)


def events_since(s: u.Services, mark: int, type_: str) -> list[dict]:
    return [e for e in s.events()[mark:] if e["type"] == type_]


def prepare_hero() -> str:
    """The hero's case as it stands after consent: details stored, photo uploaded, status PROCESSING."""
    case = api("POST", "/api/cases", {"farmer_id": "F0001"})[1]
    for status in ("QUEUED", "CALLING", "IN_CALL", "EVIDENCE"):
        api("POST", f"/api/cases/{case['id']}/status", {"status": status})
    api("PATCH", f"/api/cases/{case['id']}/slots", dict(HERO_SLOTS))
    u.post_form(u.url("orchestrator", f"/api/cases/{case['id']}/evidence"), {"meta": json.dumps(HERO_META)}, {"photo": ("crop.jpg", PHOTO, "image/jpeg")})
    api("POST", f"/api/cases/{case['id']}/status", {"status": "PROCESSING", "reason": "photo and consent"})
    return case["id"]


def d1(mock: bool) -> None:
    print("\n-- D1: the first decision provider is broken --", flush=True)
    second = ("mock", "mock") if mock else ("head", "laya")
    s = u.Services("orchestrator", "s1", S1_CHAIN_TEXT=f"broken,{second[0]},llm", S1_CHAIN_REPORT=f"broken,{second[1]},llm")
    try:
        mark = len(s.events())
        status, out = u.call("POST", u.url("s1", "/decide"), {"decision": "ROUTE", "case_id": "case_0001", "live": True,
                                                             "state": {"agent_question": "Was your crop damaged?", "expected": "yes_no", "utterance": "yes"}}, timeout=600)
        check("D1 the next provider answers", status == 200 and out.get("provider") == second[0] and out.get("fallback_from") == "broken",
              f"answered by {out.get('provider')}, fallback from {out.get('fallback_from')}: {out.get('fallback_reason')}" if status == 200 else str(out)[:200])
        time.sleep(1.0)
        decision = events_since(s, mark, "s1.decision")
        notice = events_since(s, mark, "fallback.used")
        check("D1 the ticker row is marked and the dashboard gets a fallback notice",
              bool(decision) and decision[-1]["data"]["fallback_from"] == "broken" and any(e["data"]["component"] == "s1" for e in notice),
              f"{len(notice)} fallback notice(s)")
    finally:
        s.close()


def d2() -> None:
    print("\n-- D2: the browser agent gets only 5 seconds --", flush=True)
    ok, why = u.filer_can_run()
    if not ok:
        check("D2 the Filer can run", False, why)
        return
    s = u.Services("orchestrator", "portal", "filer", FILING_TIMEOUT_S="5", FILING_MODE="auto")
    try:
        health = u.call("GET", u.url("filer", "/health"))[1]
        photo = pathlib.Path(s.tmp) / "crop.jpg"
        photo.write_bytes(PHOTO)
        from tests.test_phase3 import HERO_FORM

        mark = len(s.events())
        t0 = time.time()
        status, out = u.call("POST", u.url("filer", "/file"), {"case_id": "case_0001", "form": {**HERO_FORM, "remarks": "Drill D2."}, "photo_path": str(photo),
                                                             "mode": "auto"}, timeout=120)
        time.sleep(1.0)
        notice = [e["data"] for e in events_since(s, mark, "fallback.used") if e["data"].get("component") == "filer"]
        if not health["agent"]["usable"]:
            print(f"      the browser agent is not usable here ({health['agent']['detail']}): the scripted fill takes over at once", flush=True)
        check("D2 the scripted fill finishes the form and the switch is announced",
              status == 200 and out.get("mode_used") == "scripted" and not out.get("mismatches") and bool(notice),
              f"{out.get('claim_ref')} in {time.time() - t0:.0f} s; reason: {out.get('fallback_reason')}" if status == 200 else str(out)[:200])
    finally:
        s.close()


def d4() -> None:
    print("\n-- D4: the first LLM's key is wrong --", flush=True)
    code = r'''
import json, os, sys
sys.path.insert(0, os.getcwd())
from apps.voice import extract, lines, prompts
call = lines.CallContext(case_id="case_0001", farmer_id="F0001", name_en="Ramlal Verma", village_en="Khajuriya Kalan",
                         crop_en="wheat", khasra="214", is_hero=True, slots={}, storm_started_at="2026-03-12T15:30:00+05:30")
user = prompts.extract_user(call, step="CAUSE", question="What caused the damage?", utterance="Hail fell, the wheat is completely flattened.", known={})
out = extract.extract_sync(prompts.EXTRACT_SYSTEM, user)
print(json.dumps({"provider": out.get("provider"), "model": out.get("model"), "ok": out.get("data") is not None, "ms": out.get("total_ms"),
                  "failed": [f"{f['provider']}:{f['model']}: {f['reason'][:80]}" for f in out.get("failed", [])]}, ensure_ascii=False))
'''
    env = dict(os.environ, GROQ_API_KEY="drill-wrong-key", PYTHONUTF8="1")  # only this child process gets the wrong key
    run = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    try:
        out = json.loads(run.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        check("D4 the drill ran", False, (run.stderr or run.stdout)[-300:])
        return
    for line in out["failed"]:
        print(f"      failed first: {line}", flush=True)
    check("D4 another provider answers the call's question", out["ok"] and out["provider"] != "groq",
          f"answered by {out['provider']}:{out['model']} in {out['ms']} ms" if out["ok"] else
          "no provider answered: on a live call the agent would ask the farmer to repeat, and escalate after three tries")


def d6() -> None:
    print("\n-- D6: the Filer is killed while it is filing --", flush=True)
    ok, why = u.filer_can_run()
    if not ok:
        check("D6 the Filer can run", False, why)
        return
    s = u.Services("orchestrator", "portal", "weather", "registry", "mandi", "s1", "filer", S1_CHAIN_TEXT="mock", S1_CHAIN_REPORT="mock",
                   FILING_MODE="scripted", FILER_TEST_DELAY_S="20")
    try:
        case_id = prepare_hero()
        answer: dict = {}
        worker = threading.Thread(target=lambda: answer.update(result=api("POST", f"/api/cases/{case_id}/pipeline/run", {}, timeout=200)))
        worker.start()
        time.sleep(6)
        s.stop("filer")
        worker.join(60)
        status, out = answer.get("result", (0, {}))
        check("D6 the case is FAILED with a reason", status == 200 and out.get("status") == "FAILED" and bool(out.get("failed")), str(out.get("failed"))[:160])
        check("D6 the orchestrator stays up", api("GET", "/health")[0] == 200)
        s.env["FILER_TEST_DELAY_S"] = "0"
        s.start("filer")
        status, out = api("POST", f"/api/cases/{case_id}/pipeline/run", {}, timeout=120)
        check("D6 filing again after restarting the Filer files the report (F on the dashboard)", status == 200 and out.get("status") == "FILED",
              f"{out.get('claim_ref')}, filed by {out.get('filing_mode')}")
    finally:
        s.close()


def d7() -> None:
    print("\n-- D7: the orchestrator is killed --", flush=True)
    s = u.Services("orchestrator", "portal")
    try:
        case = api("POST", "/api/cases", {"farmer_id": "F0001"})[1]
        api("POST", f"/api/cases/{case['id']}/status", {"status": "QUEUED"})
        s.stop("orchestrator")
        try:
            u.call("GET", u.url("orchestrator", "/health"), timeout=2)
            down = False
        except Exception:  # noqa: BLE001
            down = True
        check("D7 the orchestrator is down", down)
        t0 = time.time()
        s.start("orchestrator")
        st = api("GET", "/api/state")[1]
        kept = {c["id"]: c["status"] for c in st["cases"]}
        check("D7 it comes back with the cases it had", kept.get(case["id"]) == "QUEUED", f"back in {time.time() - t0:.1f} s; {kept}")
        check("D7 reset works afterwards", api("POST", "/api/scenario/reset", {})[0] == 200 and api("GET", "/api/state")[1]["cases"] == [])
        print("      the dashboard shows \"Connection lost. Retrying.\" while it is down and reconnects by itself (its browser does this)", flush=True)
    finally:
        s.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock-s1", action="store_true")
    ap.add_argument("--only", default="", help="comma-separated drills, e.g. D1,D6")
    args = ap.parse_args()
    only = {x.strip().upper() for x in args.only.split(",") if x.strip()}
    drills = [("D1", lambda: d1(args.mock_s1)), ("D2", d2), ("D4", d4), ("D6", d6), ("D7", d7)]
    for name, fn in drills:
        if only and name not in only:
            continue
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            check(f"{name} ran to the end", False, f"{type(e).__name__}: {str(e)[:200]}")
    failed = [n for n, ok in results if not ok]
    print(f"\nDRILLS {'PASSED' if not failed else 'FAILED'}: {len(results) - len(failed)} of {len(results)} checks" + (f"; failed: {failed}" if failed else ""))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
