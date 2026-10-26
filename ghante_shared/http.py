"""Tiny JSON-over-HTTP helpers on the standard library (no extra dependency)."""
from __future__ import annotations

import json
import queue
import threading
import urllib.error
import urllib.request

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # local services: never through a proxy


class HttpError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status, self.body = status, body


def request_json(method: str, url: str, payload: dict | None = None, timeout: float = 10.0, headers: dict | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with _opener.open(req, timeout=timeout) as r:
            body = r.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        raise HttpError(e.code, e.read().decode("utf-8", "replace")) from None


def get_json(url: str, timeout: float = 10.0):
    return request_json("GET", url, None, timeout)


def post_json(url: str, payload: dict | None = None, timeout: float = 10.0):
    return request_json("POST", url, payload if payload is not None else {}, timeout)


def post_event(orch_url: str, type_: str, data: dict | None = None, *, case_id: str | None = None, agent: str = "system",
               live: bool | None = None, wait: bool = False) -> None:
    """Send an event to the orchestrator. Never raises: a missing orchestrator must not break the caller.

    Leave `live` unset when the caller does not know whether the case is the hero's: the orchestrator then decides from the case.
    """
    payload = {"type": type_, "data": data or {}, "case_id": case_id, "agent": agent}
    if live is not None:
        payload["live"] = live
    if wait:
        _send_event(orch_url, payload)
        return
    global _event_thread
    _event_queue.put((orch_url, payload))
    with _event_lock:
        if _event_thread is None or not _event_thread.is_alive():
            _event_thread = threading.Thread(target=_event_worker, name="events", daemon=True)
            _event_thread.start()


# Events are sent by one background thread, so they reach the orchestrator in the order they were raised.
# (One thread per event let a farmer's turn and the agent's reply arrive the wrong way round.)
_event_queue: queue.Queue = queue.Queue()
_event_lock = threading.Lock()
_event_thread: threading.Thread | None = None


def _send_event(orch_url: str, payload: dict) -> None:
    try:
        post_json(f"{orch_url}/internal/events", payload, timeout=3.0)
    except Exception:
        pass


def _event_worker() -> None:
    while True:
        orch_url, payload = _event_queue.get()
        _send_event(orch_url, payload)
        _event_queue.task_done()


def flush_events(timeout: float = 5.0) -> None:
    """Wait until every queued event has been sent (used before a process exits and in checks)."""
    import time

    deadline = time.time() + timeout
    while _event_queue.unfinished_tasks and time.time() < deadline:
        time.sleep(0.02)
