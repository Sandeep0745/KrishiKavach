"""Registry MCP server (SystemDesign §9). Port 8102.

Farmers and policies are read from SQLite. Anything about a case goes through the orchestrator API,
so the orchestrator stays the only writer and every change produces an event.
"""
from __future__ import annotations

from ghante_shared import config, db, http

from ._base import make_server, run_http

HOST, PORT = "127.0.0.1", config.port_of(config.MCP_REGISTRY_URL, 8102)
server = make_server("registry", "Insured farmers, their policies and their crop-loss cases.", HOST, PORT)
_conn = None


def conn():
    global _conn
    if _conn is None:
        _conn = db.connect()
    return _conn


def _farmer(row) -> dict | None:
    f = db.row_to_dict(row)
    if f:
        f.pop("sim", None)  # simulator personas are never exposed to agents
    return f


@server.tool()
def list_farmers_in_villages(village_ids: list[str]) -> dict:
    """Insured farmers in the given villages, each with a policy summary and plot location."""
    if not village_ids:
        return {"farmers": []}
    marks = ",".join("?" * len(village_ids))
    rows = conn().execute(
        f"SELECT f.id, f.name, f.village_id, f.is_hero, f.notes, p.id AS policy_id, p.crop, p.status AS policy_status,"
        f" p.insured_area_ha, p.plot_lat, p.plot_lon FROM farmer f JOIN policy p ON p.farmer_id = f.id"
        f" WHERE f.village_id IN ({marks}) ORDER BY f.id", list(village_ids))
    return {"farmers": [db.row_to_dict(r) for r in rows]}


@server.tool()
def get_farmer(farmer_id: str) -> dict:
    """One farmer by id, with village details."""
    f = _farmer(conn().execute("SELECT * FROM farmer WHERE id = ?", (farmer_id,)).fetchone())
    if f is None:
        return {"error": "farmer not found"}
    f["village"] = db.row_to_dict(conn().execute("SELECT * FROM village WHERE id = ?", (f["village_id"],)).fetchone())
    return f


@server.tool()
def get_policy(farmer_id: str) -> dict:
    """The crop insurance policy of a farmer."""
    p = db.row_to_dict(conn().execute("SELECT * FROM policy WHERE farmer_id = ?", (farmer_id,)).fetchone())
    return p or {"error": "policy not found"}


@server.tool()
def get_case(case_id: str) -> dict:
    """A crop-loss case with its slots, farmer, policy and evidence."""
    try:
        return http.get_json(f"{config.ORCH_URL}/api/cases/{case_id}")
    except http.HttpError as e:
        return {"error": f"orchestrator answered {e.status}", "detail": e.body[:200]}
    except Exception as e:
        return {"error": f"orchestrator not reachable: {type(e).__name__}"}


@server.tool()
def update_case_slots(case_id: str, slots: dict) -> dict:
    """Save one or more collected details (slots) on a case. Only pass the slots that changed."""
    try:
        return {"slots": http.request_json("PATCH", f"{config.ORCH_URL}/api/cases/{case_id}/slots", slots)}
    except http.HttpError as e:
        return {"error": f"orchestrator answered {e.status}", "detail": e.body[:200]}
    except Exception as e:
        return {"error": f"orchestrator not reachable: {type(e).__name__}"}


@server.tool()
def set_case_status(case_id: str, status: str, reason: str = "") -> dict:
    """Move a case to a new status (for example ESCALATED or NO_DAMAGE). Invalid moves are refused."""
    try:
        return http.post_json(f"{config.ORCH_URL}/api/cases/{case_id}/status", {"status": status, "reason": reason, "agent": "intake"})
    except http.HttpError as e:
        return {"error": f"orchestrator answered {e.status}", "detail": e.body[:200]}
    except Exception as e:
        return {"error": f"orchestrator not reachable: {type(e).__name__}"}


if __name__ == "__main__":
    run_http(server, HOST, PORT)
