"""FasalClaim Sandbox: our own demo claim portal (SystemDesign §14). Port 8090.

A sandbox with fictional data. It is not a government website and copies no government branding.
Run:  python -m apps.portal.main
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import threading
import uuid

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from ghante_shared import config, models

config.ensure_dirs()
templates = Jinja2Templates(directory=str(pathlib.Path(__file__).parent / "templates"))
_lock = threading.Lock()

STATES = ["Madhya Pradesh", "Maharashtra", "Rajasthan", "Uttar Pradesh"]
DISTRICTS = ["Sehore", "Bhopal", "Dewas", "Raisen", "Shajapur"]
SEASONS = ["Rabi 2025-26", "Kharif 2025", "Kharif 2026"]
CROPS = ["Wheat", "Gram", "Soybean", "Paddy", "Maize"]
CAUSES = ["Hailstorm", "Inundation", "Landslide", "Cloudburst", "Natural fire", "Unseasonal rain (post-harvest)", "Cyclone (post-harvest)"]
STAGES = ["Standing crop", "Harvested (cut and spread)"]
SUBMITTERS = ["Farmer", "Authorised assistant (on behalf of farmer)"]
OPTIONS = {"states": STATES, "districts": DISTRICTS, "seasons": SEASONS, "crops": CROPS, "causes": CAUSES, "stages": STAGES, "submitters": SUBMITTERS}

STEP1 = ["application_no", "farmer_name", "mobile", "state", "district", "tehsil", "village"]
STEP2 = ["season", "crop", "khasra_no", "insured_area_ha", "loss_date", "loss_time", "cause_of_loss", "crop_stage", "affected_area_ha", "damage_pct", "remarks"]
STEP3 = ["gps_lat", "gps_lon", "submitted_by", "declaration"]
OPTIONAL = {"remarks", "gps_lat", "gps_lon"}
CHOICES = {"state": STATES, "district": DISTRICTS, "season": SEASONS, "crop": CROPS, "cause_of_loss": CAUSES, "crop_stage": STAGES, "submitted_by": SUBMITTERS}
ALL_FIELDS = STEP1 + STEP2 + STEP3


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.PORTAL_DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS draft (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS claim (seq INTEGER PRIMARY KEY AUTOINCREMENT, reference TEXT UNIQUE, data TEXT NOT NULL,"
                 " photo_path TEXT, submitted_via TEXT, created_at TEXT)")
    return conn


def validate(fields: list[str], data: dict) -> list[str]:
    errors = []
    for name in fields:
        value = str(data.get(name, "")).strip()
        if not value and name not in OPTIONAL:
            errors.append(f"{name} is required")
        elif value and name in CHOICES and value not in CHOICES[name]:
            errors.append(f"{name} must be one of the listed options")
    for name in ("insured_area_ha", "affected_area_ha", "damage_pct"):
        if name in fields and str(data.get(name, "")).strip():
            try:
                number = float(data[name])
                if number < 0 or (name == "damage_pct" and number > 100):
                    raise ValueError
            except ValueError:
                errors.append(f"{name} must be a valid number")
    return errors


def create_claim(data: dict, photo_path: str | None, via: str) -> str:
    with _lock, db() as conn:
        cur = conn.execute("INSERT INTO claim (data, photo_path, submitted_via, created_at) VALUES (?,?,?,?)",
                           (json.dumps(data, ensure_ascii=False), photo_path, via, models.utc_now_iso()))
        reference = f"FCS-{cur.lastrowid:06d}"
        conn.execute("UPDATE claim SET reference = ? WHERE seq = ?", (reference, cur.lastrowid))
    return reference


def claim_row(row: sqlite3.Row) -> dict:
    return {"reference": row["reference"], **json.loads(row["data"]), "has_photo": bool(row["photo_path"]),
            "submitted_via": row["submitted_via"], "created_at": row["created_at"]}


def page(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, {"opt": OPTIONS, **ctx})


async def home(request: Request):
    return page(request, "home.html")


async def step1(request: Request):
    if request.method == "GET":
        return page(request, "step1.html", data={}, errors=[])
    form = await request.form()
    data = {k: str(form.get(k, "")).strip() for k in STEP1}
    errors = validate(STEP1, data)
    if errors:
        return page(request, "step1.html", data=data, errors=errors)
    draft = uuid.uuid4().hex[:12]
    with _lock, db() as conn:
        conn.execute("INSERT INTO draft (id, data) VALUES (?, ?)", (draft, json.dumps(data, ensure_ascii=False)))
    return RedirectResponse(f"/claim/{draft}/step2", status_code=303)


def load_draft(draft: str) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT data FROM draft WHERE id = ?", (draft,)).fetchone()
    return json.loads(row["data"]) if row else None


async def step2(request: Request):
    draft = request.path_params["draft"]
    data = load_draft(draft)
    if data is None:
        return RedirectResponse("/claim/new/step1", status_code=303)
    if request.method == "GET":
        return page(request, "step2.html", data=data, errors=[], draft=draft)
    form = await request.form()
    data.update({k: str(form.get(k, "")).strip() for k in STEP2})
    errors = validate(STEP2, data)
    if errors:
        return page(request, "step2.html", data=data, errors=errors, draft=draft)
    with _lock, db() as conn:
        conn.execute("UPDATE draft SET data = ? WHERE id = ?", (json.dumps(data, ensure_ascii=False), draft))
    return RedirectResponse(f"/claim/{draft}/step3", status_code=303)


async def step3(request: Request):
    draft = request.path_params["draft"]
    data = load_draft(draft)
    if data is None or "season" not in data:
        return RedirectResponse("/claim/new/step1", status_code=303)
    if request.method == "GET":
        return page(request, "step3.html", data=data, errors=[], draft=draft)
    form = await request.form()
    data.update({k: str(form.get(k, "")).strip() for k in STEP3})
    errors = validate(STEP3, data)
    photo = form.get("photo")
    photo_path = None
    if photo is not None and getattr(photo, "filename", ""):
        content = await photo.read()
        if len(content) > 8 * 1024 * 1024:
            errors.append("photo must be smaller than 8 MB")
        elif content:
            ext = pathlib.Path(photo.filename).suffix.lower()
            ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp") else ".bin"
            target = config.PORTAL_UPLOAD_DIR / f"{draft}{ext}"
            target.write_bytes(content)
            photo_path = str(target)
    if photo_path is None and not errors:
        errors.append("photo is required")
    if errors:
        return page(request, "step3.html", data=data, errors=errors, draft=draft)
    reference = create_claim(data, photo_path, "form")
    with _lock, db() as conn:
        conn.execute("DELETE FROM draft WHERE id = ?", (draft,))
    return RedirectResponse(f"/claim/confirmation/{reference}", status_code=303)


async def confirmation(request: Request):
    with db() as conn:
        row = conn.execute("SELECT * FROM claim WHERE reference = ?", (request.path_params["reference"],)).fetchone()
    if row is None:
        return page(request, "home.html", message="No report was found for that reference number.")
    return page(request, "confirmation.html", claim=claim_row(row))


async def admin(request: Request):
    with db() as conn:
        rows = [claim_row(r) for r in conn.execute("SELECT * FROM claim ORDER BY seq DESC LIMIT 1000")]
        total = conn.execute("SELECT COUNT(*) AS n FROM claim").fetchone()["n"]
    return page(request, "admin.html", claims=rows, total=total)


async def api_create(request: Request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)
    data = {k: str(body.get(k, "")).strip() for k in ALL_FIELDS}
    data["declaration"] = "on" if body.get("declaration") in (True, "on", "true", "yes") else ""
    errors = validate(ALL_FIELDS, data)
    if errors:
        return JSONResponse({"error": "invalid claim", "details": errors}, status_code=422)
    return JSONResponse({"reference": create_claim(data, str(body.get("photo_ref") or "") or None, "api")}, status_code=201)


async def api_get(request: Request):
    with db() as conn:
        row = conn.execute("SELECT * FROM claim WHERE reference = ?", (request.path_params["reference"],)).fetchone()
    return JSONResponse(claim_row(row)) if row else JSONResponse({"error": "not found"}, status_code=404)


async def api_count(request: Request):
    with db() as conn:
        return JSONResponse({"claims": conn.execute("SELECT COUNT(*) AS n FROM claim").fetchone()["n"]})


async def api_reset(request: Request):
    with _lock, db() as conn:
        conn.execute("DELETE FROM claim")
        conn.execute("DELETE FROM draft")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'claim'")
    for f in config.PORTAL_UPLOAD_DIR.glob("*"):
        if f.is_file():
            f.unlink()
    return JSONResponse({"ok": True})


async def health(request: Request):
    return JSONResponse({"ok": True, "service": "portal"})


app = Starlette(routes=[
    Route("/", home), Route("/health", health),
    Route("/claim/new/step1", step1, methods=["GET", "POST"]),
    Route("/claim/confirmation/{reference}", confirmation),
    Route("/claim/{draft}/step2", step2, methods=["GET", "POST"]),
    Route("/claim/{draft}/step3", step3, methods=["GET", "POST"]),
    Route("/admin/claims", admin),
    Route("/api/claims", api_create, methods=["POST"]), Route("/api/claims/count", api_count),
    Route("/api/claims/{reference}", api_get), Route("/api/reset", api_reset, methods=["POST"]),
])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=config.port_of(config.PORTAL_URL, 8090), log_level="warning")
