"""Decision providers. Each has NAME, available() -> (ok, reason) and decide(decision, state) -> answers.

Answer shapes (SystemDesign §8.1):
  choice: {"value": label, "confidence": float, "probs": {label: float}}
  yes/no: {"value": bool, "confidence": float}   (confidence is the probability of the stated value)
"""
from __future__ import annotations

from . import head, laya, llm, mock

REGISTRY = {p.NAME: p for p in (head, laya, llm, mock)}
