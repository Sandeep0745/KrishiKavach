"""Gate G3 automated tests (context/Testing.md §5). Run:  python -m unittest tests.test_phase3 -v

T3-04 (browser agent on a free LLM), T3-06, T3-08 and T3-09 need a person and the real services. These cover the rest:
the rules, the graph, the pipeline end to end, the scripted fill in a real browser, failure and recovery, and reviewer approval.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import pathlib
import time
import unittest

from apps.orchestrator.pipeline import graph as graph_mod
from apps.orchestrator.pipeline import rules
from apps.voice import flow as f
from apps.voice import lines
from ghante_shared import config
from tests import _util as u

ROOT = pathlib.Path(__file__).resolve().parent.parent
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
NOW = dt.datetime(2026, 3, 12, 16, 0, tzinfo=IST)
PHOTO = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 20 + b"\xff\xd9"
HERO_SLOTS = {"identity_confirmed": True, "damage_confirmed": True, "khasra_confirmed": True, "cause_text": "Hail fell", "peril": "hailstorm",
              "loss_time_text": "half past three", "loss_datetime": "2026-03-12T15:30:00+05:30", "damage_pct": 70, "crop_stage": "standing", "consent": True}
HERO_META = {"label": "hail_damage", "confidence": 0.8, "latency_ms": 240, "edge_mode": "zeroshot", "lat": 23.02023, "lon": 76.72114,
             "captured_at": "2026-10-07T10:15:00Z", "captured_offline": False}  # about 120 m north of the plot
# What the portal must hold for the hero (SystemDesign §14.2)
HERO_FORM = {"application_no": "APP-SEH-000451", "farmer_name": "Ramlal Verma", "mobile": "+91 00000 00451", "state": "Madhya Pradesh",
             "district": "Sehore", "tehsil": "Ashta", "village": "Khajuriya Kalan", "season": "Rabi 2025-26", "crop": "Wheat", "khasra_no": "214",
             "insured_area_ha": "1.8", "loss_date": "2026-03-12", "loss_time": "15:30", "cause_of_loss": "Hailstorm", "crop_stage": "Standing crop",
             "affected_area_ha": "1.26", "damage_pct": "70", "gps_lat": "23.02023", "gps_lon": "76.72114",
             "submitted_by": "Authorised assistant (on behalf of farmer)", "declaration": "on"}


def case_of(**changes) -> dict:
    """The hero's case as the pipeline sees it, with changes for a persona."""
    case = {"id": "case_0001", "is_hero": True, "deadline_at": "2026-03-15T15:30:00+05:30", "slots": dict(HERO_SLOTS),
            "farmer": {"name": "Ramlal Verma", "mobile": "+91 00000 00451"},
            "village": {"name": "Khajuriya Kalan", "tehsil": "Ashta", "district": "Sehore", "state": "Madhya Pradesh"},
            "policy": {"application_no": "APP-SEH-000451", "season": "Rabi 2025-26", "crop": "wheat", "khasra_no": "214", "insured_area_ha": 1.8,
                       "status": "active", "valid_from": "2025-11-01", "valid_to": "2026-04-30", "plot_lat": 23.01915, "plot_lon": 76.72114},
            "storm": {"id": "storm_sehore_20260312", "type": "hailstorm", "started_at": "2026-03-12T15:30:00+05:30"}}
    for key, value in changes.items():
        if isinstance(value, dict):
            case[key] = {**case[key], **value}
        else:
            case[key] = value
    return case


EVIDENCE = {"id": "ev_0001_1", "edge_label": "hail_damage", "edge_confidence": 0.8, "lat": 23.02023, "lon": 76.72114, "gps_source": "phone",
            "photo_path": "x.jpg", "sha256": "ab" * 32}
HAIL = {"hail": True, "precipitation_mm": 27.8, "wind_gust_kmh": 85, "source": "replay"}
NO_HAIL = {"hail": False, "precipitation_mm": 0.0, "wind_gust_kmh": 12, "source": "replay"}


def judge(case=None, evidence=EVIDENCE, weather=HAIL, distance=120.0, now=NOW):
    checks = rules.run_checks(case or case_of(), evidence, weather, distance, now)
    return (*rules.verdict_of(checks), checks)


