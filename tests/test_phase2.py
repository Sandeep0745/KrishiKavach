"""Gate G2 automated tests (context/Testing.md §4). Run:  python -m unittest tests.test_phase2 -v

The spoken tests T2-01 to T2-14 need a person. These cover what can be proved without a microphone.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import http.client
import json
import pathlib
import socket
import threading
import time
import unittest

from apps.voice import flow as f
from apps.voice import lines, words
from ghante_shared import config, livekit_token
from tests import _util as u

ROOT = pathlib.Path(__file__).resolve().parent.parent


def hero(**slots) -> lines.CallContext:
    return lines.CallContext(case_id="case_0001", farmer_id="F0001", name_en="Ramlal Verma", village_en="Khajuriya Kalan",
                             crop_en="wheat", khasra="214", is_hero=True, slots=dict(slots), storm_started_at="2026-03-12T15:30:00+05:30")


def route(intent: str, confidence: float = 0.9, distress: float = 0.0) -> dict:
    return {"intent": intent, "confidence": confidence, "distress": distress}


def keys(action: f.Action) -> list[str]:
    return [s.key or "<llm>" for s in action.say]


class T2_16_TurnLogic(unittest.TestCase):
    """Every row of the rule table in SystemDesign §10.3, with mocked ROUTE answers."""

    def flow_at(self, step: str, **kw) -> f.CallFlow:
        """A flow that has reached `step` by plain yes answers and LLM extractions."""
        flow = f.CallFlow(hero(), **kw)
        flow.open()
        script = {"GREET": None, "EVENT": ("yes",), "KHASRA": ("yes",), "CAUSE": ("yes",),
                  "TIME": ("llm", {"slots": {"cause_text": "Hail fell"}}, {"value": "hailstorm", "confidence": 0.9}),
                  "EXTENT": ("llm", {"slots": {"loss_time": "15:30"}}, None), "STAGE": ("llm", {"slots": {"damage_pct": 70}}, None),
                  "PHOTO": ("llm", {"slots": {"crop_stage": "standing"}}, None), "CONSENT": ("photo",)}
        for name in ["GREET", "EVENT", "KHASRA", "CAUSE", "TIME", "EXTENT", "STAGE", "PHOTO", "CONSENT"]:
            if flow.step == step:
                return flow
            if flow.step != name:
                continue
            nxt = script[{"GREET": "EVENT", "EVENT": "KHASRA", "KHASRA": "CAUSE", "CAUSE": "TIME", "TIME": "EXTENT", "EXTENT": "STAGE",
                          "STAGE": "PHOTO", "PHOTO": "CONSENT"}[name]]
            if nxt[0] == "yes":
                flow.on_turn("yes", route("yes"))
            elif nxt[0] == "llm":
                self.assertTrue(flow.on_turn("Hail fell in the afternoon", route("gives_details")).use_llm)
                flow.apply_extraction(nxt[1], nxt[2])
            else:
                flow.on_evidence("hail_damage", 0.82, "ev_1")
        self.assertEqual(flow.step, step)
        return flow

    def test_open_says_greet(self):
        flow = f.CallFlow(hero())
        action = flow.open()
        self.assertEqual((keys(action), action.path, flow.step), (["greet"], "scripted", "GREET"))
        self.assertEqual(flow.expects(), "yes_no")
        self.assertIn("Ramlal", flow.question())

    def test_row1_wants_human_and_distress_escalate(self):
        for r in (route("wants_human", 0.6), route("gives_details", 0.9, distress=0.7)):
            flow = self.flow_at("CAUSE")
            a = flow.on_turn("I want to talk to a person", r)
            self.assertEqual((keys(a), a.status[0], a.end, a.path, a.use_llm), (["escalate"], "ESCALATED", "escalated", "fast", False))
        flow = self.flow_at("CAUSE")
        self.assertTrue(flow.on_turn("I want to talk to a person", route("wants_human", 0.59)).use_llm, "below the threshold the LLM decides")

    def test_row2_wrong_person(self):
        flow = f.CallFlow(hero()); flow.open()
        a = flow.on_turn("Wrong number", route("wrong_person", 0.7))
        self.assertEqual((keys(a), a.end, a.status[0]), (["wrong_person"], "wrong_person", "ESCALATED"))
        flow = f.CallFlow(hero()); flow.open()
        a = flow.on_turn("no", route("no", 0.8))  # a plain no to "am I speaking with Ramlal ji?"
        self.assertEqual((keys(a), a.end), (["wrong_person"], "wrong_person"))

    def test_row3_plain_yes_takes_the_fast_path_and_asks_the_next_question(self):
        flow = f.CallFlow(hero()); flow.open()
        a = flow.on_turn("Yes, speaking.", route("yes", 0.5))
        self.assertEqual((a.path, a.use_llm, keys(a), a.slots, flow.step), ("fast", False, ["event"], {"identity_confirmed": True}, "EVENT"))
        a = flow.on_turn("yes sir", route("yes", 0.9))
        self.assertEqual((keys(a), a.slots, flow.step), (["khasra"], {"damage_confirmed": True}, "KHASRA"))
        a = flow.on_turn("yes", route("yes", 0.9))
        self.assertEqual((keys(a), a.slots, flow.step, a.status), (["cause"], {"khasra_confirmed": True}, "CAUSE", None))

    def test_row3_guards_low_confidence_long_reply_and_detail_steps_go_to_the_llm(self):
        flow = f.CallFlow(hero()); flow.open()
        self.assertTrue(flow.on_turn("yes", route("yes", 0.49)).use_llm, "confidence below FAST_PATH_MIN")
        flow.on_turn("yes", route("yes", 0.9))
        a = flow.on_turn("Yes, the hail flattened more than half the crop", route("yes", 0.9))
        self.assertTrue(a.use_llm and a.path == "llm", "a long reply may carry details")
        flow = self.flow_at("CAUSE")
        self.assertTrue(flow.on_turn("yes", route("yes", 0.95)).use_llm, "a detail step never takes a yes as its answer")

    def test_row3_no_at_event_khasra_consent(self):
        flow = self.flow_at("EVENT")
        a = flow.on_turn("no, it is fine", route("no", 0.8))
        self.assertEqual((keys(a), a.status[0], a.end, a.slots), (["no_damage"], "NO_DAMAGE", "completed", {"damage_confirmed": False}))
        flow = self.flow_at("KHASRA")
        a = flow.on_turn("no", route("no", 0.8))
        self.assertEqual((keys(a), a.status[0], a.end), (["escalate"], "ESCALATED", "escalated"))
        flow = self.flow_at("CONSENT")
        a = flow.on_turn("no", route("no", 0.8))
        self.assertEqual((keys(a), a.status[0], a.end, a.run_pipeline, a.slots), (["no_consent"], "ESCALATED", "escalated", False, {"consent": False}))
        self.assertEqual(flow.on_turn("yes", route("yes")).rule, "ended", "nothing happens after the call has ended")

    def test_row4_unclear_llm_then_rephrase_then_escalate(self):
        flow = self.flow_at("CAUSE")
        a1 = flow.on_turn("hmm", route("unclear", 0.8))
        self.assertTrue(a1.use_llm)
        a1b = flow.apply_extraction({"slots": {}, "answer": ""})
        self.assertEqual(keys(a1b), ["rephrase"])
        a2 = flow.on_turn("uh", route("unclear", 0.8))
        self.assertEqual((keys(a2), a2.path, a2.use_llm, a2.end), (["rephrase"], "fast", False, None))
        a3 = flow.on_turn("eh", route("unclear", 0.8))
        self.assertEqual((keys(a3), a3.status[0], a3.end), (["escalate"], "ESCALATED", "escalated"))
        flow = self.flow_at("CAUSE")
        flow.on_turn("hmm", route("unclear")); flow.on_turn("hail", route("gives_details"))
        self.assertTrue(flow.on_turn("hmm", route("unclear")).use_llm, "the count restarts after a clear turn")

    def test_row5_details_and_questions_go_to_the_llm(self):
        for intent in ("gives_details", "asks_question"):
            flow = self.flow_at("CAUSE")
            a = flow.on_turn("Hail fell", route(intent, 0.9))
            self.assertEqual((a.use_llm, a.path, a.say), (True, "llm", []))
        flow = self.flow_at("CAUSE")
        self.assertTrue(flow.on_turn("Hail fell", None).use_llm, "with the decision service down every turn goes to the LLM")

    def test_T2_04_two_answers_at_once(self):
        flow = self.flow_at("EVENT")
        self.assertTrue(flow.on_turn("Yes, the hail flattened more than half the crop", route("gives_details")).use_llm)
        a = flow.apply_extraction({"slots": {"damage_confirmed": True, "cause_text": "The hail flattened the crop", "damage_pct": 70}, "answer": ""},
                                  {"value": "hailstorm", "confidence": 0.81})
        self.assertEqual(a.slots, {"damage_confirmed": True, "cause_text": "The hail flattened the crop", "damage_pct": 70, "peril": "hailstorm"})
        self.assertEqual((keys(a), flow.step, a.path), (["khasra"], "KHASRA", "llm"))
        flow.on_turn("yes", route("yes"))
        self.assertEqual(flow.step, "TIME", "cause and extent are not asked again")

    def test_extraction_rules(self):
        flow = self.flow_at("EVENT")
        a = flow.apply_extraction({"slots": {"consent": True, "khasra_confirmed": True, "damage_confirmed": True}})
        self.assertEqual(a.slots, {"damage_confirmed": True}, "a yes/no slot is taken only for the question that was asked")
        flow = self.flow_at("TIME")
        a = flow.apply_extraction({"slots": {"loss_time": "15:45", "loss_time_text": "quarter to four", "damage_pct": 250, "crop_stage": "lying"}})
        self.assertEqual(a.slots, {"loss_datetime": "2026-03-12T15:45:00+05:30", "loss_time_text": "quarter to four"})
        flow = self.flow_at("EVENT")
        a = flow.apply_extraction({"slots": {"damage_confirmed": False}})
        self.assertEqual((keys(a), a.status[0], a.path), (["no_damage"], "NO_DAMAGE", "llm"))
        flow = self.flow_at("CAUSE")
        a = flow.apply_extraction({"slots": {"wants_human": True}})
        self.assertEqual((keys(a), a.end), (["escalate"], "escalated"))
        flow = self.flow_at("CAUSE")
        a = flow.apply_extraction("not json")
        self.assertEqual((keys(a), a.rule), (["rephrase"], "llm_failed"))

    def test_peril_is_accepted_when_the_model_and_the_llm_agree(self):
        flow = self.flow_at("CAUSE")
        a = flow.apply_extraction({"slots": {"cause_text": "Hail fell, the wheat is completely flattened", "peril": "hailstorm"}}, {"value": "hailstorm", "confidence": 0.45})
        self.assertEqual((a.slots["peril"], flow.step), ("hailstorm", "TIME"), "no second question when both name the same cause")
        flow = self.flow_at("CAUSE")
        a = flow.apply_extraction({"slots": {"cause_text": "The crop is spoiled", "peril": "not_covered"}}, {"value": "inundation", "confidence": 0.45})
        self.assertEqual((keys(a), flow.step), (["cause"], "CAUSE"), "they disagree and the model is unsure: ask once more")

    def test_correction_at_the_read_back_is_stored_and_read_back_again(self):
        flow = self.flow_at("CONSENT")
        self.assertTrue(flow.on_turn("no, it was fifty percent", route("no", 0.9)).use_llm, "a no with more words is not a refusal")
        a = flow.apply_extraction({"slots": {"damage_pct": 50, "consent": False}, "answer": ""})
        self.assertEqual((a.rule, a.slots, keys(a), a.end, a.run_pipeline, flow.step), ("corrected", {"damage_pct": 50}, ["consent"], None, False, "CONSENT"))
        self.assertIn("about 50 percent", a.text(flow.call))
        a = flow.on_turn("yes", route("yes"))
        self.assertEqual((a.rule, a.slots), ("consent_yes", {"consent": True}))
        flow = self.flow_at("CONSENT")
        a = flow.on_turn("no sir", route("no", 0.9))
        self.assertEqual((a.rule, a.end), ("no_consent", "escalated"), "a plain no is still a refusal")

    def test_a_share_is_taken_only_when_the_farmer_said_one(self):
        flow = self.flow_at("CAUSE")
        a = flow.apply_extraction({"slots": {"cause_text": "Hail fell", "peril": "hailstorm", "damage_pct": 100}}, {"value": "hailstorm", "confidence": 0.9},
                                  "Hail fell, the wheat is completely flattened.")
        self.assertNotIn("damage_pct", a.slots, "'completely flattened' describes the crop, not a share of the field")
        flow = self.flow_at("CAUSE")
        a = flow.apply_extraction({"slots": {"cause_text": "hail", "damage_pct": 100}}, {"value": "hailstorm", "confidence": 0.9}, "The hail destroyed the whole crop")
        self.assertEqual(a.slots["damage_pct"], 100)
        flow = self.flow_at("EXTENT")
        a = flow.apply_extraction({"slots": {"damage_pct": 100}}, None, "the whole field")
        self.assertEqual(a.slots, {"damage_pct": 100}, "at the extent question the answer is taken as given")

    def test_time_stage_and_llm_sentences_are_taken_only_when_the_farmer_said_them(self):
        said = "Hail fell, the wheat is completely flattened."
        flow = self.flow_at("CAUSE")
        a = flow.apply_extraction({"slots": {"cause_text": "Hail fell", "peril": "hailstorm", "loss_time": "15:30", "crop_stage": "standing"},
                                   "answer": "Crop loss must be reported within 72 hours."}, {"value": "hailstorm", "confidence": 0.9}, said)
        self.assertEqual(set(a.slots), {"cause_text", "peril"}, "hail falling says nothing about the time or the crop stage")
        self.assertEqual((keys(a), flow.step), (["time"], "TIME"), "the farmer asked nothing, so the LLM's sentence is not spoken")
        flow = self.flow_at("CAUSE")
        a = flow.apply_extraction({"slots": {"cause_text": "hail", "loss_time": "15:00", "crop_stage": "standing"}}, {"value": "hailstorm", "confidence": 0.9},
                                  "Hail fell at three o'clock in the afternoon, the crop was standing")
        self.assertEqual((a.slots["loss_datetime"], a.slots["crop_stage"]), ("2026-03-12T15:00:00+05:30", "standing"))
        flow = self.flow_at("EVENT")
        a = flow.apply_extraction({"slots": {}, "answer": "The report must be made within 72 hours."}, None, "How many days do I have to report it?")
        self.assertEqual(a.say[0].text, "The report must be made within 72 hours.", "the farmer asked, so the LLM's sentence is spoken")

    def test_side_question_is_answered_then_the_question_is_asked_again(self):
        flow = self.flow_at("EVENT")
        a = flow.apply_extraction({"slots": {}, "answer": "After the report, a surveyor from the insurance company will contact you."})
        self.assertEqual((keys(a), flow.step), (["<llm>", "event_again"], "EVENT"))
        flow.apply_extraction({"slots": {}, "answer": "Okay."})
        a = flow.apply_extraction({"slots": {}, "answer": "Okay."})
        self.assertEqual((a.rule, a.end, keys(a)[-1]), ("stalled", "escalated", "escalate"), "the same question is asked at most three times")

    def test_peril_low_confidence_asks_once_more(self):
        flow = self.flow_at("CAUSE")
        a = flow.apply_extraction({"slots": {"cause_text": "The crop got spoiled"}}, {"value": "inundation", "confidence": 0.4})
        self.assertEqual((a.slots, keys(a), flow.step), ({"cause_text": "The crop got spoiled"}, ["cause"], "CAUSE"))
        a = flow.apply_extraction({"slots": {"cause_text": "Water filled the field"}}, {"value": "inundation", "confidence": 0.4})
        self.assertEqual((a.slots["peril"], flow.step), ("inundation", "TIME"))
        flow = self.flow_at("CAUSE")
        flow.apply_extraction({"slots": {"cause_text": "I don't know"}}, None)
        a = flow.apply_extraction({"slots": {"cause_text": "I don't know"}}, None)
        self.assertEqual(a.slots["peril"], "not_covered")

    def test_photo_step_evidence_retake_timeout_and_consent(self):
        flow = self.flow_at("STAGE")
        a = flow.apply_extraction({"slots": {"crop_stage": "standing"}})
        self.assertEqual((keys(a), a.status[0], flow.step, flow.expects()), (["photo"], "EVIDENCE", "PHOTO", "evidence"))
        self.assertEqual(keys(flow.on_turn("okay", route("yes"))), ["photo_wait"])
        a = flow.on_evidence("not_a_crop", 0.9, "ev_1")
        self.assertEqual((keys(a), flow.step), (["photo_retake"], "PHOTO"))
        a = flow.on_evidence("hail_damage", 0.82, "ev_2")
        self.assertEqual((keys(a), flow.step, a.status), (["photo_ok", "consent"], "CONSENT", None))
        text = a.text(flow.call)
        self.assertIn("wheat, khasra 214, cause hailstorm, time half past three in the afternoon, about 70 percent damage", text)
        a = flow.on_turn("yes, please do it", route("yes", 0.7))
        self.assertEqual((keys(a), a.status[0], a.run_pipeline, a.slots, flow.step), (["filing"], "PROCESSING", True, {"consent": True}, "FILING"))
        self.assertEqual(keys(flow.on_turn("how long will it take", route("asks_question"))), ["filing_wait"])
        a = flow.on_pipeline_result({"claim_ref": "FCS-000147", "verdict": "eligible"})
        self.assertEqual((keys(a), a.end), (["reference"], "completed"))
        self.assertIn("F, C, S, zero, zero, zero, one, four, seven", a.text(flow.call))

    def test_photo_timeout_and_pipeline_not_ready(self):
        flow = self.flow_at("PHOTO")
        a = flow.on_photo_timeout()
        self.assertEqual((keys(a), flow.step), (["photo_skip", "consent"], "CONSENT"))
        a = flow.on_turn("yes", route("yes"))
        self.assertEqual(a.status, ("PROCESSING", "consent, no photo"))
        self.assertEqual(keys(flow.on_pipeline_result(None)), ["filing_slow"])
        flow = self.flow_at("CONSENT"); flow.on_turn("yes", route("yes"))
        a = flow.on_pipeline_result({"verdict": "review", "claim_ref": None})
        self.assertEqual((keys(a), a.end), (["not_filed"], "escalated"))

    def test_early_photo_is_kept(self):
        flow = self.flow_at("EXTENT")
        self.assertEqual(flow.on_evidence("hail_damage", 0.8, "ev_1").say, [])
        flow.apply_extraction({"slots": {"damage_pct": 50}})
        a = flow.apply_extraction({"slots": {"crop_stage": "standing"}})
        self.assertEqual((keys(a), a.status[0], flow.step), (["photo_ok", "consent"], "EVIDENCE", "CONSENT"))

    def test_short_flow_and_resume(self):
        flow = f.CallFlow(hero(), short=True)
        self.assertEqual(flow.prefilled, {"khasra_confirmed": True, "loss_datetime": "2026-03-12T15:30:00+05:30", "loss_time_text": "recorded storm time",
                                          "crop_stage": "standing"})
        flow.open(); flow.on_turn("yes", route("yes"))
        self.assertEqual((keys(flow.on_turn("yes", route("yes"))), flow.step), (["cause"], "CAUSE"))
        flow.apply_extraction({"slots": {"cause_text": "hail"}}, {"value": "hailstorm", "confidence": 0.9})
        self.assertEqual(flow.step, "EXTENT")
        a = flow.apply_extraction({"slots": {"damage_pct": 50}})
        self.assertEqual((keys(a), flow.step), (["photo"], "PHOTO"))
        resumed = f.CallFlow(hero(identity_confirmed=True, damage_confirmed=True, khasra_confirmed=True))
        a = resumed.open()
        self.assertEqual((keys(a), resumed.step), (["resume", "cause"], "CAUSE"))


class T2_LlmRequest(unittest.TestCase):
    """The LLM path's safety net: when the first request is slow, a second one is sent and the first answer wins."""

    def setUp(self):
        from apps.voice import extract

        self.x = extract
        self.saved = (extract._attempt, extract.chain, extract.HEDGE_AFTER_S, extract.TIMEOUT_S, extract._keep, extract._keep_b, extract.KeepAlive.warm)
        real_add = extract.usage.add
        extract.usage.add = lambda *a, **k: None  # a test must not count as real use in logs/usage.json
        self.addCleanup(setattr, extract.usage, "add", real_add)
        extract.chain = lambda: [("groq", "model-a"), ("gemini", "model-b")]
        extract.HEDGE_AFTER_S, extract.TIMEOUT_S = 0.15, 1.0
        extract.KeepAlive.warm = lambda self, url, timeout=8.0: True
        self.addCleanup(self.restore)

    def restore(self):
        x = self.x
        x._attempt, x.chain, x.HEDGE_AFTER_S, x.TIMEOUT_S, x._keep, x._keep_b, x.KeepAlive.warm = self.saved

    def test_fast_answer_needs_no_second_request(self):
        self.x._attempt = lambda provider, model, system, user, pool: {"data": {"slots": {}}, "provider": provider, "model": model, "ms": 5}
        out = self.x.extract_sync("s", "u")
        self.assertEqual((out["provider"], out["hedged"], out["won"], out["failed"]), ("groq", False, "first", []))

    def test_slow_first_request_is_overtaken_by_the_second(self):
        first_pool = self.x._keep

        def attempt(provider, model, system, user, pool):
            time.sleep(0.8 if pool is first_pool else 0.02)
            return {"data": {"from": "first" if pool is first_pool else "second"}, "provider": provider, "model": model, "ms": 1}

        self.x._attempt = attempt
        second_pool = self.x._keep_b
        t0 = time.time()
        out = self.x.extract_sync("s", "u")
        self.assertEqual((out["data"], out["hedged"], out["won"]), ({"from": "second"}, True, "second"))
        self.assertLess(time.time() - t0, 0.6, "the answer must not wait for the slow request")
        self.assertIs(self.x._keep, second_pool, "the connection that answered becomes the main one")
        self.assertIsNot(self.x._keep_b, first_pool, "the stuck connection is replaced")

    def test_error_moves_to_the_next_provider_and_total_failure_is_reported(self):
        def attempt(provider, model, system, user, pool):
            if provider == "groq":
                raise OSError("network down")
            return {"data": {"ok": True}, "provider": provider, "model": model, "ms": 1}

        self.x._attempt = attempt
        out = self.x.extract_sync("s", "u")
        self.assertEqual((out["provider"], out["failed"][0]["provider"]), ("gemini", "groq"))
        self.x._attempt = lambda *a: (_ for _ in ()).throw(ValueError("bad json"))
        out = self.x.extract_sync("s", "u")
        self.assertIsNone(out["data"])
        self.assertEqual([f["provider"] for f in out["failed"]], ["groq", "gemini"])


