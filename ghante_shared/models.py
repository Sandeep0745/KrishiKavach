"""Canonical names from context/SystemDesign.md: statuses, transitions, slots, perils, events."""
from __future__ import annotations

import datetime as dt
import itertools
import time

# ---- case statuses (SystemDesign §5) ----
AFFECTED, QUEUED, CALLING, IN_CALL, NO_ANSWER, UNREACHABLE = "AFFECTED", "QUEUED", "CALLING", "IN_CALL", "NO_ANSWER", "UNREACHABLE"
NO_DAMAGE, ESCALATED, EVIDENCE, PROCESSING, INELIGIBLE, FILING, FILED, FAILED = (
    "NO_DAMAGE", "ESCALATED", "EVIDENCE", "PROCESSING", "INELIGIBLE", "FILING", "FILED", "FAILED")

STATUSES = [AFFECTED, QUEUED, CALLING, IN_CALL, NO_ANSWER, UNREACHABLE, NO_DAMAGE, ESCALATED, EVIDENCE, PROCESSING, INELIGIBLE, FILING, FILED, FAILED]
TERMINAL = {FILED, NO_DAMAGE, ESCALATED, INELIGIBLE, UNREACHABLE, FAILED}

TRANSITIONS: dict[str, set[str]] = {
    AFFECTED: {QUEUED},
    QUEUED: {CALLING},
    CALLING: {IN_CALL, NO_ANSWER},
    NO_ANSWER: {QUEUED, UNREACHABLE},
    IN_CALL: {NO_DAMAGE, ESCALATED, EVIDENCE},
    EVIDENCE: {PROCESSING, ESCALATED},  # ESCALATED: no consent, or the farmer asks for a person while the photo is awaited
    PROCESSING: {INELIGIBLE, ESCALATED, FILING},
    FILING: {FILED, FAILED},
    ESCALATED: {FILING},  # reviewer approval (P1), only when escalated for review
    FAILED: {FILING},  # filing is tried again after the portal or the Filer was down (Testing T3-07, drill D6)
    UNREACHABLE: set(), NO_DAMAGE: set(), INELIGIBLE: set(), FILED: set(),
}

# ---- slots (SystemDesign §4) ----
SLOT_NAMES = ["identity_confirmed", "damage_confirmed", "khasra_confirmed", "cause_text", "peril", "loss_time_text",
              "loss_datetime", "damage_pct", "crop_stage", "consent"]
PERILS = ["hailstorm", "inundation", "landslide", "cloudburst", "natural_fire", "unseasonal_rain", "cyclone", "not_covered"]
CROP_STAGES = ["standing", "harvested"]
EDGE_LABELS = ["hail_damage", "waterlogged", "lodged", "healthy", "not_a_crop"]
CALL_OUTCOMES = ["completed", "no_answer", "declined", "escalated", "wrong_person", "dropped"]
AGENTS = ["sentinel", "dispatcher", "intake", "evidence", "eligibility", "filing", "followup", "system"]
VERDICTS = ["eligible", "ineligible", "review"]
FILING_MODES = ["agent", "scripted", "api"]


def empty_slots() -> dict:
    return {name: None for name in SLOT_NAMES}


def validate_slots(partial: dict) -> dict:
    """Return a cleaned partial slot dict or raise ValueError."""
    clean: dict = {}
    for key, value in partial.items():
        if key not in SLOT_NAMES:
            raise ValueError(f"unknown slot: {key}")
        if value is None:
            clean[key] = None
        elif key in ("identity_confirmed", "damage_confirmed", "khasra_confirmed", "consent"):
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be true or false")
            clean[key] = value
        elif key == "peril":
            if value not in PERILS:
                raise ValueError(f"peril must be one of {PERILS}")
            clean[key] = value
        elif key == "crop_stage":
            if value not in CROP_STAGES:
                raise ValueError(f"crop_stage must be one of {CROP_STAGES}")
            clean[key] = value
        elif key == "damage_pct":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
                raise ValueError("damage_pct must be a number from 0 to 100")
            clean[key] = int(round(value))
        else:
            clean[key] = str(value)
    return clean


# ---- events (SystemDesign §7) ----
_counter = itertools.count(1)


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_event(type_: str, data: dict | None = None, *, case_id: str | None = None, agent: str = "system",
              live: bool = False, sim_ts: str | None = None) -> dict:
    return {
        "id": f"evt_{int(time.time() * 1000):013d}_{next(_counter):06d}",
        "ts": utc_now_iso(),
        "sim_ts": sim_ts,
        "type": type_,
        "case_id": case_id,
        "agent": agent if agent in AGENTS else "system",
        "live": bool(live),
        "data": data or {},
    }
