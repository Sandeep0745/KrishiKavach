r"""Rehearse the whole demo without the phone, several times in a row (Testing T5-01, the part a machine can do).

Each run follows DemoScript.md: reset; start the storm; after about 15 seconds ring the hero; the hero call is played as text
(the farmer's lines of Testing.md 9.2) against the real Intake agent, the real decision models and the real LLM; the photo is
uploaded; the report is filed by the Filer (browser agent, scripted fill as its fallback); then the presenter's P resumes the
district and the run ends on the closing banner. Every run must end the same way, with no manual fix.

    .venv-voice\Scripts\python.exe scripts\demo_check.py              # five runs (about 15 minutes)
    .venv-voice\Scripts\python.exe scripts\demo_check.py --runs 1
    python scripts/demo_check.py --offline                            # no LiveKit, no LLM, test decision provider: checks the wiring only

It uses spare ports and a temporary data folder, so a running demo is not disturbed. What it cannot check: the voice itself,
the phone, the camera, the projector and the room. Those stay manual (HumanSetupChecklist.md).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests import _util as u  # noqa: E402

for candidate in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
    if candidate.exists():  # the backend services run from the main environment
        os.environ.setdefault("GHANTE_SERVICE_PYTHON", str(candidate))
        break
# This process talks to the test services: point the configuration at them before it is read.
for _name, _service, _path in (("ORCH_URL", "orchestrator", ""), ("MCP_REGISTRY_URL", "registry", "/mcp"), ("MCP_WEATHER_URL", "weather", "/mcp"),
                               ("S1_URL", "s1", "")):
    os.environ[_name] = u.url(_service, _path)
os.environ["GHANTE_LOG_DIR"] = tempfile.mkdtemp(prefix="ghante_demo_logs_")  # this process's own usage counts stay out of the real log

from ghante_shared import config, http  # noqa: E402

TOTALS = {"filed": 312, "unreachable": 11, "no_damage": 9, "escalated": 5, "ineligible": 3, "failed": 0}
ANSWERS = {"GREET": "Yes, speaking.", "EVENT": "Yes, there is a lot of damage.", "KHASRA": "Yes, that is the field.", "CAUSE": "Hail fell, the wheat is completely flattened.",
           "TIME": "Around half past three in the afternoon.", "EXTENT": "More than half, about seventy percent.", "STAGE": "The crop was standing."}
CONSENT = "Yes, please do it."
# What the LLM is expected to take from each detail answer; used only with --offline, where there is no LLM.
CANNED = {ANSWERS["EVENT"]: {"slots": {"damage_confirmed": True}}, ANSWERS["CAUSE"]: {"slots": {"cause_text": "Hail fell", "peril": "hailstorm"}},
          ANSWERS["TIME"]: {"slots": {"loss_time": "15:30", "loss_time_text": "Around half past three in the afternoon"}},
          ANSWERS["EXTENT"]: {"slots": {"damage_pct": 70}}, ANSWERS["STAGE"]: {"slots": {"crop_stage": "standing"}}}
PHOTO = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 8 + b"\xff\xd9"
# A stand-in photo: no model looked at it, so no time is given (report.py would otherwise print it as a measured photo check).
PHOTO_META = {"label": "hail_damage", "confidence": 0.82, "latency_ms": None, "edge_mode": "zeroshot", "lat": 23.0192, "lon": 76.7211,
              "captured_at": "2026-10-08T10:15:00Z", "captured_offline": False}

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    if not ok:
        failures.append(name)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)
    return bool(ok)


def api(method: str, path: str, payload: dict | None = None, timeout: float = 30):
    return u.call(method, u.url("orchestrator", path), payload, timeout=timeout)


def state() -> dict:
    return api("GET", "/api/state")[1]


def sim_statuses(st: dict) -> dict[str, str]:
    return {c["id"]: c["status"] for c in st["cases"] if not c["is_hero"]}


async def wait_until(predicate, seconds: float, step: float = 0.25) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(step)
    return False


def upload_photo(case_id: str) -> str:
    status, _, body = u.post_form(u.url("orchestrator", f"/api/cases/{case_id}/evidence"), {"meta": json.dumps(PHOTO_META)},
                                  {"photo": ("crop.jpg", PHOTO, "image/jpeg")})
    if status != 201:
        raise RuntimeError(f"photo upload answered {status}: {body[:200]}")
    return json.loads(body)["evidence_id"]


# ---------- the hero call, two ways ----------
async def call_with_livekit(ring: dict) -> tuple[str | None, str]:
    """The real Intake agent in a LiveKit text session (no audio), with the real LLM. Returns (call outcome, last words)."""
    from livekit.agents import AgentSession

    from apps.voice import agent as va
    from apps.voice.brain import CallBrain
    from apps.voice.services import Services

    call = await va.load_call(ring["case_id"])
    brain = CallBrain(call, Services(call))
    session = AgentSession(llm=va.build_llm())
    agent = va.IntakeAgent(brain, call_id=ring["call_id"])
    va.attach(session, agent)
    spoken: list[str] = []
    session.on("conversation_item_added", lambda ev: spoken.append(getattr(ev.item, "text_content", "") or "")
               if getattr(ev.item, "role", None) == "assistant" else None)
    try:
        first = await session.start(agent, capture_run=True)
        await first
        turns = 0
        while agent.brain.flow.step in ANSWERS and turns < 14:
            turns += 1
            await session.run(user_input=ANSWERS[agent.brain.flow.step])
        if not agent.brain.waiting_for_photo:
            raise RuntimeError(f"the agent did not ask for the photo (step {agent.brain.flow.step} after {turns} turns)")
        evidence_id = upload_photo(ring["case_id"])
        await agent.on_evidence({"evidence_id": evidence_id, "edge_label": "hail_damage", "edge_confidence": 0.82})
        if not await wait_until(lambda: agent.brain.flow.step == "CONSENT", 20):
            raise RuntimeError(f"the photo did not lead to the read-back (step {agent.brain.flow.step})")
        await asyncio.sleep(1.0)
        await session.run(user_input=CONSENT)
        await wait_until(lambda: agent.finished is not None, 150)
        await asyncio.sleep(0.5)
        return agent.finished, (spoken[-1] if spoken else "")
    finally:
        await session.aclose()


async def call_offline(ring: dict) -> tuple[str | None, str]:
    """The Intake agent's call logic with canned extractions instead of the LLM (no LiveKit). Checks the wiring only."""
    from apps.voice import lines
    from apps.voice import services as services_mod
    from apps.voice.brain import CallBrain
    from ghante_shared import mcp_client

    class Canned(services_mod.Services):
        async def extract(self, *, step, question, utterance, known):
            return {"data": CANNED.get(utterance, {"slots": {}}), "provider": "canned", "model": "offline", "ms": 1, "total_ms": 1, "failed": []}

    # as apps.voice.agent.load_call does, without importing LiveKit
    case = await mcp_client.call_tool(config.MCP_REGISTRY_URL, "get_case", {"case_id": ring["case_id"]}, server="registry", client="intake", case_id=ring["case_id"])
    call = lines.CallContext.from_case(case)
    brain = CallBrain(call, Canned(call))
    await brain.open()
    turns = 0
    while brain.flow.step in ANSWERS and turns < 14:
        turns += 1
        await brain.farmer_turn(ANSWERS[brain.flow.step])
    if not brain.waiting_for_photo:
        raise RuntimeError(f"the call logic did not ask for the photo (step {brain.flow.step})")
    await brain.flush()
    await brain.evidence("hail_damage", 0.82, upload_photo(ring["case_id"]))
    reply = await brain.farmer_turn(CONSENT)
    if not reply.run_pipeline:
        raise RuntimeError(f"consent was not taken (rule {reply.rule})")
    last = await brain.pipeline()
    await brain.flush()
    await brain.services.end_call(ring["call_id"], last.end or "completed")
    return last.end, last.text


