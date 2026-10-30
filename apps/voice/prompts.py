"""Prompts for the conversation LLM (SystemDesign §10.4).

On the LLM path the model does one job per turn: read what the farmer said and return JSON with the facts it contains and,
if the farmer asked something, one short English sentence in answer. The call flow (apps/voice/flow.py) decides what is asked next,
so the wording of every question stays scripted and comes from the audio cache.
"""
from __future__ import annotations

import json

from .lines import CallContext

EXTRACT_SYSTEM = """A phone assistant is filing a crop-loss report for an Indian farmer who speaks English (speech-recognition text, may have small errors). You get the question the assistant asked and the farmer's reply. Return ONE JSON object, nothing else:
{"slots": {"identity_confirmed": true|false|null, "damage_confirmed": true|false|null, "khasra_confirmed": true|false|null, "consent": true|false|null, "cause_text": string|null, "peril": "hailstorm"|"inundation"|"unseasonal_rain"|"natural_fire"|"not_covered"|null, "loss_time": "HH:MM"|null, "loss_time_text": string|null, "damage_pct": number|null, "crop_stage": "standing"|"harvested"|null, "wants_human": true|false}, "answer": string}

Slots: fill one only if the farmer said it in THIS reply, in words; otherwise null. Never guess, never infer one fact from another (hail falling says nothing about the time, the share damaged or the crop stage).
- identity_confirmed: is this the farmer asked for ("wrong number", "he is not here" = false). damage_confirmed: was the crop damaged. khasra_confirmed: was the damage in the plot the assistant named. consent: agrees that the report is filed now.
- cause_text: the farmer's words for the cause. peril: hailstorm = hail; inundation = water standing in the field, flood; unseasonal_rain = rain on a crop that was already cut; natural_fire = fire, lightning; not_covered = insects, disease, drought, animals, theft.
- loss_time: only if the farmer says when. 24-hour: "three o'clock" in the afternoon = "15:00", "half past three" = "15:30", "five in the evening" = "17:00". If asked for the time and the reply is only "in the afternoon" or "when the hail fell", use storm_time. loss_time_text: the farmer's words.
- damage_pct: only if the farmer states a share. less than half = 30, half = 50, more than half = 70, the whole field / the whole crop = 100, or the number said ("seventy percent" = 70). "flattened", "fell over", "a lot of damage" are not a share: null.
- crop_stage: only if said. standing = the crop was standing; harvested = it was cut and lying in the field.
- wants_human: true only if the farmer asks for a person or an officer.
- At step CONSENT the details were read back. If the farmer corrects one ("no, it was seventy percent"), fill that slot and leave consent null.

answer: "" unless the farmer asked a question. Then ONE short sentence of simple spoken English (no question in it), using only these facts: crop loss must be reported to the insurer within seventy-two hours; after the report a surveyor from the insurance company contacts the farmer; the caller is an automated assistant of the crop insurance help desk; it cannot say when or how much will be paid. If the facts do not cover it, say a colleague will explain. Never promise money or a date; never ask for Aadhaar, bank details or an OTP."""


def extract_user(call: CallContext, *, step: str, question: str, utterance: str, known: dict) -> str:
    storm_time = call.storm_started_at[11:16] if len(call.storm_started_at) >= 16 else ""
    return json.dumps({
        "farmer": {"name": call.name_en, "village": call.village_en, "crop": call.crop_en, "plot_number": call.khasra},
        "response_language": call.language,
        "storm_time": storm_time,
        "step": step,
        "assistant_asked": question,
        "farmer_said": utterance,
        "already_known": {k: v for k, v in known.items() if v is not None},
    }, ensure_ascii=False)


def extract_system(call: CallContext) -> str:
    from .languages import SUPPORTED
    return EXTRACT_SYSTEM + ("\nThe farmer reply is an English translation of speech. Keep slot values and cause_text in English. "
                             "The answer field, when needed, must be in " + SUPPORTED[call.language] + ". Never translate enum values.")


def instructions(call: CallContext) -> str:
    """Instructions for LiveKit's own LLM object. It only speaks if the structured path is unavailable."""
    return (
        "You are a polite female assistant calling a farmer on behalf of a crop insurance help desk. "
        f"Speak in {call.language}. Use short sentences, at most two per turn, and ask one question at a time. "
        "Your output is spoken aloud: no lists, no symbols.\n"
        f"Farmer: {call.name_en}, village {call.village_en}. Crop: {call.crop_en}. Khasra number: {call.khasra}. "
        "A hailstorm was recorded in the village this afternoon.\n"
        "Facts you may state: crop loss must be reported to the insurer within 72 hours; after the report a surveyor contacts the farmer. "
        "You cannot say when or how much will be paid. Never promise money or a date. Never ask for Aadhaar, bank details or an OTP. "
        "If asked anything else, say that a person from the team will help."
    )