class T2_Words(unittest.TestCase):
    def test_times_and_references(self):
        self.assertEqual(words.clock(15, 30), "half past three in the afternoon")
        self.assertEqual(words.clock(16, 45), "quarter to five in the evening")
        self.assertEqual(words.clock(9, 15), "quarter past nine in the morning")
        self.assertEqual(words.clock(21, 10), "9:10 at night")
        self.assertEqual(words.clock_from_iso("2026-03-12T15:00:00+05:30"), "three o'clock in the afternoon")
        self.assertEqual(words.digits("FCS-000147"), "F, C, S, zero, zero, zero, one, four, seven")

    def test_every_line_renders_in_english(self):
        call = hero()
        for key in lines.LINES:
            spoken = lines.render(key, call, peril="hailstorm", time="3 o'clock in the afternoon", pct="70", ref_spoken=words.digits("FCS-000147"))
            self.assertNotIn("{", spoken, key)
            self.assertTrue(spoken.isascii(), f"{key}: the call is in English only")


class SseReader:
    """Collects the JSON messages of a Server-Sent Events stream in a background thread."""

    def __init__(self, service: str, path: str) -> None:
        self.messages: list[dict] = []
        self._conn = http.client.HTTPConnection("127.0.0.1", u.PORT[service], timeout=30)
        self._conn.request("GET", path)
        self._resp = self._conn.getresponse()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            while True:
                line = self._resp.readline()
                if not line:
                    return
                if line.startswith(b"data: "):
                    self.messages.append(json.loads(line[6:].decode("utf-8")))
        except Exception:
            return

    def wait_for(self, type_: str, seconds: float = 5.0) -> dict | None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            for m in self.messages:
                if m.get("type") == type_:
                    return m
            time.sleep(0.05)
        return None

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.sock.shutdown(socket.SHUT_RDWR)  # wakes the reading thread; closing alone would wait for the next keep-alive
        with contextlib.suppress(Exception):
            self._conn.close()


