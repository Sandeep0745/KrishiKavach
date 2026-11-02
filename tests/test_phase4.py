"""Gate G4 automated tests (context/Testing.md §6). Run:  python -m unittest tests.test_phase4 -v

The district run with the test decision provider and a scripted hero (HERO_SIM=1): detection, ranking, calling with a limit
and retries, the final totals, real records in the portal, determinism, pause and resume, and the dashboard during a run.
"""
from __future__ import annotations

import asyncio
import collections
import datetime as dt
import json
import pathlib
import time
import unittest

from apps.orchestrator import dispatcher as dispatcher_mod
from apps.orchestrator import simulator as simulator_mod
from apps.orchestrator.clock import SimClock
from tests import _util as u

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOTALS = {"filed": 312, "unreachable": 11, "no_damage": 9, "escalated": 5, "ineligible": 3, "failed": 0}
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


class T4_Pieces(unittest.TestCase):
    def test_priority_from_a_triage_answer(self):
        self.assertEqual(dispatcher_mod.priority_of({"value": "high", "confidence": 0.9, "probs": {"high": 0.9, "medium": 0.05, "low": 0.05}}), 92.5)
        self.assertEqual(dispatcher_mod.priority_of({"value": "medium", "confidence": 0.8}), 40.0)
        self.assertIsNone(dispatcher_mod.priority_of(None))

    def test_calling_hours(self):
        window = {"from": "08:00", "to": "20:00"}
        at = lambda h, m: dt.datetime(2026, 3, 12, h, m, tzinfo=IST)  # noqa: E731
        self.assertTrue(dispatcher_mod.in_calling_hours(at(16, 0), window))
        self.assertTrue(dispatcher_mod.in_calling_hours(at(19, 59), window))
        self.assertFalse(dispatcher_mod.in_calling_hours(at(20, 0), window))
        self.assertFalse(dispatcher_mod.in_calling_hours(at(7, 59), window))
        self.assertEqual(dispatcher_mod.next_opening(at(20, 5), window), dt.datetime(2026, 3, 13, 8, 0, tzinfo=IST))
        self.assertEqual(dispatcher_mod.next_opening(at(6, 0), window), at(8, 0))

    def test_personas(self):
        self.assertFalse(simulator_mod.answers_on({"outcome": "no_answer", "answer_on_attempt": 0}, 3))
        self.assertEqual([simulator_mod.answers_on({"outcome": "files", "answer_on_attempt": 2}, n) for n in (1, 2, 3)], [False, True, True])
        self.assertEqual((simulator_mod.peril_of("A lot of hail came down"), simulator_mod.peril_of("Insects attacked the crop")), ("hailstorm", "not_covered"))
        farmers = json.loads((ROOT / "data" / "seed" / "farmers.json").read_text(encoding="utf-8"))
        outcomes = collections.Counter((f["sim"] or {}).get("outcome", "hero") for f in farmers)
        self.assertEqual(dict(outcomes), {"hero": 1, "files": 311, "no_answer": 11, "no_damage": 9, "wants_human": 5, "lapsed": 2, "pest": 1})

    def test_clock_runs_pauses_jumps_and_waits(self):
        async def run():
            clock = SimClock("2026-03-12T15:30:00+05:30", speed=600)
            clock.jump_to(dt.datetime(2026, 3, 12, 15, 50, tzinfo=IST))
            self.assertEqual(clock.now_iso(), "2026-03-12T15:50:00+05:30")
            t0 = time.monotonic()
            waiter = asyncio.create_task(clock.sleep(60))          # one scenario minute = 0.1 s at this speed
            await asyncio.sleep(0.3)
            self.assertFalse(waiter.done(), "a paused clock does not move, so nothing that waits on it finishes")
            clock.resume()
            await waiter
            took = time.monotonic() - t0
            self.assertTrue(0.38 <= took <= 0.9, took)
            clock.pause()
            frozen = clock.now()
            await asyncio.sleep(0.1)
            self.assertEqual(clock.now(), frozen)
            clock.set_speed(6000)
            clock.resume()
            await clock.sleep(600)
            self.assertLess(time.monotonic() - t0, 2.0)
            clock.reset()
            self.assertEqual((clock.now_iso(), clock.speed, clock.paused), ("2026-03-12T15:30:00+05:30", 600, True))

        asyncio.run(run())

    def test_weather_record_covers_every_seeded_farm(self):
        """A farm of an outer village lies just outside the storm's circle; the footprint includes the listed villages' land."""
        from mcp_servers import weather

        farmers = json.loads((ROOT / "data" / "seed" / "farmers.json").read_text(encoding="utf-8"))
        dry = [f["id"] for f in farmers if not weather.get_weather_at(f["policy"]["plot_lat"], f["policy"]["plot_lon"], "2026-03-12T15:30:00+05:30")["hail"]]
        self.assertEqual(dry, [])
        self.assertFalse(weather.get_weather_at(23.5, 77.4, "2026-03-12T15:30:00+05:30")["hail"], "Bhopal had no hail")
        self.assertFalse(weather.get_weather_at(23.02, 76.72, "2026-03-12T20:00:00+05:30")["hail"], "nor did the core, hours later")


