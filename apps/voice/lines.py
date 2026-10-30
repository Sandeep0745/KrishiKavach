"""Scripted English lines of the call (SystemDesign §10.2) and the values that fill them.

Pure Python with no LiveKit import, so the lines can be tested anywhere and reused by the audio-cache builder.
Someone on the team must read every line aloud once and correct anything that sounds unnatural.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import words, languages
from ghante_shared import config

LINES: dict[str, str] = {
    "greet": "Hello, am I speaking with {name} ji?",
    "event": "I am calling from crop insurance help; I am an automated assistant. A hailstorm was recorded in your village, {village}, "
             "this afternoon. Was your {crop} crop damaged?",
    "khasra": "I am sorry to hear that. The insurer must be told within seventy-two hours, and I can do that for you now. "
              "Was the damage in the field with khasra number {khasra}?",
    "cause": "What caused the damage: hail, heavy rain, water standing in the field, or something else?",
    "time": "At about what time did it happen?",
    "extent": "About how much of the field is damaged: less than half, half, more than half, or all of it?",
    "stage": "Was the crop standing in the field, or was it cut and lying in the field?",
    "photo": "Now please press the 'Take photo' button on the phone and take one photo of the damaged crop. I am on the line.",
    "photo_ok": "I have the photo.",
    "consent": "Let me repeat: {crop}, khasra {khasra}, cause {peril}, time {time}, about {pct} percent damage. "
               "Shall I file this report for you?",
    "filing": "All right, I am filling in the form. It takes about a minute; please stay on the line.",
    "reference": "Your report has been filed. Your reference number is {ref_spoken}. It has also been sent to you as a message. "
                 "The insurance company will contact you for the survey. Thank you, goodbye.",
    "no_damage": "Good to hear that your crop is fine. If you see damage later, tell the helpline within seventy-two hours. Thank you.",
    "escalate": "All right, one of our colleagues will call you shortly. Thank you.",
    "wrong_person": "Sorry, wrong number. Thank you.",
    "rephrase": "Sorry, I did not understand. Please say that once more.",
    "no_consent": "All right, I am not filing anything now. Our colleague will speak with you.",
    "filing_slow": "This is taking a little longer. You will get the reference number in a message. Thank you.",
    # lines added while building the call (Phase 2)
    "resume": "Hello {name} ji, this is crop insurance help calling again. Our last call was cut short.",
    "event_again": "Was your {crop} crop damaged?",
    "khasra_again": "Was the damage in the field with khasra number {khasra}?",
    "photo_wait": "Please take your time with the photo. I am on the line.",
    "photo_retake": "This does not look like a photo of the crop. Please take one more photo of the damaged crop.",
    "photo_skip": "The photo did not come through. No problem, our colleague will take one later.",
    "not_filed": "The report could not be filed just now. Our colleague will call you soon. Thank you.",
    "filing_wait": "The form is being filled in. Just a little longer.",
}

# The message card sent to the farmer's phone when the report is filed (shown as a simulated SMS; it is read, not spoken).
MESSAGE_FILED = ("Crop insurance help: your crop loss report has been filed. Reference number {claim_ref}. "
                 "The insurance company will contact you for the survey.")


@dataclass
class CallContext:
    """What the agent knows about the farmer before the first word. Built from the case loaded through the registry MCP server."""
    case_id: str
    farmer_id: str = ""
    name_en: str = ""
    village_en: str = ""
    crop_en: str = "wheat"
    khasra: str = ""
    is_hero: bool = False
    slots: dict = field(default_factory=dict)
    storm_started_at: str = ""   # ISO time of the recorded storm; the default loss time in the short flow
    plot_lat: float | None = None
    plot_lon: float | None = None
    language: str = "en-IN"  # direct text fixtures remain English; real registry calls use the state default

    @property
    def first_name(self) -> str:
        return (self.name_en or "").split(" ")[0]

    @classmethod
    def from_case(cls, case: dict) -> "CallContext":
        farmer, village, policy = case.get("farmer") or {}, case.get("village") or {}, case.get("policy") or {}
        storm = case.get("storm") or {}
        return cls(case_id=case["id"], farmer_id=case.get("farmer_id", ""), name_en=farmer.get("name", ""),
                   village_en=village.get("name", ""), crop_en=policy.get("crop", "wheat"), khasra=str(policy.get("khasra_no", "")),
                   is_hero=bool(case.get("is_hero")), slots=dict(case.get("slots") or {}), storm_started_at=storm.get("started_at") or "",
                   plot_lat=policy.get("plot_lat"), plot_lon=policy.get("plot_lon"),
                   language=(languages.initial(village.get("state", ""), village.get("district", ""), config.env("VOICE_DEFAULT_LANGUAGE"))
                             if config.env("VOICE_MULTILINGUAL", "1") != "0" else "en-IN"))


def _values(call: CallContext, extra: dict) -> dict:
    values = {"name": call.first_name, "village": call.village_en, "crop": call.crop_en, "khasra": call.khasra,
              "peril": "", "time": "", "pct": "", "ref_spoken": ""}
    values.update(extra)
    return values


def render(key: str, call: CallContext, *, language: str | None = None, **extra) -> str:
    """The text of a scripted line with the farmer's values filled in."""
    language = languages.code(language or call.language) or "en-IN"
    values = _values(call, extra)
    if language != "en-IN":
        glossary = languages.GLOSSARY[language]
        values["crop"] = glossary.get(str(values["crop"]).lower(), values["crop"])
        values["peril"] = glossary.get(extra.get("peril_code"), values["peril"])
        if extra.get("loss_datetime"):
            values["time"] = extra["loss_datetime"][11:16]
    return languages.TRANSLATIONS.get(language, LINES)[key].format(**values)
