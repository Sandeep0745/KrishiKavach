"""Orchestrator (SystemDesign §6): cases, events, state, the hero call and evidence upload.

Run:  python -m apps.orchestrator.main
The claim pipeline (Phase 3) is in apps/orchestrator/pipeline/. The district run (Phase 4) is scenario.py, sentinel.py,
dispatcher.py and simulator.py.
"""
from __future__ import annotations

import asyncio
import contextlib
import html
import json
import shutil
import time

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ghante_shared import config, db, http, livekit_token, models

from .bus import EventBus
from .cases import CaseStore, NotFound, TransitionError
from .clock import SimClock
from .pipeline import rules
from .pipeline.service import Pipeline
from .scenario import Scenario

config.ensure_dirs()
bus = EventBus()
conn = db.connect()
_scenario = db.load_scenario()
clock = SimClock(_scenario["storm"]["started_at"], speed=config.env_float("SIM_SPEED", 180.0))
store = CaseStore(conn, bus, clock, deadline_hours=int(_scenario.get("deadline_hours", 72)))
farmer_queues: dict[str, set[asyncio.Queue]] = {}
pipeline = Pipeline(store, lambda farmer_id, type_, data: send_to_farmer(farmer_id, type_, data))
scenario = Scenario(store, clock, pipeline, _scenario)
from .weather_watch import WeatherWatch
weather_watch = WeatherWatch(scenario, store)
farmer_messages: dict[str, list[dict]] = {}  # farmer_id -> message cards already sent; a phone that connects later still gets them
ringing: dict[str, dict] = {}            # farmer_id -> the call.incoming payload of a call that is ringing now
ring_timers: dict[str, asyncio.Task] = {}  # call_id -> the task that gives up when nobody answers
RING_TIMEOUT_S = config.env_float("RING_TIMEOUT_S", 60.0)
farmer_polled: dict[str, float] = {}       # farmer_id -> when a phone last asked /poll (a tunnel can hold back the event stream)
POLL_FRESH_S = 8.0


def phones_of(farmer_id: str) -> int:
    """Phones listening for this farmer: open event streams, or at least one if a phone polled in the last few seconds."""
    n = len(farmer_queues.get(farmer_id, set()))
    if time.monotonic() - farmer_polled.get(farmer_id, -1e9) < POLL_FRESH_S:
        n = max(n, 1)
    return n
MAX_PHOTO_BYTES = 8 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}

if conn.execute("SELECT COUNT(*) AS n FROM farmer").fetchone()["n"] == 0:
    db.load_seed(conn)


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


async def body_json(request: Request) -> dict:
    try:
        data = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("body must be JSON") from None
    if not isinstance(data, dict):
        raise ValueError("body must be a JSON object")
    return data


async def health(request: Request) -> JSONResponse:
    hero = store.hero_farmer_id()
    return JSONResponse({"ok": True, "service": "orchestrator", "project_root": str(config.ROOT), "cases": store.stats()["affected"], "pipeline_engine": pipeline.engine,
                         "scenario": scenario.state, "hero_phones": phones_of(hero) if hero else 0})


async def get_state(request: Request) -> JSONResponse:
    return JSONResponse(store.snapshot())


async def scenario_reset(request: Request) -> JSONResponse:
    for farmer_id, payload in list(ringing.items()):
        send_to_farmer(farmer_id, "call.cancelled", {"call_id": payload["call_id"]})
    ringing.clear()
    for task in ring_timers.values():
        task.cancel()
    ring_timers.clear()
    scenario.reset()
    pipeline.reset()
    farmer_messages.clear()
    info = store.reset()
    with contextlib.suppress(OSError):
        shutil.rmtree(config.EVIDENCE_DIR)
    config.ensure_dirs()
    portal_ok = True
    try:
        await asyncio.to_thread(http.post_json, f"{config.PORTAL_URL}/api/reset", {}, 3.0)
    except Exception:
        portal_ok = False  # the portal may simply not be running
    with contextlib.suppress(Exception):  # the decision service forgets the last run's repeated answers
        await asyncio.to_thread(http.post_json, f"{config.S1_URL}/reset", {}, 2.0)
    store.emit("snapshot", store.snapshot())
    return JSONResponse({"ok": True, "portal_reset": portal_ok, **info})