def explain_call(services: u.Services, mark: int, case_id: str) -> None:
    """What happened on the hero's call, turn by turn, from the event log: enough to see why it ended where it did."""
    print("      what happened on the call:", flush=True)
    for e in services.events()[mark:]:
        d = e.get("data") or {}
        if e["type"] == "fallback.used":
            print(f"        fallback {d.get('component')}: {d.get('from')} -> {d.get('to')} ({str(d.get('reason'))[:100]})", flush=True)
        if e.get("case_id") != case_id:
            continue
        if e["type"] == "call.turn":
            print(f"        {d.get('speaker'):6} {d.get('path') or '':8} {d.get('rule') or '':16} {str(d.get('text'))[:70]}", flush=True)
        elif e["type"] == "s1.decision":
            print(f"        S1 {d.get('decision')} by {d.get('provider')}{' after ' + str(d.get('fallback_from')) if d.get('fallback_from') else ''}: "
                  f"{json.dumps(d.get('answers'), ensure_ascii=False)[:110]}", flush=True)
        elif e["type"] == "case.status_changed":
            print(f"        status {d.get('from')} -> {d.get('to')}: {d.get('reason')}", flush=True)
        elif e["type"] == "call.slot":
            print(f"        slot {d.get('slot')} = {d.get('value')}", flush=True)