class WithOrchestrator(unittest.TestCase):
    EXTRA_ENV: dict = {}

    @classmethod
    def setUpClass(cls):
        cls.s = u.Services("orchestrator", LIVEKIT_URL="wss://example.invalid", LIVEKIT_API_KEY="testkey", LIVEKIT_API_SECRET="s" * 40, **cls.EXTRA_ENV)
        cls.addClassCleanup(cls.s.close)

    def setUp(self):
        self.assertEqual(u.call("POST", u.url("orchestrator", "/api/scenario/reset"), {})[0], 200)
        self.mark = len(self.s.events())  # the event log is shared by the tests of a class

    def events(self) -> list[dict]:
        return self.s.events()[self.mark:]

    def api(self, method: str, path: str, payload: dict | None = None):
        return u.call(method, u.url("orchestrator", path), payload)

    def types(self, case_id: str | None = None) -> list[str]:
        return [e["type"] for e in self.events() if case_id is None or e["case_id"] == case_id]


class T2_15_Evidence(WithOrchestrator):
    PHOTO = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 20 + b"\xff\xd9"
    META = {"label": "hail_damage", "confidence": 0.82, "latency_ms": 41, "edge_mode": "zeroshot", "lat": 23.0192, "lon": 76.7211,
            "captured_at": "2026-10-07T10:15:00Z", "captured_offline": False}

    def upload(self, case_id: str, meta: dict, content: bytes | None = None, ctype: str = "image/jpeg"):
        status, _, body = u.post_form(u.url("orchestrator", f"/api/cases/{case_id}/evidence"), {"meta": json.dumps(meta)},
                                      {"photo": ("crop.jpg", self.PHOTO if content is None else content, ctype)})
        return status, json.loads(body)

    def test_T2_15_photo_is_stored_hashed_and_announced(self):
        case = self.api("POST", "/api/cases", {"farmer_id": "F0001"})[1]
        status, out = self.upload(case["id"], self.META)
        self.assertEqual(status, 201, out)
        self.assertEqual(out["sha256"], hashlib.sha256(self.PHOTO).hexdigest())
        with u._opener.open(u.url("orchestrator", f"/api/evidence/{out['evidence_id']}/photo"), timeout=10) as r:
            self.assertEqual(r.read(), self.PHOTO, "the stored file is the uploaded file")
        stored = self.api("GET", f"/api/cases/{case['id']}")[1]["evidence"]
        self.assertEqual(len(stored), 1)
        self.assertEqual((stored[0]["edge_label"], stored[0]["edge_confidence"], stored[0]["lat"], stored[0]["captured_offline"], stored[0]["sha256"]),
                         ("hail_damage", 0.82, 23.0192, False, out["sha256"]))
        event = [e for e in self.events() if e["type"] == "evidence.received"][0]
        self.assertEqual((event["case_id"], event["live"], event["data"]["evidence_id"], event["data"]["edge_label"]), (case["id"], True, out["evidence_id"], "hail_damage"))
        self.assertEqual(event["data"]["thumb_url"], f"/api/evidence/{out['evidence_id']}/photo")
        status, second = self.upload(case["id"], {**self.META, "captured_offline": True})
        self.assertEqual((status, second["evidence_id"] != out["evidence_id"]), (201, True))

    def test_T2_15b_bad_uploads_are_refused(self):
        case = self.api("POST", "/api/cases", {"farmer_id": "F0001"})[1]
        self.assertEqual(self.upload(case["id"], {**self.META, "label": "tractor"})[0], 400)
        self.assertEqual(self.upload(case["id"], {**self.META, "confidence": 7})[0], 400)
        self.assertEqual(self.upload(case["id"], self.META, ctype="text/plain")[0], 415)
        self.assertEqual(self.upload(case["id"], self.META, content=b"")[0], 400)
        self.assertEqual(self.upload("case_9999", self.META)[0], 404)
        self.assertEqual(self.api("GET", f"/api/cases/{case['id']}")[1]["evidence"], [])