async def _optional_body(request: Request) -> dict:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - these controls are usually pressed with no body at all
        return {}


def _speed(data: dict) -> float | None:
    value = data.get("speed")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value <= 100000 else None


async def scenario_start(request: Request) -> JSONResponse:
    """Presenter: the storm is on record; detect it, open the cases, rank them and start calling."""
    data = await _optional_body(request)
    try:
        scenario.start(_speed(data))
    except ValueError as e:
        return err(409, str(e))
    return JSONResponse({"ok": True, **scenario.info()})


async def scenario_pause(request: Request) -> JSONResponse:
    changed = scenario.pause("presenter")
    return JSONResponse({"ok": True, "changed": changed, **scenario.info()})


async def scenario_resume(request: Request) -> JSONResponse:
    data = await _optional_body(request)
    changed = scenario.resume(_speed(data))
    return JSONResponse({"ok": True, "changed": changed, **scenario.info()})


async def get_queue(request: Request) -> JSONResponse:
    """The Dispatcher's queue: who is called next, and the order in which first calls were placed so far."""
    d = scenario.dispatcher
    if d is None:
        return JSONResponse({"state": scenario.state, "queue": [], "called": []})
    return JSONResponse({"state": scenario.state, **d.info(), "queue": d.queue(), "called": list(d.call_order)})


async def open_case(request: Request) -> JSONResponse:
    """Development and test helper: open a case for one farmer. The Dispatcher does this for everyone in Phase 4."""
    try:
        data = await body_json(request)
        return JSONResponse(store.open_case(str(data.get("farmer_id", ""))), status_code=201)
    except ValueError as e:
        return err(400, str(e))
    except NotFound as e:
        return err(404, f"not found: {e.args[0]}")


async def get_case(request: Request) -> JSONResponse:
    try:
        return JSONResponse(store.get(request.path_params["case_id"]))
    except NotFound:
        return err(404, "case not found")


async def patch_slots(request: Request) -> JSONResponse:
    try:
        data = await body_json(request)
        return JSONResponse(store.update_slots(request.path_params["case_id"], data))
    except NotFound:
        return err(404, "case not found")
    except ValueError as e:
        return err(400, str(e))


async def post_status(request: Request) -> JSONResponse:
    try:
        data = await body_json(request)
        result = store.set_status(request.path_params["case_id"], str(data.get("status", "")), str(data.get("reason", "")),
                                  agent=str(data.get("agent", "system")))
        return JSONResponse({"ok": True, **result})
    except NotFound:
        return err(404, "case not found")
    except TransitionError as e:
        return err(409, str(e))
    except ValueError as e:
        return err(400, str(e))


async def internal_event(request: Request) -> JSONResponse:
    try:
        data = await body_json(request)
    except ValueError as e:
        return err(400, str(e))
    type_ = data.get("type")
    if not isinstance(type_, str) or not type_:
        return err(400, "type is required")
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}
    event = store.emit(type_, payload, case_id=data.get("case_id"), agent=str(data.get("agent", "system")),
                       live=data.get("live") if isinstance(data.get("live"), bool) else None)
    return JSONResponse({"ok": True, "id": event["id"]})


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


