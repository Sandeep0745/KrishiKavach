"""Gate G1 automated tests (context/Testing.md §3). Run from the project root:

    python -m unittest tests.test_phase1 -v
"""
from __future__ import annotations

import asyncio
import collections
import http.client
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest

from tests import _util as u

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HERO = {"application_no": "APP-SEH-000451", "farmer_name": "Ramlal Verma", "mobile": "+91 00000 00451", "state": "Madhya Pradesh",
        "district": "Sehore", "tehsil": "Ashta", "village": "Khajuriya Kalan"}
LOSS = {"season": "Rabi 2025-26", "crop": "Wheat", "khasra_no": "214", "insured_area_ha": "1.8", "loss_date": "2026-03-12", "loss_time": "15:30",
        "cause_of_loss": "Hailstorm", "crop_stage": "Standing crop", "affected_area_ha": "1.26", "damage_pct": "70", "remarks": "Test report"}
FINAL = {"gps_lat": "23.0272", "gps_lon": "76.7317", "submitted_by": "Authorised assistant (on behalf of farmer)", "declaration": "on"}
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


class T1_01_Seed(unittest.TestCase):
    def run_seed(self, tmp: str) -> dict:
        import shutil

        work = pathlib.Path(tmp) / "data"
        shutil.copytree(ROOT / "data", work)
        env = dict(os.environ, GHANTE_VAR_DIR=str(pathlib.Path(tmp) / "var"), PYTHONUTF8="1")
        code = ("import sys, json; sys.path.insert(0, r'%s'); sys.argv=['seed'];"
                "from ghante_shared import config; import pathlib;"
                "config.DATA_DIR = pathlib.Path(r'%s'); config.SEED_DIR = config.DATA_DIR/'seed'; config.SCENARIO_PATH = config.DATA_DIR/'scenarios'/'sehore_hail.json';"
                "import runpy; runpy.run_path(r'%s', run_name='__main__')") % (ROOT, work, ROOT / "scripts" / "seed.py")
        r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        return {name: (work / rel).read_bytes() for name, rel in (("farmers", "seed/farmers.json"), ("villages", "seed/villages.json"), ("scenario", "scenarios/sehore_hail.json"))}

    def test_T1_01_seed_counts_and_determinism(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first, second = self.run_seed(a), self.run_seed(b)
        self.assertEqual(first, second, "running the seed twice must give identical files")
        self.assertEqual(first["farmers"], (ROOT / "data/seed/farmers.json").read_bytes(), "committed seed differs from generated seed")
        farmers = json.loads(first["farmers"])
        villages = json.loads(first["villages"])
        scenario = json.loads(first["scenario"])
        self.assertEqual(len(villages), 12)
        self.assertEqual(len(farmers), 340)
        self.assertEqual(len({f["policy"]["id"] for f in farmers}), 340)
        heroes = [f for f in farmers if f["is_hero"]]
        self.assertEqual(len(heroes), 1)
        self.assertIsNone(heroes[0]["sim"])
        self.assertEqual(heroes[0]["policy"]["khasra_no"], "214")
        outcomes = collections.Counter(f["sim"]["outcome"] for f in farmers if f["sim"])
        self.assertEqual(dict(outcomes), {"files": 311, "no_answer": 11, "no_damage": 9, "wants_human": 5, "pest": 1, "lapsed": 2})
        # the totals the dashboard must end on (SystemDesign §12.2)
        filed = outcomes["files"] + 1
        self.assertEqual({"FILED": filed, "UNREACHABLE": outcomes["no_answer"], "NO_DAMAGE": outcomes["no_damage"],
                          "ESCALATED": outcomes["wants_human"], "INELIGIBLE": outcomes["pest"] + outcomes["lapsed"]}, scenario["expected_totals"])
        self.assertTrue(all(f["mobile"].startswith("+91 00000 0") for f in farmers), "phone numbers must use the fake pattern")


class WithServices(unittest.TestCase):
    SERVICES: tuple[str, ...] = ()
    EXTRA_ENV: dict[str, str] = {}

    @classmethod
    def setUpClass(cls):
        cls.s = u.Services(*cls.SERVICES, **cls.EXTRA_ENV)

    @classmethod
    def tearDownClass(cls):
        cls.s.close()


class T1_02_03_Mcp(WithServices):
    SERVICES = ("orchestrator", "weather", "registry", "mandi")

    def tool(self, service: str, name: str, args: dict, **kw) -> dict:
        os.environ["ORCH_URL"] = u.url("orchestrator")
        from ghante_shared import config, mcp_client

        config.ORCH_URL = u.url("orchestrator")
        return asyncio.run(mcp_client.call_tool(u.url(service, "/mcp"), name, args, **kw))

    def test_T1_02_weather_tools(self):
        from ghante_shared import mcp_client

        self.assertEqual(set(asyncio.run(mcp_client.list_tools(u.url("weather", "/mcp")))), {"list_storm_events", "get_weather_at", "get_crop_risk"})
        events = self.tool("weather", "list_storm_events", {"district": "Sehore", "since": "2026-03-12T00:00:00+05:30"})["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(len(events[0]["villages"]), 12)
        self.assertEqual(self.tool("weather", "list_storm_events", {"district": "Bhopal", "since": "2026-03-12T00:00:00+05:30"})["events"], [])
        policy = self.tool("registry", "get_policy", {"farmer_id": "F0001"})
        at_plot = self.tool("weather", "get_weather_at", {"lat": policy["plot_lat"], "lon": policy["plot_lon"], "at": "2026-03-12T15:30:00+05:30"})
        self.assertTrue(at_plot["hail"])
        far = self.tool("weather", "get_weather_at", {"lat": policy["plot_lat"] + 0.9, "lon": policy["plot_lon"], "at": "2026-03-12T15:30:00+05:30"})
        self.assertFalse(far["hail"])
        next_day = self.tool("weather", "get_weather_at", {"lat": policy["plot_lat"], "lon": policy["plot_lon"], "at": "2026-03-13T15:30:00+05:30"})
        self.assertFalse(next_day["hail"])

    def test_T1_03_registry_tools(self):
        from ghante_shared import mcp_client

        self.assertEqual(set(asyncio.run(mcp_client.list_tools(u.url("registry", "/mcp")))),
                         {"list_farmers_in_villages", "get_farmer", "get_policy", "get_case", "update_case_slots", "set_case_status"})
        all_villages = [f"V{i:02d}" for i in range(1, 13)]
        farmers = self.tool("registry", "list_farmers_in_villages", {"village_ids": all_villages})["farmers"]
        self.assertEqual(len(farmers), 340)
        self.assertNotIn("sim", farmers[0])
        self.assertEqual(self.tool("registry", "get_policy", {"farmer_id": "F0001"})["khasra_no"], "214")
        hero = self.tool("registry", "get_farmer", {"farmer_id": "F0001"})
        self.assertEqual(hero["name"], "Ramlal Verma")
        self.assertNotIn("sim", hero)
        status, case = u.call("POST", u.url("orchestrator", "/api/cases"), {"farmer_id": "F0001"})
        self.assertEqual(status, 201)
        out = self.tool("registry", "update_case_slots", {"case_id": case["id"], "slots": {"damage_confirmed": True, "damage_pct": 70}},
                        server="registry", client="intake", case_id=case["id"])
        self.assertEqual(out["slots"]["damage_pct"], 70)
        got = self.tool("registry", "get_case", {"case_id": case["id"]})
        self.assertTrue(got["slots"]["damage_confirmed"])
        self.assertIn("error", self.tool("registry", "update_case_slots", {"case_id": case["id"], "slots": {"peril": "aliens"}}))
        self.assertIn("error", self.tool("registry", "set_case_status", {"case_id": case["id"], "status": "FILED"}))
        import time

        time.sleep(0.5)
        types = collections.Counter(e["type"] for e in self.s.events())
        self.assertEqual(types["call.slot"], 2)
        self.assertGreaterEqual(types["mcp.tool_called"], 1)
        slot_events = [e for e in self.s.events() if e["type"] == "call.slot"]
        self.assertTrue(all(e["live"] for e in slot_events), "events of the hero case must be marked live")

    def test_T1_03b_mandi_fixture(self):
        price = self.tool("mandi", "get_price", {"crop": "wheat", "district": "Sehore"})
        self.assertEqual(price["source"], "fixture")
        self.assertGreater(price["modal_price_inr_per_quintal"], 0)


class T1_04_DecisionService(WithServices):
    SERVICES = ("orchestrator", "s1")
    # "broken" is not a provider and laya is not installed in the test environment, so both chains must fall through to mock
    EXTRA_ENV = {"S1_CHAIN_TEXT": "broken,mock", "S1_CHAIN_REPORT": "mock"}

    def decide(self, decision: str, state: dict, **kw):
        return u.call("POST", u.url("s1", "/decide"), {"decision": decision, "state": state, **kw})

    def test_T1_04_all_four_decisions_and_fallback(self):
        status, r = self.decide("ROUTE", {"agent_question": "Was the crop damaged?", "utterance": "Yes, there is a lot of damage."}, case_id="case_x")
        self.assertEqual(status, 200, r)
        self.assertEqual(set(r), {"decision", "answers", "provider", "model", "latency_ms", "fallback_from", "fallback_reason", "cached"})
        self.assertEqual(r["answers"]["intent"]["value"], "yes")
        self.assertAlmostEqual(sum(r["answers"]["intent"]["probs"].values()), 1.0, places=2)
        self.assertEqual(r["provider"], "mock")
        self.assertEqual(r["fallback_from"], "broken")
        status, r = self.decide("PERIL", {"cause_text": "Hail fell"})
        self.assertEqual(r["answers"]["peril"]["value"], "hailstorm")
        status, r = self.decide("TRIAGE", {"hail_intensity": "severe", "distance_km": 1.4, "crop": "wheat"})
        self.assertEqual(r["answers"]["damage_likelihood"]["value"], "high")
        self.assertIsNone(r["fallback_from"])
        status, r = self.decide("VERIFY", {"peril": "hailstorm", "damage_pct": 70, "edge_label": "healthy", "edge_confidence": 0.9, "hail": True, "distance_from_plot_m": 100})
        self.assertFalse(r["answers"]["evidence_consistent"]["value"])
        self.assertEqual(set(r["answers"]), {"evidence_consistent"})
        self.assertEqual(self.decide("NOPE", {})[0], 400)
        self.assertEqual(u.call("POST", u.url("s1", "/decide"), {"decision": "ROUTE"})[0], 400)
        status, h = u.call("GET", u.url("s1", "/health"))
        self.assertEqual(h["chains"]["ROUTE"], ["broken", "mock"])
        import time

        time.sleep(0.7)
        events = self.s.events()
        s1_events = [e for e in events if e["type"] == "s1.decision"]
        self.assertEqual(len(s1_events), 4)
        self.assertEqual({e["data"]["decision"] for e in s1_events}, {"ROUTE", "PERIL", "TRIAGE", "VERIFY"})
        self.assertTrue(any(e["type"] == "fallback.used" and e["data"]["component"] == "s1" for e in events))

    def test_T1_04b_report_rendering(self):
        from apps.s1 import decisions

        report = decisions.render_report("TRIAGE", {"hail_intensity": "severe", "distance_km": 2, "crop": "wheat", "crop_stage": "close to harvest"})
        self.assertEqual(report, "Hail intensity at this village was severe. The farm is 2 km from the storm core. Crop: wheat, close to harvest.")
        self.assertIn("no hail", decisions.render_report("VERIFY", {"hail": False}))
        self.assertIn("a damaged crop flattened by the storm", decisions.render_report("VERIFY", {"edge_label": "lodged"}))


class T1_04c_HeadMaths(unittest.TestCase):
    def test_softmax_head_learns_separable_classes(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not installed")
        from apps.s1.providers import head

        rng = np.random.default_rng(0)
        centres = rng.normal(size=(5, 32))
        X = np.vstack([centres[c] + 0.3 * rng.normal(size=(20, 32)) for c in range(5)])
        X /= np.linalg.norm(X, axis=1, keepdims=True)
        y = np.repeat(np.arange(5), 20)
        W, b = head.train_softmax(X, y, 5)
        P = head.softmax_probs(W, b, X)
        self.assertEqual(float((P.argmax(1) == y).mean()), 1.0)
        self.assertTrue(np.allclose(P.sum(1), 1.0))


class T1_05_06_07_Portal(WithServices):
    SERVICES = ("portal",)

    def fill_form(self) -> str:
        status, location, _ = u.post_form(u.url("portal", "/claim/new/step1"), HERO)
        self.assertEqual(status, 303)
        self.assertRegex(location, r"^/claim/[0-9a-f]{12}/step2$")
        status, location, _ = u.post_form(u.url("portal", location), LOSS)
        self.assertEqual(status, 303)
        self.assertTrue(location.endswith("/step3"))
        status, location, _ = u.post_form(u.url("portal", location), FINAL, files={"photo": ("crop.png", PNG, "image/png")})
        self.assertEqual(status, 303)
        self.assertRegex(location, r"^/claim/confirmation/FCS-\d{6}$")
        return location

    def test_T1_05_three_page_form(self):
        location = self.fill_form()
        reference = location.rsplit("/", 1)[1]
        status, html = u.get_text(u.url("portal", location))
        self.assertEqual(status, 200)
        self.assertIn(f'<span id="reference">{reference}</span>', html)
        status, claim = u.call("GET", u.url("portal", f"/api/claims/{reference}"))
        self.assertEqual(status, 200)
        for key, value in {**HERO, **LOSS, **{k: FINAL[k] for k in ("gps_lat", "gps_lon", "submitted_by")}}.items():
            self.assertEqual(claim[key], value, key)
        self.assertTrue(claim["has_photo"])
        self.assertEqual(claim["submitted_via"], "form")
        status, html = u.get_text(u.url("portal", "/admin/claims"))
        self.assertIn(reference, html)

    def test_T1_05b_validation(self):
        status, location, html = u.post_form(u.url("portal", "/claim/new/step1"), {**HERO, "farmer_name": ""})
        self.assertEqual(status, 200)
        self.assertIn("farmer_name is required", html)
        status, location, _ = u.post_form(u.url("portal", "/claim/new/step1"), HERO)
        status, _, html = u.post_form(u.url("portal", location), {**LOSS, "damage_pct": "170"})
        self.assertEqual(status, 200)
        self.assertIn("damage_pct must be a valid number", html)
        status, location3, _ = u.post_form(u.url("portal", location), LOSS)
        status, _, html = u.post_form(u.url("portal", location3), FINAL)  # no photo
        self.assertEqual(status, 200)
        self.assertIn("photo is required", html)

    def test_T1_06_api_and_reset(self):
        body = {**HERO, **LOSS, **FINAL, "declaration": True, "photo_ref": "evidence/case_0002.jpg"}
        status, out = u.call("POST", u.url("portal", "/api/claims"), body)
        self.assertEqual(status, 201, out)
        self.assertRegex(out["reference"], r"^FCS-\d{6}$")
        status, claim = u.call("GET", u.url("portal", f"/api/claims/{out['reference']}"))
        self.assertEqual(claim["submitted_via"], "api")
        self.assertEqual(u.call("POST", u.url("portal", "/api/claims"), {**body, "crop": ""})[0], 422)
        self.assertEqual(u.call("POST", u.url("portal", "/api/reset"), {})[0], 200)
        self.assertEqual(u.call("GET", u.url("portal", "/api/claims/count"))[1]["claims"], 0)
        self.assertEqual(u.call("GET", u.url("portal", f"/api/claims/{out['reference']}"))[0], 404)
        status, out = u.call("POST", u.url("portal", "/api/claims"), body)
        self.assertEqual(out["reference"], "FCS-000001", "numbering restarts after a reset")

    def test_T1_07_sandbox_banner_and_no_government_branding(self):
        location = self.fill_form()
        status, loc2, _ = u.post_form(u.url("portal", "/claim/new/step1"), HERO)
        pages = ["/", "/claim/new/step1", loc2, "/admin/claims", location]
        banned = ["pmfby", "pradhan mantri", "government of india", "ministry of", "bharat sarkar", "emblem", "gov.in", "nic.in"]
        for path in pages:
            status, html = u.get_text(u.url("portal", path))
            self.assertEqual(status, 200, path)
            self.assertIn("Demo sandbox — not a government website", html, path)
            low = html.lower().replace("not a government website", "")
            for word in banned:
                self.assertNotIn(word, low, f"{word!r} on {path}")


class T1_08_StateMachine(WithServices):
    SERVICES = ("orchestrator",)

    def status(self, case_id: str, status: str):
        return u.call("POST", u.url("orchestrator", f"/api/cases/{case_id}/status"), {"status": status, "reason": "test"})

    def new_case(self, farmer_id: str) -> str:
        status, case = u.call("POST", u.url("orchestrator", "/api/cases"), {"farmer_id": farmer_id})
        self.assertEqual(status, 201, case)
        self.assertEqual(case["status"], "AFFECTED")
        self.assertEqual(case["deadline_at"], "2026-03-15T15:30:00+05:30")
        return case["id"]

    def test_T1_08_transitions(self):
        from ghante_shared import models

        self.assertEqual(set(models.TRANSITIONS), set(models.STATUSES), "every status needs a transition entry")
        happy = self.new_case("F0002")
        for step in ("QUEUED", "CALLING", "IN_CALL", "EVIDENCE", "PROCESSING", "FILING", "FILED"):
            self.assertEqual(self.status(happy, step)[0], 200, step)
        self.assertEqual(self.status(happy, "QUEUED")[0], 409, "FILED is terminal")
        bad = self.new_case("F0003")
        self.assertEqual(self.status(bad, "QUEUED")[0], 200)
        status, body = self.status(bad, "FILED")
        self.assertEqual(status, 409)
        self.assertIn("not allowed", body["error"])
        self.assertEqual(self.status(bad, "DANCING")[0], 409)
        # three unanswered attempts end in UNREACHABLE, not earlier
        ring = self.new_case("F0004")
        self.assertEqual(self.status(ring, "QUEUED")[0], 200)
        for attempt in (1, 2, 3):
            self.assertEqual(self.status(ring, "CALLING")[0], 200)
            self.assertEqual(self.status(ring, "NO_ANSWER")[0], 200)
            if attempt < 3:
                self.assertEqual(self.status(ring, "UNREACHABLE")[0], 409, "too early")
                self.assertEqual(self.status(ring, "QUEUED")[0], 200)
        self.assertEqual(self.status(ring, "QUEUED")[0], 409, "no fourth attempt")
        self.assertEqual(self.status(ring, "UNREACHABLE")[0], 200)
        self.assertEqual(self.status("case_9999", "QUEUED")[0], 404)
        self.assertEqual(u.call("POST", u.url("orchestrator", "/api/cases"), {"farmer_id": "F9999"})[0], 404)
        changes = [e for e in self.s.events() if e["type"] == "case.status_changed" and e["case_id"] == happy]
        self.assertEqual([e["data"]["to"] for e in changes], ["QUEUED", "CALLING", "IN_CALL", "EVIDENCE", "PROCESSING", "FILING", "FILED"])
        status, state = u.call("GET", u.url("orchestrator", "/api/state"))
        self.assertEqual(state["stats"]["filed"], 1)
        self.assertEqual(state["stats"]["unreachable"], 1)
        self.assertEqual(state["stats"]["affected"], 3)
        self.assertEqual(state["stats"]["live"], 0)

    def test_T1_08b_slots_validation(self):
        case_id = self.new_case("F0005")
        patch = lambda body: u.call("PATCH", u.url("orchestrator", f"/api/cases/{case_id}/slots"), body)  # noqa: E731
        self.assertEqual(patch({"peril": "hailstorm", "damage_pct": 70, "consent": True})[0], 200)
        self.assertEqual(patch({"damage_pct": 170})[0], 400)
        self.assertEqual(patch({"consent": "yes"})[0], 400)
        self.assertEqual(patch({"favourite_colour": "green"})[0], 400)
        status, case = u.call("GET", u.url("orchestrator", f"/api/cases/{case_id}"))
        self.assertEqual(case["slots"]["peril"], "hailstorm")
        self.assertEqual(case["slots"]["damage_pct"], 70)
        self.assertNotIn("sim", case["farmer"])


class T1_09_EventStream(WithServices):
    SERVICES = ("orchestrator",)

    def test_T1_09_stream_snapshot_then_events_and_log(self):
        got: list[dict] = []
        ready, done = threading.Event(), threading.Event()

        def reader():
            conn = http.client.HTTPConnection("127.0.0.1", u.PORT["orchestrator"], timeout=20)
            conn.request("GET", "/api/events/stream")
            resp = conn.getresponse()
            self.assertEqual(resp.getheader("Content-Type").split(";")[0], "text/event-stream")
            while not (got and got[-1]["type"] == "agent.started" and got[-1]["data"].get("summary") == "test"):
                line = resp.readline().decode("utf-8")
                if line.startswith("data: "):
                    got.append(json.loads(line[6:]))
                    ready.set()
            done.set()
            conn.close()

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        self.assertTrue(ready.wait(10), "no snapshot received")
        self.assertEqual(got[0]["type"], "snapshot")
        self.assertEqual(set(got[0]["data"]), {"clock", "stats", "storm", "villages", "cases", "farms", "scenario"})
        self.assertEqual(len(got[0]["data"]["villages"]), 12)
        status, out = u.call("POST", u.url("orchestrator", "/internal/events"), {"type": "agent.started", "agent": "evidence", "data": {"summary": "test"}})
        self.assertEqual(status, 200)
        self.assertTrue(done.wait(10), "posted event did not arrive on the stream")
        # Since Phase 5 a new stream replays the run's recent events after the snapshot and closes the replay with `tallies`.
        types = [e["type"] for e in got]
        self.assertIn("tallies", types)
        self.assertLess(types.index("tallies"), len(got) - 1, "the replay ends before new events")
        self.assertEqual(set(got[types.index("tallies")]["data"]), {"s1", "s1_cached", "mcp"})
        posted = got[-1]
        self.assertEqual(posted["id"], out["id"])
        self.assertEqual(set(posted), {"id", "ts", "sim_ts", "type", "case_id", "agent", "live", "data"})
        self.assertEqual(posted["sim_ts"], "2026-03-12T15:30:00+05:30")
        self.assertIn(out["id"], [e["id"] for e in self.s.events()])
        self.assertEqual(u.call("POST", u.url("orchestrator", "/internal/events"), {"data": {}})[0], 400)

    def test_T1_09b_reset(self):
        status, case = u.call("POST", u.url("orchestrator", "/api/cases"), {"farmer_id": "F0010"})
        self.assertEqual(status, 201)
        status, out = u.call("POST", u.url("orchestrator", "/api/scenario/reset"), {})
        self.assertEqual(status, 200)
        self.assertEqual(out["farmers"], 340)
        status, state = u.call("GET", u.url("orchestrator", "/api/state"))
        self.assertEqual(state["cases"], [])
        self.assertEqual(state["clock"]["hours_left"], 72.0)


class T1_11_WebShell(WithServices):
    SERVICES = ("orchestrator",)

    def fetch(self, path):
        with u._opener.open(u.url("orchestrator", path), timeout=10) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read().decode("utf-8")

    def test_T1_11a_pages_and_static_files_are_served(self):
        status, ctype, body = self.fetch("/")
        self.assertEqual(status, 200)
        self.assertTrue(ctype.startswith("text/html"))
        self.assertIn("72 Ghante", body)
        self.assertIn("Simulated farmers", body)  # honesty rule: simulated and live are always labelled
        status, ctype, body = self.fetch("/farmer")
        self.assertEqual(status, 200)
        self.assertIn("Crop Insurance Help", body)
        for path, kind in (("/static/app.js", "javascript"), ("/static/styles.css", "css")):
            status, ctype, body = self.fetch(path)
            self.assertEqual(status, 200)
            self.assertIn(kind, ctype)
            self.assertGreater(len(body), 500)

    def test_T1_11b_sample_covers_every_event_type_and_the_dashboard_knows_them(self):
        sample = [json.loads(line) for line in (ROOT / "data" / "fixtures" / "events_sample.jsonl").read_text(encoding="utf-8").splitlines()]
        types = {e["type"] for e in sample}
        design = {"sim.clock", "storm.detected", "case.created", "case.status_changed", "s1.decision", "call.started", "call.turn", "call.slot",
                  "evidence.received", "agent.started", "agent.finished", "mcp.tool_called", "filing.step", "claim.filed", "stats.updated", "fallback.used"}
        self.assertEqual(types, design)
        script = (ROOT / "apps" / "web" / "app.js").read_text(encoding="utf-8")
        rendered = design - {"stats.updated"}  # counters are derived from the cases, so they always agree with the dots
        for type_ in rendered:
            self.assertIn(f'"{type_}"', script, f"the dashboard does not handle {type_}")
        for e in sample:
            if e["type"] == "s1.decision" and e["data"]["decision"] == "VERIFY":
                self.assertEqual(set(e["data"]["answers"]), {"evidence_consistent"})

    def test_T1_11c_dashboard_renders_the_replayed_sample(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed here; do the manual check T1-11 instead")
        sample = [json.loads(line) for line in (ROOT / "data" / "fixtures" / "events_sample.jsonl").read_text(encoding="utf-8").splitlines()]
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
            self.assertEqual(page.locator("#map .dot:not(.g-idle)").count(), 0)
            for e in sample:
                self.assertEqual(u.call("POST", u.url("orchestrator", "/internal/events"), e)[0], 200)
            page.wait_for_function("document.querySelectorAll('#map .dot.g-done').length === 20", timeout=10000)
            self.assertEqual(page.locator("#map .dot:not(.g-idle)").count(), 24)
            self.assertEqual(page.locator("#map .dot.hero").count(), 1)
            legend = {row.get_attribute("data-key"): row.locator(".n").inner_text() for row in page.locator("#legend li").all()}
            self.assertEqual(legend, {"total": "24", "wait": "0", "call": "0", "work": "0", "done": "20", "human": "1", "nodamage": "1",
                                      "unreach": "1", "inelig": "1", "failed": "0"})
            self.assertEqual(page.inner_text("#truth"), "Simulated farmers: 23. Live: 1.")
            self.assertEqual(page.inner_text("#clock-num"), "68 h 00 m")
            self.assertEqual(page.inner_text("#banner"), "20 of 24 claims filed. 68 hours left. 2 need follow-up.")
            self.assertEqual(page.locator("#ticker li").count(), 28)
            self.assertEqual(page.locator("#mcp li").count(), 3)
            self.assertEqual(page.locator("#transcript .turn").count(), 4)
            self.assertIn("FCS-000007", page.inner_text("#hero-result"))
            self.assertIn("Fallback in use", page.inner_text("#notices"))
            self.assertEqual(page.locator("#slots li.done").count(), 3)
            size = page.evaluate("[document.documentElement.scrollWidth, innerWidth, document.documentElement.scrollHeight, innerHeight]")
            self.assertEqual(size[0], size[1], "the dashboard must not scroll sideways")
            self.assertEqual(size[2], size[3], "the dashboard must fit one screen")
            page.click("#btn-reset")
            page.click("#btn-reset")  # reset asks for a second press
            page.wait_for_function("document.querySelectorAll('#map .dot:not(.g-idle)').length === 0", timeout=10000)
            self.assertTrue(page.locator("#hero").is_hidden())
            self.assertEqual(errors, [])
            browser.close()


class T1_12a_ScriptedLines(unittest.TestCase):
    """The spoken part of T1-12 needs a person; this checks the words the agent will say."""

    def test_T1_12a_lines_render_for_the_hero(self):
        from apps.voice import lines

        call = lines.CallContext.from_case({
            "id": "case_0001", "farmer_id": "F0001", "is_hero": True, "slots": {},
            "farmer": {"name": "Ramlal Verma"}, "village": {"name": "Khajuriya Kalan"}, "policy": {"crop": "wheat", "khasra_no": "214"}})
        self.assertEqual(lines.render("greet", call), "Hello, am I speaking with Ramlal ji?")
        event = lines.render("event", call)
        self.assertIn("Khajuriya Kalan", event)
        self.assertIn("wheat", event)
        self.assertIn("automated assistant", event)  # the assistant says it is automated
        self.assertIn("khasra number 214", lines.render("khasra", call))
        for key in lines.LINES:
            text = lines.render(key, call, ref_spoken="x")
            self.assertNotIn("{", text, key)
            self.assertTrue(text.isascii(), f"{key}: the call is in English only")


if __name__ == "__main__":
    unittest.main(verbosity=2)
