"""Filer service (SystemDesign §14.3). Port 8300. Fills the sandbox portal's claim form in a visible browser window.

    POST /file   {"case_id", "form", "photo_path", "mode": "auto" | "agent" | "scripted"}
    ->           {"claim_ref", "mode_used", "seconds", "steps", "llm_steps", "mismatches", "fallback_reason"}

Run from the browser environment:  .venv-browser\\Scripts\\python.exe -m apps.filer.main
The only site this service ever opens is our own sandbox portal on this computer.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import pathlib
import time
from urllib.parse import urlparse

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ghante_shared import config, http

from . import agent_mode
from .browser import BrowserProcess, version
from .scripted import PortalBrowser

PORTAL = config.PORTAL_URL
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
window = BrowserProcess()
portal = PortalBrowser(PORTAL, field_delay_ms=config.env_int("FILER_FIELD_DELAY_MS", 250))
_busy = asyncio.Lock()


def portal_is_ours() -> bool:
    """The Filer refuses to work on anything but a portal on this computer."""
    return (urlparse(PORTAL).hostname or "") in LOCAL_HOSTS


def scripted_available() -> tuple[bool, str]:
    try:
        import playwright.async_api  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return False, f"Playwright is not installed in this environment ({type(e).__name__})"
    return True, "ready"


def step_reporter(case_id: str, mode: str, offset: int = 0):
    def report(n: int, action: str, field: str) -> None:
        http.post_event(config.ORCH_URL, "filing.step", {"n": offset + n, "action": action, "field": field, "mode": mode}, case_id=case_id, agent="filing")

    return report


async def open_window() -> None:
    ws = await asyncio.to_thread(window.ensure, PORTAL + "/")
    await portal.connect(ws)


def read_claim(reference: str) -> dict | None:
    try:
        return http.get_json(f"{PORTAL}/api/claims/{reference}", timeout=5.0)
    except Exception:  # noqa: BLE001
        return None


def compare(form: dict, record: dict | None) -> list[str]:
    """Names of the fields where the portal's record differs from what was sent."""
    if record is None:
        return ["(record not found)"]
    differ = [k for k, v in form.items() if str(record.get(k, "")) != str(v)]
    if not record.get("has_photo"):
        differ.append("photo")
    return differ


async def file_claim(case_id: str, form: dict, photo_path: str, mode: str) -> dict:
    t0 = time.perf_counter()
    await open_window()
    await portal.go_home()
    delay = config.env_float("FILER_TEST_DELAY_S", 0.0)
    if delay > 0:  # test T3-09 only: makes filing slow so the call's "taking longer" path can be heard
        print(f"[filer] waiting {delay:.0f} s before filing (FILER_TEST_DELAY_S is set)", flush=True)
        await asyncio.sleep(delay)
    used, steps, llm_steps, fallback_reason, reference = mode, 0, 0, "", None
    if mode in ("agent", "auto"):
        ok, why = agent_mode.available()
        if ok:
            limit = config.env_float("FILING_TIMEOUT_S", 75.0)
            try:
                out = await agent_mode.run(window.http_url, PORTAL, form, photo_path, limit, step_reporter(case_id, "agent"), portal)
            except Exception as exc:  # agent initialization and CDP errors also need the auto fallback
                out = {"actions": 0, "llm_steps": 0, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
            steps, llm_steps = out["actions"], out["llm_steps"]
            await open_window()  # recover if the agent lost its browser connection
            reference = await portal.reference_on_screen()
            if reference:
                used = "agent"
            else:
                why = out["error"] or "the agent finished without reaching the confirmation page"
        if not reference:
            if mode == "agent":
                raise RuntimeError(f"agent mode failed: {why}")
            fallback_reason = why
            http.post_event(config.ORCH_URL, "fallback.used", {"component": "filer", "from": "agent", "to": "scripted", "reason": why[:160]},
                            case_id=case_id, agent="filing")
    if not reference:
        ok, why = scripted_available()
        if not ok:
            raise RuntimeError(why)
        reference, more = await portal.fill(form, photo_path, step_reporter(case_id, "scripted", offset=steps))
        steps += more
        used = "scripted"
    record = await asyncio.to_thread(read_claim, reference)
    if record is None:
        raise RuntimeError(f"the portal has no report with the reference {reference} that the page showed")
    http.flush_events(2.0)
    return {"claim_ref": reference, "mode_used": used, "seconds": round(time.perf_counter() - t0, 1), "steps": steps, "llm_steps": llm_steps,
            "mismatches": compare(form, record), "fallback_reason": fallback_reason}


async def post_file(request: Request) -> JSONResponse:
    try:
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("form"), dict):
            raise ValueError
    except (ValueError, json.JSONDecodeError):
        return JSONResponse({"error": 'body must be {"case_id", "form": {...}, "photo_path", "mode"}'}, status_code=400)
    if not portal_is_ours():
        return JSONResponse({"error": "PORTAL_URL is not on this computer; the Filer only works on the sandbox portal"}, status_code=403)
    photo = pathlib.Path(str(body.get("photo_path") or ""))
    if not photo.is_file():
        return JSONResponse({"error": "photo_path does not point to a file"}, status_code=400)
    mode = str(body.get("mode") or "auto").lower()
    if mode not in ("auto", "agent", "scripted"):
        return JSONResponse({"error": "mode must be auto, agent or scripted"}, status_code=400)
    if _busy.locked():
        return JSONResponse({"error": "another report is being filed in the browser right now"}, status_code=409)
    async with _busy:
        try:
            out = await file_claim(str(body.get("case_id") or ""), {k: str(v) for k, v in body["form"].items()}, str(photo.resolve()), mode)
        except Exception as e:  # noqa: BLE001 - report the reason; the pipeline marks the case FAILED
            return JSONResponse({"error": f"{type(e).__name__}: {str(e)[:300]}"}, status_code=502)
    return JSONResponse(out)


async def health(request: Request) -> JSONResponse:
    agent_ok, agent_why = agent_mode.available()
    scripted_ok, scripted_why = scripted_available()
    return JSONResponse({"ok": True, "service": "filer", "portal": PORTAL, "portal_is_local": portal_is_ours(),
                         "browser": pathlib.Path(window.path).name if window.path else None, "window_open": version() is not None,
                         "scripted": {"usable": scripted_ok, "detail": scripted_why}, "agent": {"usable": agent_ok, "detail": agent_why,
                                                                                               "models": [f"{p}:{m}" for p, m in agent_mode.chain()]}})


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    if config.env("FILER_OPEN_AT_START", "1") != "0" and portal_is_ours() and scripted_available()[0]:
        try:
            await open_window()  # the window is ready, and in place, before the first report
        except Exception as e:  # noqa: BLE001 - it is tried again when the first report arrives
            print(f"[filer] the browser window could not be opened yet: {type(e).__name__}: {str(e)[:160]}", flush=True)
    yield
    await portal.close()
    window.close()


app = Starlette(lifespan=lifespan, routes=[Route("/file", post_file, methods=["POST"]), Route("/health", health)])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=config.port_of(config.FILER_URL, 8300), log_level="warning")
