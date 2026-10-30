"""Everything the call needs from outside the voice process: the decision service, the LLM, the registry MCP server and the
orchestrator. All functions are async and never raise for an ordinary outage: they return None and the call carries on with a
fallback, which is reported as a fallback.used event.
"""
from __future__ import annotations

import asyncio
import time

from ghante_shared import config, http, mcp_client

from . import extract as extract_mod
from . import prompts, languages
from .lines import CallContext


class Services:
    def __init__(self, call: CallContext) -> None:
        self.call = call
        self._reported: set[str] = set()

    # ---------- events ----------
    def emit(self, type_: str, data: dict, agent: str = "intake") -> None:
        http.post_event(config.ORCH_URL, type_, data, case_id=self.call.case_id, agent=agent, live=self.call.is_hero)

    def fallback(self, component: str, from_: str, to: str, reason: str) -> None:
        key = f"{component}:{from_}:{to}"
        if key in self._reported:  # say it once per call, not on every turn
            return
        self._reported.add(key)
        self.emit("fallback.used", {"component": component, "from": from_, "to": to, "reason": reason[:160]})

    # ---------- decision service ----------
    async def _decide(self, decision: str, state: dict) -> dict | None:
        body = {"decision": decision, "case_id": self.call.case_id, "state": state, "live": self.call.is_hero}
        try:
            return await asyncio.to_thread(http.post_json, f"{config.S1_URL}/decide", body, 4.0)
        except Exception as e:  # noqa: BLE001
            self.fallback("s1", "decision service", "llm", f"{decision}: {type(e).__name__}")
            return None

    async def route(self, question: str, expected: str, utterance: str) -> dict | None:
        """ROUTE for one farmer reply: {"intent", "confidence", "distress", "ms", "provider"} or None when the service is down."""
        t0 = time.perf_counter()
        out = await self._decide("ROUTE", {"agent_question": question, "expected": expected, "utterance": utterance})
        if not out:
            return None
        intent = out["answers"].get("intent") or {}
        distress = out["answers"].get("distress") or {}
        p_distress = float(distress.get("confidence") or 0.0) if distress.get("value") is True else 0.0
        return {"intent": intent.get("value"), "confidence": float(intent.get("confidence") or 0.0), "distress": p_distress,
                "ms": round((time.perf_counter() - t0) * 1000), "model_ms": out.get("latency_ms"), "provider": out.get("provider")}

    async def peril(self, cause_text: str, crop_stage: str | None) -> dict | None:
        out = await self._decide("PERIL", {"cause_text": cause_text, "crop_stage": crop_stage or "standing"})
        if not out:
            return None
        answer = out["answers"].get("peril") or {}
        return {"value": answer.get("value"), "confidence": float(answer.get("confidence") or 0.0)}

    # ---------- conversation LLM ----------
    async def warm(self) -> None:
        """Open the LLM connection while the greeting plays, so the first detail turn does not pay for the handshake."""
        try:
            await asyncio.to_thread(extract_mod.warm)
        except Exception:  # noqa: BLE001
            pass

    async def extract(self, *, step: str, question: str, utterance: str, known: dict) -> dict:
        user = prompts.extract_user(self.call, step=step, question=question, utterance=utterance, known=known)
        out = await asyncio.to_thread(extract_mod.extract_sync, prompts.extract_system(self.call), user)
        for failure in out["failed"]:
            nxt = out["provider"] or "ask again"
            self.fallback("llm", f"{failure['provider']}:{failure['model']}", nxt, failure["reason"])
        data = out.get("data")
        if isinstance(data, dict) and isinstance(data.get("answer"), str) and data["answer"].strip():
            answer_language = languages.script_language(data["answer"])
            expected_script = None if self.call.language == "en-IN" else self.call.language
            if answer_language != expected_script:
                self.fallback("reply_language", "llm answer", self.call.language, "answer did not use the selected language")
                data["answer"] = languages.ANSWER_FALLBACK[self.call.language]
        return out

    # ---------- case record, through the registry MCP server ----------
    async def save_slots(self, slots: dict) -> None:
        await mcp_client.call_tool(config.MCP_REGISTRY_URL, "update_case_slots", {"case_id": self.call.case_id, "slots": slots},
                                   server="registry", client="intake", case_id=self.call.case_id)

    async def set_status(self, status: str, reason: str) -> None:
        await mcp_client.call_tool(config.MCP_REGISTRY_URL, "set_case_status", {"case_id": self.call.case_id, "status": status, "reason": reason},
                                   server="registry", client="intake", case_id=self.call.case_id)

    # ---------- orchestrator ----------
    async def run_pipeline(self) -> dict | None:
        """Start filing and wait for the reference (SystemDesign §6). None when it fails or the pipeline is not built yet."""
        try:
            return await asyncio.to_thread(http.post_json, f"{config.ORCH_URL}/api/cases/{self.call.case_id}/pipeline/run", {}, 95.0)
        except Exception as e:  # noqa: BLE001
            self.fallback("pipeline", "filing on the call", "reference by message", f"{type(e).__name__}: {str(e)[:80]}")
            return None

    async def end_call(self, call_id: str | None, outcome: str) -> None:
        if not call_id:
            return
        try:
            await asyncio.to_thread(http.post_json, f"{config.ORCH_URL}/api/calls/{call_id}/end", {"outcome": outcome}, 5.0)
        except Exception:  # noqa: BLE001 - the call is over either way
            pass
