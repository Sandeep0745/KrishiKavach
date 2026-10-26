"""Usage log for limited free allowances (NFR-14). One JSON file, updated under a lock."""
from __future__ import annotations

import json
import threading

from . import config

_lock = threading.Lock()


def add(provider: str, metric: str, amount: float = 1) -> None:
    """Add to logs/usage.json, e.g. add("groq", "llm_requests") or add("sarvam", "tts_chars", 120)."""
    with _lock:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(config.USAGE_LOG.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        bucket = data.setdefault(provider, {})
        bucket[metric] = round(bucket.get(metric, 0) + amount, 3)
        config.USAGE_LOG.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def read() -> dict:
    try:
        return json.loads(config.USAGE_LOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
