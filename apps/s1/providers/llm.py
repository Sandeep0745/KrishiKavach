"""LLM fallback for decisions: the first Groq model in LLM_CHAIN, asked for JSON. Shown on the dashboard as "LLM fallback".

Free tier only. Counts requests in logs/usage.json.
"""
from __future__ import annotations

import json

from ghante_shared import config, http, usage

NAME = "llm"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _groq_model() -> str | None:
    for item in config.env("LLM_CHAIN", "groq:openai/gpt-oss-20b").split(","):
        provider, _, model = item.strip().partition(":")
        if provider == "groq" and model:
            return model
    return None


MODEL = _groq_model() or "none"


def available() -> tuple[bool, str]:
    if not config.env("GROQ_API_KEY"):
        return False, "GROQ_API_KEY is empty"
    if not _groq_model():
        return False, "no groq:<model> entry in LLM_CHAIN"
    return True, "ready"


def decide(decision: str, state: dict) -> dict:
    from .. import decisions as d

    ok, reason = available()
    if not ok:
        raise RuntimeError(reason)
    questions = d.QUESTIONS[decision]
    spec = {}
    for name, q in questions.items():
        spec[name] = {"question": q["instructions"], "allowed_values": list(q["criteria"]) if q["type"] == "choice" else [True, False],
                      **({"meaning": q["criteria"]} if q["type"] == "choice" else {})}
    payload_state = {"report": d.render_report(decision, state)} if d.KIND[decision] == "report" else d.laya_inputs(decision, state)[0]
    system = ("You are a strict classifier. Answer every question about the given state. Reply with one JSON object only: "
              '{"<question name>": {"value": <one allowed value>, "confidence": <number 0 to 1>}}. No other text.')
    user = json.dumps({"state": payload_state, "questions": spec}, ensure_ascii=False)
    body = {"model": _groq_model(), "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    out = http.request_json("POST", GROQ_URL, body, timeout=20.0,
                            headers={"Authorization": f"Bearer {config.env('GROQ_API_KEY')}", "User-Agent": "ghante72/0.1"})
    usage.add("groq", "llm_requests")
    usage.add("groq", "llm_tokens", (out.get("usage") or {}).get("total_tokens", 0))
    raw = json.loads(out["choices"][0]["message"]["content"])
    answers = {}
    for name, q in questions.items():
        a = raw.get(name)
        if not isinstance(a, dict) or "value" not in a:
            raise ValueError(f"LLM reply has no answer for {name}")
        conf = a.get("confidence")
        conf = round(float(conf), 4) if isinstance(conf, (int, float)) and not isinstance(conf, bool) else None
        if q["type"] == "choice":
            if a["value"] not in q["criteria"]:
                raise ValueError(f"LLM gave a value outside the allowed list for {name}")
            answers[name] = {"value": a["value"], "confidence": conf, "probs": {}}
        else:
            answers[name] = {"value": bool(a["value"]), "confidence": conf}
    return answers