async def events_stream(request: Request) -> StreamingResponse:
    """Dashboard stream (Server-Sent Events). First message is a snapshot, then every event as it happens."""
    queue = bus.subscribe()

    async def gen():
        try:
            yield sse(models.new_event("snapshot", store.snapshot(), sim_ts=clock.now_iso()))
            for earlier in bus.recent():  # a dashboard opened mid-demo shows the ticker, the tool calls and the live call so far
                yield sse(earlier)
            yield sse(models.new_event("tallies", dict(bus.tallies), sim_ts=clock.now_iso()))
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield sse(event)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- the hero call (SystemDesign §6 and §10.1) ----------
def _stop_ringing(call_id: str, farmer_id: str | None = None) -> None:
    task = ring_timers.pop(call_id, None)
    if task is not None and task is not asyncio.current_task():
        task.cancel()
    for fid, payload in list(ringing.items()):
        if payload["call_id"] == call_id and (farmer_id is None or fid == farmer_id):
            ringing.pop(fid, None)


async def _ring_timeout(call_id: str, farmer_id: str) -> None:
    await asyncio.sleep(RING_TIMEOUT_S)
    if ringing.get(farmer_id, {}).get("call_id") != call_id:
        return
    _stop_ringing(call_id, farmer_id)
    send_to_farmer(farmer_id, "call.cancelled", {"call_id": call_id})
    with contextlib.suppress(Exception):
        store.end_call(call_id, "no_answer")


async def hero_call(request: Request) -> JSONResponse:
    """Presenter: ring the hero farmer's phone. Opens the hero's case first if the storm has not been dispatched yet."""
    farmer_id = store.hero_farmer_id()
    if farmer_id is None:
        return err(404, "no hero farmer in the data")
    try:
        case = store.open_case(farmer_id)
        call = store.place_call(case["id"], "hero call")
    except TransitionError as e:
        return err(409, f"{e}. The hero's case is left from an earlier run: press Reset (R twice), then Start storm, then Call hero")
    except NotFound as e:
        return err(404, f"not found: {e.args[0]}")
    if not scenario.pause("live call"):  # the fleet waits while the live call runs; the presenter resumes it with P
        clock.pause()
    payload = {"call_id": call["id"], "case_id": case["id"], "caller_name": "Crop Insurance Help"}
    ringing[farmer_id] = payload
    send_to_farmer(farmer_id, "call.incoming", payload)
    phones = phones_of(farmer_id)
    ring_timers[call["id"]] = asyncio.create_task(_ring_timeout(call["id"], farmer_id))
    return JSONResponse({"ok": True, "call_id": call["id"], "case_id": case["id"], "farmer_id": farmer_id, "room": call["room"], "phones": phones})


async def call_accept(request: Request) -> JSONResponse:
    """Farmer app: the call was answered. Returns what the phone needs to join the room; joining dispatches the Intake agent."""
    call_id = request.path_params["call_id"]
    key, secret, url = config.env("LIVEKIT_API_KEY"), config.env("LIVEKIT_API_SECRET"), config.env("LIVEKIT_URL")
    if not (key and secret and url):
        return err(503, "LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set in .env")
    try:
        call = store.answer_call(call_id)
        case = store.get(call["case_id"])
    except NotFound:
        return err(404, "call not found")
    except TransitionError as e:
        return err(409, str(e))
    _stop_ringing(call_id)
    token = livekit_token.make_token(key, secret, identity=f"farmer-{case['farmer_id']}", name=case["farmer"]["name"], room=call["room"],
                                     agent_name="intake", agent_metadata={"case_id": case["id"], "call_id": call_id})
    return JSONResponse({"livekit_url": url, "token": token, "room": call["room"], "case_id": case["id"], "call_id": call_id})


async def call_decline(request: Request) -> JSONResponse:
    call_id = request.path_params["call_id"]
    try:
        _stop_ringing(call_id)
        call = store.end_call(call_id, "declined")
    except NotFound:
        return err(404, "call not found")
    return JSONResponse({"ok": True, "outcome": call["outcome"]})


async def call_end(request: Request) -> JSONResponse:
    """Voice worker or farmer app: the call is over. The first report sets the outcome."""
    call_id = request.path_params["call_id"]
    try:
        data = await body_json(request)
        _stop_ringing(call_id)
        call = store.end_call(call_id, str(data.get("outcome", "completed")))
    except NotFound:
        return err(404, "call not found")
    except ValueError as e:
        return err(400, str(e))
    return JSONResponse({"ok": True, "outcome": call["outcome"]})