class FleetCase(unittest.TestCase):
    ENV: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.s = u.Services("orchestrator", "portal", "weather", "registry", "mandi", "s1", S1_CHAIN_TEXT="mock", S1_CHAIN_REPORT="mock",
                           MAX_PARALLEL_CALLS="8", SIM_SPEED="180", S1_SIM_CACHE="1", **cls.ENV)  # set here: a machine's .env may say otherwise
        cls.addClassCleanup(cls.s.close)

    def api(self, method: str, path: str, payload: dict | None = None):
        return u.call(method, u.url("orchestrator", path), payload, timeout=30)

    def reset(self) -> None:
        self.assertEqual(self.api("POST", "/api/scenario/reset", {})[0], 200)
        self.mark = len(self.s.events())

    def events(self, type_: str | None = None) -> list[dict]:
        return [e for e in self.s.events()[self.mark:] if type_ is None or e["type"] == type_]

    def state(self) -> dict:
        return self.api("GET", "/api/state")[1]

    def wait_for(self, predicate, seconds: float, what: str) -> dict:
        deadline = time.time() + seconds
        while time.time() < deadline:
            st = self.state()
            if predicate(st):
                return st
            time.sleep(0.25)
        self.fail(f"timed out waiting for {what}: {json.dumps(self.state()['scenario'])}")