class T3_02_EligibilityRules(unittest.TestCase):
    """Testing.md §10: each persona gets the expected verdict and reason."""

    def test_E1_hero_passes_every_rule(self):
        verdict, reasons, checks = judge()
        self.assertEqual((verdict, reasons), ("eligible", []))
        self.assertEqual([c["n"] for c in checks], ["1", "2", "3", "4", "5", "6", "7", "7a", "7b"])
        self.assertTrue(all(c["passed"] for c in checks))

    def test_E2_lapsed_policy(self):
        verdict, reasons, _ = judge(case_of(policy={"status": "lapsed"}))
        self.assertEqual((verdict, reasons), ("ineligible", ["Policy not active"]))
        verdict, reasons, _ = judge(case_of(policy={"valid_to": "2026-02-28"}))
        self.assertEqual((verdict, reasons), ("ineligible", ["Storm date is outside the policy period"]))

    def test_E3_pest_is_not_covered(self):
        verdict, reasons, _ = judge(case_of(slots={"peril": "not_covered", "cause_text": "Insects attacked the crop"}), weather=HAIL)
        self.assertEqual(verdict, "ineligible")
        self.assertIn("Peril not covered", reasons[0])
        # unseasonal rain is covered only after harvest
        self.assertEqual(judge(case_of(slots={"peril": "unseasonal_rain"}))[0], "ineligible")
        self.assertEqual(judge(case_of(slots={"peril": "unseasonal_rain", "crop_stage": "harvested"}))[0], "eligible")

    def test_E4_photo_far_from_the_plot(self):
        verdict, reasons, _ = judge(distance=15000.0)
        self.assertEqual(verdict, "review")
        self.assertEqual(reasons, ["Photo location far from insured plot (15.0 km)"])

    def test_E5_healthy_photo(self):
        verdict, reasons, _ = judge(case_of(slots={"damage_pct": 80}), evidence={**EVIDENCE, "edge_label": "healthy", "edge_confidence": 0.85})
        self.assertEqual((verdict, reasons), ("review", ["Evidence inconsistent: the photo shows a healthy crop"]))
        # a weak "healthy" is left to the model's second opinion
        self.assertEqual(judge(evidence={**EVIDENCE, "edge_label": "healthy", "edge_confidence": 0.4})[0], "eligible")

    def test_E6_no_hail_on_record(self):
        verdict, reasons, _ = judge(weather=NO_HAIL)
        self.assertEqual((verdict, reasons), ("review", ["Evidence inconsistent: the weather record shows no hail at that place and time"]))
        self.assertEqual(judge(weather=None)[0], "review")

    def test_E7_not_a_crop_and_no_photo(self):
        verdict, reasons, _ = judge(evidence={**EVIDENCE, "edge_label": "not_a_crop"})
        self.assertEqual((verdict, reasons), ("review", ["No usable photo: it does not show a crop"]))
        verdict, reasons, _ = judge(evidence=None, distance=None)
        self.assertEqual(verdict, "review")
        self.assertEqual(reasons[0], "No usable photo: none was received")

    def test_E8_harvested_crop_hit_by_hail(self):
        self.assertEqual(judge(case_of(slots={"crop_stage": "harvested"}))[:2], ("eligible", []))

    def test_missing_details_go_to_a_person_and_ineligible_wins(self):
        self.assertEqual(judge(case_of(slots={"consent": None}))[:2], ("review", ["No consent on record"]))
        self.assertEqual(judge(case_of(slots={"peril": None}))[0], "review")
        self.assertEqual(judge(case_of(slots={"loss_datetime": "2026-03-12T20:00:00+05:30"}))[1],
                         ["Evidence inconsistent: the stated time is 270 minutes from the recorded storm"])
        verdict, reasons, _ = judge(case_of(policy={"status": "lapsed"}), distance=15000.0)
        self.assertEqual((verdict, reasons), ("ineligible", ["Policy not active"]), "a rule that ends the claim is reported, not the review reasons")

    def test_T3_03_deadline(self):
        late = dt.datetime(2026, 3, 15, 15, 31, tzinfo=IST)
        verdict, reasons, _ = judge(now=late)
        self.assertEqual((verdict, reasons), ("ineligible", ["Reported outside 72 hours of the loss"]))
        self.assertEqual(judge(now=dt.datetime(2026, 3, 15, 15, 30, tzinfo=IST))[0], "eligible", "the last minute still counts")

    def test_weather_is_looked_up_at_the_storm_time_when_the_farmer_is_roughly_right(self):
        storm = "2026-03-12T15:30:00+05:30"
        self.assertEqual(rules.weather_time(case_of(slots={"loss_datetime": "2026-03-12T15:00:00+05:30"})), storm, "'around three' means this storm")
        self.assertEqual(rules.weather_time(case_of(slots={"loss_datetime": None})), storm)
        self.assertEqual(rules.weather_time(case_of(slots={"loss_datetime": "2026-03-12T20:00:00+05:30"})), "2026-03-12T20:00:00+05:30",
                         "a time far from the storm is looked up as stated")

    def test_verify_answer_is_read_as_a_probability(self):
        self.assertEqual(rules.p_consistent({"answers": {"evidence_consistent": {"value": True, "confidence": 0.9}}}), 0.9)
        self.assertAlmostEqual(rules.p_consistent({"answers": {"evidence_consistent": {"value": False, "confidence": 0.9}}}), 0.1)
        self.assertIsNone(rules.p_consistent(None))
        state = rules.verify_state(case_of(), EVIDENCE, HAIL, 120.0)
        self.assertEqual((state["peril"], state["hail"], state["distance_from_plot_m"], state["minutes_from_storm"], state["edge_label"]),
                         ("hailstorm", True, 120, 0, "hail_damage"))