# ---------- evidence ----------
def clean_meta(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("meta must be a JSON object")
    meta: dict = {}
    label = raw.get("label")
    if label is not None and label not in models.EDGE_LABELS:
        raise ValueError(f"label must be one of {models.EDGE_LABELS}")
    meta["label"] = label
    for name, low, high in (("confidence", 0, 1), ("latency_ms", 0, 600000), ("lat", -90, 90), ("lon", -180, 180)):
        value = raw.get(name)
        if value is None:
            meta[name] = None
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise ValueError(f"{name} must be a number from {low} to {high}")
        else:
            meta[name] = float(value)
    for name in ("edge_mode", "captured_at", "gps_source"):
        meta[name] = str(raw[name])[:40] if raw.get(name) is not None else None
    meta["captured_offline"] = bool(raw.get("captured_offline"))
    return meta


async def post_evidence(request: Request) -> JSONResponse:
    """Farmer app: multipart with `photo` (the image) and `meta` (JSON text: label, confidence, latency_ms, edge_mode, lat, lon,
    captured_at, captured_offline)."""
    case_id = request.path_params["case_id"]
    try:
        form = await request.form(max_files=2, max_fields=10)
    except Exception:
        return err(400, "body must be multipart form data")
    photo = form.get("photo")
    if photo is None or not hasattr(photo, "read"):
        return err(400, "photo file is required")
    suffix = PHOTO_TYPES.get((photo.content_type or "").split(";")[0].strip().lower())
    if suffix is None:
        return err(415, "photo must be JPEG, PNG or WebP")
    content = await photo.read()
    if not content:
        return err(400, "photo is empty")
    if len(content) > MAX_PHOTO_BYTES:
        return err(413, "photo is larger than 8 MB")
    try:
        meta = clean_meta(json.loads(form.get("meta") or "{}"))
        out = await asyncio.to_thread(store.add_evidence, case_id, content, meta, suffix)
    except (json.JSONDecodeError, TypeError):
        return err(400, "meta must be JSON text")
    except ValueError as e:
        return err(400, str(e))
    except NotFound:
        return err(404, "case not found")
    return JSONResponse(out, status_code=201)


async def evidence_photo(request: Request):
    try:
        path = store.evidence_path(request.path_params["evidence_id"])
    except NotFound:
        return err(404, "evidence not found")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})


def send_to_farmer(farmer_id: str, type_: str, data: dict) -> int:
    """Push a message to a farmer's phone (call.incoming, call.cancelled, message). Returns how many phones got it."""
    message = {"type": type_, "ts": models.utc_now_iso(), "data": data}
    if type_ == "message":
        farmer_messages.setdefault(farmer_id, []).append(message)
    queues = farmer_queues.get(farmer_id, set())
    for q in list(queues):
        with contextlib.suppress(asyncio.QueueFull):
            q.put_nowait(message)
    return len(queues)


async def farmer_stream(request: Request) -> StreamingResponse:
    farmer_id = request.path_params["farmer_id"]
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    farmer_queues.setdefault(farmer_id, set()).add(queue)

    async def gen():
        try:
            yield sse({"type": "connected", "ts": models.utc_now_iso(), "data": {"farmer_id": farmer_id}})
            if farmer_id in ringing:  # the phone opened the app while its call was already ringing
                yield sse({"type": "call.incoming", "ts": models.utc_now_iso(), "data": ringing[farmer_id]})
            for earlier in list(farmer_messages.get(farmer_id, [])):
                yield sse(earlier)
            while True:
                try:
                    yield sse(await asyncio.wait_for(queue.get(), timeout=15))
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            farmer_queues.get(farmer_id, set()).discard(queue)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def farmer_poll(request: Request) -> JSONResponse:
    """Farmer app, every 2 s: the call ringing now and the message cards. Works where a tunnel buffers the event stream."""
    farmer_id = request.path_params["farmer_id"]
    farmer_polled[farmer_id] = time.monotonic()
    return JSONResponse({"ringing": ringing.get(farmer_id), "messages": farmer_messages.get(farmer_id, [])[-20:]},
                        headers={"Cache-Control": "no-store"})


