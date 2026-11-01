"""Replay recorded events into a running orchestrator, so the dashboard can be built and tested without the real agents.

    python scripts/replay_events.py                       # data/fixtures/events_sample.jsonl at 1 event every 0.15 s
    python scripts/replay_events.py --file logs/events.jsonl --delay 0.05
    python scripts/replay_events.py --make-sample         # regenerate the sample file

The sample is synthetic and covers every event type in SystemDesign §7.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ghante_shared import config, http  # noqa: E402

SAMPLE = config.DATA_DIR / "fixtures" / "events_sample.jsonl"


def make_sample() -> list[dict]:
    farmers = json.loads((config.SEED_DIR / "farmers.json").read_text(encoding="utf-8"))
    scenario = json.loads(config.SCENARIO_PATH.read_text(encoding="utf-8"))
    storm = scenario["storm"]
    ev: list[dict] = []

    def add(type_, data, case_id=None, agent="system", live=False):
        ev.append({"type": type_, "data": data, "case_id": case_id, "agent": agent, "live": live})

    add("sim.clock", {"sim_ts": storm["started_at"], "paused": False, "speed": 180, "hours_left": 72.0})
    add("agent.started", {"summary": "watching weather for Sehore"}, agent="sentinel")
    add("mcp.tool_called", {"server": "weather", "tool": "list_storm_events", "args_summary": "district=Sehore", "ms": 38, "client": "sentinel"}, agent="sentinel")
    add("storm.detected", {"event_id": storm["id"], "type": storm["type"], "center": {"lat": storm["center_lat"], "lon": storm["center_lon"]},
                           "radius_km": storm["radius_km"], "villages": scenario["villages"]}, agent="sentinel")
    add("agent.finished", {"summary": "hailstorm over 12 villages", "seconds": 0.4, "ok": True}, agent="sentinel")
    add("mcp.tool_called", {"server": "registry", "tool": "list_farmers_in_villages", "args_summary": "village_ids=12", "ms": 21, "client": "dispatcher"}, agent="dispatcher")
    sample = farmers[::14][:24]  # the hero first, then farmers spread over all twelve villages
    intensity = {v["village_id"]: v for v in scenario["villages"]}
    for f in sample:
        cid = "case_" + f["id"][1:]
        add("case.created", {"farmer_id": f["id"], "village_id": f["village_id"], "lat": f["policy"]["plot_lat"], "lon": f["policy"]["plot_lon"],
                             "deadline_at": "2026-03-15T15:30:00+05:30", "is_hero": f["is_hero"]}, cid, "dispatcher", f["is_hero"])
    for f in sample:
        cid = "case_" + f["id"][1:]
        level = {"severe": "high", "moderate": "medium", "light": "low"}[intensity[f["village_id"]]["intensity"]]
        add("s1.decision", {"decision": "TRIAGE", "answers": {"damage_likelihood": {"value": level, "confidence": 0.78, "probs": {"high": 0.78, "medium": 0.1, "low": 0.12}}},
                            "provider": "laya", "model": "convaiinnovations/laya-multilingual", "latency_ms": 176, "fallback_from": None, "cached": False}, cid, "dispatcher", f["is_hero"])
        add("case.status_changed", {"from": "AFFECTED", "to": "QUEUED", "reason": "triaged"}, cid, "dispatcher", f["is_hero"])
    add("stats.updated", {"affected": 24, "queued": 24, "in_call": 0, "in_progress": 0, "filed": 0, "no_damage": 0, "escalated": 0, "ineligible": 0, "unreachable": 0, "failed": 0, "simulated": 23, "live": 1})
    hero = "case_0001"
    add("call.started", {"call_id": "call_0001_1", "attempt": 1}, hero, "dispatcher", True)
    add("case.status_changed", {"from": "QUEUED", "to": "CALLING", "reason": "hero call"}, hero, "dispatcher", True)
    add("case.status_changed", {"from": "CALLING", "to": "IN_CALL", "reason": "answered"}, hero, "intake", True)
    turns = [("agent", "Hello, am I speaking with Ramlal ji?", "scripted", None),
             ("farmer", "Yes, speaking.", "fast", ("identity_confirmed", True)),
             ("agent", "A hailstorm was recorded in your village this afternoon. Was your wheat crop damaged?", "scripted", None),
             ("farmer", "Yes, the hail flattened more than half the crop.", "llm", ("damage_pct", 70))]
    for speaker, text, path, slot in turns:
        if speaker == "farmer":
            add("s1.decision", {"decision": "ROUTE", "answers": {"intent": {"value": "yes" if path == "fast" else "gives_details", "confidence": 0.74, "probs": {}}},
                                "provider": "head", "model": "intfloat/multilingual-e5-small", "latency_ms": 19, "fallback_from": None, "cached": False}, hero, "intake", True)
        add("call.turn", {"speaker": speaker, "text": text, "path": path,
                          "latency_ms": {"stt": 180, "s1": 19, "llm_ttft": 0 if path != "llm" else 420, "tts_ttfb": 90, "total": 300 if path != "llm" else 720}}, hero, "intake", True)
        if slot:
            add("call.slot", {"slot": slot[0], "value": slot[1]}, hero, "intake", True)
    add("s1.decision", {"decision": "PERIL", "answers": {"peril": {"value": "hailstorm", "confidence": 0.81, "probs": {}}}, "provider": "head",
                        "model": "intfloat/multilingual-e5-small", "latency_ms": 18, "fallback_from": None, "cached": False}, hero, "intake", True)
    add("call.slot", {"slot": "peril", "value": "hailstorm"}, hero, "intake", True)
    add("case.status_changed", {"from": "IN_CALL", "to": "EVIDENCE", "reason": "slots collected"}, hero, "intake", True)
    add("evidence.received", {"evidence_id": "ev_0001", "edge_label": "hail_damage", "edge_confidence": 0.82, "edge_latency_ms": 41, "lat": 23.0272,
                              "lon": 76.7317, "captured_offline": False, "thumb_url": None}, hero, "evidence", True)
    add("case.status_changed", {"from": "EVIDENCE", "to": "PROCESSING", "reason": "photo and consent"}, hero, "evidence", True)
    for agent, summary in (("evidence", "weather record matches: hail at this location, 15:30"), ("eligibility", "eligible: policy active, peril covered, inside 72 hours")):
        add("agent.started", {"summary": agent}, hero, agent, True)
        if agent == "evidence":
            add("mcp.tool_called", {"server": "weather", "tool": "get_weather_at", "args_summary": "lat=23.0272, lon=76.7317", "ms": 31, "client": "evidence"}, hero, agent, True)
        else:
            add("s1.decision", {"decision": "VERIFY", "answers": {"evidence_consistent": {"value": True, "confidence": 0.88}},
                                "provider": "laya", "model": "convaiinnovations/laya-multilingual", "latency_ms": 310, "fallback_from": None, "cached": False}, hero, agent, True)
        add("agent.finished", {"summary": summary, "seconds": 0.6, "ok": True}, hero, agent, True)
    add("case.status_changed", {"from": "PROCESSING", "to": "FILING", "reason": "eligible"}, hero, "eligibility", True)
    add("agent.started", {"summary": "filling the sandbox portal form"}, hero, "filing", True)
    for n, field in enumerate(["application_no", "farmer_name", "crop", "loss_date", "cause_of_loss", "damage_pct", "photo", "declaration", "submit"], start=1):
        add("filing.step", {"n": n, "action": "click" if field == "submit" else "fill", "field": field, "mode": "agent", "screenshot_url": None}, hero, "filing", True)
    add("agent.finished", {"summary": "form submitted", "seconds": 48.2, "ok": True}, hero, "filing", True)
    add("claim.filed", {"claim_ref": "FCS-000007", "filing_mode": "agent", "seconds": 48.2, "time_to_file_s": 160}, hero, "followup", True)
    add("case.status_changed", {"from": "FILING", "to": "FILED", "reason": "reference received"}, hero, "followup", True)
    outcomes = ["FILED"] * 15 + ["NO_DAMAGE", "ESCALATED", "UNREACHABLE", "INELIGIBLE", "FILED", "FILED", "FILED", "FILED"]
    for f, outcome in zip(sample[1:], outcomes):
        cid = "case_" + f["id"][1:]
        add("case.status_changed", {"from": "QUEUED", "to": "CALLING", "reason": "dispatch"}, cid, "dispatcher")
        if outcome == "UNREACHABLE":
            add("case.status_changed", {"from": "CALLING", "to": "NO_ANSWER", "reason": "no answer"}, cid, "dispatcher")
            add("case.status_changed", {"from": "NO_ANSWER", "to": "UNREACHABLE", "reason": "three attempts"}, cid, "dispatcher")
            continue
        add("case.status_changed", {"from": "CALLING", "to": "IN_CALL", "reason": "answered"}, cid, "intake")
        if outcome in ("NO_DAMAGE", "ESCALATED"):
            add("case.status_changed", {"from": "IN_CALL", "to": outcome, "reason": "persona"}, cid, "intake")
            continue
        add("case.status_changed", {"from": "IN_CALL", "to": "EVIDENCE", "reason": "slots collected"}, cid, "intake")
        add("case.status_changed", {"from": "EVIDENCE", "to": "PROCESSING", "reason": "photo and consent"}, cid, "evidence")
        if outcome == "INELIGIBLE":
            add("case.status_changed", {"from": "PROCESSING", "to": "INELIGIBLE", "reason": "policy not active"}, cid, "eligibility")
            continue
        add("case.status_changed", {"from": "PROCESSING", "to": "FILING", "reason": "eligible"}, cid, "eligibility")
        add("case.status_changed", {"from": "FILING", "to": "FILED", "reason": "reference received"}, cid, "followup")
    add("fallback.used", {"component": "filer", "from": "agent", "to": "scripted", "reason": "sample event"})
    add("stats.updated", {"affected": 24, "queued": 0, "in_call": 0, "in_progress": 0, "filed": 20, "no_damage": 1, "escalated": 1, "ineligible": 1, "unreachable": 1, "failed": 0, "simulated": 23, "live": 1})
    add("sim.clock", {"sim_ts": "2026-03-12T19:30:00+05:30", "paused": True, "speed": 180, "hours_left": 68.0})
    return ev


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=str(SAMPLE))
    ap.add_argument("--delay", type=float, default=0.15, help="seconds between events")
    ap.add_argument("--make-sample", action="store_true")
    args = ap.parse_args()
    if args.make_sample:
        events = make_sample()
        SAMPLE.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8", newline="\n")
        print(f"wrote {len(events)} sample events, types: {sorted({e['type'] for e in events})}")
        return 0
    lines = [json.loads(line) for line in pathlib.Path(args.file).read_text(encoding="utf-8").splitlines() if line.strip()]
    sent = 0
    for e in lines:
        if e.get("type") == "snapshot":
            continue
        try:
            http.post_json(f"{config.ORCH_URL}/internal/events", {k: e.get(k) for k in ("type", "data", "case_id", "agent", "live")}, timeout=5)
            sent += 1
        except Exception as ex:
            print(f"orchestrator not reachable at {config.ORCH_URL}: {type(ex).__name__}. Start it with: python scripts/dev.py --only orchestrator")
            return 1
        time.sleep(args.delay)
    print(f"replayed {sent} events")
    return 0


if __name__ == "__main__":
    sys.exit(main())
