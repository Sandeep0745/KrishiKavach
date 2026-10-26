"""Configuration: reads .env once, then environment variables. No secrets are ever printed."""
from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_env(path: pathlib.Path | None = None) -> None:
    """Load KEY=VALUE lines from .env into os.environ without overriding what is already set."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(env(name, str(default)))
    except ValueError:
        return default


VAR_DIR = pathlib.Path(env("GHANTE_VAR_DIR", str(ROOT / "var")))
LOG_DIR = pathlib.Path(env("GHANTE_LOG_DIR", str(ROOT / "logs")))
DATA_DIR = ROOT / "data"
DB_PATH = VAR_DIR / "app.db"
PORTAL_DB_PATH = VAR_DIR / "portal.db"
EVIDENCE_DIR = VAR_DIR / "evidence"
PORTAL_UPLOAD_DIR = VAR_DIR / "portal_uploads"
EVENTS_LOG = LOG_DIR / "events.jsonl"
USAGE_LOG = LOG_DIR / "usage.json"

SCENARIO = env("SCENARIO", "sehore_hail")
SCENARIO_PATH = DATA_DIR / "scenarios" / f"{SCENARIO}.json"
SEED_DIR = DATA_DIR / "seed"

PORTS = {"orchestrator": 8000, "portal": 8090, "mcp_weather": 8101, "mcp_registry": 8102, "mcp_mandi": 8103, "s1": 8200, "filer": 8300, "web": 5173}

def _local(url: str) -> str:
    """Service-to-service addresses use 127.0.0.1, not the name "localhost". On Windows the name is tried over IPv6 first and each
    new connection then waits about 2 seconds before falling back; measured in the first spoken test as 2.06 s on every turn."""
    return url.replace("://localhost:", "://127.0.0.1:").replace("://localhost/", "://127.0.0.1/")


ORCH_URL = _local(env("ORCH_URL", "http://localhost:8000").rstrip("/"))
S1_URL = _local(env("S1_URL", "http://localhost:8200").rstrip("/"))
FILER_URL = _local(env("FILER_URL", "http://localhost:8300").rstrip("/"))
PORTAL_URL = _local(env("PORTAL_URL", "http://localhost:8090").rstrip("/"))
MCP_WEATHER_URL = _local(env("MCP_WEATHER_URL", "http://localhost:8101/mcp"))
MCP_REGISTRY_URL = _local(env("MCP_REGISTRY_URL", "http://localhost:8102/mcp"))
MCP_MANDI_URL = _local(env("MCP_MANDI_URL", "http://localhost:8103/mcp"))


def port_of(url: str, default: int) -> int:
    """Port number from a URL such as http://localhost:8000."""
    try:
        from urllib.parse import urlparse

        return urlparse(url).port or default
    except ValueError:
        return default


def ensure_dirs() -> None:
    for d in (VAR_DIR, LOG_DIR, EVIDENCE_DIR, PORTAL_UPLOAD_DIR):
        d.mkdir(parents=True, exist_ok=True)