# ---------- claim pipeline (SystemDesign §6 and §13) ----------
async def pipeline_run(request: Request) -> JSONResponse:
    """Voice worker or simulator: run Evidence -> Eligibility -> Filing -> Follow-up for a case and wait for the outcome.
    If filing takes longer than the wait, the answer has pending=true and the run finishes in the background."""
    case_id = request.path_params["case_id"]
    try:
        case = store.get(case_id)
    except NotFound:
        return err(404, "case not found")
    task = pipeline.running(case_id)
    if task is None:
        if case["status"] == models.FILED:
            return JSONResponse(pipeline.result(case_id))
        if case["status"] == models.PROCESSING:
            task = pipeline.start(case_id)
        elif case["status"] == models.FAILED:
            task = pipeline.start(case_id, start_at="filing", note="Second attempt after a failed submission.")
        else:
            return err(409, f"a case in status {case['status']} cannot be processed; it must be PROCESSING (or FAILED, to try filing again)")
    return JSONResponse(await pipeline.wait(task, case_id))


async def case_review(request: Request) -> JSONResponse:
    """Dashboard: a person decides a case that Eligibility sent to review. Approval continues at filing."""
    case_id = request.path_params["case_id"]
    try:
        data = await body_json(request)
        case = store.get(case_id)
    except ValueError as e:
        return err(400, str(e))
    except NotFound:
        return err(404, "case not found")
    if not isinstance(data.get("approve"), bool):
        return err(400, "approve must be true or false")
    if case["status"] != models.ESCALATED or case.get("verdict") != "review":
        return err(409, "only a case that Eligibility sent to review can be decided here")
    if pipeline.running(case_id):
        return err(409, "this case is already being filed")
    note = str(data.get("note") or "")[:200]
    store.emit("review.decision", {"approve": data["approve"], "note": note, "by": "human reviewer", "reasons": case.get("verdict_reasons") or []},
               case_id=case_id, agent="system")
    if not data["approve"]:
        return JSONResponse({"ok": True, "approved": False, "status": case["status"]})
    task = pipeline.start(case_id, start_at="filing", note="Approved by a human reviewer" + (f": {note}" if note else "."))
    return JSONResponse({"ok": True, "approved": True, **(await pipeline.wait(task, case_id))})


def _row(label: str, value: object) -> str:
    return f"<dt>{html.escape(label)}</dt><dd>{html.escape('' if value is None else str(value))}</dd>"


