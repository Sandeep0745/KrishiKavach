"""SQLite storage (SystemDesign §4). Standard library only.

The orchestrator is the only writer of cases, evidence and calls. The registry MCP server reads farmers and policies.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS village (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, tehsil TEXT, district TEXT, state TEXT, lat REAL, lon REAL);
CREATE TABLE IF NOT EXISTS farmer (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, mobile TEXT, village_id TEXT REFERENCES village(id),
  is_hero INTEGER NOT NULL DEFAULT 0, notes TEXT, sim TEXT);
CREATE TABLE IF NOT EXISTS policy (
  id TEXT PRIMARY KEY, farmer_id TEXT NOT NULL REFERENCES farmer(id), application_no TEXT, season TEXT, crop TEXT,
  khasra_no TEXT, insured_area_ha REAL, sum_insured_inr INTEGER, status TEXT, valid_from TEXT, valid_to TEXT,
  plot_lat REAL, plot_lon REAL);
CREATE TABLE IF NOT EXISTS storm_event (
  id TEXT PRIMARY KEY, type TEXT, started_at TEXT, center_lat REAL, center_lon REAL, radius_km REAL, villages TEXT);
CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY, farmer_id TEXT NOT NULL REFERENCES farmer(id), policy_id TEXT, storm_event_id TEXT,
  status TEXT NOT NULL, priority REAL, deadline_at TEXT, attempts INTEGER NOT NULL DEFAULT 0, slots TEXT NOT NULL,
  verdict TEXT, verdict_reasons TEXT, claim_ref TEXT, filing_mode TEXT, opened_at TEXT, filed_at TEXT,
  time_to_file_s REAL, is_hero INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id), photo_path TEXT, sha256 TEXT, edge_label TEXT,
  edge_confidence REAL, edge_latency_ms REAL, edge_mode TEXT, lat REAL, lon REAL, captured_at TEXT, uploaded_at TEXT,
  captured_offline INTEGER NOT NULL DEFAULT 0, weather TEXT, distance_from_plot_m REAL, loss_estimate_inr REAL);
CREATE TABLE IF NOT EXISTS call (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(id), attempt INTEGER, room TEXT, started_at TEXT,
  ended_at TEXT, outcome TEXT);
CREATE INDEX IF NOT EXISTS idx_farmer_village ON farmer(village_id);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
CREATE INDEX IF NOT EXISTS idx_cases_farmer ON cases(farmer_id);
"""

JSON_FIELDS = {"sim", "villages", "slots", "verdict_reasons", "weather"}
BOOL_FIELDS = {"is_hero", "captured_offline"}


def connect(path: pathlib.Path | None = None) -> sqlite3.Connection:
    path = path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")  # safe with WAL; a full disk sync per change made the 340-farmer run crawl on Windows
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    # columns added after the first build: a database made earlier gets them here
    for table, column, kind in (("evidence", "gps_source", "TEXT"),):
        if column not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    conn.commit()
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for key, value in list(out.items()):
        if key in JSON_FIELDS and isinstance(value, str):
            out[key] = json.loads(value)
        elif key in BOOL_FIELDS:
            out[key] = bool(value)
    return out


def load_seed(conn: sqlite3.Connection, seed_dir: pathlib.Path | None = None, scenario_path: pathlib.Path | None = None) -> dict:
    """Replace villages, farmers, policies and the storm event with the seed files. Clears cases, evidence and calls."""
    seed_dir = seed_dir or config.SEED_DIR
    scenario = json.loads((scenario_path or config.SCENARIO_PATH).read_text(encoding="utf-8"))
    villages = json.loads((seed_dir / "villages.json").read_text(encoding="utf-8"))
    farmers = json.loads((seed_dir / "farmers.json").read_text(encoding="utf-8"))
    with conn:
        for table in ("call", "evidence", "cases", "policy", "farmer", "storm_event", "village"):
            conn.execute(f"DELETE FROM {table}")
        conn.executemany(
            "INSERT INTO village (id, name, tehsil, district, state, lat, lon) VALUES (:id, :name, :tehsil, :district, :state, :lat, :lon)",
            villages)
        for f in farmers:
            conn.execute(
                "INSERT INTO farmer (id, name, mobile, village_id, is_hero, notes, sim) VALUES (?,?,?,?,?,?,?)",
                (f["id"], f["name"], f["mobile"], f["village_id"], int(f["is_hero"]), f["notes"],
                 json.dumps(f["sim"], ensure_ascii=False) if f["sim"] is not None else None))
            p = f["policy"]
            conn.execute(
                "INSERT INTO policy (id, farmer_id, application_no, season, crop, khasra_no, insured_area_ha, sum_insured_inr,"
                " status, valid_from, valid_to, plot_lat, plot_lon) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p["id"], f["id"], p["application_no"], p["season"], p["crop"], p["khasra_no"], p["insured_area_ha"],
                 p["sum_insured_inr"], p["status"], p["valid_from"], p["valid_to"], p["plot_lat"], p["plot_lon"]))
        s = scenario["storm"]
        conn.execute(
            "INSERT INTO storm_event (id, type, started_at, center_lat, center_lon, radius_km, villages) VALUES (?,?,?,?,?,?,?)",
            (s["id"], s["type"], s["started_at"], s["center_lat"], s["center_lon"], s["radius_km"],
             json.dumps(scenario["villages"], ensure_ascii=False)))
    return {"villages": len(villages), "farmers": len(farmers), "storm_event": scenario["storm"]["id"]}


def load_scenario(scenario_path: pathlib.Path | None = None) -> dict:
    return json.loads((scenario_path or config.SCENARIO_PATH).read_text(encoding="utf-8"))
