"""The call as a state machine (SystemDesign §10.2 and §10.3). Pure Python: no LiveKit, no network.

The voice agent feeds it what happened (a farmer turn with its ROUTE answer, what the LLM extracted, a photo, the pipeline
result) and it answers with an Action: what to say, which slots to store, whether the case changes status, whether the call ends.
Keeping the rules here means every row of the rule table can be tested without a microphone.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import lines, words

FAST_PATH_MIN = 0.5        # lowest ROUTE confidence for a plain yes/no to skip the LLM (measured in Phase 1)
FAST_MAX_WORDS = 5         # a longer reply may carry details, so it always goes to the LLM
WANTS_HUMAN_MIN = 0.6
WRONG_PERSON_MIN = 0.7
DISTRESS_MIN = 0.7
PERIL_MIN = 0.6            # below this the agent asks for the cause once more
NO_CONSENT_MAX_WORDS = 2   # "no", "no sir": a longer reply at the read-back may be a correction
MAX_ASKS = 3               # the same question is asked at most this many times before a person takes over
_NUMBER_WORDS = r"ten|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred"
# Words that state a share of the field. "the wheat is completely flattened" describes how the crop looks; "the whole crop",
# "more than half" state a share.
SHARE_WORDS = re.compile(r"\b(?:half(?! past)|percent|per cent|(?:whole|entire|full|complete) (?:field|crop|farm)|all of (?:it|the)|everything|"
                         r"quarter(?! (?:past|to))|third|acre|bigha|hectare|" + _NUMBER_WORDS + r")\b|%|[0-9]", re.IGNORECASE)
# The same idea for the time and the crop stage: outside their own question they are taken only if the farmer used such a word.
TIME_WORDS = re.compile(r"o'?clock|\b(?:[ap]\.?m|morning|afternoon|evening|night|noon|hours?|time|half past|quarter (?:past|to))\b|[0-9]", re.IGNORECASE)
STAGE_WORDS = re.compile(r"\b(?:standing|stood|cut|harvest\w*|reap\w*|threshing|lying|kept|bundles?)\b", re.IGNORECASE)
# A sentence written by the LLM is spoken only when the farmer asked something.
QUESTION_WORDS = re.compile(r"\?|\b(what|when|who|whom|how|why|where|which)\b", re.IGNORECASE)
BOOL_SLOTS = ("identity_confirmed", "damage_confirmed", "khasra_confirmed", "consent")


@dataclass(frozen=True)
class Step:
    name: str
    line: str             # scripted line that asks for it
    expects: str          # yes_no | detail | evidence
    slot: str | None      # the slot whose value completes the step
    again: str | None = None  # shorter wording when the question has to be repeated


STEPS = [
    Step("GREET", "greet", "yes_no", "identity_confirmed"),
    Step("EVENT", "event", "yes_no", "damage_confirmed", again="event_again"),
    Step("KHASRA", "khasra", "yes_no", "khasra_confirmed", again="khasra_again"),
    Step("CAUSE", "cause", "detail", "peril"),
    Step("TIME", "time", "detail", "loss_datetime"),
    Step("EXTENT", "extent", "detail", "damage_pct"),
    Step("STAGE", "stage", "detail", "crop_stage"),
    Step("PHOTO", "photo", "evidence", None),
    Step("CONSENT", "consent", "yes_no", "consent"),
]
STEP = {s.name: s for s in STEPS}
SHORT_SKIPS = ("KHASRA", "TIME", "STAGE")


@dataclass
class Say:
    """One thing to speak: a scripted line (key) or a sentence written by the LLM (text)."""
    key: str | None = None
    text: str | None = None
    values: dict = field(default_factory=dict)

    def spoken(self, call: lines.CallContext) -> str:
        return lines.render(self.key, call, **self.values) if self.key else (self.text or "")


@dataclass
class Action:
    rule: str                                  # which rule fired; used by tests and the log
    path: str = "fast"                         # fast | llm | scripted
    say: list[Say] = field(default_factory=list)
    slots: dict = field(default_factory=dict)  # slot values to store
    status: tuple[str, str] | None = None      # (new case status, reason)
    end: str | None = None                     # call outcome when the call ends after speaking
    use_llm: bool = False                      # hand the turn to the LLM for extraction, then call apply_extraction
    run_pipeline: bool = False                 # consent given: start filing

    def text(self, call: lines.CallContext) -> str:
        return " ".join(s.spoken(call) for s in self.say if s.spoken(call))


class CallFlow:
    def __init__(self, call: lines.CallContext, *, short: bool = False, fast_min: float = FAST_PATH_MIN) -> None:
        self.call = call
        self.short = short
        self.fast_min = fast_min
        self.slots: dict = {name: None for name in ("identity_confirmed", "damage_confirmed", "khasra_confirmed", "cause_text", "peril",
                                                    "loss_time_text", "loss_datetime", "damage_pct", "crop_stage", "consent")}
        self.slots.update({k: v for k, v in (call.slots or {}).items() if k in self.slots})
        self.resumed = any(v is not None for v in self.slots.values())
        self.prefilled: dict = {}
        if short:
            for key, value in (("khasra_confirmed", True), ("loss_datetime", call.storm_started_at or None),
                               ("loss_time_text", "recorded storm time" if call.storm_started_at else None), ("crop_stage", "standing")):
                if self.slots[key] is None and value is not None:
                    self.slots[key] = value
                    self.prefilled[key] = value
        self.evidence: dict | None = None
        self.photo_skipped = False
        self.photo_retakes = 0
        self.peril_clarified = False
        self.unclear_streak = 0
        self.asked: dict[str, int] = {}
        self.status_evidence_sent = False
        self.ended: str | None = None
        self.step: str = "GREET"

    # ---------- where we are ----------
    def _done(self, step: Step) -> bool:
        if step.name == "PHOTO":
            return self.evidence is not None or self.photo_skipped
        return self.slots.get(step.slot) is not None

    def next_step(self) -> str | None:
        for step in STEPS:
            if not self._done(step):
                return step.name
        return None

    def expects(self) -> str:
        return STEP[self.step].expects if self.step in STEP else "detail"

    def question(self, *, language: str | None = None) -> str:
        """The question the farmer is answering now (given to ROUTE and to the LLM)."""
        if self.step not in STEP:
            return ""
        return lines.render(STEP[self.step].line, self.call, language=language, **self._values(self.step))

    def _values(self, step_name: str) -> dict:
        if step_name != "CONSENT":
            return {}
        pct = self.slots.get("damage_pct")
        peril = self.slots.get("peril") or "not_covered"
        return {"peril": words.PERIL_EN.get(peril, words.PERIL_EN["not_covered"]), "time": words.clock_from_iso(self.slots.get("loss_datetime")),
                "pct": str(pct) if isinstance(pct, int) else "", "peril_code": peril, "loss_datetime": self.slots.get("loss_datetime")}

    # ---------- building actions ----------
    def _ask(self, step_name: str, *, again: bool = False) -> list[Say]:
        step = STEP[step_name]
        self.asked[step_name] = self.asked.get(step_name, 0) + 1
        key = step.again if (again and step.again) else step.line
        return [Say(key=key, values=self._values(step_name))]

    def _advance(self, rule: str, path: str, before: list[Say] | None = None, slots: dict | None = None) -> Action:
        """Move to the first step that is not done and ask its question."""
        action = Action(rule=rule, path=path, say=list(before or []), slots=dict(slots or {}))
        nxt = self.next_step()
        if nxt is None:  # everything collected and consent given
            return action
        repeat = nxt == self.step
        if repeat and self.asked.get(nxt, 0) >= MAX_ASKS:
            return self._end(rule="stalled", path=path, line="escalate", status=("ESCALATED", f"no usable answer at {nxt}"), outcome="escalated",
                             before=action.say, slots=action.slots)
        self.step = nxt
        if nxt in ("PHOTO", "CONSENT") and not self.status_evidence_sent:  # CONSENT directly: the photo arrived early
            self.status_evidence_sent = True
            action.status = ("EVIDENCE", "details collected, waiting for the photo")
        if nxt == "CONSENT" and self.evidence is not None and not repeat:
            action.say.append(Say(key="photo_ok"))
        action.say.extend(self._ask(nxt, again=repeat))
        return action

    def _end(self, *, rule: str, path: str, line: str, status: tuple[str, str] | None, outcome: str, before: list[Say] | None = None,
             slots: dict | None = None) -> Action:
        self.ended = outcome
        self.step = "END"
        return Action(rule=rule, path=path, say=[*(before or []), Say(key=line)], slots=dict(slots or {}), status=status, end=outcome)

    def _store(self, updates: dict) -> dict:
        changed = {k: v for k, v in updates.items() if k in self.slots and v is not None and self.slots[k] != v}
        self.slots.update(changed)
        return changed

    # ---------- events ----------
    def open(self) -> Action:
        """First words of the call."""
        if self.resumed and self.slots.get("identity_confirmed"):
            action = self._advance("resume", "scripted", before=[Say(key="resume")])
            return action
        self.step = "GREET"
        return Action(rule="open", path="scripted", say=self._ask("GREET"))

    def on_turn(self, utterance: str, route: dict | None) -> Action:
        """One farmer turn. `route` is the ROUTE answer: {"intent", "confidence", "distress"}; None when the decision service is down."""
        if self.ended:
            return Action(rule="ended", path="fast")
        route = route or {}
        intent, conf = route.get("intent"), float(route.get("confidence") or 0.0)
        distress = float(route.get("distress") or 0.0)
        short = len(utterance.split()) <= FAST_MAX_WORDS
        if intent != "unclear":
            self.unclear_streak = 0
        if self.step == "FILING":  # the form is being filled; nothing the farmer says now changes the report
            return Action(rule="filing_wait", path="fast", say=[Say(key="filing_wait")])

        if distress >= DISTRESS_MIN or (intent == "wants_human" and conf >= WANTS_HUMAN_MIN):
            return self._end(rule="wants_human", path="fast", line="escalate", status=("ESCALATED", "farmer asked for a person"), outcome="escalated")
        if intent == "wrong_person" and conf >= WRONG_PERSON_MIN:
            return self._end(rule="wrong_person", path="fast", line="wrong_person", status=("ESCALATED", "wrong person on the line"), outcome="wrong_person")

        if self.step == "PHOTO":
            # Waiting for the photo. A short remark needs no LLM; anything longer may be a question.
            if short and intent in ("yes", "no", "unclear", None):
                return Action(rule="photo_wait", path="fast", say=[Say(key="photo_wait")])
            return Action(rule="llm", path="llm", use_llm=True)

        # At the read-back a "no" followed by anything ("no, it was seventy percent") is a correction, not a refusal: the LLM reads it.
        plain = short and not (self.step == "CONSENT" and intent == "no" and len(utterance.split()) > NO_CONSENT_MAX_WORDS)
        if self.expects() == "yes_no" and intent in ("yes", "no") and conf >= self.fast_min and plain:
            slot = STEP[self.step].slot
            if intent == "yes":
                changed = self._store({slot: True})
                if self.step == "CONSENT":
                    self.step = "FILING"
                    return Action(rule="consent_yes", path="fast", say=[Say(key="filing")], slots=changed,
                                  status=("PROCESSING", "photo and consent" if self.evidence else "consent, no photo"), run_pipeline=True)
                return self._advance("yes", "fast", slots=changed)
            changed = self._store({slot: False})
            return self._no(self.step, "fast", changed)

        if intent == "unclear":
            self.unclear_streak += 1
            if self.unclear_streak == 2:
                return Action(rule="rephrase", path="fast", say=[Say(key="rephrase")])
            if self.unclear_streak >= 3:
                return self._end(rule="unclear_escalate", path="fast", line="escalate", status=("ESCALATED", "could not understand the farmer"),
                                 outcome="escalated")
        return Action(rule="llm", path="llm", use_llm=True)

    def _no(self, step_name: str, path: str, slots: dict, before: list[Say] | None = None) -> Action:
        if step_name == "GREET":
            return self._end(rule="wrong_person", path=path, line="wrong_person", status=("ESCALATED", "wrong person on the line"),
                             outcome="wrong_person", before=before, slots=slots)
        if step_name == "EVENT":
            return self._end(rule="no_damage", path=path, line="no_damage", status=("NO_DAMAGE", "farmer reports no damage"), outcome="completed",
                             before=before, slots=slots)
        if step_name == "KHASRA":
            return self._end(rule="other_plot", path=path, line="escalate", status=("ESCALATED", "damage is on a different plot"), outcome="escalated",
                             before=before, slots=slots)
        return self._end(rule="no_consent", path=path, line="no_consent", status=("ESCALATED", "no consent to file"), outcome="escalated",
                         before=before, slots=slots)

    def said(self, pattern: re.Pattern, own_step: str, utterance: str | None) -> bool:
        """May a value the LLM returned be taken? Yes at its own question and at the read-back; elsewhere only if the farmer used a
        word for it. Asking again is never wrong; filing something the farmer did not say could be."""
        return self.step in (own_step, "CONSENT") or utterance is None or bool(pattern.search(utterance))

    def apply_extraction(self, extracted: dict | None, peril: dict | None = None, utterance: str | None = None, asked: bool | None = None) -> Action:
        """After the LLM path. `extracted` is the LLM's JSON (see prompts.EXTRACT_SYSTEM); `peril` is the PERIL answer for cause_text;
        `utterance` is what the farmer said, used to check that a number the LLM returned was really spoken."""
        if self.ended:
            return Action(rule="ended", path="llm")
        if not isinstance(extracted, dict):
            return self._no_progress("llm_failed", answer=None)
        raw = extracted.get("slots") if isinstance(extracted.get("slots"), dict) else {}
        answer = extracted.get("answer")
        if asked is None:
            asked = utterance is None or bool(QUESTION_WORDS.search(utterance))
        before = []
        if asked and isinstance(answer, str) and answer.strip():
            before = [Say(text=answer.strip()[:200])]
        if raw.get("wants_human") is True:
            return self._end(rule="wants_human", path="llm", line="escalate", status=("ESCALATED", "farmer asked for a person"), outcome="escalated")

        updates: dict = {}
        current = STEP[self.step].slot if self.step in STEP else None
        for name in BOOL_SLOTS:
            value = raw.get(name)
            # A yes/no slot is taken only for the question that was asked. This stops the LLM from "hearing" consent early.
            if isinstance(value, bool) and name == current:
                updates[name] = value
        cause = raw.get("cause_text")
        if isinstance(cause, str) and cause.strip():
            updates["cause_text"] = cause.strip()[:200]
        pct = raw.get("damage_pct")
        if isinstance(pct, (int, float)) and not isinstance(pct, bool) and 1 <= pct <= 100:
            # "the wheat is completely flattened" is not a share of the field, whatever the LLM makes of it.
            if self.said(SHARE_WORDS, "EXTENT", utterance):
                updates["damage_pct"] = int(round(pct))
        if raw.get("crop_stage") in ("standing", "harvested") and self.said(STAGE_WORDS, "STAGE", utterance):
            updates["crop_stage"] = raw["crop_stage"]
        loss_time = raw.get("loss_time")
        if (isinstance(loss_time, str) and re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", loss_time.strip()) and self.call.storm_started_at
                and self.said(TIME_WORDS, "TIME", utterance)):
            hh, mm = loss_time.strip().split(":")
            date, offset = self.call.storm_started_at[:10], self.call.storm_started_at[19:] or "+05:30"
            updates["loss_datetime"] = f"{date}T{int(hh):02d}:{mm}:00{offset}"
            text = raw.get("loss_time_text")
            updates["loss_time_text"] = text.strip()[:80] if isinstance(text, str) and text.strip() else loss_time.strip()

        # Someone who describes the damage has confirmed it, and has shown they are the right person.
        described = "cause_text" in updates or "damage_pct" in updates
        if described and self.slots["damage_confirmed"] is None and "damage_confirmed" not in updates:
            updates["damage_confirmed"] = True
        if (described or updates.get("damage_confirmed") is not None) and self.slots["identity_confirmed"] is None and "identity_confirmed" not in updates:
            updates["identity_confirmed"] = True

        if "cause_text" in updates and self.slots["peril"] is None:
            model_label, llm_label = (peril or {}).get("value"), raw.get("peril")
            label = model_label or llm_label
            conf = float((peril or {}).get("confidence") or (0.6 if label else 0.0))
            agree = model_label is not None and model_label == llm_label  # the decision model and the LLM name the same cause
            if label in words.PERIL_EN and (conf >= PERIL_MIN or agree or self.peril_clarified):
                updates["peril"] = label
            elif self.peril_clarified:
                updates["peril"] = "not_covered"  # still unclear after asking twice: Eligibility sends it to a person
            else:
                self.peril_clarified = True  # ask for the cause once more

        if self.step == "CONSENT":
            corrected = {k: v for k, v in updates.items() if k not in ("consent", "cause_text") and self.slots.get(k) != v}
            if corrected:
                # The farmer corrected a detail at the read-back. Store it and read everything back again; nothing is filed on this turn.
                updates.pop("consent", None)
                return self._advance("corrected", "llm", before=before, slots=self._store(updates))

        for name, step_name in (("identity_confirmed", "GREET"), ("damage_confirmed", "EVENT"), ("khasra_confirmed", "KHASRA"), ("consent", "CONSENT")):
            if updates.get(name) is False:
                return self._no(step_name, "llm", self._store(updates), before=before)

        changed = self._store(updates)
        if changed.get("consent") is True:
            self.step = "FILING"
            return Action(rule="consent_yes", path="llm", say=[*before, Say(key="filing")], slots=changed,
                          status=("PROCESSING", "photo and consent" if self.evidence else "consent, no photo"), run_pipeline=True)
        if self.step == "PHOTO":
            return Action(rule="photo_wait", path="llm", say=before or [Say(key="photo_wait")], slots=changed)
        if not changed and not before:
            return self._no_progress("no_progress", answer=None)
        return self._advance("llm", "llm", before=before, slots=changed)

    def _no_progress(self, rule: str, answer: str | None) -> Action:
        """Nothing usable came out of the turn: ask to repeat, and give up politely if this keeps happening."""
        self.asked[self.step] = self.asked.get(self.step, 0) + 1
        if self.asked[self.step] > MAX_ASKS:
            return self._end(rule="stalled", path="llm", line="escalate", status=("ESCALATED", f"no usable answer at {self.step}"), outcome="escalated")
        return Action(rule=rule, path="llm", say=[Say(key="rephrase")])

    def on_evidence(self, label: str | None, confidence: float | None = None, evidence_id: str | None = None) -> Action:
        """The phone uploaded a photo (SystemDesign §10.5)."""
        if self.ended or self.step not in ("PHOTO",):
            if self.evidence is None and not self.ended:
                self.evidence = {"evidence_id": evidence_id, "edge_label": label, "edge_confidence": confidence}  # early photo: keep it
            return Action(rule="evidence_ignored", path="scripted")
        if label == "not_a_crop" and self.photo_retakes == 0:
            self.photo_retakes = 1
            return Action(rule="photo_retake", path="scripted", say=[Say(key="photo_retake")])
        self.evidence = {"evidence_id": evidence_id, "edge_label": label, "edge_confidence": confidence}
        return self._advance("evidence", "scripted")

    def on_photo_timeout(self) -> Action:
        """No photo after the waiting time: go on without it. Eligibility then sends the case to a person."""
        if self.ended or self.step != "PHOTO":
            return Action(rule="timeout_ignored", path="scripted")
        self.photo_skipped = True
        return self._advance("photo_skip", "scripted", before=[Say(key="photo_skip")])

    def on_pipeline_result(self, result: dict | None) -> Action:
        """Filing finished (or did not). `result` is the answer of POST /api/cases/{id}/pipeline/run, or None when it failed or is not built."""
        if self.ended:
            return Action(rule="ended", path="scripted")
        ref = (result or {}).get("claim_ref")
        if ref:
            self.ended = "completed"
            self.step = "END"
            return Action(rule="reference", path="scripted", say=[Say(key="reference", values={"ref_spoken": words.digits(ref)})], end="completed")
        verdict = (result or {}).get("verdict")
        if (result or {}).get("status") == "FAILED":  # the form could not be submitted: do not promise a reference by message
            return self._end(rule="not_filed", path="scripted", line="not_filed", status=None, outcome="escalated")
        if verdict in ("ineligible", "review"):
            return self._end(rule="not_filed", path="scripted", line="not_filed", status=None, outcome="escalated" if verdict == "review" else "completed")
        return self._end(rule="filing_slow", path="scripted", line="filing_slow", status=None, outcome="completed")