async def evidence_pack(request: Request):
    """One page with everything known about a case: statement, photo, weather record, checks and outcome (P1)."""
    try:
        case = store.get(request.path_params["case_id"])
    except NotFound:
        return err(404, "case not found")
    ev = store.latest_evidence(case["id"])
    weather, distance = (ev or {}).get("weather"), (ev or {}).get("distance_from_plot_m")
    checks = rules.run_checks(case, ev, weather, distance, clock.now())
    slots, policy, farmer, village = case["slots"], case.get("policy") or {}, case.get("farmer") or {}, case.get("village") or {}
    parts = ["<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>",
             f"<title>Evidence pack {html.escape(case['id'])}</title><style>body{{font:16px/1.5 system-ui,Segoe UI,Arial,sans-serif;max-width:820px;margin:24px auto;padding:0 16px;color:#1d2a24}}"
             ".note{background:#fff4d6;color:#6b4a00;padding:8px 12px;border-radius:6px;font-weight:600}dl{display:grid;grid-template-columns:230px 1fr;gap:4px 12px}"
             "dt{color:#5d6b63}dd{margin:0}img{max-width:100%;max-height:360px;border-radius:6px}li.fail{color:#a3281f;font-weight:600}h2{margin-top:28px}</style></head><body>",
             "<p class='note'>Demo data. The farmer, the policy and the storm are synthetic.</p>",
             f"<h1>Evidence pack: {html.escape(str(farmer.get('name')))}, {html.escape(str(village.get('name')))}</h1><dl>",
             _row("Case", case["id"]), _row("Status", case["status"]), _row("Reference", case.get("claim_ref") or "not filed"),
             _row("Filed by", {"agent": "browser agent", "scripted": "scripted browser fill", "api": "portal API"}.get(case.get("filing_mode"), "")),
             _row("Application number", policy.get("application_no")), _row("Crop and plot", f"{policy.get('crop')}, khasra {policy.get('khasra_no')}, {policy.get('insured_area_ha')} ha"),
             "</dl><h2>What the farmer said on the call</h2><dl>",
             _row("Cause (farmer's words)", slots.get("cause_text")), _row("Cause (classified)", slots.get("peril")), _row("Time of loss", slots.get("loss_datetime")),
             _row("Share of crop lost", f"{slots.get('damage_pct')}%" if slots.get("damage_pct") is not None else ""), _row("Crop stage", slots.get("crop_stage")),
             _row("Consent to file", "yes" if slots.get("consent") else "no"), "</dl><h2>Photo</h2>"]
    if ev:
        parts += [f"<img src='/api/evidence/{html.escape(ev['id'])}/photo' alt='Photo taken by the farmer'><dl>",
                  _row("Checked on the phone", f"{rules.PHOTO_WORDS.get(ev.get('edge_label'), 'not checked')}"
                       + (f", {round(ev['edge_confidence'] * 100)}% sure" if ev.get("edge_confidence") is not None else "")),
                  _row("SHA-256 of the file", ev.get("sha256")), _row("Location", f"{ev.get('lat')}, {ev.get('lon')} (source: {ev.get('gps_source') or 'phone'})"),
                  _row("Distance from the insured plot", f"{round(distance)} m" if distance is not None else "not known"),
                  _row("Taken with no network", "yes" if ev.get("captured_offline") else "no"), "</dl>"]
    else:
        parts.append("<p>No photo was received.</p>")
    parts.append("<h2>Weather record at that place and time</h2><dl>")
    if weather:
        parts += [_row("Hail", "yes" if weather.get("hail") else "no"), _row("Rain", f"{weather.get('precipitation_mm')} mm"),
                  _row("Wind gusts", f"{weather.get('wind_gust_kmh')} km/h"), _row("Source", weather.get("source"))]
    else:
        parts.append(_row("Record", "not read yet"))
    if (ev or {}).get("loss_estimate_inr"):
        parts.append(_row("Illustrative value of the lost crop", f"about Rs {int(ev['loss_estimate_inr']):,} (affected area x a typical yield x the mandi price; not an assessment, not filed)"))
    parts.append("</dl><h2>Checks</h2><ul>")
    parts += [f"<li class='{'ok' if c['passed'] else 'fail'}'>{'Passed' if c['passed'] else 'Failed'}: {html.escape(c['detail'])}</li>" for c in checks]
    parts.append(f"</ul><p>Verdict: <b>{html.escape(case.get('verdict') or 'not decided yet')}</b>"
                 + ("".join(f"<br>{html.escape(r)}" for r in case.get("verdict_reasons") or [])) + "</p></body></html>")
    return HTMLResponse("".join(parts), headers=NO_CACHE)


WEB_DIR = config.ROOT / "apps" / "web"
NO_CACHE = {"Cache-Control": "no-cache"}  # the files change while we build; the phone must never show an old copy


