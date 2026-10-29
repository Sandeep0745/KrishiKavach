"""Simulator (SystemDesign §12.3 and §12.4, FR-50): plays the non-hero farmers from their scripted personas.

A simulated farmer has no voice and no phone. What is simulated is the farmer's side only: whether the call is answered and
what is said. The case then goes through the same case store, the same eligibility rules, the same decision model and a real
record in the sandbox portal. Nothing here calls an LLM, a speech service or the browser agent.
"""
from __future__ import annotations

import random

from ghante_shared import models

from .cases import CaseStore
from .clock import SimClock

RETRY_AFTER_S = 30 * 60        # scenario seconds before an unanswered farmer is called again
PERIL_WORDS = (("hail", "hailstorm"), ("insect", "not_covered"), ("caterpillar", "not_covered"), ("water", "inundation"), ("flood", "inundation"),
               ("fire", "natural_fire"))
HERO_PERSONA = {"outcome": "files", "answer_on_attempt": 1,
                "answers": {"cause_text": "Hail fell", "loss_time": "15:30", "damage_pct": 70, "crop_stage": "standing"},
                "photo": {"label": "hail_damage", "confidence": 0.82}, "gps_offset_m": 120}


def peril_of(cause_text: str) -> str:
    """Keyword map for scripted answers (there is no speech to classify)."""
    for word, peril in PERIL_WORDS:
        if word in cause_text.lower():
            return peril
    return "not_covered"


def answers_on(persona: dict, attempt: int) -> bool:
    if persona["outcome"] == "no_answer":
        return False
    return attempt >= int(persona.get("answer_on_attempt") or 1)


class Simulator:
    def __init__(self, store: CaseStore, clock: SimClock) -> None:
        self.store, self.clock = store, clock

    async def call(self, case_id: str, persona: dict) -> str:
        """One call attempt. Returns "retry" (not answered, call again later), "unreachable", "closed" (the call settled the case)
        or "process" (details and evidence collected: the pipeline should run)."""
        store, clock = self.store, self.clock
        call = store.place_call(case_id, "dispatch")
        rng = random.Random(f"{case_id}:{call['attempt']}")  # the same run every time
        await clock.sleep(rng.uniform(20, 40))               # ringing
        await clock.wait_running()
        if not answers_on(persona, call["attempt"]):
            store.end_call(call["id"], "no_answer")          # CALLING -> NO_ANSWER
            if call["attempt"] >= 3:
                store.set_status(case_id, models.UNREACHABLE, "no answer on three attempts", agent="dispatcher")
                return "unreachable"
            return "retry"
        store.answer_call(call["id"])                        # CALLING -> IN_CALL
        await clock.sleep(rng.uniform(120, 240))             # talking
        await clock.wait_running()
        outcome, answers = persona["outcome"], persona.get("answers") or {}
        if outcome == "no_damage":
            store.update_slots(case_id, {"identity_confirmed": True, "damage_confirmed": False}, agent="intake", announce=False)
            store.set_status(case_id, models.NO_DAMAGE, "farmer reports no damage", agent="intake")
            store.end_call(call["id"], "completed")
            return "closed"
        if outcome == "wants_human":
            store.update_slots(case_id, {"identity_confirmed": True}, agent="intake", announce=False)
            store.set_status(case_id, models.ESCALATED, "farmer asked for a person", agent="intake")
            store.end_call(call["id"], "escalated")
            return "closed"
        storm_day = (store.storm() or {}).get("started_at", "")[:10]
        cause = str(answers.get("cause_text") or "")
        store.update_slots(case_id, {
            "identity_confirmed": True, "damage_confirmed": True, "khasra_confirmed": True, "cause_text": cause, "peril": peril_of(cause),
            "loss_time_text": str(answers.get("loss_time") or ""), "loss_datetime": f"{storm_day}T{answers.get('loss_time', '15:30')}:00+05:30",
            "damage_pct": answers.get("damage_pct"), "crop_stage": answers.get("crop_stage") or "standing", "consent": True}, agent="intake", announce=False)
        store.set_status(case_id, models.EVIDENCE, "details collected", agent="intake")
        store.add_sim_evidence(case_id, persona.get("photo") or {}, float(persona.get("gps_offset_m") or 0))
        store.set_status(case_id, models.PROCESSING, "photo and consent", agent="intake")
        store.end_call(call["id"], "completed")
        return "process"
