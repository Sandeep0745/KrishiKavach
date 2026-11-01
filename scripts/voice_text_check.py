r"""Check the voice agent without a microphone: real LiveKit sessions in text mode, the real decision models, the real
conversation LLM, the real MCP servers and the orchestrator. No speech credit is used.

    .venv-voice\Scripts\python.exe scripts\voice_text_check.py

It starts its own services on spare ports with a temporary data folder. The spoken tests (T2-01 to T2-14) still need a person.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import pathlib
import struct
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
# Point this process at the test services before the configuration is read.
for name, service, path in (("ORCH_URL", "orchestrator", ""), ("MCP_REGISTRY_URL", "registry", "/mcp"), ("MCP_WEATHER_URL", "weather", "/mcp"),
                            ("S1_URL", "s1", "")):
    os.environ[name] = u.url(service, path)
os.environ["GHANTE_LOG_DIR"] = tempfile.mkdtemp(prefix="ghante_voice_logs_")  # this process's usage counts stay out of the real log

from ghante_shared import config, http, livekit_token  # noqa: E402

results: list[bool] = []
# What the farmer of Testing.md 9.2 answers to each question. The check answers the question the agent is on, as a person would.
ANSWERS = {"GREET": "Yes, speaking.", "EVENT": "Yes, there is a lot of damage.", "KHASRA": "Yes, that is the field.", "CAUSE": "Hail fell, the wheat is completely flattened.",
           "TIME": "Around half past three in the afternoon.", "EXTENT": "More than half, about seventy percent.", "STAGE": "The crop was standing."}
DETAIL_STEPS = ("CAUSE", "TIME", "EXTENT", "STAGE")
EXPECTED = {"identity_confirmed": True, "damage_confirmed": True, "khasra_confirmed": True, "peril": "hailstorm",
            "loss_datetime": "2026-03-12T15:30:00+05:30", "damage_pct": 70, "crop_stage": "standing", "consent": True}
PHOTO = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 8 + b"\xff\xd9"


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)


def api(method: str, path: str, payload: dict | None = None):
    return u.call(method, u.url("orchestrator", path), payload)


def turns_since(services: u.Services, mark: int) -> list[dict]:
    return [e["data"] for e in services.events()[mark:] if e["type"] == "call.turn"]



FILER_OK, FILER_WHY = u.filer_can_run()

async def wait_for(predicate, seconds: float = 15.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.2)
    return False


async def start_call(services: u.Services):
    """Reset, ring the hero, answer, and return a started text-mode session with the agent."""
    from livekit.agents import AgentSession

    from apps.voice import agent as va
    from apps.voice.brain import CallBrain
    from apps.voice.services import Services

    api("POST", "/api/scenario/reset", {})
    mark = len(services.events())
    status, ring = api("POST", "/api/hero/call", {})
    assert status == 200, ring
    status, room = api("POST", f"/api/calls/{ring['call_id']}/accept", {})
    assert status == 200, room
    call = await va.load_call(ring["case_id"])
    brain = CallBrain(call, Services(call))
    session = AgentSession(llm=va.build_llm())
    agent = va.IntakeAgent(brain, call_id=ring["call_id"])
    va.attach(session, agent)
    first = await session.start(agent, capture_run=True)
    await first
    return session, agent, ring, room, mark


async def say(session, text: str) -> None:
    await session.run(user_input=text)


def show(turns: list[dict], routes: list[dict] | None = None) -> None:
    routes = list(routes or [])
    for t in turns:
        lat = t.get("latency_ms") or {}
        timing = ", ".join(f"{k} {v} ms" for k, v in lat.items() if k in ("s1", "llm", "total")) + (", second request sent" if lat.get("hedged") else "")
        heard = ""
        if t["speaker"] == "farmer" and routes:
            intent = routes.pop(0)["answers"]["intent"]
            heard = f"   ROUTE: {intent['value']} {intent['confidence']}"
        print(f"      {t['speaker']:<6} {str(t.get('path')):<8} {t['text'][:110]}" + (f"   [{timing}]" if timing else "") + heard, flush=True)


def routes_since(services: u.Services, mark: int) -> list[dict]:
    return [e["data"] for e in services.events()[mark:] if e["type"] == "s1.decision" and e["data"]["decision"] == "ROUTE"]


async def happy_path(services: u.Services) -> None:
    print("\n-- happy path, the script of Testing.md 9.2 --", flush=True)
    session, agent, ring, room, mark = await start_call(services)
    try:
        claims = livekit_token.decode_unverified(room["token"])
        check("accepting the call returns a room token that dispatches the intake agent",
              claims["video"]["room"] == ring["room"] and claims["roomConfig"]["agents"][0]["agentName"] == "intake")
        said: list[tuple[str, str]] = []
        while agent.brain.flow.step in ANSWERS and len(said) < 14:
            step = agent.brain.flow.step
            said.append((step, ANSWERS[step]))
            await say(session, ANSWERS[step])
        check("the seven questions are answered and the agent is waiting for the photo", agent.brain.waiting_for_photo,
              f"step {agent.brain.flow.step} after {len(said)} farmer turns: {' '.join(s for s, _ in said)}")
        check("no question had to be asked twice", len(said) == len(ANSWERS), f"{len(said)} farmer turns for {len(ANSWERS)} questions")
        status, _, body = u.post_form(u.url("orchestrator", f"/api/cases/{ring['case_id']}/evidence"),
                                      {"meta": json.dumps({"label": "hail_damage", "confidence": 0.82, "latency_ms": 41, "edge_mode": "zeroshot",
                                                           "lat": 23.0192, "lon": 76.7211, "captured_at": "2026-10-07T10:15:00Z"})},
                                      {"photo": ("crop.jpg", PHOTO, "image/jpeg")})
        evidence = json.loads(body)
        before = len(turns_since(services, mark))
        await agent.on_evidence({"evidence_id": evidence.get("evidence_id"), "edge_label": "hail_damage", "edge_confidence": 0.82})
        await wait_for(lambda: len(turns_since(services, mark)) > before)
        check("the photo message moves the call to the read-back", agent.brain.flow.step == "CONSENT" and status == 201, f"step {agent.brain.flow.step}")
        await say(session, "Yes, please do it.")
        ended = await wait_for(lambda: agent.finished is not None, 75)
        want = "completed" if FILER_OK else "escalated"
        check("after consent the report is filed and the call ends by itself", ended and agent.finished == want, f"outcome {agent.finished}")
    finally:
        await session.aclose()
    await asyncio.sleep(1.5)
    case = api("GET", f"/api/cases/{ring['case_id']}")[1]
    got = {k: case["slots"].get(k) for k in EXPECTED}
    check("T2-02 all slots hold the values of the script", got == EXPECTED, json.dumps({k: v for k, v in got.items() if v != EXPECTED[k]}, ensure_ascii=False) or "all equal")
    from apps.voice import words

    if FILER_OK:
        ref = case.get("claim_ref") or ""
        check("T3-08 (as text) the case is FILED and has a reference from the portal",
              case["status"] == "FILED" and ref.startswith("FCS-") and case["calls"][-1]["outcome"] == "completed",
              f"{case['status']}, {ref}, filed by {case.get('filing_mode')}, verdict {case.get('verdict')} {case.get('verdict_reasons') or ''}")
    else:
        check("with no Filer the case ends FAILED and the call says it was not filed", case["status"] == "FAILED", f"{case['status']} ({FILER_WHY})")
    http.flush_events()
    turns = turns_since(services, mark)
    show(turns, routes_since(services, mark))
    if FILER_OK:
        spoken = [t["text"] for t in turns if t["speaker"] == "agent"]
        check("T3-08 (as text) the agent reads the reference out on the same call",
              bool(case.get("claim_ref")) and any(words.digits(case["claim_ref"]) in t for t in spoken[-2:]), (spoken[-1] if spoken else "")[:120])
    farmer = [t for t in turns if t["speaker"] == "farmer"]
    agent_turns = [t for t in turns if t["speaker"] == "agent"]
    plain = {t["text"]: t["path"] for t in farmer}
    check("T2-03 the plain yes turns took the fast path", all(plain.get(x) == "fast" for x in (ANSWERS["GREET"], ANSWERS["KHASRA"], "Yes, please do it.")),
          ", ".join(f"{t['path']}" for t in farmer))
    detail_said = [text for step, text in said if step in DETAIL_STEPS]
    check("T2-03 the detail turns went to the LLM", bool(detail_said) and all(plain.get(t) == "llm" for t in detail_said), f"{len(detail_said)} detail answers")
    check("each of the seven questions was asked", [s for s, _ in said] == list(ANSWERS), " ".join(s for s, _ in said))
    order = [t["speaker"] for t in turns]
    check("turns are logged in the order they happened", order[:4] == ["agent", "farmer", "agent", "farmer"], " ".join(o[0] for o in order))
    check("every agent turn was reported with its path", len(agent_turns) >= len(farmer) + 2 and all(t.get("path") for t in agent_turns),
          f"{len(agent_turns)} agent turns for {len(farmer)} farmer turns")
    events = services.events()[mark:]
    tools = [f"{e['data']['server']}.{e['data']['tool']}" for e in events if e["type"] == "mcp.tool_called"]
    check("the call used the registry and weather MCP servers", {"registry.get_case", "weather.get_weather_at", "registry.update_case_slots",
                                                                "registry.set_case_status"} <= set(tools), ", ".join(sorted(set(tools))))
    route = [e["data"] for e in events if e["type"] == "s1.decision" and e["data"]["decision"] == "ROUTE"]
    ms = sorted(d["latency_ms"] for d in route)
    check("ROUTE answered every farmer turn from the trained head", len(route) == len(farmer) and all(d["provider"] == "head" for d in route),
          f"{len(route)} decisions, median {ms[len(ms) // 2] if ms else '-'} ms")
    llm_ms = sorted(t["latency_ms"]["llm"] for t in farmer if "llm" in (t.get("latency_ms") or {}))
    fast_ms = sorted(t["latency_ms"].get("s1", 0) for t in farmer if t["path"] == "fast")
    print(f"      thinking time per turn (no audio): fast path median {fast_ms[len(fast_ms) // 2] if fast_ms else '-'} ms; "
          f"LLM path median {llm_ms[len(llm_ms) // 2] if llm_ms else '-'} ms, slowest {llm_ms[-1] if llm_ms else '-'} ms", flush=True)
    tokens = [t.get("llm_tokens") or 0 for t in farmer if t["path"] == "llm"]
    models = sorted({t.get("llm_model") for t in farmer if t.get("llm_model")})
    print(f"      LLM use in this call: {len(tokens)} requests, {sum(tokens)} tokens in total, largest {max(tokens) if tokens else 0}; models {models}. "
          f"Groq's free limit is 8,000 tokens a minute for each model.", flush=True)
    fallbacks = [e["data"] for e in events if e["type"] == "fallback.used"]
    check("no fallback was needed", fallbacks == [], json.dumps(fallbacks, ensure_ascii=False)[:300])
    pipeline_tools = sorted({f"{e['data']['server']}.{e['data']['tool']}" for e in events if e["type"] == "mcp.tool_called" and e["data"].get("client") == "pipeline"})
    check("T3-10 the pipeline used the MCP servers as a second client", "weather.get_weather_at" in pipeline_tools, ", ".join(pipeline_tools))
    verify = [e["data"] for e in events if e["type"] == "s1.decision" and e["data"]["decision"] == "VERIFY"]
    if verify:
        a = verify[0]["answers"]["evidence_consistent"]
        print(f"      VERIFY: {verify[0]['provider']} said {a['value']} with confidence {a['confidence']} in {verify[0]['latency_ms']} ms", flush=True)
    for e in events:
        if e["type"] == "agent.finished":
            print(f"      {e['agent']:<11} {e['data']['seconds']} s  {e['data']['summary']}", flush=True)


async def two_answers(services: u.Services) -> None:
    print("\n-- T2-04 two answers at once --", flush=True)
    session, agent, ring, _, mark = await start_call(services)
    try:
        await say(session, "Yes, speaking.")
        await say(session, "Yes, the hail flattened more than half the crop")
        await agent.brain.flush()
    finally:
        await session.aclose()
    slots = api("GET", f"/api/cases/{ring['case_id']}")[1]["slots"]
    check("damage, cause and extent are all stored from one sentence",
          slots["damage_confirmed"] is True and slots["peril"] == "hailstorm" and slots["damage_pct"] == 70,
          json.dumps({k: slots[k] for k in ("damage_confirmed", "cause_text", "peril", "damage_pct")}, ensure_ascii=False))
    check("the next question is the plot number, not the cause", agent.brain.flow.step == "KHASRA", agent.brain.flow.step)
    http.flush_events()
    await asyncio.sleep(0.5)
    show(turns_since(services, mark), routes_since(services, mark))


async def ending(services: u.Services, name: str, lines_: list[str], status: str, outcome: str) -> None:
    session, agent, ring, _, mark = await start_call(services)
    try:
        for line in lines_:
            await say(session, line)
        await wait_for(lambda: agent.finished is not None, 30)
    finally:
        await session.aclose()
    http.flush_events()
    await asyncio.sleep(0.8)
    case = api("GET", f"/api/cases/{ring['case_id']}")[1]
    last = [t for t in turns_since(services, mark) if t["speaker"] == "agent"][-1]
    ok = case["status"] == status and agent.finished == outcome and case["calls"][-1]["outcome"] == outcome
    check(name, ok, f"{case['status']}, call {case['calls'][-1]['outcome']}; last words: {last['text'][:70]}")
    if not ok:
        show(turns_since(services, mark), routes_since(services, mark))


async def speech_cache() -> None:
    print("\n-- audio cache, with a stand-in speech engine (no credit used) --", flush=True)
    from apps.voice import agent as va
    from apps.voice import lines, speech
    from apps.voice.brain import CallBrain
    from apps.voice.services import Services

    call = lines.CallContext(case_id="case_0001", name_en="Ramlal Verma", village_en="Khajuriya Kalan", khasra="214")
    cache = speech.SpeechCache(pathlib.Path(tempfile.mkdtemp(prefix="ghante_tts_")), voice="test")
    asked: list[str] = []

    async def tone(segment: str):
        asked.append(segment)
        rate = 22050
        for _ in range(5):
            yield b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(rate // 10)), rate, 1

    agent = va.IntakeAgent(CallBrain(call, Services(call)), cache=cache, synth=tone)
    text = lines.render("event", call)

    async def pieces():
        for i in range(0, len(text), 17):  # the text arrives in small pieces, as it does from a language model
            yield text[i:i + 17]

    async def play() -> tuple[int, float]:
        frames, seconds = 0, 0.0
        async for frame in agent.tts_node(pieces(), None):
            frames += 1
            seconds += frame.samples_per_channel / frame.sample_rate
        return frames, seconds

    frames1, seconds1 = await play()
    segments = speech.split_segments(text)
    check("first time: each sentence is synthesised once and saved", asked == segments and all(cache.has(s) for s in segments),
          f"{len(asked)} sentences, {frames1} frames, {seconds1:.1f} s of audio")
    frames2, seconds2 = await play()
    check("second time: everything plays from the cache, no synthesis request", asked == segments and frames2 == frames1 and abs(seconds2 - seconds1) < 0.01,
          f"cache hits {agent.stats['cache_hits']}, live {agent.stats['live_segments']}")

    from apps.voice import piper_tts

    ok, why = piper_tts.available()
    if not ok:
        print(f"      local voice not checked: {why}", flush=True)
        return
    os.environ["CREDIT_SAVER"] = "1"  # with credit saver on, a sentence that is not cached goes to the local voice, never to Sarvam
    local = va.IntakeAgent(CallBrain(call, Services(call)), cache=speech.SpeechCache(pathlib.Path(tempfile.mkdtemp(prefix="ghante_tts_")), voice="none"))
    local.local_cache = speech.SpeechCache(pathlib.Path(tempfile.mkdtemp(prefix="ghante_tts_")), provider="piper", model="piper", voice=piper_tts.VOICE)
    sentence = "After the report, a surveyor from the insurance company will contact you."

    async def one():
        yield sentence

    t0 = time.perf_counter()
    first_at, frames, seconds = None, 0, 0.0
    async for frame in local.tts_node(one(), None):
        if first_at is None:
            first_at = time.perf_counter() - t0
        frames += 1
        seconds += frame.samples_per_channel / frame.sample_rate
    check("with credit saver on, an uncached sentence is spoken by the local voice", frames > 0 and seconds > 1.0 and local.local_cache.has(sentence),
          f"{piper_tts.VOICE}: {seconds:.1f} s of audio, first audio after {first_at or 0:.2f} s (includes loading the voice)")


def token_check() -> None:
    print("\n-- room token --", flush=True)
    from livekit import api as lkapi

    token = livekit_token.make_token("APItestkey", "s" * 40, identity="farmer-F0001", name="Ramlal Verma", room="case-case_0001-1",
                                     agent_name="intake", agent_metadata={"case_id": "case_0001", "call_id": "call_0001_1"})
    claims = lkapi.TokenVerifier("APItestkey", "s" * 40).verify(token)
    agents = list(claims.room_config.agents) if claims.room_config else []
    check("LiveKit's own verifier accepts our token and reads the agent dispatch",
          claims.identity == "farmer-F0001" and claims.video.room == "case-case_0001-1" and claims.video.room_join is True
          and len(agents) == 1 and agents[0].agent_name == "intake" and json.loads(agents[0].metadata)["case_id"] == "case_0001",
          f"identity {claims.identity}, room {claims.video.room}, agent {agents[0].agent_name if agents else '-'}")


async def run(services: u.Services) -> None:
    import importlib.metadata as md

    print(f"livekit-agents {md.version('livekit-agents')}, mcp {md.version('mcp')}", flush=True)
    ready = await wait_for(lambda: (http.get_json(f"{config.S1_URL}/health")["providers"]["head"]["detail"] == "ready"), 180)
    check("the decision service has its reply model loaded", ready)
    await happy_path(services)
    await two_answers(services)
    print("\n-- endings --", flush=True)
    await ending(services, "T2-06 asking for a person escalates and ends the call", ["Yes, speaking.", "I want to talk to a person"], "ESCALATED", "escalated")
    await ending(services, "T2-07 no damage ends the call with NO_DAMAGE", ["Yes, speaking.", "no, the crop is fine"], "NO_DAMAGE", "completed")
    await ending(services, "T2-08 wrong number ends the call", ["no, wrong number"], "ESCALATED", "wrong_person")
    await speech_cache()


def main() -> int:
    try:
        token_check()
    except Exception as e:  # noqa: BLE001
        check("room token check ran", False, f"{type(e).__name__}: {str(e)[:200]}")
    names = ["orchestrator", "registry", "weather", "mandi", "portal", "s1"] + (["filer"] if FILER_OK else [])
    print(f"Filer: {'will run from ' + u.filer_python() if FILER_OK else 'cannot run here (' + FILER_WHY + ')'}", flush=True)
    services = u.Services(*names)
    try:
        asyncio.run(run(services))
    except Exception as e:  # noqa: BLE001 - report every kind of failure in one line
        import traceback

        traceback.print_exc()
        check("voice text check ran to the end", False, f"{type(e).__name__}: {str(e)[:300]}")
    finally:
        services.close()
    ok = bool(results) and all(results)
    print(f"\n{sum(results)} of {len(results)} checks passed")
    print("VOICE TEXT CHECK PASSED" if ok else "VOICE TEXT CHECK FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