class T3_Form(unittest.TestCase):
    def test_form_matches_the_portal_fields(self):
        form = rules.build_form(case_of(), EVIDENCE, HAIL, 120.0)
        self.assertEqual({k: form[k] for k in HERO_FORM}, HERO_FORM)
        self.assertEqual(set(form), set(HERO_FORM) | {"remarks"})
        for part in ("with consent", "hail damage, 80% sure", "Weather record: hail, 27.8 mm rain, gusts 85 km/h", "120 m from the plot"):
            self.assertIn(part, form["remarks"])
        from apps.portal import main as portal  # every value must be one the portal's lists accept

        self.assertEqual(portal.validate(portal.ALL_FIELDS, form), [])

    def test_form_without_a_photo_and_with_a_reviewer_note(self):
        form = rules.build_form(case_of(slots={"damage_pct": 33, "crop_stage": "harvested", "loss_datetime": "2026-03-12T16:05:00+05:30"}), None, HAIL, None,
                                "Approved by a human reviewer.")
        self.assertEqual((form["gps_lat"], form["affected_area_ha"], form["loss_time"], form["crop_stage"]), ("", "0.59", "16:05", "Harvested (cut and spread)"))
        self.assertIn("No photo was received.", form["remarks"])
        self.assertTrue(form["remarks"].endswith("Approved by a human reviewer."))


class T3_Graph(unittest.TestCase):
    """The same graph description runs on the built-in runner and, where it is installed, on LangGraph."""

    def engines(self) -> list[str]:
        return ["built-in"] + (["langgraph"] if graph_mod.engine_name() == "langgraph" else [])

    def run_graph(self, engine: str, verdict: str, ref: str | None, start_at: str = "evidence") -> list[str]:
        seen: list[str] = []

        def node(name, out):
            async def run(state):
                seen.append(name)
                return out
            return run

        g = graph_mod.build({"evidence": node("evidence", {"pack": {"weather": {"hail": True}}}), "eligibility": node("eligibility", {"verdict": verdict}),
                             "filing": node("filing", {"claim_ref": ref} if ref else {"failed": "portal down"}), "followup": node("followup", {})}, engine)
        state = asyncio.run(g.ainvoke({"case_id": "case_0001", "start_at": start_at}))
        self.assertEqual(state["case_id"], "case_0001")
        return seen

    def test_paths(self):
        for engine in self.engines():
            with self.subTest(engine=engine):
                self.assertEqual(self.run_graph(engine, "eligible", "FCS-000001"), ["evidence", "eligibility", "filing", "followup"])
                self.assertEqual(self.run_graph(engine, "review", None), ["evidence", "eligibility"])
                self.assertEqual(self.run_graph(engine, "ineligible", None), ["evidence", "eligibility"])
                self.assertEqual(self.run_graph(engine, "eligible", None), ["evidence", "eligibility", "filing"], "no reference: follow-up does not run")
                self.assertEqual(self.run_graph(engine, "review", "FCS-000002", start_at="filing"), ["filing", "followup"], "reviewer approval starts at filing")

    def test_engine_is_reported(self):
        self.assertIn(graph_mod.engine_name(), ("langgraph", "built-in"))


class T3_CallEndings(unittest.TestCase):
    def flow_at_filing(self) -> f.CallFlow:
        call = lines.CallContext(case_id="case_0001", farmer_id="F0001", name_en="Ramlal Verma", village_en="Khajuriya Kalan",
                                 crop_en="wheat", khasra="214", is_hero=True, slots=dict(HERO_SLOTS), storm_started_at="2026-03-12T15:30:00+05:30")
        flow = f.CallFlow(call)
        flow.step = "FILING"
        return flow

    def test_what_the_agent_says_for_each_pipeline_result(self):
        cases = [({"claim_ref": "FCS-000147", "verdict": "eligible", "status": "FILED"}, "reference", "completed"),
                 ({"verdict": "review", "status": "ESCALATED", "claim_ref": None}, "not_filed", "escalated"),
                 ({"verdict": "ineligible", "status": "INELIGIBLE", "claim_ref": None}, "not_filed", "completed"),
                 ({"verdict": "eligible", "status": "FAILED", "claim_ref": None}, "not_filed", "escalated"),
                 ({"verdict": "eligible", "status": "FILING", "claim_ref": None, "pending": True}, "filing_slow", "completed"),
                 (None, "filing_slow", "completed")]
        for result, rule, outcome in cases:
            with self.subTest(result=result):
                action = self.flow_at_filing().on_pipeline_result(result)
                self.assertEqual((action.rule, action.end), (rule, outcome))
        spoken = self.flow_at_filing().on_pipeline_result({"claim_ref": "FCS-000147"}).text(self.flow_at_filing().call)
        self.assertIn("zero, zero, zero, one, four, seven", spoken, "the reference is read digit by digit")