class T2_Calls(WithOrchestrator):
    def test_hero_call_rings_the_phone_and_accept_returns_a_room_token(self):
        phone = SseReader("orchestrator", "/api/farmer/F0001/stream")
        self.addCleanup(phone.close)
        self.assertIsNotNone(phone.wait_for("connected"))
        t0 = time.time()
        status, out = self.api("POST", "/api/hero/call", {})
        self.assertEqual((status, out["farmer_id"], out["case_id"], out["phones"]), (200, "F0001", "case_0001", 1), out)
        ring = phone.wait_for("call.incoming", 2.0)
        self.assertIsNotNone(ring, "the phone must ring within 2 seconds")
        self.assertLess(time.time() - t0, 2.0)
        self.assertEqual((ring["data"]["call_id"], ring["data"]["case_id"]), (out["call_id"], "case_0001"))
        self.assertEqual(self.api("GET", "/api/cases/case_0001")[1]["status"], "CALLING")
        self.assertEqual(self.api("POST", "/api/hero/call", {})[0], 409, "a second ring while the first is ringing is refused")

        status, room = self.api("POST", f"/api/calls/{out['call_id']}/accept", {})
        self.assertEqual(status, 200, room)
        self.assertEqual((room["livekit_url"], room["room"]), ("wss://example.invalid", out["room"]))
        claims = livekit_token.decode_unverified(room["token"])
        self.assertTrue(livekit_token.verify(room["token"], "s" * 40))
        self.assertEqual((claims["iss"], claims["sub"], claims["video"]["room"], claims["video"]["roomJoin"]), ("testkey", "farmer-F0001", out["room"], True))
        dispatch = claims["roomConfig"]["agents"][0]
        self.assertEqual((dispatch["agentName"], json.loads(dispatch["metadata"])), ("intake", {"case_id": "case_0001", "call_id": out["call_id"]}))
        case = self.api("GET", "/api/cases/case_0001")[1]
        self.assertEqual((case["status"], case["attempts"], case["calls"][0]["room"], case["storm"]["started_at"]),
                         ("IN_CALL", 1, out["room"], "2026-03-12T15:30:00+05:30"))

        self.assertEqual(self.api("POST", f"/api/calls/{out['call_id']}/end", {"outcome": "bogus"})[0], 400)
        self.assertEqual(self.api("POST", f"/api/calls/{out['call_id']}/end", {"outcome": "dropped"})[1]["outcome"], "dropped")
        self.assertEqual(self.api("POST", f"/api/calls/{out['call_id']}/end", {"outcome": "completed"})[1]["outcome"], "dropped", "the first report wins")
        types = self.types("case_0001")
        for needed in ("case.created", "call.started", "case.status_changed", "call.ended"):
            self.assertIn(needed, types)
        ended = [e for e in self.events() if e["type"] == "call.ended" and e["data"]["call_id"] == out["call_id"]]
        self.assertEqual((len(ended), ended[0]["data"]["outcome"]), (1, "dropped"))
        # the call dropped part-way: ringing again continues the same case
        status, again = self.api("POST", "/api/hero/call", {})
        self.assertEqual((status, again["call_id"] != out["call_id"]), (200, True), again)
        self.assertEqual(self.api("GET", "/api/cases/case_0001")[1]["attempts"], 2)

    def test_decline_then_ring_again(self):
        out = self.api("POST", "/api/hero/call", {})[1]
        self.assertEqual(out["phones"], 0, "no phone is connected in this test")
        self.assertEqual(self.api("POST", f"/api/calls/{out['call_id']}/decline", {})[1]["outcome"], "declined")
        self.assertEqual(self.api("GET", "/api/cases/case_0001")[1]["status"], "NO_ANSWER")
        self.assertEqual(self.api("POST", f"/api/calls/{out['call_id']}/accept", {})[0], 409)
        again = self.api("POST", "/api/hero/call", {})[1]
        self.assertEqual((again["call_id"], self.api("GET", "/api/cases/case_0001")[1]["attempts"]), ("call_0001_2", 2))
        self.assertEqual(self.api("POST", "/api/calls/call_nope/accept", {})[0], 404)

    def test_a_phone_that_connects_late_still_rings(self):
        out = self.api("POST", "/api/hero/call", {})[1]
        phone = SseReader("orchestrator", "/api/farmer/F0001/stream")
        self.addCleanup(phone.close)
        ring = phone.wait_for("call.incoming", 2.0)
        self.assertEqual(ring["data"]["call_id"], out["call_id"])

    def test_consent_refused_while_waiting_for_the_photo_can_escalate(self):
        case = self.api("POST", "/api/cases", {"farmer_id": "F0002"})[1]
        for status in ("QUEUED", "CALLING", "IN_CALL", "EVIDENCE", "ESCALATED"):
            self.assertEqual(self.api("POST", f"/api/cases/{case['id']}/status", {"status": status})[0], 200, status)


