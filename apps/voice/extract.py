"""The LLM path of a turn: one JSON-mode request to a free-tier chat model. Standard library only.

LLM_CHAIN lists the providers in order, for example groq:openai/gpt-oss-20b,gemini:gemini-3.1-flash-lite. The next one is tried when a
provider fails or is too slow. Requests and tokens are counted in logs/usage.json.
"""
from __future__ import annotations

import concurrent.futures
import json
import threading
import time
from http import client as httplib
from urllib.parse import urlsplit

from ghante_shared import config, http, usage

PROVIDERS = {
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "GEMINI_API_KEY"),
}
DEFAULT_CHAIN = "groq:openai/gpt-oss-20b"
# Tried after LLM_CHAIN when every entry there failed. Groq counts its free limits per model, so a second Groq model still
# answers when the first has hit its tokens-per-minute limit (seen in Phase 2: HTTP 429 after two test calls back to back).
# Gemini models checked on the team's free key on 8 Oct 2026 (scripts/spikes/gemini_probe.py): gemini-3.8-flash answered 429
# (no free quota), gemini-3.1-flash-lite and gemini-flash-lite-latest answered the call's question in about 1.3 s.
BACKUPS = "groq:openai/gpt-oss-120b,gemini:gemini-3.1-flash-lite,gemini:gemini-flash-lite-latest"
TIMEOUT_S = config.env_float("VOICE_LLM_TIMEOUT_S", 6.0)
_no_reasoning_effort: set[str] = set()  # models that refused the reasoning_effort field


class KeepAlive:
    """One open HTTPS connection per provider. A new TLS handshake on every turn cost 5 to 10 seconds on a slow Wi-Fi link
    (measured in Phase 2); with the connection kept open a turn costs only the model's own time."""

    def __init__(self) -> None:
        self._conns: dict[str, httplib.HTTPSConnection] = {}
        self._lock = threading.Lock()

    def _open(self, host: str, timeout: float) -> httplib.HTTPSConnection:
        conn = httplib.HTTPSConnection(host, timeout=timeout)
        conn.connect()
        self._conns[host] = conn
        return conn

    def _drop(self, host: str) -> None:
        conn = self._conns.pop(host, None)
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def warm(self, url: str, timeout: float = 8.0) -> bool:
        """Open the connection ahead of the first request. Returns False if the host could not be reached."""
        host = urlsplit(url).netloc
        with self._lock:
            if host in self._conns:
                return True
            try:
                self._open(host, timeout)
                return True
            except Exception:  # noqa: BLE001
                self._drop(host)
                return False

    def post_json(self, url: str, body: dict, headers: dict, timeout: float) -> dict:
        parts = urlsplit(url)
        data = json.dumps(body).encode("utf-8")
        with self._lock:
            for attempt in (1, 2):
                reused = parts.netloc in self._conns
                try:
                    conn = self._conns.get(parts.netloc) or self._open(parts.netloc, timeout)
                    if conn.sock is not None:
                        conn.sock.settimeout(timeout)
                    conn.request("POST", parts.path, body=data, headers={"Content-Type": "application/json", "Connection": "keep-alive", **headers})
                    resp = conn.getresponse()
                    raw = resp.read()
                except (httplib.HTTPException, OSError):
                    self._drop(parts.netloc)
                    if reused and attempt == 1:
                        continue  # the server closed an idle connection: try once more on a new one
                    raise
                if resp.status >= 400:
                    raise http_error(resp.status, raw.decode("utf-8", "replace"))
                return json.loads(raw.decode("utf-8"))
        raise RuntimeError("unreachable")


def http_error(status: int, body: str) -> Exception:
    return http.HttpError(status, body)


_keep = KeepAlive()
_keep_b = KeepAlive()   # second connection, used only when the first request is slow
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="llm")
HEDGE_AFTER_S = config.env_float("VOICE_LLM_HEDGE_S", 2.0)   # 0 turns the second request off


def warm() -> list[str]:
    """Open the connections to the providers in the chain. Called when a call starts, while the greeting plays."""
    ready = [provider for provider, _model in chain() if _keep.warm(PROVIDERS[provider][0])]
    first = chain()[:1]
    if first and HEDGE_AFTER_S > 0:
        _keep_b.warm(PROVIDERS[first[0][0]][0])
    return ready


def chain() -> list[tuple[str, str]]:
    out = []
    listed = (config.env("LLM_CHAIN", "") or DEFAULT_CHAIN).split(",") + config.env("LLM_BACKUPS", BACKUPS).split(",")
    for item in listed:
        provider, _, model = item.strip().partition(":")
        if provider in PROVIDERS and model and config.env(PROVIDERS[provider][1]) and (provider, model) not in out:
            out.append((provider, model))
    return out