class T4_Fleet(FleetCase):
    ENV = {"HERO_SIM": "1"}

    def ranked_queue(self) -> dict:
        """Start with the clock almost standing still, so every case is ranked before the first call goes out."""
        self.reset()
        status, out = self.api("POST", "/api/scenario/start", {"speed": 0.01})
        self.assertEqual(status, 200, out)
        self.wait_for(lambda st: st["scenario"].get("triage_done"), 60, "all cases ranked")
        return self.api("GET", "/api/queue")[1]

    def run_to_the_end(self, speed: float = 300) -> dict:
        self.assertEqual(self.api("POST", "/api/scenario/resume", {"speed": speed})[0], 200)
        return self.wait_for(lambda st: st["scenario"]["state"] == "finished", 240, "the scenario to finish")

    def test_T4_01_to_T4_06_one_full_run_and_a_second_one(self):
        # ---- T4-01 detection and cases ----
        queue = self.ranked_queue()
        st = self.state()
        self.assertEqual(self.api("POST", "/api/scenario/start", {})[0], 409, "a second start is refused")
        detected = self.events("storm.detected")
        self.assertEqual(len(detected), 1)
        self.assertEqual((len(detected[0]["data"]["villages"]), detected[0]["agent"], detected[0]["data"]["type"]), (12, "sentinel", "hailstorm"))
        self.assertEqual(len(st["cases"]), 340)
        self.assertEqual({c["deadline_at"] for c in st["cases"]}, {"2026-03-15T15:30:00+05:30"}, "storm time plus 72 hours")
        self.assertEqual(len(self.events("case.created")), 340)
        tools = collections.Counter((e["data"]["server"], e["data"]["tool"], e["data"]["client"]) for e in self.events("mcp.tool_called"))
        self.assertEqual(tools[("weather", "list_storm_events", "sentinel")], 1)
        self.assertEqual(tools[("registry", "list_farmers_in_villages", "dispatcher")], 12)
        self.assertEqual(st["clock"]["sim_ts"][:16], "2026-03-12T15:50", "the run starts at the detection time")

        # ---- T4-02 triage and queue order ----
        time.sleep(0.5)
        triage = [e for e in self.events("s1.decision") if e["data"]["decision"] == "TRIAGE"]
        self.assertEqual(len(triage), 340)
        self.assertEqual(len({e["case_id"] for e in triage}), 340)
        self.assertEqual((queue["triaged"], queue["total"], len(queue["queue"]), queue["called"]), (340, 340, 340, []))
        order = [(q["priority"], -q["distance_km"]) for q in queue["queue"]]
        self.assertEqual(order, sorted(order, reverse=True), "highest priority first; nearer the storm core first among equals")
        priority = {c["id"]: c["priority"] for c in st["cases"]}
        village = {c["id"]: c["village_id"] for c in st["cases"]}
        intensity = {v["village_id"]: v["intensity"] for v in detected[0]["data"]["villages"]}
        mean = lambda kind: sum(p for cid, p in priority.items() if intensity[village[cid]] == kind) / sum(1 for cid in priority if intensity[village[cid]] == kind)  # noqa: E731
        self.assertGreater(mean("severe"), mean("moderate"))
        self.assertGreater(mean("moderate"), mean("light"))
        self.assertTrue(all(c["status"] == "QUEUED" for c in st["cases"]))
        first_20 = [q["case_id"] for q in queue["queue"][:20]]

        # ---- the run ----
        final = self.run_to_the_end()
        time.sleep(1.0)
        events = self.events()

        # ---- T4-03 concurrency and retries ----
        on_call: set[str] = set()
        most = 0
        for e in events:
            if e["type"] == "case.status_changed":
                (on_call.add if e["data"]["to"] in ("CALLING", "IN_CALL") else on_call.discard)(e["case_id"])
                most = max(most, len(on_call))
        self.assertEqual(most, 8, "the limit is reached and never passed")
        self.assertEqual(final["scenario"]["max_on_call_seen"], 8)
        farmers = {f["id"]: f for f in json.loads((ROOT / "data" / "seed" / "farmers.json").read_text(encoding="utf-8"))}
        cases = {c["id"]: c for c in final["cases"]}
        for c in cases.values():
            persona = farmers[c["farmer_id"]]["sim"]
            if persona and persona["outcome"] == "no_answer":
                self.assertEqual((c["status"], c["attempts"]), ("UNREACHABLE", 3), c["id"])
            elif persona and persona["outcome"] == "files":
                self.assertEqual((c["status"], c["attempts"]), ("FILED", persona["answer_on_attempt"]), c["id"])
        calls = collections.Counter(e["data"]["outcome"] for e in events if e["type"] == "call.ended")
        self.assertEqual(calls["no_answer"], 11 * 3 + 40 * 1 + 10 * 2)
        self.assertEqual(sum(calls.values()), sum(c["attempts"] for c in cases.values()))

        # ---- T4-04 totals ----
        self.assertEqual({k: final["stats"][k] for k in TOTALS}, TOTALS)
        self.assertEqual((final["stats"]["affected"], final["stats"]["queued"], final["stats"]["in_call"], final["stats"]["in_progress"]), (340, 0, 0, 0))
        finished = [e for e in events if e["type"] == "scenario.finished"]
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0]["data"]["totals"], TOTALS)
        self.assertTrue(final["clock"]["paused"], "the clock stops with the last case, so the hours left stay on screen")
        reasons = collections.Counter(e["data"]["reason"] for e in events if e["type"] == "case.status_changed" and e["data"]["to"] == "INELIGIBLE")
        self.assertEqual(reasons["Policy not active"], 2)
        self.assertEqual(sum(reasons.values()), 3)

        # ---- T4-05 real records ----
        self.assertEqual(u.call("GET", u.url("portal", "/api/claims/count"))[1]["claims"], 312)
        refs = [c["claim_ref"] for c in cases.values() if c["status"] == "FILED"]
        self.assertEqual(len(set(refs)), 312)
        for ref in refs:
            status, record = u.call("GET", u.url("portal", f"/api/claims/{ref}"))
            self.assertEqual((status, record["submitted_via"]), (200, "api"), ref)
        self.assertEqual(len([e for e in events if e["type"] == "claim.filed"]), 312)
        self.assertEqual([e for e in events if e["type"] == "filing.step"], [], "no browser and no LLM for simulated farmers")
        self.assertEqual([e["data"] for e in events if e["type"] == "fallback.used"], [])
        verify = [e for e in events if e["type"] == "s1.decision" and e["data"]["decision"] == "VERIFY"]
        self.assertEqual(len(verify), 312 - 0, "one second opinion for every case the rules passed")
        self.assertGreater(sum(1 for e in verify if e["data"]["cached"]), 250, "identical reports are computed once")
        triage_cached = sum(1 for e in triage if e["data"]["cached"])
        self.assertTrue(150 <= triage_cached <= 300, f"{triage_cached} of 340 rankings were repeats; the rest were computed in this run, not remembered from an earlier one")
        self.assertFalse(any(e["type"] == "call.turn" for e in events))

        # ---- T4-06 determinism ----
        again = self.ranked_queue()
        self.assertEqual([q["case_id"] for q in again["queue"][:20]], first_20)
        second = self.run_to_the_end()
        self.assertEqual({k: second["stats"][k] for k in TOTALS}, TOTALS)
        self.assertEqual({c["id"]: (c["status"], c["attempts"]) for c in second["cases"]}, {c["id"]: (c["status"], c["attempts"]) for c in cases.values()})

    def test_T4_07_pause_freezes_the_fleet_and_resume_continues(self):
        self.reset()
        self.assertEqual(self.api("POST", "/api/scenario/start", {"speed": 240})[0], 200)
        self.wait_for(lambda st: st["stats"]["filed"] >= 15, 90, "some cases to be filed")
        self.assertEqual(self.api("POST", "/api/scenario/pause", {})[1]["state"], "paused")
        time.sleep(1.0)  # cases inside a pipeline step finish that step
        before = self.state()
        mark = len(self.s.events())
        time.sleep(2.0)
        after = self.state()
        self.assertEqual({c["id"]: c["status"] for c in after["cases"]}, {c["id"]: c["status"] for c in before["cases"]})
        self.assertEqual(after["clock"]["sim_ts"], before["clock"]["sim_ts"])
        self.assertEqual((after["scenario"]["state"], after["scenario"]["paused_by"]), ("paused", "presenter"))
        quiet = [e["type"] for e in self.s.events()[mark:] if e["type"] in ("case.status_changed", "call.started", "claim.filed", "s1.decision")]
        self.assertEqual(quiet, [], "nothing happens to the simulated farmers while paused")
        self.assertEqual(self.api("POST", "/api/scenario/resume", {"speed": 300})[1]["state"], "running")
        final = self.wait_for(lambda st: st["scenario"]["state"] == "finished", 240, "the scenario to finish after the pause")
        self.assertEqual({k: final["stats"][k] for k in TOTALS}, TOTALS)

    def test_T4_08_dashboard_shows_the_run(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed here; do the manual checks T4-08 to T4-10 instead")
        self.reset()
        with sync_playwright() as p:
            try:
                browser = u.launch_chromium(p)
            except Exception as e:
                self.skipTest(f"no browser for Playwright: {type(e).__name__}")
            page = browser.new_page(viewport={"width": 1600, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(u.url("orchestrator", "/"))
            page.wait_for_function("document.getElementById('conn').textContent === 'connected'", timeout=10000)
            self.assertEqual(page.locator("#map .dot.g-idle").count(), 340, "every insured farm is on the map before the storm")
            self.assertEqual(page.inner_text("#truth"), "Simulated farmers: 0. Live: 0.")
            self.assertTrue(page.locator("#btn-pause").is_disabled())
            page.keyboard.press("s")
            page.wait_for_function("document.querySelectorAll('#map .dot.g-done').length >= 40", timeout=60000)
            self.assertTrue(page.locator("#btn-start").is_disabled())
            self.assertEqual(page.locator("#map .dot").count(), 340)
            self.assertEqual(page.locator("#map .dot.g-idle").count(), 0)
            page.keyboard.press("p")
            page.wait_for_function("document.getElementById('btn-pause').textContent === 'Resume'", timeout=5000)
            self.assertEqual(page.inner_text("#runstate"), "Paused. Press P to resume.")
            time.sleep(1.2)
            # T4-08: the counters on screen equal the server's state
            st = self.state()
            legend = {row.get_attribute("data-key"): int(row.locator(".n").inner_text()) for row in page.locator("#legend li").all()}
            s = st["stats"]
            self.assertEqual(legend, {"total": 340, "wait": s["queued"], "call": s["in_call"], "work": s["in_progress"], "done": s["filed"], "human": s["escalated"],
                                      "nodamage": s["no_damage"], "unreach": s["unreachable"], "inelig": s["ineligible"], "failed": s["failed"]})
            self.assertEqual(page.inner_text("#truth"), "Simulated farmers: 340. Live: 0.", "in this headless run the hero is simulated too, and shown as such")
            self.assertTrue(page.locator("#hero").is_hidden())
            self.assertRegex(page.inner_text("#s1-count"), r"made, median \d+ ms")
            self.assertGreater(page.locator("#ticker li").count(), 10)
            self.assertGreater(page.locator("#mcp li").count(), 10)
            import os

            if os.environ.get("GHANTE_SHOT"):
                page.screenshot(path=os.environ["GHANTE_SHOT"])
            page.keyboard.press("p")
            page.wait_for_function("document.getElementById('banner').hidden === false", timeout=120000)
            self.assertRegex(page.inner_text("#banner"), r"^312 of 340 claims filed\. \d+ hours left\. 16 need follow-up\.$")
            self.assertEqual(page.locator("#map .dot.g-done").count(), 312)
            self.assertTrue(page.locator("#btn-pause").is_disabled())
            size = page.evaluate("[document.documentElement.scrollWidth, innerWidth, document.documentElement.scrollHeight, innerHeight]")
            self.assertEqual((size[0], size[2]), (size[1], size[3]), "the dashboard fits one screen")
            if os.environ.get("GHANTE_SHOT"):
                page.screenshot(path=os.environ["GHANTE_SHOT"].replace(".png", "-end.png"))
            # T4-11: reset gives a clean state quickly
            t0 = time.time()
            page.click("#btn-reset")
            page.click("#btn-reset")
            page.wait_for_function("document.querySelectorAll('#map .dot.g-idle').length === 340", timeout=10000)
            self.assertLess(time.time() - t0, 10)
            self.assertFalse(page.locator("#btn-start").is_disabled())
            self.assertEqual(errors, [])
            browser.close()


class T4_LiveHero(FleetCase):
    """Without HERO_SIM the live farmer is ranked with the others but never called by the Dispatcher."""
    ENV = {"HERO_SIM": "0", "LIVEKIT_URL": "wss://example.invalid", "LIVEKIT_API_KEY": "testkey", "LIVEKIT_API_SECRET": "s" * 40, "RING_TIMEOUT_S": "1.0"}

    def test_fleet_finishes_around_the_live_farmer_and_the_hero_call_pauses_it(self):
        self.reset()
        self.assertEqual(self.api("POST", "/api/scenario/start", {"speed": 300})[0], 200)
        self.wait_for(lambda st: st["stats"]["filed"] >= 5, 90, "the first filings")
        # the presenter rings the live farmer: the simulated farmers freeze
        status, ring = self.api("POST", "/api/hero/call", {})
        self.assertEqual(status, 200, ring)
        st = self.state()
        self.assertEqual((st["scenario"]["state"], st["scenario"]["paused_by"], st["clock"]["paused"]), ("paused", "live call", True))
        time.sleep(1.6)  # nobody answers in this test: the ring times out, and the fleet stays paused until the presenter resumes it
        st = self.state()
        hero = next(c for c in st["cases"] if c["is_hero"])
        self.assertEqual((hero["status"], st["scenario"]["state"]), ("NO_ANSWER", "paused"))
        self.assertEqual(self.api("POST", "/api/scenario/resume", {})[1]["state"], "running")
        st = self.wait_for(lambda st: st["scenario"].get("fleet_finished"), 240, "the simulated farmers to be settled")
        hero = next(c for c in st["cases"] if c["is_hero"])
        self.assertEqual(hero["status"], "NO_ANSWER", "the Dispatcher leaves the live farmer to the presenter")
        self.assertEqual((st["scenario"]["state"], st["scenario"]["paused_by"]), ("paused", "fleet finished"))
        self.assertEqual({k: st["stats"][k] for k in TOTALS}, {**TOTALS, "filed": 311})
        self.assertEqual(st["stats"]["queued"], 1)
        triage = [e for e in self.events("s1.decision") if e["data"]["decision"] == "TRIAGE"]
        self.assertEqual([e["case_id"] for e in triage if e["live"]], [hero["id"]], "only the live farmer's ranking is marked live")
        self.assertEqual(self.events("scenario.finished"), [], "not finished while the live case is open")


if __name__ == "__main__":
    unittest.main()