class T2_RingTimeout(WithOrchestrator):
    EXTRA_ENV = {"RING_TIMEOUT_S": "1"}

    def test_unanswered_call_stops_ringing(self):
        phone = SseReader("orchestrator", "/api/farmer/F0001/stream")
        self.addCleanup(phone.close)
        phone.wait_for("connected")
        out = self.api("POST", "/api/hero/call", {})[1]
        self.assertIsNotNone(phone.wait_for("call.incoming", 2.0))
        cancelled = phone.wait_for("call.cancelled", 4.0)
        self.assertEqual(cancelled["data"]["call_id"], out["call_id"])
        case = self.api("GET", "/api/cases/case_0001")[1]
        self.assertEqual((case["status"], case["calls"][0]["outcome"]), ("NO_ANSWER", "no_answer"))


class T2_Brain(unittest.TestCase):
    """A whole call as text: the flow rules, the decision service, the registry MCP server and the orchestrator together.
    The decision service runs its keyword test provider here; the LLM is replaced by canned extractions."""

    EXTRACTIONS = {
        "Yes, the hail flattened more than half the crop": {"slots": {"damage_confirmed": True, "cause_text": "The hail flattened the crop", "damage_pct": 70}, "answer": ""},
        "Around three o'clock": {"slots": {"loss_time": "15:00", "loss_time_text": "Around three o'clock"}, "answer": ""},
        "It was standing in the field": {"slots": {"crop_stage": "standing"}, "answer": ""},
        "When will the surveyor come?": {"slots": {}, "answer": "After the report, a surveyor from the insurance company will contact you."},
    }

    @classmethod
    def setUpClass(cls):
        cls.s = u.Services("orchestrator", "registry", "s1", S1_CHAIN_TEXT="mock", S1_CHAIN_REPORT="mock")
        cls.addClassCleanup(cls.s.close)
        for key, service, path in (("ORCH_URL", "orchestrator", ""), ("MCP_REGISTRY_URL", "registry", "/mcp"), ("S1_URL", "s1", "")):
            setattr(config, key, u.url(service, path))

    def setUp(self):
        self.assertEqual(u.call("POST", u.url("orchestrator", "/api/scenario/reset"), {})[0], 200)
        self.mark = len(self.s.events())

    def make_brain(self, **kw):
        from apps.voice import brain as brain_mod
        from apps.voice import services as services_mod

        case = u.call("POST", u.url("orchestrator", "/api/cases"), {"farmer_id": "F0001"})[1]
        for status in ("QUEUED", "CALLING", "IN_CALL"):
            u.call("POST", u.url("orchestrator", f"/api/cases/{case['id']}/status"), {"status": status})
        call = lines.CallContext.from_case(u.call("GET", u.url("orchestrator", f"/api/cases/{case['id']}"))[1])
        self.assertEqual(call.storm_started_at, "2026-03-12T15:30:00+05:30")
        test = self

        class CannedLlm(services_mod.Services):
            asked: list[str] = []

            async def extract(self, *, step, question, utterance, known):
                self.asked.append(utterance)
                test.assertIn(utterance, test.EXTRACTIONS, "this turn was not expected to reach the LLM")
                return {"data": test.EXTRACTIONS[utterance], "provider": "canned", "model": "test", "ms": 1, "total_ms": 1, "failed": []}

        services = CannedLlm(call)
        services.asked = []
        return brain_mod.CallBrain(call, services, **kw), services

    def case(self) -> dict:
        return u.call("GET", u.url("orchestrator", "/api/cases/case_0001"))[1]

    def events(self, type_: str) -> list[dict]:
        return [e for e in self.s.events()[self.mark:] if e["type"] == type_]

    def test_remark_during_photo_wait_is_not_consent(self):
        """Found in the first spoken test: "yes, go on" said while waiting for the photo arrived as the photo timer ran out, and
        was taken as the answer to the consent question that had not been asked yet."""
        async def run():
            brain, _ = self.make_brain()
            await brain.open()
            for utterance in ("Yes, speaking.", "Yes, the hail flattened more than half the crop", "yes", "Around three o'clock", "It was standing in the field"):
                await brain.farmer_turn(utterance)
            self.assertTrue(brain.waiting_for_photo)
            real_route = brain.services.route

            async def slow_route(*a):
                out = await real_route(*a)
                await asyncio.sleep(0.3)  # the timer runs out while the remark is still being read
                return out

            brain.services.route = slow_route
            turn = asyncio.create_task(brain.farmer_turn("yes, go on"))
            await asyncio.sleep(0.05)
            timeout = asyncio.create_task(brain.photo_timeout())
            return brain, await turn, await timeout

        brain, turn, timeout = asyncio.run(run())
        self.assertEqual((turn.rule, turn.run_pipeline), ("photo_wait", False))
        self.assertEqual(timeout.rule, "photo_skip")
        self.assertEqual((brain.flow.step, brain.flow.slots["consent"]), ("CONSENT", None))

    def test_happy_path_as_text(self):
        async def run():
            brain, services = self.make_brain()
            said = [(await brain.open())]
            for utterance in ("Yes, speaking.", "Yes, the hail flattened more than half the crop", "yes", "Around three o'clock", "It was standing in the field"):
                said.append(await brain.farmer_turn(utterance))
            self.assertTrue(brain.waiting_for_photo)
            said.append(await brain.farmer_turn("yes okay"))
            said.append(await brain.evidence("hail_damage", 0.82, "ev_0001_1"))
            said.append(await brain.farmer_turn("yes"))
            self.assertTrue(said[-1].run_pipeline)
            said.append(await brain.pipeline())
            await brain.flush()
            return brain, services, said

        brain, services, said = asyncio.run(run())
        time.sleep(1.0)  # events are posted from background threads
        # The phone announced a photo on the call but none was uploaded, so the pipeline (Phase 3) sends the case to a person.
        self.assertEqual([r.rule for r in said], ["open", "yes", "llm", "yes", "llm", "llm", "photo_wait", "evidence", "consent_yes", "not_filed"])
        self.assertEqual([r.path for r in said], ["scripted", "fast", "llm", "fast", "llm", "llm", "fast", "scripted", "fast", "scripted"])
        self.assertEqual(services.asked, ["Yes, the hail flattened more than half the crop", "Around three o'clock", "It was standing in the field"], "plain yes turns never reach the LLM")
        self.assertIn("Khajuriya Kalan", said[1].text)
        self.assertIn("khasra number 214", said[2].text)
        self.assertIn("what time", said[3].text, "cause and extent were given together, so the next question is the time")
        self.assertIn("cause hailstorm, time three o'clock in the afternoon, about 70 percent", said[7].text)
        self.assertEqual((said[-1].end, said[-1].segments[0][1]), ("escalated", True))
        case = self.case()
        self.assertEqual(case["slots"], {"identity_confirmed": True, "damage_confirmed": True, "khasra_confirmed": True, "cause_text": "The hail flattened the crop",
                                         "peril": "hailstorm", "loss_time_text": "Around three o'clock", "loss_datetime": "2026-03-12T15:00:00+05:30",
                                         "damage_pct": 70, "crop_stage": "standing", "consent": True})
        self.assertEqual((case["status"], case["verdict"], case["verdict_reasons"][0]), ("ESCALATED", "review", "No usable photo: none was received"))
        decisions = [e["data"]["decision"] for e in self.events("s1.decision")]
        self.assertEqual((decisions.count("ROUTE"), decisions.count("PERIL")), (7, 1))
        self.assertTrue(all(e["live"] for e in self.events("s1.decision")))
        tools = [e["data"]["tool"] for e in self.events("mcp.tool_called")]
        self.assertIn("update_case_slots", tools)
        self.assertEqual(tools.count("set_case_status"), 2)  # EVIDENCE, then PROCESSING
        farmer_turns = [e["data"] for e in self.events("call.turn")]
        self.assertEqual([t["path"] for t in farmer_turns], ["fast", "llm", "fast", "llm", "llm", "fast", "fast"])
        self.assertTrue(all(t["speaker"] == "farmer" and "s1" in t["latency_ms"] for t in farmer_turns))
        self.assertGreaterEqual(len(self.events("call.slot")), 10)
        # this test runs without the weather and price servers: their absence is shown, and nothing else fell back
        self.assertEqual({e["data"]["component"] for e in self.events("fallback.used")}, {"mcp weather", "mcp mandi"})

    def test_endings_as_text(self):
        async def ending(turns: list[str], **kw):
            brain, _ = self.make_brain(**kw)
            await brain.open()
            reply = None
            for t in turns:
                reply = await brain.farmer_turn(t)
            await brain.flush()
            return reply

        for turns, rule, status, outcome in (
                (["no, wrong number"], "wrong_person", "ESCALATED", "wrong_person"),
                (["yes", "no, the crop is fine"], "no_damage", "NO_DAMAGE", "completed"),
                (["yes", "I want to talk to a person"], "wants_human", "ESCALATED", "escalated")):
            u.call("POST", u.url("orchestrator", "/api/scenario/reset"), {})
            reply = asyncio.run(ending(turns))
            self.assertEqual((reply.rule, reply.end, self.case()["status"]), (rule, outcome, status), turns)

    def test_side_question_and_short_flow(self):
        async def run():
            brain, services = self.make_brain(short=True)
            await brain.open()
            await brain.farmer_turn("yes")
            answer = await brain.farmer_turn("When will the surveyor come?")
            await brain.flush()
            return brain, answer

        brain, answer = asyncio.run(run())
        self.assertEqual(answer.segments, [("After the report, a surveyor from the insurance company will contact you.", False), ("Was your wheat crop damaged?", True)])
        slots = self.case()["slots"]
        self.assertEqual((slots["khasra_confirmed"], slots["crop_stage"], slots["loss_datetime"], slots["identity_confirmed"]),
                         (True, "standing", "2026-03-12T15:30:00+05:30", True))

    def test_decision_service_down_sends_every_turn_to_the_llm(self):
        from apps.voice import brain as brain_mod

        async def run():
            brain, services = self.make_brain()
            saved = config.S1_URL
            config.S1_URL = "http://127.0.0.1:9"  # nothing listens here
            try:
                test_extractions = dict(self.EXTRACTIONS)
                self.EXTRACTIONS["yes"] = {"slots": {"identity_confirmed": True}, "answer": ""}
                await brain.open()
                reply = await brain.farmer_turn("yes")
            finally:
                config.S1_URL = saved
                self.EXTRACTIONS.clear(); self.EXTRACTIONS.update(test_extractions)
            await brain.flush()
            return reply

        reply = asyncio.run(run())
        time.sleep(0.5)
        self.assertEqual((reply.path, reply.rule), ("llm", "llm"))
        self.assertIn("s1", [e["data"]["component"] for e in self.events("fallback.used")])


