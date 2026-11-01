"""Check full-demo prerequisites before starting services or scheduling a reset."""
from __future__ import annotations

import json
import pathlib
import socket
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from ghante_shared import config

    problems = []
    for name in (".venv", ".venv-voice", ".venv-browser"):
        if not (ROOT / name / "Scripts" / "python.exe").is_file():
            problems.append(f"Missing {name}: run setup/2c-install-packages.cmd.")
    if not (ROOT / ".env").is_file():
        problems.append("Missing .env: run setup/4-open-env.cmd and configure the service keys.")
    addresses = [config.ORCH_URL, config.PORTAL_URL, config.MCP_WEATHER_URL,
                 config.MCP_REGISTRY_URL, config.MCP_MANDI_URL, config.S1_URL, config.FILER_URL]
    from urllib.parse import urlparse
    expected = ("orchestrator", "portal", "mcp-weather", "mcp-registry", "mcp-mandi", "s1", "filer")
    occupied = []
    healthy = []
    own_demo = False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for address, service in zip(addresses, expected):
        parsed = urlparse(address)
        port = parsed.port or 80
        with socket.socket() as probe:
            probe.settimeout(0.25)
            if probe.connect_ex((parsed.hostname or "127.0.0.1", port)) == 0:
                occupied.append(port)
                try:
                    health_url = f"{parsed.scheme}://{parsed.netloc}/health"
                    with opener.open(health_url, timeout=3) as response:
                        health = json.loads(response.read())
                    if health.get("ok") is True and health.get("service") == service:
                        healthy.append(port)
                        if service == "orchestrator":
                            owner = health.get("project_root")
                            own_demo = bool(owner) and pathlib.Path(owner).resolve() == ROOT.resolve()
                except Exception:
                    pass
    if len(healthy) == len(addresses) and own_demo and not problems:
        print("The demo is already running and healthy. Reopening its pages; no new services or reset needed.")
        return 2
    for port in occupied:
        problems.append(f"Port {port} is in use, but the complete demo is not healthy. Stop the existing demo before starting this copy.")
    for problem in problems:
        print(problem)
    if problems:
        print("Startup cancelled; no reset was sent.")
        return 1
    print("Startup prerequisites passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
