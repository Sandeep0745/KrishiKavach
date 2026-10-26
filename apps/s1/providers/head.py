"""Trained head for the farmer's replies (Phase 0 decision): sentence encoder + softmax regression on our own examples (English since 9 Oct 2026).

Used for ROUTE and PERIL. Non-generative, returns a probability for every label. Measured in Phase 0 with
intfloat/multilingual-e5-small: ROUTE 29/30, PERIL 11/12, about 19 ms per reply on CPU.
"""
from __future__ import annotations

import json
import threading

from ghante_shared import config

NAME = "head"
MODEL = config.env("HEAD_ENCODER", "intfloat/multilingual-e5-small")
TRAIN_FILES = {"ROUTE": "route_train.jsonl", "PERIL": "peril_train.jsonl"}
ANSWER_KEY = {"ROUTE": "intent", "PERIL": "peril"}
_lock = threading.Lock()
_state: dict = {}


def available() -> tuple[bool, str]:
    try:
        import numpy  # noqa: F401
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError as e:
        return False, f"missing package: {e.name}"
    for f in TRAIN_FILES.values():
        if not (config.DATA_DIR / "eval" / f).exists():
            return False, f"missing training file data/eval/{f}"
    return True, "ready" if _state else "loads on first use"


def train_softmax(X, y, n_classes: int, l2: float = 1e-3, lr: float = 2.0, steps: int = 1500):
    """Plain softmax regression by gradient descent. X: (n, d) L2-normalised rows, y: (n,) class indexes."""
    import numpy as np

    n, d = X.shape
    W, b, Y = np.zeros((n_classes, d)), np.zeros(n_classes), np.eye(n_classes)[y]
    for _ in range(steps):
        z = X @ W.T + b
        z -= z.max(1, keepdims=True)
        P = np.exp(z)
        P /= P.sum(1, keepdims=True)
        G = (P - Y) / n
        W -= lr * (G.T @ X + l2 * W)
        b -= lr * G.sum(0)
    return W, b


def softmax_probs(W, b, X, scale: float = 1.0):
    import numpy as np

    z = scale * (X @ W.T + b)
    z -= z.max(1, keepdims=True)
    P = np.exp(z)
    return P / P.sum(1, keepdims=True)


def _load() -> dict:
    with _lock:
        if _state:
            return _state
        import numpy as np
        import torch
        from transformers import AutoModel, AutoTokenizer

        tok = AutoTokenizer.from_pretrained(MODEL)
        model = AutoModel.from_pretrained(MODEL)
        model.eval()
        prefix = "query: " if "e5" in MODEL.lower() else ""

        def embed(texts: list[str]):
            with torch.no_grad():
                enc = tok([prefix + t for t in texts], padding=True, truncation=True, max_length=64, return_tensors="pt")
                out = model(**enc).last_hidden_state
                mask = enc["attention_mask"].unsqueeze(-1).float()
                v = torch.nn.functional.normalize((out * mask).sum(1) / mask.sum(1), dim=-1)
            return v.cpu().numpy().astype(np.float64)

        heads = {}
        for decision, fname in TRAIN_FILES.items():
            rows = [json.loads(line) for line in (config.DATA_DIR / "eval" / fname).read_text(encoding="utf-8").splitlines() if line.strip()]
            labels = sorted({r["label"] for r in rows})
            X = embed([r["text"] for r in rows])
            y = np.array([labels.index(r["label"]) for r in rows])
            W, b = train_softmax(X, y, len(labels))
            heads[decision] = (labels, W, b, len(rows))
        _state.update(embed=embed, heads=heads)
        return _state


def decide(decision: str, state: dict) -> dict:
    from .. import decisions as d

    if decision not in TRAIN_FILES:
        raise ValueError(f"the head does not answer {decision}")
    st = _load()
    labels, W, b, _n = st["heads"][decision]
    text = d.text_of(decision, state).strip()
    if not text:
        raise ValueError("empty text")
    scale = config.env_float("HEAD_TEMPERATURE", 1.0)
    P = softmax_probs(W, b, st["embed"]([text]), scale)[0]
    i = int(P.argmax())
    answers = {ANSWER_KEY[decision]: {"value": labels[i], "confidence": round(float(P[i]), 4), "probs": {l: round(float(p), 4) for l, p in zip(labels, P)}}}
    if decision == "ROUTE":
        # Distress is not modelled yet (no training data). The wants_human intent and the LLM path cover it for now.
        answers["distress"] = {"value": False, "confidence": None, "modelled": False}
    return answers
