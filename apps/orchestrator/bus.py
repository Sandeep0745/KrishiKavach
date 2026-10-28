"""In-process event bus: every event goes to logs/events.jsonl and to every connected stream."""
from __future__ import annotations

import asyncio
import collections
import json
import threading

from ghante_shared import config


# What a dashboard that connects (or reloads) mid-demo is sent after the snapshot, so its panels are not empty:
# the latest rows of the decision ticker and the tool-call log, every fallback notice, and the live call so far.
REPLAY_LIMITS = {"s1.decision": 40, "mcp.tool_called": 30, "fallback.used": 10, "review.decision": 3, "scenario.finished": 1}
REPLAY_LIVE_LIMITS = {"call.turn": 7, "evidence.received": 1, "agent.started": 4, "agent.finished": 4, "filing.step": 1, "claim.filed": 1}


class EventBus:
    def __init__(self) -> None:
        self._recent: dict[str, collections.deque] = {}
        self.tallies = {"s1": 0, "s1_cached": 0, "mcp": 0}
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._file = config.EVENTS_LOG.open("a", encoding="utf-8", newline="\n")  # kept open: the fleet writes thousands of events

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: dict) -> dict:
        """Log the event and hand it to every subscriber. Safe to call from any thread."""
        line = json.dumps(event, ensure_ascii=False)
        self._remember(event)
        with self._lock:
            self._file.write(line + "\n")
            self._file.flush()
        loop = self._loop
        if loop is not None and loop.is_running():
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is loop:
                self._fan_out(event)
            else:
                loop.call_soon_threadsafe(self._fan_out, event)
        return event

    def _remember(self, event: dict) -> None:
        type_ = event["type"]
        if type_ == "snapshot":  # a reset: what came before belongs to the last run
            self._recent.clear()
            self.tallies = {"s1": 0, "s1_cached": 0, "mcp": 0}
            return
        if type_ == "s1.decision":
            self.tallies["s1"] += 1
            self.tallies["s1_cached"] += 1 if (event.get("data") or {}).get("cached") else 0
        elif type_ == "mcp.tool_called":
            self.tallies["mcp"] += 1
        limit = REPLAY_LIMITS.get(type_) or (REPLAY_LIVE_LIMITS.get(type_) if event.get("live") else None)
        if limit:
            self._recent.setdefault(type_, collections.deque(maxlen=limit)).append(event)

    def recent(self) -> list[dict]:
        """The remembered events, oldest first (event ids sort in time order)."""
        return sorted((e for q in list(self._recent.values()) for e in list(q)), key=lambda e: e["id"])

    def _fan_out(self, event: dict) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                self._subscribers.discard(q)  # a stuck client must not block the others

    def clear_log(self) -> None:
        with self._lock:
            self._file.close()
            config.EVENTS_LOG.write_text("", encoding="utf-8")
            self._file = config.EVENTS_LOG.open("a", encoding="utf-8", newline="\n")
