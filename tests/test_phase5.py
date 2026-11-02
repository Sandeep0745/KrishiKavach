"""Gate G5 automated parts (context/Testing.md §7). Run:  python -m unittest tests.test_phase5 -v

Most of G5 is a person's job (five runs with the phone, the hotspot, the video, the rehearsals). What a machine can check is
here: a dashboard opened or reloaded mid-demo shows what happened so far; it fits the projector sizes; no key leaks; the
report reads a run. The whole demo order is rehearsed by scripts/demo_check.py and the fallbacks by scripts/drills.py.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

from tests import _util as u

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIT = """() => {
  const clipped = [];
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || el.closest('[hidden]') || el.children.length) continue;
    if (el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 1 && ['hidden', 'clip'].includes(cs.overflowX)) clipped.push(el.id || el.className || el.tagName);
  }
  return {sw: document.documentElement.scrollWidth, iw: innerWidth, sh: document.documentElement.scrollHeight, ih: innerHeight, clipped};
}"""


class T5_Dashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = u.Services("orchestrator", "portal", "weather", "registry", "mandi", "s1", S1_CHAIN_TEXT="mock", S1_CHAIN_REPORT="mock", HERO_SIM="0",
                           S1_SIM_CACHE="1", MAX_PARALLEL_CALLS="8", LIVEKIT_URL="wss://example.invalid", LIVEKIT_API_KEY="k", LIVEKIT_API_SECRET="s" * 40,
                           RING_TIMEOUT_S="120")
        cls.addClassCleanup(cls.s.close)

    def api(self, method: str, path: str, payload: dict | None = None):
        return u.call(method, u.url("orchestrator", path), payload, timeout=30)

    def test_a_dashboard_opened_mid_demo_shows_the_run_so_far_and_fits_the_projector(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("Playwright is not installed here; open the dashboard mid-run by hand instead")
        self.assertEqual(self.api("POST", "/api/scenario/reset", {})[0], 200)
        self.api("POST", "/api/scenario/start", {"speed": 180})
        time.sleep(8)
        ring = self.api("POST", "/api/hero/call")[1]
        self.api("POST", f"/api/calls/{ring['call_id']}/accept")
        turns = [("agent", "Hello, am I speaking with Ramlal ji?", "scripted"), ("farmer", "Yes, speaking.", "fast"),
                 ("agent", "Was your wheat crop damaged?", "fast")]
        for speaker, text, path in turns:
            self.api("POST", "/internal/events", {"type": "call.turn", "case_id": ring["case_id"], "agent": "intake", "live": True,
                                                  "data": {"speaker": speaker, "text": text, "path": path, "latency_ms": {"total": 400}}})
        self.api("POST", "/internal/events", {"type": "fallback.used", "agent": "system", "data": {"component": "s1", "from": "laya", "to": "llm", "reason": "drill"}})
        time.sleep(0.5)
        with sync_playwright() as p:
            try:
                browser = u.launch_chromium(p)
            except Exception as e:
                self.skipTest(f"no browser for Playwright: {type(e).__name__}")
            errors: list[str] = []
            for width, height in ((1920, 1080), (1366, 768)):
                page = browser.new_page(viewport={"width": width, "height": height})
                page.on("pageerror", lambda e: errors.append(str(e)))
                for visit in (1, 2):  # open, then reload: the second must not show anything twice
                    page.goto(u.url("orchestrator", "/")) if visit == 1 else page.reload()
                    page.wait_for_function("document.getElementById('conn').textContent === 'connected'", timeout=10000)
                    page.wait_for_function("document.querySelectorAll('#transcript .turn').length === 3", timeout=10000)
                    time.sleep(0.5)
                    st = self.api("GET", "/api/state")[1]
                    self.assertEqual(page.locator("#transcript .turn").count(), 3, "the live call so far, once")
                    self.assertFalse(page.locator("#hero").is_hidden())
                    self.assertGreaterEqual(page.locator("#ticker li").count(), 20)
                    self.assertLessEqual(page.locator("#ticker li").count(), 40)
                    self.assertGreaterEqual(page.locator("#mcp li").count(), 10)
                    made = int(page.inner_text("#s1-count").split(" made")[0].replace(",", ""))
                    self.assertGreaterEqual(made, 340, "the count is the run's total, not the rows replayed")
                    self.assertEqual(page.locator("#notices li").count(), 1, "the fallback notice, once")
                    self.assertEqual(page.inner_text("#runstate"), "Simulated farmers paused for the live call. Press P to resume.")
                    self.assertEqual(st["scenario"]["paused_by"], "live call")
                    fit = page.evaluate(FIT)
                    if visit == 2 and os.environ.get("GHANTE_SHOT_DIR"):  # a picture of each projector size, to look at
                        page.screenshot(path=str(pathlib.Path(os.environ["GHANTE_SHOT_DIR"]) / f"dashboard-{width}x{height}.png"))
                    self.assertEqual((fit["sw"], fit["sh"]), (fit["iw"], fit["ih"]), f"no scrolling at {width}x{height}")
                    self.assertEqual(fit["clipped"], [], f"no clipped text at {width}x{height}")
                    agents_lit = page.locator("#agents li.on").count()
                    self.assertEqual(agents_lit, 0, "a reload does not light every agent at once")
                page.close()
            self.assertEqual(errors, [])
            browser.close()
        health = self.api("GET", "/health")[1]
        self.assertEqual((health["scenario"], health["hero_phones"]), ("paused", 0))


class T5_Scripts(unittest.TestCase):
    def test_smoke_fails_when_required_services_are_down(self):
        import contextlib
        import io
        from unittest.mock import Mock, patch
        from scripts import smoke

        opener = Mock()
        opener.open.side_effect = OSError("service unavailable")
        env = {key: "configured" for key, _, _ in smoke.KEYS}
        output = io.StringIO()
        with (tempfile.TemporaryDirectory() as config_dir,
                patch.object(smoke, "ROOT", pathlib.Path(config_dir)),
                patch.object(smoke, "tool_version", return_value="20.0"), \
                patch.object(smoke, "read_env", return_value=env), \
                patch.object(smoke, "demo_readiness", return_value=0), \
                patch.object(smoke.urllib.request, "build_opener", return_value=opener), \
                contextlib.redirect_stdout(output)):
            (pathlib.Path(config_dir) / ".env").write_text("", encoding="utf-8")
            self.assertEqual(smoke.main(), 1)
        self.assertIn("7 item(s) need attention", output.getvalue())
        self.assertEqual(opener.open.call_count, 7)

    def test_T5_09_secrets_check_finds_a_planted_key_and_never_prints_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            planted = "gsk_" + "Ab3" * 12
            (pathlib.Path(tmp) / "notes.md").write_text(f"oops: {planted}\n", encoding="utf-8")
            (pathlib.Path(tmp) / "clean.py").write_text("print('fine')  # openai.APIConnectionError in a log is a name, not a key\n", encoding="utf-8")
            out = subprocess.run([sys.executable, str(ROOT / "scripts" / "secrets_check.py"), tmp], capture_output=True, text=True, cwd=ROOT)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("notes.md:1: something shaped like a Groq key", out.stdout)
            self.assertNotIn(planted, out.stdout + out.stderr)
            (pathlib.Path(tmp) / "notes.md").unlink()
            # Copied vendor caches can contain provider-owned keys in fixtures.
            for folder in (".runtime", ".setup-tools", ".venv"):
                vendor = pathlib.Path(tmp) / folder
                vendor.mkdir()
                (vendor / "fixture.txt").write_text(planted, encoding="utf-8")
            out = subprocess.run([sys.executable, str(ROOT / "scripts" / "secrets_check.py"), tmp], capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("PASS  no key outside .env", out.stdout)
            logs = pathlib.Path(tmp) / "logs"
            logs.mkdir()
            (logs / "app.log").write_text(planted, encoding="utf-8")
            out = subprocess.run([sys.executable, str(ROOT / "scripts" / "secrets_check.py"), tmp], capture_output=True, text=True, cwd=ROOT)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("app.log:1: something shaped like a Groq key", out.stdout)
            self.assertNotIn(planted, out.stdout + out.stderr)

    def test_T5_07_report_reads_a_run(self):
        events = [{"id": "evt_1", "type": "snapshot", "live": False, "data": {}},
                  {"id": "evt_2", "type": "call.turn", "live": True, "data": {"speaker": "agent", "path": "fast", "latency_ms": {"total": 610}}},
                  {"id": "evt_3", "type": "call.turn", "live": True, "data": {"speaker": "agent", "path": "llm", "latency_ms": {"total": 1210}}},
                  {"id": "evt_4", "type": "s1.decision", "live": True, "data": {"decision": "ROUTE", "provider": "head", "latency_ms": 24, "cached": False}},
                  {"id": "evt_5", "type": "claim.filed", "live": True, "data": {"claim_ref": "FCS-000312", "filing_mode": "agent", "seconds": 32.0, "time_to_file_s": 151.0}},
                  {"id": "evt_6", "type": "scenario.finished", "live": False, "data": {"totals": {"filed": 312}, "affected": 340, "hours_left": 68.03,
                                                                                     "sim_ts": "2026-03-12T19:28:00+05:30", "running_seconds": 73.0}}]
        with tempfile.TemporaryDirectory() as tmp:
            log = pathlib.Path(tmp) / "events.jsonl"
            log.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
            out = subprocess.run([sys.executable, str(ROOT / "scripts" / "report.py"), str(log)], capture_output=True, text=True, cwd=ROOT,
                                 env={**__import__("os").environ, "GHANTE_LOG_DIR": tmp})
        self.assertEqual(out.returncode, 0, out.stderr)
        for part in ("fast path              n 1, median 610 ms", "FCS-000312 filed by the browser agent, 32 s to file; ring to reference 2 min 31 s",
                     "closing line: 312 of 340 claims filed, 68 hours left", "ROUTE   head      1 decisions"):
            self.assertIn(part, out.stdout)


if __name__ == "__main__":
    unittest.main()