# ---------------------------------------------------------------------------------------------------------------------------
class WithPipeline(unittest.TestCase):
    """Orchestrator, portal, the three MCP servers, the decision service (test provider) and, where it can run, the Filer."""

    NEEDS_FILER = True
    filer_ok, filer_why = False, "not checked"

    @classmethod
    def setUpClass(cls):
        WithPipeline.filer_ok, WithPipeline.filer_why = u.filer_can_run()
        names = ["orchestrator", "portal", "weather", "registry", "mandi", "s1"] + (["filer"] if cls.filer_ok else [])
        cls.s = u.Services(*names, S1_CHAIN_TEXT="mock", S1_CHAIN_REPORT="mock", PIPELINE_WAIT_S="60")
        cls.addClassCleanup(cls.s.close)

    def setUp(self):
        if self.NEEDS_FILER and not self.filer_ok:
            self.skipTest(f"the Filer cannot run here: {self.filer_why}")
        self.assertEqual(self.api("POST", "/api/scenario/reset", {})[0], 200)
        self.mark = len(self.s.events())

    def api(self, method: str, path: str, payload: dict | None = None, timeout: float = 90):
        return u.call(method, u.url("orchestrator", path), payload, timeout=timeout)

    def events(self, type_: str | None = None, case_id: str | None = None) -> list[dict]:
        time.sleep(0.4)  # events from other processes arrive over HTTP
        return [e for e in self.s.events()[self.mark:] if (type_ is None or e["type"] == type_) and (case_id is None or e["case_id"] == case_id)]

    def prepare(self, farmer_id: str = "F0001", slots: dict | None = None, meta: dict | None = HERO_META) -> str:
        """A case as it stands when the farmer has just said yes: details stored, photo uploaded, status PROCESSING."""
        case = self.api("POST", "/api/cases", {"farmer_id": farmer_id})[1]
        for status in ("QUEUED", "CALLING", "IN_CALL", "EVIDENCE"):
            self.assertEqual(self.api("POST", f"/api/cases/{case['id']}/status", {"status": status})[0], 200)
        self.assertEqual(self.api("PATCH", f"/api/cases/{case['id']}/slots", dict(HERO_SLOTS if slots is None else slots))[0], 200)
        if meta is not None:
            lat, lon = case["policy"]["plot_lat"], case["policy"]["plot_lon"]
            meta = {**meta, "lat": meta.get("lat", lat) if farmer_id == "F0001" else lat + 0.001, "lon": meta.get("lon", lon) if farmer_id == "F0001" else lon}
            status, _, body = u.post_form(u.url("orchestrator", f"/api/cases/{case['id']}/evidence"), {"meta": json.dumps(meta)},
                                          {"photo": ("crop.jpg", PHOTO, "image/jpeg")})
            self.assertEqual(status, 201, body)
        self.assertEqual(self.api("POST", f"/api/cases/{case['id']}/status", {"status": "PROCESSING", "reason": "photo and consent"})[0], 200)
        return case["id"]

    def run_pipeline(self, case_id: str):
        return self.api("POST", f"/api/cases/{case_id}/pipeline/run", {})

    def portal(self, path: str):
        return u.call("GET", u.url("portal", path))


