"""Deterministic keyword rules. FOR AUTOMATED TESTS ONLY: never put "mock" in a chain used for a demo."""
from __future__ import annotations

NAME = "mock"
MODEL = "keyword-rules-test-only"


def available() -> tuple[bool, str]:
    return True, "test provider"


def _choice(labels: list[str], pick: str) -> dict:
    probs = {label: (0.9 if label == pick else round(0.1 / (len(labels) - 1), 4)) for label in labels}
    return {"value": pick, "confidence": 0.9, "probs": probs}


def decide(decision: str, state: dict) -> dict:
    from .. import decisions as d

    if decision == "ROUTE":
        t = d.text_of(decision, state)
        t = t.lower()
        pick = ("wants_human" if "person" in t or "officer" in t or "human" in t else "wrong_person" if "wrong number" in t else "asks_question" if "?" in t
                else "no" if t.startswith("no") else "yes" if t.startswith("yes") else "gives_details" if t else "unclear")
        return {"intent": _choice(d.ROUTE_INTENTS, pick), "distress": {"value": False, "confidence": 0.9}}
    if decision == "PERIL":
        t = d.text_of(decision, state)
        t = t.lower()
        pick = "hailstorm" if "hail" in t else "inundation" if "water" in t or "flood" in t else "natural_fire" if "fire" in t else "not_covered"
        return {"peril": _choice(d.PERIL_LABELS, pick)}
    if decision == "TRIAGE":
        pick = {"severe": "high", "moderate": "medium"}.get(str(state.get("hail_intensity")), "low")
        return {"damage_likelihood": _choice(["high", "medium", "low"], pick)}
    if decision == "VERIFY":
        ok = bool(state.get("hail")) and state.get("edge_label") not in ("healthy", "not_a_crop") and float(state.get("distance_from_plot_m", 0)) <= 2000
        return {"evidence_consistent": {"value": ok, "confidence": 0.9}}
    raise ValueError(decision)
