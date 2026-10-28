"""The four System One decisions (SystemDesign §8.2): which kind of input each takes and how the state is rendered."""
from __future__ import annotations

from ghante_shared import config

# kind "text": a reply from the call -> S1_CHAIN_TEXT.  kind "report": a short English report -> S1_CHAIN_REPORT.
KIND = {"ROUTE": "text", "PERIL": "text", "TRIAGE": "report", "VERIFY": "report"}

PHOTO_WORDS = {"hail_damage": "a crop damaged by hail", "lodged": "a damaged crop flattened by the storm", "waterlogged": "a waterlogged field",
               "healthy": "a healthy, undamaged crop", "not_a_crop": "something that is not a crop field"}

ROUTE_INTENTS = ["yes", "no", "gives_details", "asks_question", "wants_human", "wrong_person", "unclear"]
PERIL_LABELS = ["hailstorm", "inundation", "unseasonal_rain", "natural_fire", "not_covered"]

QUESTIONS = {
    "ROUTE": {
        "intent": {"type": "choice", "instructions": "A phone agent asked `agent_question`. What is the farmer doing in `farmer_reply`?", "criteria": {
            "yes": "a plain yes, agreement or confirmation", "no": "a plain no, refusal or denial",
            "gives_details": "states facts such as cause of damage, time, how much area, or crop stage",
            "asks_question": "asks the agent a question, for example about money or the survey",
            "wants_human": "asks to talk to a person or an officer instead of the assistant",
            "wrong_person": "says it is a wrong number or that the person asked for is not here",
            "unclear": "unrelated, garbled or impossible to understand"}},
        "distress": {"type": "noul", "instructions": "Is the speaker in `farmer_reply` crying, panicking or very angry?"},
    },
    "PERIL": {
        "peril": {"type": "choice", "instructions": "What caused the crop damage described in `cause_text`?", "criteria": {
            "hailstorm": "hail or hailstones", "inundation": "flooding or standing water in the field",
            "unseasonal_rain": "rain falling on a crop that was already cut", "natural_fire": "fire or lightning",
            "not_covered": "pests, insects, disease, drought, animals or theft"}},
    },
    "TRIAGE": {
        "damage_likelihood": {"type": "choice", "instructions": "Read `report`. How likely is serious crop damage on this farm?", "criteria": {
            "high": "severe hail and the farm is very close to the storm core",
            "medium": "moderate hail at a middle distance",
            "low": "light hail and the farm is far from the storm core"}},
    },
    "VERIFY": {
        # Phase 1 measurement: a second question ("needs human review") always came back "no" from Laya, so it was dropped.
        # Human review is decided from this one answer plus the plain rules in the Eligibility agent.
        "evidence_consistent": {"type": "noul", "instructions": "Read `report`. Do the farmer's statement, the photo and the weather record agree with each other?"},
    },
}


def chain_for(decision: str) -> list[str]:
    name = "S1_CHAIN_TEXT" if KIND[decision] == "text" else "S1_CHAIN_REPORT"
    default = "head,llm" if KIND[decision] == "text" else "laya,llm"
    return [p.strip() for p in config.env(name, default).split(",") if p.strip()]


def text_of(decision: str, state: dict) -> str:
    """The text a text decision is about."""
    if decision == "ROUTE":
        return str(state.get("utterance") or state.get("farmer_reply") or "")
    return str(state.get("cause_text") or "")


def render_report(decision: str, state: dict) -> str:
    """English sentences for report decisions. Phase 0 showed Laya needs sentences, not a raw field dictionary."""
    if decision == "TRIAGE":
        parts = [f"Hail intensity at this village was {state.get('hail_intensity', 'unknown')}.",
                 f"The farm is {state.get('distance_km', '?')} km from the storm core.",
                 f"Crop: {state.get('crop', 'wheat')}, {state.get('crop_stage', 'close to harvest')}."]
        if state.get("notes"):
            parts.append(f"Note: {state['notes']}.")
        return " ".join(parts)
    if decision == "VERIFY":
        # Wording measured in Phase 3 (scripts/spikes/verify_wording.py, Phase3Results.md). With the exact figures in the text
        # ("27.8 mm", "0 minutes", "7 metres") Laya called 94 of 120 consistent cases inconsistent, the hero's among them. Said in
        # words, with the figures turned into what they mean, it passed 120 of 120. The figures themselves are judged by the
        # eligibility rules (SystemDesign §13, checks 7 to 7b), with the same limits as here.
        distance, minutes = state.get("distance_from_plot_m"), state.get("minutes_from_storm")
        place = ("at the insured plot" if distance is None or float(distance) <= 2000 else f"far from the insured plot, {round(float(distance) / 1000)} km away")
        when = ("matches the time of the recorded storm" if minutes is None or abs(float(minutes)) <= 180
                else f"is {round(abs(float(minutes)) / 60)} hours away from the recorded storm")
        weather = "a hailstorm" if state.get("hail") else ("rain but no hail" if float(state.get("precipitation_mm") or 0) > 0 else "clear weather with no hail")
        return (f"The farmer says the crop was damaged by {str(state.get('peril', 'unknown')).replace('_', ' ')}. "
                f"The photo taken on the phone shows {PHOTO_WORDS.get(str(state.get('edge_label')), 'an unclear scene')}. "
                f"The weather record for that place and time shows {weather}. The photo was taken {place}. The time the farmer gave {when}.")
    raise ValueError(decision)


def laya_inputs(decision: str, state: dict) -> tuple[dict, dict]:
    """(state, questions) in the form Laya expects."""
    if KIND[decision] == "report":
        return {"report": render_report(decision, state)}, QUESTIONS[decision]
    if decision == "ROUTE":
        return {"agent_question": str(state.get("agent_question", "")), "farmer_reply": text_of(decision, state)}, QUESTIONS[decision]
    return {"cause_text": text_of(decision, state)}, QUESTIONS[decision]