class T3_HeroPipeline(WithPipeline):
    def test_T3_01_05_10_11_hero_is_filed_through_the_browser(self):
        case_id = self.prepare()
        t0 = time.time()
        status, out = self.run_pipeline(case_id)
        took = time.time() - t0
        self.assertEqual(status, 200, out)
        self.assertEqual((out["verdict"], out["reasons"], out["status"], out["filing_mode"], out["pending"]), ("eligible", [], "FILED", "scripted", False))
        self.assertRegex(out["claim_ref"], r"^FCS-\d{6}$")
        self.assertLess(took, 15, "T3-05: scripted filing within 15 seconds")
        self.assertEqual([c["n"] for c in out["checks"]], ["1", "2", "3", "4", "5", "6", "7", "7a", "7b", "8"])

        # T3-01: the evidence pack
        case = self.api("GET", f"/api/cases/{case_id}")[1]
        ev = case["evidence"][0]
        self.assertEqual(ev["weather"]["hail"], True)
        self.assertEqual(ev["weather"]["source"], "replay")
        self.assertTrue(100 <= ev["distance_from_plot_m"] <= 140, ev["distance_from_plot_m"])
        self.assertEqual(len(ev["sha256"]), 64)
        self.assertGreater(ev["loss_estimate_inr"], 0)
        self.assertEqual((case["status"], case["verdict"], case["claim_ref"], case["filing_mode"]), ("FILED", "eligible", out["claim_ref"], "scripted"))
        self.assertIsNotNone(case["filed_at"])

        # T3-05: every field in the portal's record equals the form
        status, record = self.portal(f"/api/claims/{out['claim_ref']}")
        self.assertEqual(status, 200)
        self.assertEqual({k: record[k] for k in HERO_FORM}, HERO_FORM)
        self.assertEqual((record["has_photo"], record["submitted_via"]), (True, "form"))
        self.assertIn("Weather record: hail", record["remarks"])

        # T3-11: the four agents in order, then claim.filed
        agents = [(e["agent"], e["type"]) for e in self.events(case_id=case_id) if e["type"] in ("agent.started", "agent.finished")]
        self.assertEqual(agents, [(a, t) for a in ("evidence", "eligibility", "filing", "followup") for t in ("agent.started", "agent.finished")])
        filed = self.events("claim.filed", case_id)
        self.assertEqual(len(filed), 1)
        self.assertEqual((filed[0]["data"]["claim_ref"], filed[0]["data"]["filing_mode"], filed[0]["live"]), (out["claim_ref"], "scripted", True))
        statuses = [e["data"]["to"] for e in self.events("case.status_changed", case_id)]
        self.assertEqual(statuses[-3:], ["PROCESSING", "FILING", "FILED"])
        steps = self.events("filing.step", case_id)
        self.assertGreaterEqual(len(steps), 25)
        self.assertEqual({e["data"]["mode"] for e in steps}, {"scripted"})
        self.assertEqual([e["data"]["n"] for e in steps], list(range(1, len(steps) + 1)))
        self.assertIn(("upload", "photo"), [(e["data"]["action"], e["data"]["field"]) for e in steps])
        verify = [e for e in self.events("s1.decision", case_id) if e["data"]["decision"] == "VERIFY"]
        self.assertEqual((len(verify), verify[0]["agent"], verify[0]["live"]), (1, "eligibility", True))

        # T3-10: the pipeline is an MCP client too
        tools = [(e["data"]["server"], e["data"]["tool"], e["data"]["client"], e["agent"]) for e in self.events("mcp.tool_called", case_id)]
        self.assertIn(("weather", "get_weather_at", "pipeline", "evidence"), tools)
        self.assertIn(("mandi", "get_price", "pipeline", "evidence"), tools)

        # asking again changes nothing, and the pack page shows the outcome
        again = self.run_pipeline(case_id)[1]
        self.assertEqual((again["claim_ref"], again["status"]), (out["claim_ref"], "FILED"))
        self.assertEqual(self.portal("/api/claims/count")[1]["claims"], 1)
        status, page = u.get_text(u.url("orchestrator", f"/api/cases/{case_id}/evidence-pack"))
        self.assertEqual(status, 200)
        for part in (out["claim_ref"], "Demo data", ev["sha256"], "Passed: Weather record shows hail", "scripted browser fill"):
            self.assertIn(part, page)

    def test_T3_05_scripted_fill_five_of_five(self):
        if not self.filer_ok:
            self.skipTest(self.filer_why)
        photo = pathlib.Path(self.s.tmp) / "crop.jpg"
        photo.write_bytes(PHOTO)
        form = {**HERO_FORM, "remarks": "Reported by phone. Weather record: hail."}
        refs = []
        for _ in range(5):
            t0 = time.time()
            status, out = u.call("POST", u.url("filer", "/file"), {"case_id": "case_0001", "form": form, "photo_path": str(photo), "mode": "scripted"}, timeout=60)
            self.assertEqual(status, 200, out)
            self.assertEqual((out["mode_used"], out["mismatches"], out["llm_steps"]), ("scripted", [], 0))
            self.assertLess(time.time() - t0, 15)
            refs.append(out["claim_ref"])
        self.assertEqual(refs, [f"FCS-{n:06d}" for n in range(1, 6)])
        record = self.portal("/api/claims/FCS-000005")[1]
        self.assertEqual({k: record[k] for k in form}, form)

    def test_filer_refuses_bad_requests(self):
        photo = pathlib.Path(self.s.tmp) / "crop.jpg"
        photo.write_bytes(PHOTO)
        post = lambda body: u.call("POST", u.url("filer", "/file"), body, timeout=60)  # noqa: E731
        self.assertEqual(post({"case_id": "c", "form": HERO_FORM, "photo_path": str(photo) + ".missing"})[0], 400)
        self.assertEqual(post({"case_id": "c", "form": HERO_FORM, "photo_path": str(photo), "mode": "magic"})[0], 400)
        self.assertEqual(post({"case_id": "c"})[0], 400)
        status, out = post({"case_id": "c", "form": {**HERO_FORM, "state": "Atlantis"}, "photo_path": str(photo), "mode": "scripted"})
        self.assertEqual(status, 502)
        self.assertIn("could not fill 'state' with 'Atlantis' on page 1", out["error"])
        health = u.call("GET", u.url("filer", "/health"))[1]
        self.assertEqual((health["portal_is_local"], health["scripted"]["usable"], health["window_open"]), (True, True, True))

    def test_T3_07_portal_down_then_back(self):
        case_id = self.prepare()
        self.s.stop("portal")
        try:
            status, out = self.run_pipeline(case_id)
            self.assertEqual(status, 200, out)
            self.assertEqual((out["status"], out["claim_ref"], out["verdict"]), ("FAILED", None, "eligible"))
            self.assertIn("Filer", out["failed"])
            self.assertEqual(self.api("GET", "/health")[0], 200, "the orchestrator stays up")
            change = self.events("case.status_changed", case_id)[-1]["data"]
            self.assertEqual((change["from"], change["to"]), ("FILING", "FAILED"))
            self.assertTrue(change["reason"])
            finished = [e["data"] for e in self.events("agent.finished", case_id) if e["agent"] == "filing"]
            self.assertEqual(finished[-1]["ok"], False)
            self.assertEqual(self.events("claim.filed", case_id), [])
        finally:
            self.s.start("portal")
        status, out = self.run_pipeline(case_id)
        self.assertEqual((status, out["status"]), (200, "FILED"), out)
        self.assertRegex(out["claim_ref"], r"^FCS-\d{6}$")
        statuses = [e["data"]["to"] for e in self.events("case.status_changed", case_id)]
        self.assertEqual(statuses[-4:], ["FILING", "FAILED", "FILING", "FILED"])

    def test_T3_08_text_version_the_call_ends_with_the_reference(self):
        """The Intake agent's brain, the pipeline and the phone's message card together, without a microphone."""
        from apps.voice import brain as brain_mod
        from apps.voice import services as services_mod
        from tests.test_phase2 import SseReader

        for key, service, path in (("ORCH_URL", "orchestrator", ""), ("MCP_REGISTRY_URL", "registry", "/mcp"), ("S1_URL", "s1", "")):
            setattr(config, key, u.url(service, path))
        case = self.api("POST", "/api/cases", {"farmer_id": "F0001"})[1]
        for status in ("QUEUED", "CALLING", "IN_CALL"):
            self.api("POST", f"/api/cases/{case['id']}/status", {"status": status})
        call = lines.CallContext.from_case(self.api("GET", f"/api/cases/{case['id']}")[1])
        answers = {"Yes, the hail flattened more than half the crop": {"slots": {"cause_text": "The hail flattened the crop", "peril": "hailstorm", "damage_pct": 70}},
                   "Around three o'clock": {"slots": {"loss_time": "15:00", "loss_time_text": "Around three o'clock"}},
                   "It was standing in the field": {"slots": {"crop_stage": "standing"}}}

        class CannedLlm(services_mod.Services):
            async def extract(self, *, step, question, utterance, known):
                return {"data": answers[utterance], "provider": "canned", "model": "test", "ms": 1, "total_ms": 1, "failed": []}

        phone = SseReader("orchestrator", "/api/farmer/F0001/stream")
        self.addCleanup(phone.close)
        self.assertIsNotNone(phone.wait_for("connected"))

        async def talk():
            brain = brain_mod.CallBrain(call, CannedLlm(call))
            await brain.open()
            for utterance in ("Yes, speaking.", "Yes, the hail flattened more than half the crop", "yes", "Around three o'clock", "It was standing in the field"):
                await brain.farmer_turn(utterance)
            self.assertTrue(brain.waiting_for_photo)
            await brain.flush()
            status, _, body = u.post_form(u.url("orchestrator", f"/api/cases/{case['id']}/evidence"), {"meta": json.dumps(HERO_META)},
                                          {"photo": ("crop.jpg", PHOTO, "image/jpeg")})
            self.assertEqual(status, 201, body)
            await brain.evidence("hail_damage", 0.8, json.loads(body)["evidence_id"])
            consent = await brain.farmer_turn("yes")
            self.assertTrue(consent.run_pipeline)
            return await brain.pipeline()

        last = asyncio.run(talk())
        self.assertEqual((last.rule, last.end), ("reference", "completed"))
        case = self.api("GET", f"/api/cases/{case['id']}")[1]
        self.assertEqual(case["status"], "FILED")
        from apps.voice import words

        self.assertIn(words.digits(case["claim_ref"]), last.text, "the agent reads out the reference the portal gave")
        card = phone.wait_for("message", 5)
        self.assertIsNotNone(card, "the phone gets the message card")
        self.assertEqual((card["data"]["claim_ref"], card["data"]["simulated_sms"]), (case["claim_ref"], True))
        self.assertIn(case["claim_ref"], card["data"]["text"])
        # a phone that connects after filing still gets the card
        late = SseReader("orchestrator", "/api/farmer/F0001/stream")
        self.addCleanup(late.close)
        self.assertEqual(late.wait_for("message", 5)["data"]["claim_ref"], case["claim_ref"])
        # T3-10: the same MCP servers were used by two clients
        clients = {e["data"]["client"] for e in self.events("mcp.tool_called", case["id"])}
        self.assertEqual(clients, {"intake", "pipeline"})
        self.assertEqual(self.portal(f"/api/claims/{case['claim_ref']}")[1]["loss_time"], "15:00")


