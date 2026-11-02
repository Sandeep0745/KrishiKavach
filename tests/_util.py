"""Test helpers: start our services on spare ports with a temporary data folder, and talk to them."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE_PORT = int(os.environ.get("GHANTE_TEST_BASE_PORT", "18000"))
PORT = {"orchestrator": BASE_PORT, "portal": BASE_PORT + 90, "weather": BASE_PORT + 101, "registry": BASE_PORT + 102,
        "mandi": BASE_PORT + 103, "s1": BASE_PORT + 200, "filer": BASE_PORT + 300}
MODULE = {"orchestrator": "apps.orchestrator.main", "portal": "apps.portal.main", "weather": "mcp_servers.weather",
          "registry": "mcp_servers.registry", "mandi": "mcp_servers.mandi", "s1": "apps.s1.main", "filer": "apps.filer.main"}
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def url(service: str, path: str = "") -> str:
    return f"http://127.0.0.1:{PORT[service]}{path}"


def test_env(tmp: str, **extra: str) -> dict:
    env = dict(os.environ)
    env.update({
        "GHANTE_VAR_DIR": str(pathlib.Path(tmp) / "var"), "GHANTE_LOG_DIR": str(pathlib.Path(tmp) / "logs"),
        "ORCH_URL": url("orchestrator"), "PORTAL_URL": url("portal"), "S1_URL": url("s1"), "FILER_URL": url("filer"),
        # the Filer's browser: no window, no pauses between fields, its own debugging port and profile
        "FILER_HEADLESS": "1", "FILER_FIELD_DELAY_MS": "0", "FILER_CDP_PORT": str(BASE_PORT + 333),
        "FILER_PROFILE_DIR": str(pathlib.Path(tmp) / "filer_profile"), "FILING_MODE": "scripted",
        "MCP_WEATHER_URL": url("weather", "/mcp"), "MCP_REGISTRY_URL": url("registry", "/mcp"), "MCP_MANDI_URL": url("mandi", "/mcp"),
        "WEATHER_WATCH_MODE": "off", "WEATHER_MODE": "replay", "MANDI_MODE": "fixture", "PYTHONUTF8": "1", "PYTHONPATH": str(ROOT),
    })
    env.update(extra)
    return env


def filer_python() -> str:
    """The Filer runs from the browser environment when there is one (Windows laptop); otherwise from this Python."""
    explicit = os.environ.get("GHANTE_FILER_PYTHON")
    if explicit:
        return explicit
    for candidate in (ROOT / ".venv-browser" / "Scripts" / "python.exe", ROOT / ".venv-browser" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def launch_chromium(p, **kwargs):
    """A browser for the dashboard tests: Playwright's own Chromium when it was downloaded, otherwise the installed Chrome or Edge
    (the team laptop has no Playwright download; run these tests there with .venv-browser, which has Playwright)."""
    problems = []
    for channel in (None, "chrome", "msedge"):
        try:
            return p.chromium.launch(**kwargs) if channel is None else p.chromium.launch(channel=channel, **kwargs)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{channel or 'chromium'}: {type(e).__name__}")
    raise RuntimeError("; ".join(problems))


def filer_can_run() -> tuple[bool, str]:
    """Is Playwright importable where the Filer would run, and is there a browser for it to drive?"""
    check = "import playwright.async_api, starlette, uvicorn; from apps.filer.browser import find_browser; print(find_browser() or '')"
    try:
        out = subprocess.run([filer_python(), "-c", check], cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT)), capture_output=True, text=True, timeout=60)
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}"
    if out.returncode != 0:
        return False, (out.stderr.strip().splitlines() or ["import failed"])[-1][:200]
    return (True, out.stdout.strip()) if out.stdout.strip() else (False, "no Chrome, Edge or Chromium found")


class Services:
    """Start a set of services; stop them on close()."""

    def __init__(self, *names: str, **extra_env: str) -> None:
        self.tmp = tempfile.mkdtemp(prefix="ghante_test_")
        self.env = test_env(self.tmp, **extra_env)
        self.procs: list[subprocess.Popen] = []
        self.by_name: dict[str, subprocess.Popen] = {}
        self._files: list = []
        self.logs = pathlib.Path(self.tmp) / "proc"
        self.logs.mkdir()
        try:
            for name in names:
                self._spawn(name)
            for name in names:
                self._wait(name)
        except Exception:
            self.close()
            raise

    def _spawn(self, name: str) -> None:
        log = open(self.logs / f"{name}.log", "a", encoding="utf-8")
        self._files.append(log)
        python = os.environ.get("GHANTE_SERVICE_PYTHON") or sys.executable  # the voice check runs from another environment
        if name == "filer":
            python = filer_python()
        proc = subprocess.Popen([python, "-m", MODULE[name]], cwd=ROOT, env=self.env, stdout=log, stderr=subprocess.STDOUT)
        self.procs.append(proc)
        self.by_name[name] = proc

    def stop(self, name: str) -> None:
        """Stop one service (to test what happens when it is down)."""
        proc = self.by_name.pop(name)
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        self.procs.remove(proc)

    def start(self, name: str) -> None:
        self._spawn(name)
        self._wait(name)

    def _wait(self, name: str, seconds: float = 40) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                with _opener.open(url(name, "/health"), timeout=1) as r:
                    if r.status == 200:
                        return
            except Exception:
                time.sleep(0.2)
        log = (self.logs / f"{name}.log").read_text(encoding="utf-8", errors="replace")[-1500:]
        raise RuntimeError(f"{name} did not start:\n{log}")

    @property
    def events_log(self) -> pathlib.Path:
        return pathlib.Path(self.tmp) / "logs" / "events.jsonl"

    def events(self) -> list[dict]:
        if not self.events_log.exists():
            return []
        return [json.loads(line) for line in self.events_log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def close(self) -> None:
        for p in self.procs:
            p.terminate()
        for p in self.procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        for f in self._files:
            f.close()


def call(method: str, target: str, payload: dict | None = None, timeout: float = 15):
    """Returns (status, parsed JSON or text)."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(target, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with _opener.open(req, timeout=timeout) as r:
            body, status = r.read().decode("utf-8"), r.status
    except urllib.error.HTTPError as e:
        body, status = e.read().decode("utf-8", "replace"), e.code
    try:
        return status, json.loads(body)
    except ValueError:
        return status, body


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_plain = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def post_form(target: str, fields: dict, files: dict | None = None):
    """POST a form without following the redirect. Returns (status, Location header, body text)."""
    if files:
        boundary = uuid.uuid4().hex
        parts = []
        for k, v in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8"))
        for k, (filename, content, ctype) in files.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n'.encode("utf-8") + content + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        data, ctype = b"".join(parts), f"multipart/form-data; boundary={boundary}"
    else:
        from urllib.parse import urlencode

        data, ctype = urlencode(fields).encode("utf-8"), "application/x-www-form-urlencoded"
    req = urllib.request.Request(target, data=data, method="POST", headers={"Content-Type": ctype})
    try:
        with _plain.open(req, timeout=15) as r:
            return r.status, r.headers.get("Location"), r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location"), e.read().decode("utf-8", "replace")


def get_text(target: str) -> tuple[int, str]:
    try:
        with _opener.open(target, timeout=15) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
