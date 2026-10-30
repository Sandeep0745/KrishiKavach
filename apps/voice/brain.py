"""One call from the first word to the last: the flow rules plus the outside services. No LiveKit in here.

The LiveKit agent (agent.py) hands every farmer turn to `farmer_turn` and speaks the Reply it gets back. Because nothing in this
file touches audio, a whole conversation can be run and checked as text.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field

from . import flow as flow_mod
from . import languages
from .lines import CallContext
from .services import Services


@dataclass
class Reply:
    text: str = ""                 # to be spoken
    path: str = "scripted"         # fast | llm | scripted
    rule: str = ""
    end: str | None = None         # call outcome: the call ends after this is spoken
    run_pipeline: bool = False
    latency_ms: dict = field(default_factory=dict)
    segments: list[tuple[str, bool]] = field(default_factory=list)  # (text, is_scripted) in speaking order
    language: str = "en-IN"
    spoken: bool = False           # set by the voice layer once the words have been said


class CallBrain:
    def __init__(self, call: CallContext, services: Services | None = None, *, short: bool = False, fast_min: float | None = None) -> None:
        self.call = call
        self.services = services or Services(call)
        kwargs = {"fast_min": fast_min} if fast_min is not None else {}
        self.flow = flow_mod.CallFlow(call, short=short, **kwargs)
        self._writes: asyncio.Queue = asyncio.Queue()
        self._writer: asyncio.Task | None = None
        self._warm: asyncio.Task | None = None
        self.turns = 0
        # One thing at a time changes the call: a farmer turn, the photo, the photo timer, the filing result. Without this the
        # photo timer could move the call to the consent question while a remark made before it was still being read, and
        # that remark ("yes, go on") was then taken as consent.
        self._lock = asyncio.Lock()

    # ---------- storing slots and status in order, without making the farmer wait ----------
    def _write(self, kind: str, *args) -> None:
        self._writes.put_nowait((kind, args))
        if self._writer is None or self._writer.done():
            self._writer = asyncio.create_task(self._drain())

    async def _drain(self) -> None:
        while not self._writes.empty():
            kind, args = self._writes.get_nowait()
            try:
                if kind == "slots":
                    await self.services.save_slots(*args)
                else:
                    await self.services.set_status(*args)
            except Exception as e:  # noqa: BLE001 - a failed write must not stop the call
                self.services.fallback("registry", kind, "kept in memory", f"{type(e).__name__}: {str(e)[:80]}")
            finally:
                self._writes.task_done()

    async def flush(self) -> None:
        """Wait until everything collected so far is stored."""
        if self._writer is not None:
            with contextlib.suppress(Exception):
                await self._writer
        if not self._writes.empty():
            await self._drain()

    def _reply(self, action: flow_mod.Action, latency: dict | None = None) -> Reply:
        if action.slots:
            self._write("slots", dict(action.slots))
        if action.status:
            self._write("status", *action.status)
        segments = [(s.spoken(self.call), s.key is not None) for s in action.say if s.spoken(self.call)]
        return Reply(text=action.text(self.call), path=action.path, rule=action.rule, end=action.end,
                     run_pipeline=action.run_pipeline, latency_ms=dict(latency or {}), segments=segments, language=self.call.language)

    # ---------- the call ----------
    async def open(self) -> Reply:
        self._warm = asyncio.create_task(self.services.warm())
        action = self.flow.open()
        if self.flow.prefilled:  # short flow: values taken from the policy and the storm record
            self._write("slots", dict(self.flow.prefilled))
        return self._reply(action)

    async def farmer_turn(self, utterance: str, *, detected_language: str | None = None, language_confidence: float = 1.0) -> Reply:
        """Utterance is the English STT translation; metadata retains the farmer's spoken language."""
        async with self._lock:
            if self.flow.ended:
                return self._reply(flow_mod.Action(rule="ended"))
            old = self.call.language
            self.call.language = languages.choose(utterance, old, detected_language, language_confidence)
            if self.call.language != old:
                self.services.emit("call.language_changed", {"from": old, "to": self.call.language,
                                                            "source": "request" if languages.requested(utterance) else "speech"})
            if languages.repeat_request(utterance) and self.flow.step in flow_mod.STEP:
                self.services.emit("call.turn", {"speaker": "farmer", "text": utterance, "language": self.call.language,
                                                 "translated": bool(detected_language), "path": "scripted", "latency_ms": {}})
                # Do not count a language preference as an answer, a refusal, or a failed question attempt.
                text = languages.CONFIRM[self.call.language] + " " + self.flow.question()
                return Reply(text=text, rule="language_repeat", language=self.call.language, segments=[(text, True)])
            return await self._farmer_turn(utterance, translated=bool(detected_language))

    async def _farmer_turn(self, utterance: str, *, translated: bool = False) -> Reply:
        utterance = (utterance or "").strip()
        self.turns += 1
        t0 = time.perf_counter()
        latency: dict = {}
        question, expected, step = self.flow.question(language="en-IN"), self.flow.expects(), self.flow.step
        route = await self.services.route(question, expected, utterance) if utterance else {"intent": "unclear", "confidence": 1.0, "distress": 0.0}
        if route:
            latency["s1"] = route.get("ms", 0)
        action = self.flow.on_turn(utterance, route)
        if action.use_llm:
            out = await self.services.extract(step=step, question=question, utterance=utterance, known=self.flow.slots)
            latency["llm"] = out.get("total_ms", 0)
            if out.get("hedged"):
                latency["hedged"] = 1  # the first request was slow and a second one was sent
            if out.get("tokens"):
                latency["tokens"] = out["tokens"]
            if out.get("model"):
                latency["model"] = out["model"]
            data = out.get("data")
            peril = None
            cause = ((data or {}).get("slots") or {}).get("cause_text") if isinstance(data, dict) else None
            if isinstance(cause, str) and cause.strip() and self.flow.slots.get("peril") is None:
                peril = await self.services.peril(cause.strip(), self.flow.slots.get("crop_stage"))
            asked = (route or {}).get("intent") == "asks_question" or bool(flow_mod.QUESTION_WORDS.search(utterance))
            action = self.flow.apply_extraction(data, peril, utterance, asked)
        latency["brain"] = round((time.perf_counter() - t0) * 1000)
        self.services.emit("call.turn", {"speaker": "farmer", "text": utterance, "path": action.path,
                                         "latency_ms": {k: latency[k] for k in ("s1", "llm", "hedged") if k in latency},
                                         "llm_tokens": latency.get("tokens"), "llm_model": latency.get("model"),
                                         "language": self.call.language, "translated": translated})
        return self._reply(action, latency)

    async def evidence(self, label: str | None, confidence: float | None = None, evidence_id: str | None = None) -> Reply:
        async with self._lock:
            return self._reply(self.flow.on_evidence(label, confidence, evidence_id))

    async def photo_timeout(self) -> Reply:
        async with self._lock:
            return self._reply(self.flow.on_photo_timeout())

    async def pipeline(self) -> Reply:
        """Called after consent: store what was collected, start filing, and return the closing words."""
        await self.flush()
        result = await self.services.run_pipeline()
        async with self._lock:
            return self._reply(self.flow.on_pipeline_result(result))

    @property
    def waiting_for_photo(self) -> bool:
        return self.flow.step == "PHOTO" and not self.flow.ended