# ---------- one run ----------
async def one_run(n: int, services: u.Services, args) -> None:
    from apps.voice import words

    print(f"\n======== run {n} ========", flush=True)
    t_run = time.time()
    check("reset", api("POST", "/api/scenario/reset", {})[0] == 200)
    mark = len(services.events())
    status, out = api("POST", "/api/scenario/start", {})
    check("[S] the storm starts", status == 200 and out.get("state") == "running", str(out)[:120])
    await asyncio.sleep(args.hero_after)
    before = state()
    check("cases are open, ranked and being called when the hero is rung",
          before["stats"]["affected"] == 340 and before["scenario"].get("triaged", 0) > 0 and before["stats"]["in_call"] > 0,
          f"{before['scenario'].get('triaged')} ranked, {before['stats']['in_call']} on a call, {before['stats']['filed']} filed, scenario time {before['clock']['sim_ts'][11:16]}")

    # ---- [H] the hero call ----
    status, ring = api("POST", "/api/hero/call", {})
    if not check("[H] the hero is rung", status == 200, str(ring)[:160]):
        return
    paused = state()
    check("the district pauses for the live call", paused["scenario"]["state"] == "paused" and paused["scenario"]["paused_by"] == "live call" and paused["clock"]["paused"],
          f"{paused['scenario']['state']}, {paused['scenario']['paused_by']}")
    status, room = api("POST", f"/api/calls/{ring['call_id']}/accept", {})
    check("the phone side accepts the call", status == 200, f"room {room.get('room')}" if status == 200 else str(room)[:120])  # never print the token
    await asyncio.sleep(1.5)  # a simulated case that was inside a pipeline step finishes that step
    frozen = state()
    t_call = time.time()
    try:
        outcome, last_words = await (call_offline(ring) if args.offline else call_with_livekit(ring))
    except Exception as e:  # noqa: BLE001
        outcome, last_words = None, f"{type(e).__name__}: {str(e)[:200]}"
    call_s = time.time() - t_call
    await asyncio.sleep(1.0)
    after_call = state()
    check("nothing moved in the district during the call", sim_statuses(after_call) == sim_statuses(frozen) and after_call["clock"]["sim_ts"] == frozen["clock"]["sim_ts"],
          f"{sum(1 for k, v in sim_statuses(after_call).items() if sim_statuses(frozen).get(k) != v)} simulated cases changed; clock {frozen['clock']['sim_ts'][11:16]} -> {after_call['clock']['sim_ts'][11:16]}")
    hero = api("GET", f"/api/cases/{ring['case_id']}")[1]
    ref = hero.get("claim_ref") or ""
    if not check("the hero's report is filed and the call ends normally", hero["status"] == "FILED" and ref.startswith("FCS-") and outcome == "completed",
                 f"status {hero['status']}, {ref or 'no reference'}, call outcome {outcome}; {last_words[:90] if not ref else ''}"):
        explain_call(services, mark, ring["case_id"])
    check("the agent reads the reference out on the call", bool(ref) and words.digits(ref) in last_words, last_words[:110])
    mode = hero.get("filing_mode")
    fell_back = [e["data"] for e in services.events()[mark:] if e["type"] == "fallback.used" and e["data"].get("component") == "filer"]
    check("filed in the browser, by the agent or by its labelled fallback",
          mode == "agent" or (mode == "scripted" and (args.filing == "scripted" or bool(fell_back))),
          f"filed by {mode}" + (f"; fallback: {fell_back[0].get('reason')}" if fell_back else ""))
    ttf = hero.get("time_to_file_s")
    print(f"      the call took {call_s:.0f} s of real time; ring to reference {ttf} s (target 210 s or less; a spoken call adds the speaking time)", flush=True)

    # ---- [P] the district carries on ----
    status, out = api("POST", "/api/scenario/resume", {})
    check("[P] the district resumes", status == 200 and out.get("state") == "running", str(out)[:120])
    deadline = time.time() + 300
    final = state()
    while time.time() < deadline and final["scenario"]["state"] != "finished":
        await asyncio.sleep(1.0)
        final = state()
    stats = final["stats"]
    check("the scenario finishes", final["scenario"]["state"] == "finished", final["scenario"]["state"])
    check("final totals are the scenario's", {k: stats[k] for k in TOTALS} == TOTALS, str({k: stats[k] for k in TOTALS}))
    hours = final["clock"].get("hours_left")
    check("the closing line reads 68 hours left", hours is not None and round(hours) == 68, f"finished at {final['clock']['sim_ts'][11:16]}, {hours} hours left")
    run_s = final["scenario"].get("running_seconds") or 0
    check("the district ran 60 to 90 real seconds, pauses excluded", 60 <= run_s <= 90, f"{run_s:.0f} s")
    claims = u.call("GET", u.url("portal", "/api/claims/count"))[1]["claims"]
    check("one portal record per filed case", claims == stats["filed"], f"{claims} records")
    print(f"      whole run: {time.time() - t_run:.0f} s of real time", flush=True)