FAKE_LIVEKIT = """
window.__lk = {connects: [], data: [], mic: []};
window.LivekitClient = {
  RoomEvent: {TrackSubscribed: "trackSubscribed", Disconnected: "disconnected"},
  Track: {Kind: {Audio: "audio"}},
  Room: class {
    constructor() {
      this.handlers = {};
      this.localParticipant = {
        setMicrophoneEnabled: async (on) => { window.__lk.mic.push(on); },
        publishData: async (bytes, opts) => { window.__lk.data.push({text: new TextDecoder().decode(bytes), topic: opts.topic}); },
      };
    }
    on(ev, fn) { this.handlers[ev] = fn; return this; }
    async connect(url, token) { window.__lk.connects.push({url, token}); }
    async startAudio() {}
    async disconnect() {}
  },
};
"""
FAKE_TRANSFORMERS = """
export const env = {};
export class RawImage {
  constructor(data, width, height, channels) { this.width = width; this.height = height; }
  static async fromBlob(blob) { return new RawImage(null, 8, 8, 3); }
}
export const AutoProcessor = { from_pretrained: async () => (async (image) => ({ pixel_values: image })) };
export const CLIPVisionModelWithProjection = { from_pretrained: async () => (async () => ({
  image_embeds: { normalize() { return { tolist() { return [[1, 0, 0, 0]]; } }; } } })) };
"""
FAKE_LABELS = {"model": "test", "vision_dtype": "fp32", "temperature": 100, "dim": 4, "labels": [
    {"id": "hail_damage", "name": "Hail damage", "embedding": [1, 0, 0, 0]}, {"id": "waterlogged", "name": "Field under water", "embedding": [0, 1, 0, 0]},
    {"id": "lodged", "name": "Crop flattened", "embedding": [0, 0, 1, 0]}, {"id": "healthy", "name": "Crop is healthy", "embedding": [0, 0, 0, 1]},
    {"id": "not_a_crop", "name": "Not a crop photo", "embedding": [0.5, 0.5, 0.5, 0.5]}]}


