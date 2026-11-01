r"""Does the farmer page's camera open a second and third time (retake, cancel and open again, and with the network off)?

    .venv-browser\Scripts\python.exe scripts\spikes\camera_reopen.py           # installed Chrome, fake camera
    python scripts/spikes/camera_reopen.py --channel chromium                    # Playwright's Chromium

Found in Phase 5: the phone-page test passed on the laptop's Chrome up to the point where the camera was opened again with the
network switched off. This shows which step fails and what the page reports. Starts its own orchestrator on spare ports.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
for candidate in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
    if candidate.exists():
        os.environ.setdefault("GHANTE_SERVICE_PYTHON", str(candidate))
        break

from tests import _util as u  # noqa: E402
from tests.test_phase2 import FAKE_LABELS, FAKE_LIVEKIT, FAKE_TRANSFORMERS  # noqa: E402

SCREEN = "(() => { const s = [...document.querySelectorAll('section[id^=screen-]')].find(e => !e.hidden); return s ? s.id : 'none'; })()"


def main() -> int:
    import json

    from playwright.sync_api import sync_playwright

    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="chrome", help="chrome, msedge or chromium")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    s = u.Services("orchestrator", LIVEKIT_URL="wss://example.invalid", LIVEKIT_API_KEY="k", LIVEKIT_API_SECRET="s" * 40)
    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel=args.channel, headless=not args.headed,
                                        args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
            print(f"browser: {args.channel} {browser.version}", flush=True)
            context = browser.new_context(viewport={"width": 390, "height": 800}, service_workers="block", permissions=["geolocation", "camera", "microphone"],
                                          geolocation={"latitude": 23.0191, "longitude": 76.7212})
            context.route("https://cdn.jsdelivr.net/npm/livekit-client**", lambda r: r.fulfill(content_type="text/javascript", body=FAKE_LIVEKIT))
            context.route("https://cdn.jsdelivr.net/npm/@huggingface/transformers**", lambda r: r.fulfill(
                content_type="text/javascript", body=FAKE_TRANSFORMERS, headers={"Access-Control-Allow-Origin": "*"}))
            context.route("**/static/label_embeddings.json", lambda r: r.fulfill(content_type="application/json", body=json.dumps(FAKE_LABELS)))
            page = context.new_page()
            log: list[str] = []
            page.on("console", lambda m: log.append(f"console.{m.type}: {m.text[:160]}"))
            page.on("pageerror", lambda e: log.append(f"pageerror: {str(e)[:160]}"))
            page.on("filechooser", lambda fc: log.append("file picker opened (the page's fallback when the camera cannot start)"))
            page.goto(u.url("orchestrator", "/farmer?farmer=F0001"))
            page.wait_for_function("document.getElementById('model').textContent === 'फोटो जाँच तैयार'", timeout=15000)
            page.click("#btn-start")
            page.wait_for_selector("#screen-idle:not([hidden])")

            def camera(name: str, button: str) -> bool:
                mark = len(log)
                t0 = time.time()
                page.click(button)
                try:
                    page.wait_for_function("document.getElementById('video').videoWidth > 0", timeout=10000)
                    ok = True
                except Exception:  # noqa: BLE001
                    ok = False
                info = page.evaluate("(() => { const v = document.getElementById('video'); return {w: v.videoWidth, ready: v.readyState, paused: v.paused,"
                                     " src: !!v.srcObject, online: navigator.onLine}; })()")
                screen = page.evaluate(SCREEN)
                results.append((name, ok))
                print(f"{'PASS' if ok else 'FAIL'}  {name}: {time.time() - t0:.1f} s, screen {screen}, video {info}", flush=True)
                for line in log[mark:]:
                    print(f"      {line}", flush=True)
                if not ok:  # ask the browser directly, outside the app, what it says now
                    probe = page.evaluate("""async () => {
                        const devices = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'videoinput').length;
                        try { const s = await navigator.mediaDevices.getUserMedia({video: true}); const w = s.getVideoTracks()[0].getSettings().width;
                              s.getTracks().forEach(t => t.stop()); return `cameras ${devices}; a plain request works now (width ${w})`; }
                        catch (e) { return `cameras ${devices}; a plain request fails too: ${e.name}: ${e.message}`; } }""")
                    print(f"      probe: {probe}", flush=True)
                return ok

            if camera("1 first open (online)", "#btn-photo-idle"):
                page.click("#btn-shutter")
                page.wait_for_selector("#screen-photo:not([hidden])", timeout=5000)
                camera("2 retake (online)", "#btn-retake")
            page.click("#btn-camera-cancel") if page.evaluate(SCREEN) == "screen-camera" else None
            page.wait_for_selector("#screen-idle:not([hidden])", timeout=5000)
            camera("3 cancel, then open again (online)", "#btn-photo-idle")
            page.click("#btn-camera-cancel") if page.evaluate(SCREEN) == "screen-camera" else None
            page.wait_for_selector("#screen-idle:not([hidden])", timeout=5000)
            context.set_offline(True)
            time.sleep(0.5)
            camera("4 open with the network off", "#btn-photo-idle")
            page.click("#btn-camera-cancel") if page.evaluate(SCREEN) == "screen-camera" else None
            context.set_offline(False)
            time.sleep(0.5)
            page.wait_for_selector("#screen-idle:not([hidden])", timeout=5000)
            camera("5 open again with the network back", "#btn-photo-idle")
            browser.close()
    finally:
        s.close()
    failed = [n for n, ok in results if not ok]
    print(f"\nCAMERA REOPEN {'PASSED' if not failed else 'FAILED'}: {len(results) - len(failed)} of {len(results)}" + (f"; failed: {failed}" if failed else ""))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