async def main_async(args) -> None:
    env = {"HERO_SIM": "0", "MAX_PARALLEL_CALLS": "8", "S1_SIM_CACHE": "1", "SIM_SPEED": "180", "FILING_MODE": args.filing, "RING_TIMEOUT_S": "60"}
    if args.offline:
        env.update(S1_CHAIN_TEXT="mock", S1_CHAIN_REPORT="mock", LIVEKIT_URL="wss://example.invalid", LIVEKIT_API_KEY="offline", LIVEKIT_API_SECRET="s" * 40)
    ok, why = u.filer_can_run()
    names = ["orchestrator", "registry", "weather", "mandi", "portal", "s1"] + (["filer"] if ok else [])
    print(f"Filer: {u.filer_python() if ok else 'cannot run here: ' + why}. Filing mode: {args.filing}. Hero rung {args.hero_after:g} s after the start.", flush=True)
    services = u.Services(*names, **env)
    try:
        if not args.offline:  # the first decisions load the models; on demo day that happens before going on stage
            ready = await wait_until(lambda: {"ROUTE", "TRIAGE"} <= set(http.get_json(f"{config.S1_URL}/health").get("warmed", [])), 300, 1.0)
            check("the decision service has its models loaded and warmed", ready, str(http.get_json(f"{config.S1_URL}/health").get("warmed")))
            u.call("POST", u.url("s1", "/decide"), {"decision": "TRIAGE", "state": {"hail_intensity": "severe", "distance_km": 1, "crop": "wheat"}}, timeout=900)
        last_filing = 0.0
        for n in range(1, args.runs + 1):
            wait = args.gap - (time.time() - last_filing)
            if n > 1 and wait > 0:
                print(f"      waiting {wait:.0f} s so the browser agent's free token allowance refills", flush=True)
                await asyncio.sleep(wait)
            await one_run(n, services, args)
            last_filing = time.time()
        print("\n---- report on the last run (scripts/report.py) ----", flush=True)
        subprocess.run([os.environ.get("GHANTE_SERVICE_PYTHON") or sys.executable, str(ROOT / "scripts" / "report.py"), str(services.events_log)], cwd=ROOT, env=services.env)
    finally:
        services.close()
        if failures:
            for name in ("orchestrator", "filer"):
                path = services.logs / f"{name}.log"
                if path.exists():
                    print(f"---- end of the {name} log ----\n{path.read_text(encoding='utf-8', errors='replace')[-1500:]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--offline", action="store_true", help="no LiveKit and no LLM: canned answers and the test decision provider")
    ap.add_argument("--filing", choices=["auto", "agent", "scripted"], default="auto")
    ap.add_argument("--hero-after", type=float, default=15.0, help="seconds after the start when the hero is rung (DemoScript: about 15)")
    ap.add_argument("--gap", type=float, default=65.0, help="least seconds between two filings by the browser agent")
    args = ap.parse_args()
    asyncio.run(main_async(args))
    runs_failed = len(failures)
    print(f"\nDEMO CHECK {'PASSED' if not failures else 'FAILED'}: {args.runs} run(s), {runs_failed} failed check(s)" + (f": {sorted(set(failures))}" if failures else ""))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
