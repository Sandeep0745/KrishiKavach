"""Start the whole backend, exercise it once with the real decision models, and stop it. Used at the end of Gate G1.

    python scripts/live_check.py            # real providers (loads the models: the first run can take a few minutes)
    python scripts/live_check.py --mock     # test provider, to check the wiring only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ghante_shared import config, http, mcp_client  # noqa: E402

HEALTH = {"orchestrator": config.ORCH_URL, "portal": config.PORTAL_URL, "mcp weather": config.MCP_WEATHER_URL.rsplit("/", 1)[0],
          "mcp registry": config.MCP_REGISTRY_URL.rsplit("/", 1)[0], "mcp mandi": config.MCP_MANDI_URL.rsplit("/", 1)[0], "decision service": config.S1_URL}


def wait_up(seconds: float = 90) -> list[str]:
    deadline, down = time.time() + seconds, list(HEALTH)
    while down and time.time() < deadline:
        for name in list(down):
            try:
                http.get_json(HEALTH[name] + "/health", timeout=2)
                down.remove(name)
            except Exception:
                pass
        time.sleep(0.5)
    return down


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()
    env = dict(os.environ, PYTHONUTF8="1")
    if args.mock:
        env.update(S1_CHAIN_TEXT="mock", S1_CHAIN_REPORT="mock")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    dev = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "dev.py")], cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, creationflags=flags)
    failures = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)

    try:
        down = wait_up()
        check("all six services start", not down, "down: " + ", ".join(down) if down else "")
        if down:
            return 1
        http.post_json(f"{config.ORCH_URL}/api/scenario/reset", {})
        case = http.post_json(f"{config.ORCH_URL}/api/cases", {"farmer_id": "F0001"})
        check("hero case opens", case["status"] == "AFFECTED" and case["farmer"]["name"] == "Ramlal Verma", case["id"])

        async def mcp_part():
            w = await mcp_client.call_tool(config.MCP_WEATHER_URL, "get_weather_at", {"lat": case["policy"]["plot_lat"], "lon": case["policy"]["plot_lon"],
                                           "at": "2026-03-12T15:30:00+05:30"}, server="weather", client="evidence", case_id=case["id"])
            s = await mcp_client.call_tool(config.MCP_REGISTRY_URL, "update_case_slots", {"case_id": case["id"], "slots": {"damage_confirmed": True}},
                                           server="registry", client="intake", case_id=case["id"])
            m = await mcp_client.call_tool(config.MCP_MANDI_URL, "get_price", {"crop": "wheat", "district": "Sehore"}, server="mandi", client="evidence")
            return w, s, m

        w, s, m = asyncio.run(mcp_part())
        check("weather MCP says hail at the hero's plot", w.get("hail") is True)
        check("registry MCP saves a slot through the orchestrator", s.get("slots", {}).get("damage_confirmed") is True)
        check("mandi MCP returns a price", m.get("modal_price_inr_per_quintal", 0) > 0)

        def decide(decision: str, state: dict) -> dict:
            return http.post_json(f"{config.S1_URL}/decide", {"decision": decision, "state": state, "case_id": case["id"], "live": True}, timeout=900)

        t0 = time.time()
        r = decide("ROUTE", {"agent_question": "Was your wheat crop damaged?", "utterance": "Yes, there is a lot of damage."})
        first_route_s = time.time() - t0
        r = decide("ROUTE", {"agent_question": "Was your wheat crop damaged?", "utterance": "Yes, there is a lot of damage."})
        check("ROUTE answers yes", r["answers"]["intent"]["value"] == "yes",
              f"provider {r['provider']}, confidence {r['answers']['intent']['confidence']}, {r['latency_ms']} ms; first call incl. model load {first_route_s:.0f} s")
        r = decide("PERIL", {"cause_text": "Hail fell, the wheat is completely flattened."})
        check("PERIL answers hailstorm", r["answers"]["peril"]["value"] == "hailstorm", f"provider {r['provider']}, {r['latency_ms']} ms")
        t0 = time.time()
        decide("TRIAGE", {"hail_intensity": "severe", "distance_km": 1.4, "crop": "wheat", "crop_stage": "close to harvest"})
        first_triage_s = time.time() - t0
        r = decide("TRIAGE", {"hail_intensity": "severe", "distance_km": 1.4, "crop": "wheat", "crop_stage": "close to harvest"})
        check("TRIAGE answers high for severe hail near the core", r["answers"]["damage_likelihood"]["value"] == "high",
              f"provider {r['provider']}, {r['latency_ms']} ms; first call incl. model load {first_triage_s:.0f} s")
        r2 = decide("TRIAGE", {"hail_intensity": "light", "distance_km": 13.3, "crop": "wheat", "crop_stage": "close to harvest"})
        check("TRIAGE answers low for light hail far away", r2["answers"]["damage_likelihood"]["value"] == "low", f"{r2['latency_ms']} ms")
        v = decide("VERIFY", {"peril": "hailstorm", "damage_pct": 70, "edge_label": "hail_damage", "edge_confidence": 0.82, "hail": True,
                              "precipitation_mm": 24, "wind_gust_kmh": 78, "distance_from_plot_m": 120, "minutes_from_storm": 5})
        check("VERIFY finds a consistent case consistent", v["answers"]["evidence_consistent"]["value"] is True,
              f"provider {v['provider']}, confidence {v['answers']['evidence_consistent']['confidence']}, {v['latency_ms']} ms")
        v2 = decide("VERIFY", {"peril": "hailstorm", "damage_pct": 80, "edge_label": "healthy", "edge_confidence": 0.85, "hail": True,
                               "precipitation_mm": 24, "wind_gust_kmh": 78, "distance_from_plot_m": 120, "minutes_from_storm": 5})
        check("VERIFY finds a healthy photo inconsistent with an 80 percent damage statement", v2["answers"]["evidence_consistent"]["value"] is False,
              f"confidence {v2['answers']['evidence_consistent']['confidence']}, {v2['latency_ms']} ms")
        time.sleep(1)
        events = [json.loads(line) for line in config.EVENTS_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
        types = {e["type"] for e in events}
        need = {"case.created", "call.slot", "mcp.tool_called", "s1.decision", "stats.updated"}
        check("events reach logs/events.jsonl", need <= types, "missing: " + ", ".join(sorted(need - types)) if not need <= types else f"{len(events)} events")
        live = [e for e in events if e["type"] == "s1.decision"]
        check("decision events are marked live for the hero case", bool(live) and all(e["live"] for e in live))
        claim = http.post_json(f"{config.PORTAL_URL}/api/claims", {
            "application_no": "APP-SEH-000451", "farmer_name": "Ramlal Verma", "mobile": "+91 00000 00451", "state": "Madhya Pradesh", "district": "Sehore",
            "tehsil": "Ashta", "village": "Khajuriya Kalan", "season": "Rabi 2025-26", "crop": "Wheat", "khasra_no": "214", "insured_area_ha": "1.8",
            "loss_date": "2026-03-12", "loss_time": "15:30", "cause_of_loss": "Hailstorm", "crop_stage": "Standing crop", "affected_area_ha": "1.26",
            "damage_pct": "70", "remarks": "live check", "submitted_by": "Authorised assistant (on behalf of farmer)", "declaration": True})
        import urllib.request
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"{config.ORCH_URL}/", timeout=5) as r:
            page = r.read().decode("utf-8")
        with opener.open(f"{config.ORCH_URL}/static/app.js", timeout=5) as r:
            script_ok = r.status == 200
        check("dashboard page and its script are served", "72 Ghante" in page and script_ok, f"{config.ORCH_URL}/")
        check("sandbox portal accepts a claim", claim["reference"].startswith("FCS-"), claim["reference"])
        out = http.post_json(f"{config.ORCH_URL}/api/scenario/reset", {})
        check("reset clears cases and the portal", out["portal_reset"] and http.get_json(f"{config.PORTAL_URL}/api/claims/count")["claims"] == 0)
    except Exception as e:
        check("live check ran to the end", False, f"{type(e).__name__}: {str(e)[:200]}")
    finally:
        try:
            dev.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
            dev.wait(timeout=25)
        except Exception:
            dev.kill()
    print(f"\nLIVE CHECK {'PASSED' if failures == 0 else f'FAILED ({failures})'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