class T2_FarmerApp(WithOrchestrator):
    """The farmer app in a headless browser with a fake camera. The call library and the photo model come from the internet on a
    real phone; here they are replaced by small stand-ins, so this checks our own code: ring, answer, photo, upload, offline queue."""

    def test_pages_are_served(self):
        for path, needle in (("/farmer", "Turn on phone"), ("/static/farmer.js", "call.incoming"), ("/static/edge-worker.js", "label_embeddings.json"),
                             ("/sw.js", "ghante72-"), ("/static/farmer.css", "--ground")):
            with u._opener.open(u.url("orchestrator", path), timeout=10) as r:
                self.assertEqual(r.status, 200, path)
                self.assertIn(needle, r.read().decode("utf-8"), path)
        self.assertEqual(self.api("GET", "/api/farmers/F0001")[1], {"id": "F0001", "name": "Ramlal Verma", "village": "Khajuriya Kalan"})
        self.assertEqual(self.api("GET", "/api/farmers/F9999")[0], 404)

    def test_ring_answer_photo_upload_and_offline_queue(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed here; the phone tests T2-01, T2-10 and T2-12 are done by hand")
        with sync_playwright() as p:
            try:
                browser = u.launch_chromium(p, args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
            except Exception as e:
                self.skipTest(f"no browser for Playwright: {type(e).__name__}")
            context = browser.new_context(viewport={"width": 390, "height": 800}, service_workers="block", permissions=["geolocation", "camera", "microphone"],
                                          geolocation={"latitude": 23.0191, "longitude": 76.7212})
            context.route("https://cdn.jsdelivr.net/npm/livekit-client**", lambda r: r.fulfill(content_type="text/javascript", body=FAKE_LIVEKIT))
            context.route("https://cdn.jsdelivr.net/npm/@huggingface/transformers**", lambda r: r.fulfill(
                content_type="text/javascript", body=FAKE_TRANSFORMERS, headers={"Access-Control-Allow-Origin": "*"}))
            context.route("**/static/label_embeddings.json", lambda r: r.fulfill(content_type="application/json", body=json.dumps(FAKE_LABELS)))
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(u.url("orchestrator", "/farmer?farmer=F0001"))
            page.wait_for_function("document.getElementById('model').textContent === 'Photo check ready'", timeout=15000)
            self.assertIn("Ramlal Verma", page.inner_text("#who"))
            page.click("#btn-start")
            page.wait_for_selector("#screen-idle:not([hidden])")

            # ring and answer
            ring = self.api("POST", "/api/hero/call", {})[1]
            self.assertEqual(ring["phones"], 1)
            page.wait_for_selector("#screen-ring:not([hidden])", timeout=2000)
            page.click("#btn-accept")
            page.wait_for_function("document.getElementById('call-state').textContent === 'Call in progress'", timeout=5000)
            lk = page.evaluate("window.__lk")
            self.assertEqual((len(lk["connects"]), lk["connects"][0]["url"], lk["mic"]), (1, "wss://example.invalid", [True]))
            self.assertEqual(livekit_token.decode_unverified(lk["connects"][0]["token"])["video"]["room"], ring["room"])
            self.assertEqual(self.api("GET", "/api/cases/case_0001")[1]["status"], "IN_CALL")

            # photo during the call: camera, on-phone check, upload, message to the agent
            page.click("#btn-photo-call")
            page.wait_for_function("document.getElementById('video').videoWidth > 0", timeout=10000)
            page.click("#btn-shutter")
            page.wait_for_function("document.getElementById('photo-label').textContent === 'Hail damage'", timeout=10000)
            self.assertIn("No internet needed", page.inner_text("#photo-detail"))
            page.click("#btn-send")
            page.wait_for_selector("#screen-call:not([hidden])")
            page.wait_for_function("window.__lk.data.length === 1", timeout=10000)
            evidence = self.api("GET", "/api/cases/case_0001")[1]["evidence"]
            self.assertEqual(len(evidence), 1)
            self.assertEqual((evidence[0]["edge_label"], evidence[0]["edge_mode"], evidence[0]["gps_source"], evidence[0]["captured_offline"], round(evidence[0]["lat"], 4)),
                             ("hail_damage", "zeroshot", "phone", False, 23.0191))
            self.assertGreater(evidence[0]["edge_confidence"], 0.9)
            message = page.evaluate("window.__lk.data[0]")
            self.assertEqual((message["topic"], json.loads(message["text"])["evidence_id"], json.loads(message["text"])["edge_label"]),
                             ("evidence", evidence[0]["id"], "hail_damage"))

            # the farmer hangs up
            page.click("#btn-hangup")
            page.wait_for_selector("#screen-idle:not([hidden])")
            deadline = time.time() + 5
            while time.time() < deadline and self.api("GET", "/api/cases/case_0001")[1]["calls"][0]["outcome"] is None:
                time.sleep(0.1)
            self.assertEqual(self.api("GET", "/api/cases/case_0001")[1]["calls"][0]["outcome"], "dropped")

            # T2-12 with no network: the photo is checked on the phone, kept, and sent when the network returns
            context.set_offline(True)
            page.click("#btn-photo-idle")
            page.wait_for_function("document.getElementById('video').videoWidth > 0", timeout=10000)
            page.click("#btn-shutter")
            page.wait_for_function("document.getElementById('photo-label').textContent === 'Hail damage'", timeout=10000)
            page.click("#btn-send")
            page.wait_for_selector("#queue-note:not([hidden])", timeout=8000)
            self.assertEqual(len(self.api("GET", "/api/cases/case_0001")[1]["evidence"]), 1, "nothing can arrive while the phone is offline")
            t0 = time.time()
            context.set_offline(False)
            while time.time() - t0 < 10 and len(self.api("GET", "/api/cases/case_0001")[1]["evidence"]) < 2:
                time.sleep(0.2)
            evidence = self.api("GET", "/api/cases/case_0001")[1]["evidence"]
            self.assertEqual(len(evidence), 2, "the queued photo must arrive within 10 seconds of the network returning")
            self.assertEqual((evidence[1]["captured_offline"], evidence[1]["edge_label"]), (True, "hail_damage"))
            self.assertEqual(page.evaluate("window.__lk.data.length"), 1, "no message to the agent when no call is running")

            # a call that is declined
            self.api("POST", "/api/scenario/reset", {})
            ring = self.api("POST", "/api/hero/call", {})[1]
            page.wait_for_selector("#screen-ring:not([hidden])", timeout=2000)
            page.click("#btn-decline")
            page.wait_for_selector("#screen-idle:not([hidden])")
            deadline = time.time() + 5
            while time.time() < deadline and self.api("GET", "/api/cases/case_0001")[1]["status"] != "NO_ANSWER":
                time.sleep(0.1)
            self.assertEqual(self.api("GET", "/api/cases/case_0001")[1]["status"], "NO_ANSWER")
            size = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
            self.assertEqual(size[0], size[1], "the phone screen must not scroll sideways")
            self.assertEqual(errors, [])
            page.screenshot(path=str(pathlib.Path(self.s.tmp) / "farmer.png"))
            browser.close()

    def test_ring_arrives_when_a_tunnel_holds_back_the_stream(self):
        """The phone link (localhost.run) can buffer the event stream, so call.incoming never arrives. The page also polls."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed here")
        with sync_playwright() as p:
            try:
                browser = u.launch_chromium(p, args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
            except Exception as e:
                self.skipTest(f"no browser for Playwright: {type(e).__name__}")
            context = browser.new_context(viewport={"width": 390, "height": 800}, service_workers="block", permissions=["camera", "microphone"])
            context.route("https://cdn.jsdelivr.net/npm/livekit-client**", lambda r: r.fulfill(content_type="text/javascript", body=FAKE_LIVEKIT))
            context.route("https://cdn.jsdelivr.net/npm/@huggingface/transformers**", lambda r: r.fulfill(
                content_type="text/javascript", body=FAKE_TRANSFORMERS, headers={"Access-Control-Allow-Origin": "*"}))
            context.route("**/static/label_embeddings.json", lambda r: r.fulfill(content_type="application/json", body=json.dumps(FAKE_LABELS)))
            context.route("**/api/farmer/*/stream", lambda r: r.abort())   # the stream never gets through
            page = context.new_page()
            page.goto(u.url("orchestrator", "/farmer?farmer=F0001"))
            page.click("#btn-start")
            page.wait_for_selector("#screen-idle:not([hidden])")
            time.sleep(2.5)
            self.assertEqual(self.api("GET", "/health")[1]["hero_phones"], 1, "a polling phone counts as connected")
            ring = self.api("POST", "/api/hero/call", {})[1]
            self.assertEqual(ring["phones"], 1)
            page.wait_for_selector("#screen-ring:not([hidden])", timeout=5000)
            page.click("#btn-decline")
            page.wait_for_selector("#screen-idle:not([hidden])")
            time.sleep(3)
            self.assertTrue(page.is_visible("#screen-idle"), "a declined call must not ring again from a late poll")
            self.api("POST", "/api/scenario/reset", {})   # call ids start again after a reset; the same id must ring again
            time.sleep(2.5)
            self.api("POST", "/api/hero/call", {})
            page.wait_for_selector("#screen-ring:not([hidden])", timeout=5000)
            browser.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