class T3_OtherOutcomes(WithPipeline):
    NEEDS_FILER = False

    def seed(self) -> list[dict]:
        return json.loads((ROOT / "data" / "seed" / "farmers.json").read_text(encoding="utf-8"))

    def test_simulated_farmer_is_filed_through_the_portal_api(self):
        case_id = self.prepare("F0006", {**HERO_SLOTS, "damage_pct": 75})
        status, out = self.run_pipeline(case_id)
        self.assertEqual(status, 200, out)
        self.assertEqual((out["status"], out["verdict"], out["filing_mode"]), ("FILED", "eligible", "api"))
        record = self.portal(f"/api/claims/{out['claim_ref']}")[1]
        self.assertEqual((record["submitted_via"], record["farmer_name"], record["damage_pct"], record["affected_area_ha"]), ("api", "Radheshyam Verma", "75", "2.25"))
        self.assertEqual(self.events("filing.step", case_id), [], "no browser for simulated farmers")
        self.assertFalse(self.events("claim.filed", case_id)[0]["live"])
        self.assertTrue(all(not e["live"] for e in self.events("s1.decision", case_id)))

    def test_E2_E3_lapsed_policy_and_pest_end_as_ineligible(self):
        farmers = self.seed()
        lapsed = next(x for x in farmers if x["policy"]["status"] == "lapsed")
        case_id = self.prepare(lapsed["id"])
        out = self.run_pipeline(case_id)[1]
        self.assertEqual((out["status"], out["verdict"], out["reasons"], out["claim_ref"]), ("INELIGIBLE", "ineligible", ["Policy not active"], None))
        agents = [e["agent"] for e in self.events("agent.finished", case_id)]
        self.assertEqual(agents, ["evidence", "eligibility"], "filing does not start")
        self.assertEqual([e for e in self.events("s1.decision", case_id) if e["data"]["decision"] == "VERIFY"], [], "the model is not asked when a rule already decided")
        pest = next(x for x in farmers if (x["sim"] or {}).get("outcome") == "pest")
        out = self.run_pipeline(self.prepare(pest["id"], {**HERO_SLOTS, "cause_text": "Insects attacked the crop", "peril": "not_covered"}))[1]
        self.assertEqual((out["status"], out["verdict"]), ("INELIGIBLE", "ineligible"))
        self.assertIn("Peril not covered", out["reasons"][0])
        self.assertEqual(self.portal("/api/claims/count")[1]["claims"], 0)

    def test_T3_12_far_away_photo_goes_to_review_and_a_person_approves(self):
        case_id = self.prepare("F0006", meta={**HERO_META, "lat": 99})  # placeholder, replaced below
        # prepare() puts simulated photos next to the plot; this one is uploaded again from 15 km away
        case = self.api("GET", f"/api/cases/{case_id}")[1]
        far = {**HERO_META, "lat": case["policy"]["plot_lat"] + 0.1357, "lon": case["policy"]["plot_lon"]}
        status, _, body = u.post_form(u.url("orchestrator", f"/api/cases/{case_id}/evidence"), {"meta": json.dumps(far)}, {"photo": ("crop.jpg", PHOTO, "image/jpeg")})
        self.assertEqual(status, 201, body)
        out = self.run_pipeline(case_id)[1]
        self.assertEqual((out["status"], out["verdict"], out["claim_ref"]), ("ESCALATED", "review", None))
        self.assertIn("Photo location far from insured plot", out["reasons"][0])
        self.assertEqual(self.run_pipeline(case_id)[0], 409, "a case waiting for a person is not processed again by itself")
        self.assertEqual(self.api("POST", f"/api/cases/{case_id}/review", {"approve": "yes"})[0], 400)
        status, kept = self.api("POST", f"/api/cases/{case_id}/review", {"approve": False, "note": "asked for a field visit"})
        self.assertEqual((status, kept["approved"], kept["status"]), (200, False, "ESCALATED"))
        status, done = self.api("POST", f"/api/cases/{case_id}/review", {"approve": True, "note": "plot checked on the map"})
        self.assertEqual(status, 200, done)
        self.assertEqual((done["approved"], done["status"], done["verdict"]), (True, "FILED", "review"), "the verdict stays what the rules said")
        record = self.portal(f"/api/claims/{done['claim_ref']}")[1]
        self.assertIn("Approved by a human reviewer: plot checked on the map", record["remarks"])
        decisions = self.events("review.decision", case_id)
        self.assertEqual([(e["agent"], e["data"]["approve"], e["data"]["by"]) for e in decisions], [("system", False, "human reviewer"), ("system", True, "human reviewer")])
        self.assertEqual(self.api("POST", f"/api/cases/{case_id}/review", {"approve": True})[0], 409, "already filed")

    def test_hero_without_a_photo_goes_to_review_then_files_through_the_api(self):
        case_id = self.prepare(meta=None)
        out = self.run_pipeline(case_id)[1]
        self.assertEqual((out["status"], out["verdict"], out["reasons"][0]), ("ESCALATED", "review", "No usable photo: none was received"))
        done = self.api("POST", f"/api/cases/{case_id}/review", {"approve": True})[1]
        self.assertEqual((done["status"], done["filing_mode"]), ("FILED", "api"))
        fallback = [e["data"] for e in self.events("fallback.used", case_id)]
        self.assertEqual([(d["component"], d["to"], d["reason"]) for d in fallback], [("filer", "portal api", "no photo to upload")])
        self.assertIn("No photo was received.", self.portal(f"/api/claims/{done['claim_ref']}")[1]["remarks"])

    def test_wrong_status_unknown_case_and_health(self):
        case = self.api("POST", "/api/cases", {"farmer_id": "F0001"})[1]
        self.assertEqual(self.run_pipeline(case["id"])[0], 409)
        self.assertEqual(self.run_pipeline("case_9999")[0], 404)
        self.assertEqual(self.api("POST", "/api/cases/case_9999/review", {"approve": True})[0], 404)
        self.assertEqual(self.api("POST", f"/api/cases/{case['id']}/review", {"approve": True})[0], 409)
        self.assertEqual(u.get_text(u.url("orchestrator", "/api/cases/case_9999/evidence-pack"))[0], 404)
        self.assertEqual(u.get_text(u.url("orchestrator", f"/api/cases/{case['id']}/evidence-pack"))[0], 200, "the pack page works before anything is known")
        self.assertIn(self.api("GET", "/health")[1]["pipeline_engine"], ("langgraph", "built-in"))


