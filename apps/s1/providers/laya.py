"""Laya (open System One model, Convai Innovations, Apache-2.0), run locally. Used for TRIAGE and VERIFY.

Phase 0: 6/6 on English triage reports at about 175 ms on CPU; about 50 % on raw Hindi replies, so it is not used for those.
"""
from __future__ import annotations

import threading

from ghante_shared import config

NAME = "laya"
MODEL = config.env("LAYA_MODEL", "convaiinnovations/laya-multilingual")
_lock = threading.Lock()
_agent = None


def available() -> tuple[bool, str]:
    try:
        import laya  # noqa: F401
    except ImportError:
        return False, "missing package: laya"
    return True, "ready" if _agent is not None else "loads on first use"


def _load():
    global _agent
    with _lock:
        if _agent is None:
            import laya

            _agent = laya.load(MODEL)
        return _agent


def decide(decision: str, state: dict) -> dict:
    from .. import decisions as d

    agent = _load()
    laya_state, questions = d.laya_inputs(decision, state)
    with _lock:  # one prediction at a time: the model is not known to be thread-safe
        result = agent.predict(laya_state, questions)
    answers = {}
    for name, a in result["answers"].items():
        if a.get("type") == "choice" or "choice" in a:
            probs = {k: round(float(v), 4) for k, v in a.get("probabilities", {}).items()}
            value = a["choice"]
            answers[name] = {"value": value, "confidence": probs.get(value, round(float(a.get("answer_confidence", 0)), 4)), "probs": probs}
        else:
            p_yes = float(a.get("noul", 0.0))
            value = p_yes >= 0.5
            answers[name] = {"value": value, "confidence": round(p_yes if value else 1 - p_yes, 4), "p_yes": round(p_yes, 4)}
    return answers