def _request(provider: str, model: str, system: str, user: str, pool: "KeepAlive | None" = None) -> tuple[dict, dict]:
    pool = pool or _keep
    url, key_name = PROVIDERS[provider]
    body = {"model": model, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    headers = {"Authorization": f"Bearer {config.env(key_name)}", "User-Agent": "ghante72/0.2"}
    wants_effort = provider == "groq" and "gpt-oss" in model and model not in _no_reasoning_effort
    if wants_effort:
        body["reasoning_effort"] = "low"  # these models think before answering; a small extraction needs little of it
    try:
        out = pool.post_json(url, body, headers, TIMEOUT_S)
    except http.HttpError as e:
        if not (wants_effort and e.status == 400):
            raise
        _no_reasoning_effort.add(model)
        body.pop("reasoning_effort", None)
        out = pool.post_json(url, body, headers, TIMEOUT_S)
    usage.add(provider, "llm_requests")
    usage.add(provider, "llm_tokens", (out.get("usage") or {}).get("total_tokens", 0))
    content = out["choices"][0]["message"]["content"]
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("the model did not return a JSON object")
    return data, out.get("usage") or {}


def _retire_slow_connection(winner: str, provider: str) -> None:
    """After a second request was needed: keep the connection that answered as the main one and replace the other, whose
    request may still be stuck, with a fresh one. Otherwise the next turn would queue behind the stuck request."""
    global _keep, _keep_b
    if winner == "second":
        _keep = _keep_b
    _keep_b = KeepAlive()
    _pool.submit(_keep_b.warm, PROVIDERS[provider][0])


def _attempt(provider: str, model: str, system: str, user: str, pool: "KeepAlive") -> dict:
    t1 = time.perf_counter()
    data, used = _request(provider, model, system, user, pool)
    return {"data": data, "provider": provider, "model": model, "ms": round((time.perf_counter() - t1) * 1000), "tokens": used.get("total_tokens", 0)}


def extract_sync(system: str, user: str) -> dict:
    """Returns {"data": {...} | None, "provider", "model", "ms", "total_ms", "hedged", "failed": [...]}; data is None when every
    provider failed.

    If the first provider has not answered after HEDGE_AFTER_S, the same request is sent again on a second connection and the
    first answer wins. One slow packet on a Wi-Fi link otherwise costs the farmer several seconds of silence.
    """
    failed: list[dict] = []
    t0 = time.perf_counter()
    providers = chain()
    for position, (provider, model) in enumerate(providers):
        futures = {_pool.submit(_attempt, provider, model, system, user, _keep): "first"}
        hedged = False
        deadline = time.perf_counter() + TIMEOUT_S + 1.0
        result = None
        while futures and result is None:
            may_hedge = not hedged and position == 0 and HEDGE_AFTER_S > 0
            wait_s = max(0.05, HEDGE_AFTER_S if may_hedge else deadline - time.perf_counter())
            done, _ = concurrent.futures.wait(list(futures), timeout=wait_s, return_when=concurrent.futures.FIRST_COMPLETED)
            for f in done:
                tag = futures.pop(f)
                try:
                    result = {**f.result(), "hedged": hedged, "won": tag}
                    break
                except Exception as e:  # noqa: BLE001 - any failure means: try the other request, then the next provider
                    failed.append({"provider": provider, "model": model, "reason": f"{type(e).__name__}: {str(e)[:120]}"})
            if result is None and not done:
                if may_hedge:
                    hedged = True
                    usage.add(provider, "llm_hedged_requests")
                    futures[_pool.submit(_attempt, provider, model, system, user, _keep_b)] = "second"
                elif time.perf_counter() >= deadline:
                    failed.append({"provider": provider, "model": model, "reason": f"no answer in {TIMEOUT_S:.0f} s"})
                    break
        if result is not None:
            if hedged:
                _retire_slow_connection(result["won"], provider)
            return {**result, "total_ms": round((time.perf_counter() - t0) * 1000), "failed": failed}
    if not failed:
        failed.append({"provider": "none", "model": "", "reason": "no usable entry in LLM_CHAIN (check the keys in .env)"})
    return {"data": None, "provider": None, "model": None, "ms": round((time.perf_counter() - t0) * 1000),
            "total_ms": round((time.perf_counter() - t0) * 1000), "hedged": False, "failed": failed}