class T3_Dashboard(WithPipeline):
    """Roadmap 3.8 and 3.9: the live-call panel shows the pipeline at work, and a person can approve or retry from the dashboard."""

    def test_filing_progress_reviewer_approval_and_retry(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed here; check the dashboard by eye during T3-08")
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

            # 1. the hero is filed through the browser
            case_id = self.prepare()
            page.wait_for_selector("#hero:not([hidden])", timeout=10000)
            self.assertTrue(page.locator("#btn-approve").is_hidden() and page.locator("#btn-retry").is_hidden())
            out = self.run_pipeline(case_id)[1]
            page.wait_for_function("document.getElementById('hero-result').textContent.includes('Reference FCS-')", timeout=10000)
            self.assertIn(out["claim_ref"], page.inner_text("#hero-result"))
            self.assertEqual(page.inner_text("#filing"), "Submitted by the scripted fill.")
            self.assertIn("Weather record at the spot: hail", page.inner_text("#evidence-match"))
            self.assertEqual(page.get_attribute("#evidence a.pack-link", "href"), f"/api/cases/{case_id}/evidence-pack")
            self.assertEqual(page.locator("#legend li[data-key=done] .n").inner_text(), "1")
            import os

            if os.environ.get("GHANTE_SHOT"):  # keep a picture of the finished call for the results page
                page.screenshot(path=os.environ["GHANTE_SHOT"])

            # 2. no photo: the checks send it to a person, who approves with the A key
            page.click("#btn-reset")
            page.click("#btn-reset")
            page.wait_for_function("document.querySelectorAll('#map .dot:not(.g-idle)').length === 0", timeout=10000)
            case_id = self.prepare(meta=None)
            self.assertEqual(self.run_pipeline(case_id)[1]["status"], "ESCALATED")
            page.wait_for_selector("#btn-approve:not([hidden])", timeout=10000)
            self.assertIn("Sent to a person", page.inner_text("#filing"))
            self.assertIn("Press A to approve", page.inner_text("#hero-result"))
            self.assertEqual(page.locator("#legend li[data-key=human] .n").inner_text(), "1")
            page.keyboard.press("a")
            page.wait_for_function("document.getElementById('hero-result').textContent.includes('Reference FCS-')", timeout=15000)
            self.assertEqual(page.inner_text("#filing"), "Submitted through the portal's API.")
            self.assertTrue(page.locator("#btn-approve").is_hidden())
            self.assertIn("Fallback in use for filer: browser form replaced by portal api.", page.inner_text("#notices"))
            self.assertEqual(self.api("GET", f"/api/cases/{case_id}")[1]["status"], "FILED")

            # 3. the portal is down: Failed, then the F key files it once the portal is back
            page.click("#btn-reset")
            page.click("#btn-reset")
            page.wait_for_function("document.querySelectorAll('#map .dot:not(.g-idle)').length === 0", timeout=10000)
            case_id = self.prepare()
            self.s.stop("portal")
            try:
                self.assertEqual(self.run_pipeline(case_id)[1]["status"], "FAILED")
                page.wait_for_selector("#btn-retry:not([hidden])", timeout=10000)
                self.assertIn("Not filed", page.inner_text("#filing"))
                self.assertEqual(page.locator("#legend li[data-key=failed] .n").inner_text(), "1")
            finally:
                self.s.start("portal")
            page.keyboard.press("f")
            page.wait_for_function("document.getElementById('hero-result').textContent.includes('Reference FCS-')", timeout=20000)
            self.assertTrue(page.locator("#btn-retry").is_hidden())
            # a dashboard opened afterwards shows the same state
            page.reload()
            page.wait_for_function("document.getElementById('conn').textContent === 'connected'", timeout=10000)
            self.assertEqual(page.locator("#legend li[data-key=done] .n").inner_text(), "1")
            self.assertTrue(page.locator("#btn-approve").is_hidden() and page.locator("#btn-retry").is_hidden())
            size = page.evaluate("[document.documentElement.scrollWidth, innerWidth, document.documentElement.scrollHeight, innerHeight]")
            self.assertEqual((size[0], size[2]), (size[1], size[3]), "the dashboard still fits one screen")
            self.assertEqual(errors, [])


class T3_FilerDown(WithPipeline):
    """Drill D6: with no Filer running the hero's case ends FAILED with a reason, and filing can be tried again."""
    NEEDS_FILER = False

    def test_hero_fails_cleanly_when_the_filer_is_not_running(self):
        if self.filer_ok:
            self.s.stop("filer")
            self.addCleanup(self.s.start, "filer")
        case_id = self.prepare()
        out = self.run_pipeline(case_id)[1]
        self.assertEqual((out["status"], out["verdict"], out["claim_ref"]), ("FAILED", "eligible", None))
        self.assertIn("the Filer could not be reached", out["failed"])
        self.assertEqual(self.api("GET", "/health")[0], 200)


class T3_SlowFiling(unittest.TestCase):
    def test_T3_09_a_run_longer_than_the_wait_answers_pending_and_still_finishes(self):
        from apps.orchestrator.pipeline.service import Pipeline

        class Clock:
            def now(self):
                return NOW

        class Store:
            clock = Clock()

            def __init__(self):
                self.case = {"id": "case_0001", "status": "FILING", "verdict": "eligible", "verdict_reasons": [], "claim_ref": None, "filing_mode": None,
                             "time_to_file_s": None}

            def get(self, case_id):
                return dict(self.case)

        async def run():
            store = Store()
            pipeline = Pipeline(store, lambda *a: 0, engine="built-in")

            async def slow(case_id, start_at, note):
                await asyncio.sleep(0.3)
                store.case.update(status="FILED", claim_ref="FCS-000009", filing_mode="scripted")
                return pipeline.result(case_id)

            pipeline._run = slow
            task = pipeline.start("case_0001")
            self.assertIs(pipeline.start("case_0001"), task, "a second request joins the run that is under way")
            early = await pipeline.wait(task, "case_0001", seconds=0.05)
            late = await pipeline.wait(task, "case_0001", seconds=2)
            return early, late, pipeline.running("case_0001")

        early, late, still = asyncio.run(run())
        self.assertEqual((early["pending"], early["claim_ref"], early["status"]), (True, None, "FILING"))
        self.assertEqual((late["pending"], late["claim_ref"], late["status"]), (False, "FCS-000009", "FILED"))
        self.assertIsNone(still)


if __name__ == "__main__":
    unittest.main()
