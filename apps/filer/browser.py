"""The one browser window the Filer drives. We start it ourselves with a debugging port, so that the browser agent
(browser-use) and the scripted fill (Playwright) can both work in the same visible window, one after the other."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import urllib.request

from ghante_shared import config

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
CDP_PORT = config.env_int("FILER_CDP_PORT", 9333)
HEADLESS = config.env("FILER_HEADLESS", "0") == "1"
PROFILE_DIR = pathlib.Path(config.env("FILER_PROFILE_DIR", str(config.VAR_DIR / "filer_profile")))


def screen_size() -> tuple[int, int] | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:  # noqa: BLE001
        return None


def window() -> tuple[int, int, int, int]:
    """(width, height, left, top). FILER_WINDOW=WIDTHxHEIGHT+LEFT+TOP places it by hand; otherwise it takes the right-hand 42 % of
    the screen, so it sits next to the dashboard on the projector."""
    explicit = config.env("FILER_WINDOW", "")
    if explicit:
        try:
            size, left, top = explicit.split("+")
            width, height = size.lower().split("x")
            return int(width), int(height), int(left), int(top)
        except ValueError:
            pass
    screen = screen_size()
    if screen:
        width = max(640, round(screen[0] * 0.42))
        return width, max(600, screen[1] - 48), max(0, screen[0] - width), 0
    return 900, 1000, 1000, 0


def find_browser() -> str | None:
    """Chrome if it is installed, otherwise Edge (part of Windows 11), otherwise a Chromium that Playwright downloaded."""
    explicit = config.env("FILER_BROWSER_PATH", "")
    if explicit:
        return explicit if pathlib.Path(explicit).exists() else None
    candidates: list[str] = []
    if sys.platform == "win32":
        roots = [os.environ.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        candidates += [str(pathlib.Path(r) / "Google" / "Chrome" / "Application" / "chrome.exe") for r in roots if r]
        candidates += [str(pathlib.Path(r) / "Microsoft" / "Edge" / "Application" / "msedge.exe") for r in roots if r]
    elif sys.platform == "darwin":
        candidates += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    else:
        candidates += [shutil.which(n) or "" for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")]
    downloaded = pathlib.Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "") or pathlib.Path.home() / ".cache" / "ms-playwright")
    if downloaded.exists():
        candidates += sorted(str(p) for p in downloaded.glob("chromium-*/chrome-*/chrome*") if p.is_file() and p.suffix in ("", ".exe"))
    return next((c for c in candidates if c and pathlib.Path(c).exists()), None)


def version(port: int | None = None) -> dict | None:
    """What the browser's debugging port says about itself, or None when no browser is listening."""
    try:
        with _opener.open(f"http://127.0.0.1:{port or CDP_PORT}/json/version", timeout=2) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


class BrowserProcess:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.path: str | None = find_browser()

    @property
    def http_url(self) -> str:
        return f"http://127.0.0.1:{CDP_PORT}"

    def ws_url(self) -> str | None:
        info = version()
        return info.get("webSocketDebuggerUrl") if info else None

    def ensure(self, start_url: str = "about:blank") -> str:
        """Start the window if it is not open. Returns the websocket address of its debugging port."""
        ws = self.ws_url()
        if ws:
            return ws
        if not self.path:
            raise RuntimeError("no Chrome, Edge or Chromium was found; install Google Chrome or set FILER_BROWSER_PATH")
        width, height, left, top = window()
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        args = [self.path, f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={PROFILE_DIR}", "--no-first-run", "--no-default-browser-check",
                "--disable-search-engine-choice-screen", "--disable-features=Translate,MediaRouter", "--hide-crash-restore-bubble",
                "--password-store=basic", f"--window-size={width},{height}", f"--window-position={left},{top}"]
        if HEADLESS:
            args.append("--headless=new")
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            args.append("--no-sandbox")  # a browser started as root (test containers) refuses to run otherwise
        args.append(start_url)
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 25
        while time.time() < deadline:
            ws = self.ws_url()
            if ws:
                return ws
            if self.proc.poll() is not None:
                raise RuntimeError(f"the browser closed as soon as it started (exit code {self.proc.returncode})")
            time.sleep(0.2)
        raise RuntimeError("the browser did not open its debugging port within 25 seconds")

    def close(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
