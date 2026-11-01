"""Keep one ngrok free development-domain link for the farmer demo.

Run after setup/7-start-everything.cmd. NGROK_AUTHTOKEN is read from .env
and passed only through the child environment, never a command or log file.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ghante_shared import config  # noqa: E402

UPSTREAM = "http://127.0.0.1:8000"
AGENT_API = "http://127.0.0.1:4048/api/tunnels"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch(url: str, *, public: bool = False) -> bytes:
    headers = {"ngrok-skip-browser-warning": "1"} if public else {}
    with opener.open(urllib.request.Request(url, headers=headers), timeout=5) as response:
        if response.status != 200:
            raise RuntimeError("The endpoint did not return HTTP 200.")
        return response.read()


def executable() -> str | None:
    bundled = ROOT / ".setup-tools" / "bin" / ("ngrok.exe" if os.name == "nt" else "ngrok")
    return str(bundled) if bundled.is_file() else shutil.which("ngrok")


def farmer_url(tunnels: dict) -> str | None:
    """Choose only the HTTPS tunnel for this app, never another local endpoint."""
    for tunnel in tunnels.get("tunnels", []):
        if tunnel.get("config", {}).get("addr", "").rstrip("/") != UPSTREAM:
            continue
        url = tunnel.get("public_url", "")
        parsed = urlsplit(url)
        if (parsed.scheme == "https" and parsed.hostname and not parsed.username
                and not parsed.password and parsed.path in ("", "/")
                and not parsed.query and not parsed.fragment):
            return url.rstrip("/") + "/farmer"
    return None


def publish_link(url: str, folder: pathlib.Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    saved = folder / "farmer-link.txt"
    previous = saved.read_text(encoding="utf-8").strip() if saved.exists() else ""
    if previous and previous != url:
        print("The account's domain changed. Replace the old bookmark with the link below.")
    saved.write_text(url + "\n", encoding="utf-8")
    (folder / "Farmer Demo.url").write_text(f"[InternetShortcut]\nURL={url}\n", encoding="utf-8")
    print(f"\nFARMER DEMO LINK: {url}\n", flush=True)
    print("Bookmark this link. Use the same ngrok account each time.")
    print(f"Saved in: {saved}")
    print("Leave this window and the demo server running. Ctrl+C closes the tunnel.")
    print("On the phone, choose Visit Site if ngrok shows its free-plan notice.", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check prerequisites without starting a tunnel")
    args = parser.parse_args(argv)
    binary = executable()
    if not binary:
        print("ngrok is missing. Follow setup/SINGLE-FARMER-LINK.md to install the free client.")
        return 1
    if not config.env("NGROK_AUTHTOKEN").strip():
        print("One-time setup: create a free account at https://dashboard.ngrok.com/signup")
        print("Copy your authtoken into .env as NGROK_AUTHTOKEN=your-token, then run this again.")
        print("Use setup/4-open-env.cmd to edit .env. Do not paste the token into chat.")
        return 1
    try:
        page = fetch(UPSTREAM + "/farmer")
        if b'id="btn-start"' not in page:
            raise RuntimeError("The local port is not serving the farmer app.")
    except Exception:
        print("The farmer app is not ready. Start setup/7-start-everything.cmd first.")
        return 1
    if args.check:
        print("Ready: ngrok installed, token configured, and farmer page available.")
        return 0
    # Do not accidentally report the URL of another running agent on this port.
    try:
        existing = json.loads(fetch(AGENT_API))
    except Exception:
        pass
    else:
        url = farmer_url(existing)
        if url:
            try:
                if b'id="btn-start"' not in fetch(url, public=True):
                    raise RuntimeError("Farmer page not returned")
            except Exception:
                print("The existing farmer tunnel is not reachable. Restart its launcher.")
                return 1
            print("The farmer tunnel is already running; reusing its verified link.")
            publish_link(url, ROOT / "var")
            return 0
        print("Port 4048 belongs to another tunnel. Close that launcher before starting this farmer link.")
        return 1
    runtime = ROOT / ".runtime"
    runtime.mkdir(exist_ok=True)
    agent_config = runtime / "ngrok-farmer.yml"
    agent_config.write_text('version: "3"\nagent:\n  web_addr: 127.0.0.1:4048\n', encoding="utf-8")
    child_env = dict(os.environ, NGROK_AUTHTOKEN=config.env("NGROK_AUTHTOKEN").strip())
    print("Connecting the account's assigned free domain...", flush=True)
    # No raw agent logs: these can include account details. No token in YAML/argv.
    try:
        proc = subprocess.Popen([binary, "http", UPSTREAM, "--config", str(agent_config),
                                 "--inspect=false", "--log", "false"], env=child_env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        print("Could not start ngrok. Check the installation in setup/SINGLE-FARMER-LINK.md.")
        return 1
    try:
        deadline = time.monotonic() + 45
        url = None
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                url = farmer_url(json.loads(fetch(AGENT_API)))
                if url:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not url:
            print("No HTTPS endpoint was created. Check the account token, network, and free-plan limits.")
            return 1
        # The edge can take a few seconds to become reachable after creation.
        for attempt in range(5):
            try:
                if b'id="btn-start"' not in fetch(url, public=True):
                    raise RuntimeError("Farmer page not returned")
                break
            except Exception:
                if attempt == 4:
                    print("The public farmer page could not be verified. Check the server and connection.")
                    return 1
                time.sleep(1)
        publish_link(url, ROOT / "var")
        code = proc.wait()
        print("Tunnel stopped. Run this launcher again to reconnect the same account domain.")
        return code
    except KeyboardInterrupt:
        print("\nClosing the farmer tunnel. The saved bookmark is reusable on the next start.")
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    sys.exit(main())