class NoCacheStatic(StaticFiles):
    """Our own files must be re-checked on every load, or a phone keeps running yesterday's script."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


async def dashboard_page(request: Request) -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", headers=NO_CACHE)


async def farmer_page(request: Request) -> FileResponse:
    return FileResponse(WEB_DIR / "farmer.html", headers=NO_CACHE)


async def service_worker(request: Request) -> FileResponse:
    """Served from the root so that its scope covers /farmer."""
    return FileResponse(WEB_DIR / "sw.js", media_type="text/javascript", headers=NO_CACHE)


async def farmer_card(request: Request) -> JSONResponse:
    try:
        return JSONResponse(store.farmer_card(request.path_params["farmer_id"]))
    except NotFound:
        return err(404, "farmer not found")


async def weather_status(request: Request):
    return JSONResponse(weather_watch.info(), headers=NO_CACHE)


def local_presenter(request: Request) -> bool:
    from urllib.parse import urlsplit
    host = urlsplit('http://' + request.headers.get('host', '')).hostname
    origin = request.headers.get('origin')
    return (request.client is not None and request.client.host in ('127.0.0.1', '::1')
            and host in ('127.0.0.1', 'localhost', '::1')
            and (not origin or origin.rstrip('/') == str(request.base_url).rstrip('/')))


async def weather_demo(request: Request):
    if not local_presenter(request):
        return err(403, 'Demo weather controls are available only on the laptop dashboard')
    try:
        weather_watch.arm_demo()
    except ValueError as exc:
        return err(409, str(exc))
    return JSONResponse(weather_watch.info())


async def weather_live(request: Request):
    if not local_presenter(request):
        return err(403, 'Weather controls are available only on the laptop dashboard')
    weather_watch.use_live()
    return JSONResponse(weather_watch.info())


@contextlib.asynccontextmanager
async def lifespan(app: Starlette):
    bus.bind_loop(asyncio.get_running_loop())
    task = asyncio.create_task(weather_watch.run())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = Starlette(lifespan=lifespan, routes=[
    Route("/", dashboard_page),
    Route("/farmer", farmer_page),
    Route("/sw.js", service_worker),
    Route("/api/farmers/{farmer_id}", farmer_card),
    Mount("/static", NoCacheStatic(directory=str(WEB_DIR)), name="static"),
    Route("/health", health),
    Route("/api/state", get_state),
    Route("/api/weather/status", weather_status),
    Route("/api/weather/demo", weather_demo, methods=["POST"]),
    Route("/api/weather/live", weather_live, methods=["POST"]),
    Route("/api/scenario/reset", scenario_reset, methods=["POST"]),
    Route("/api/scenario/start", scenario_start, methods=["POST"]),
    Route("/api/scenario/pause", scenario_pause, methods=["POST"]),
    Route("/api/scenario/resume", scenario_resume, methods=["POST"]),
    Route("/api/queue", get_queue),
    Route("/api/cases", open_case, methods=["POST"]),
    Route("/api/cases/{case_id}", get_case),
    Route("/api/cases/{case_id}/slots", patch_slots, methods=["PATCH"]),
    Route("/api/cases/{case_id}/status", post_status, methods=["POST"]),
    Route("/api/cases/{case_id}/evidence", post_evidence, methods=["POST"]),
    Route("/api/evidence/{evidence_id}/photo", evidence_photo),
    Route("/api/hero/call", hero_call, methods=["POST"]),
    Route("/api/calls/{call_id}/accept", call_accept, methods=["POST"]),
    Route("/api/calls/{call_id}/decline", call_decline, methods=["POST"]),
    Route("/api/calls/{call_id}/end", call_end, methods=["POST"]),
    Route("/api/cases/{case_id}/pipeline/run", pipeline_run, methods=["POST"]),
    Route("/api/cases/{case_id}/review", case_review, methods=["POST"]),
    Route("/api/cases/{case_id}/evidence-pack", evidence_pack),
    Route("/internal/events", internal_event, methods=["POST"]),
    Route("/api/events/stream", events_stream),
    Route("/api/farmer/{farmer_id}/stream", farmer_stream),
    Route("/api/farmer/{farmer_id}/poll", farmer_poll),
])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=config.port_of(config.ORCH_URL, 8000), log_level="warning")
