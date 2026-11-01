"""Phase 0 spike T0-3: can a browser agent on a free-tier LLM fill and submit a small form?

Starts a local test form on http://127.0.0.1:8765, lets the agent fill it, and checks what the server received.
Prints no keys. Target site is local only.
"""
from __future__ import annotations
import asyncio, http.server, json, os, pathlib, sys, threading, time, traceback, urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[2]
PORT = 8765
EXPECTED = {"farmer_name": "Ramlal Verma", "mobile": "0000000451", "crop": "Wheat", "loss_date": "2026-03-12", "damage_pct": "70"}
RECEIVED: list[dict] = []

FORM = """<!doctype html><html><head><meta charset="utf-8"><title>Test form (spike)</title></head><body>
<p><b>Demo sandbox test form - not a real service.</b></p>
<h1>Report crop loss (test)</h1>
<form method="post" action="/submit">
<p><label for="farmer_name">Farmer name</label><br><input id="farmer_name" name="farmer_name" type="text" required></p>
<p><label for="mobile">Mobile number</label><br><input id="mobile" name="mobile" type="tel" required></p>
<p><label for="crop">Crop</label><br><select id="crop" name="crop" required><option value="">Select</option><option>Wheat</option><option>Gram</option><option>Soybean</option></select></p>
<p><label for="loss_date">Date of loss</label><br><input id="loss_date" name="loss_date" type="date" required></p>
<p><label for="damage_pct">Damage percent</label><br><input id="damage_pct" name="damage_pct" type="number" min="0" max="100" required></p>
<p><button id="submit" type="submit">Submit</button></p></form></body></html>"""

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, body, code=200):
        data = body.encode("utf-8"); self.send_response(code); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        if self.path.startswith("/health"): return self._send("ok")
        self._send(FORM)
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
        fields = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
        RECEIVED.append(fields)
        self._send(f"<!doctype html><html><body><h1>Report received</h1><p>Reference number: <span id='reference'>REF-{1000 + len(RECEIVED)}</span></p></body></html>")

def read_env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("="); env[k.strip()] = v.strip()
    return env

TASK = (f"Open http://127.0.0.1:{PORT}/ . Fill the form with exactly these values: "
        f"Farmer name = {EXPECTED['farmer_name']}; Mobile number = {EXPECTED['mobile']}; Crop = {EXPECTED['crop']}; "
        f"Date of loss = 12 March 2026 (the field value must be {EXPECTED['loss_date']}); Damage percent = {EXPECTED['damage_pct']}. "
        "Then click Submit. On the next page read the reference number and return only that reference number. "
        "Do not open any other website.")

async def one_run(make_llm, label, n):
    from browser_use import Agent, Browser
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    kwargs = {"headless": True}
    if os.path.exists(chrome): kwargs["executable_path"] = chrome
    browser = Browser(**kwargs)
    before = len(RECEIVED); t0 = time.perf_counter(); steps = "?"; final = None; err = None
    try:
        agent = Agent(task=TASK, llm=make_llm(), browser=browser, use_vision=False, max_actions_per_step=10, flash_mode=True, max_failures=3)
        history = await asyncio.wait_for(agent.run(max_steps=15), timeout=170)
        for name in ("number_of_steps",):
            try: steps = getattr(history, name)()
            except Exception: pass
        try: final = history.final_result()
        except Exception: final = None
        try:
            errs = [e for e in history.errors() if e]
            if errs: err = str(errs[-1])[:300]
        except Exception: pass
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:400]}"
    finally:
        for closer in ("kill", "stop", "close"):
            fn = getattr(browser, closer, None)
            if fn:
                try:
                    r = fn()
                    if asyncio.iscoroutine(r): await asyncio.wait_for(r, 20)
                    break
                except Exception: pass
    secs = time.perf_counter() - t0
    got = RECEIVED[before] if len(RECEIVED) > before else None
    correct = got is not None and all(got.get(k) == v for k, v in EXPECTED.items())
    print(f"RUN {label} #{n}: submitted={'yes' if got else 'no'} correct={correct} steps={steps} seconds={secs:.0f} final={str(final)[:80]!r}")
    if got and not correct: print("    server received:", json.dumps(got, ensure_ascii=False))
    if err: print("    error:", err)
    return correct, err

async def main():
    env = read_env()
    if env.get("GEMINI_API_KEY"): os.environ["GOOGLE_API_KEY"] = env["GEMINI_API_KEY"]
    if env.get("GROQ_API_KEY"): os.environ["GROQ_API_KEY"] = env["GROQ_API_KEY"]
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
    import browser_use
    print("browser_use", getattr(browser_use, "__version__", "?"))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    from browser_use import ChatGoogle
    candidates = [("gemini-3.8-flash-lite", lambda: ChatGoogle(model="gemini-3.8-flash-lite")),
                  ("gemini-3.8-flash", lambda: ChatGoogle(model="gemini-3.8-flash")),
                  ("gemini-2.5-flash", lambda: ChatGoogle(model="gemini-2.5-flash"))]
    try:
        from browser_use import ChatGroq
        candidates.append(("groq gpt-oss-120b", lambda: ChatGroq(model="openai/gpt-oss-120b")))
    except Exception: pass
    done_models = 0
    for label, make in candidates:
        ok, err = await one_run(make, label, 1)
        if not ok and err and any(s in err.lower() for s in ("not found", "404", "permission", "api key", "unsupported", "invalid")) and "429" not in err:
            continue  # model not usable with this key: try the next one
        results = [ok]
        for n in (2, 3):
            await asyncio.sleep(8)  # stay under free per-minute limits
            results.append((await one_run(make, label, n))[0])
        print(f"SUMMARY {label}: {sum(results)}/3 correct")
        done_models += 1
        if sum(results) >= 2 or done_models >= 2: break
    srv.shutdown()
    print("C DONE")

if __name__ == "__main__":
    try: asyncio.run(main())
    except Exception: traceback.print_exc(file=sys.stdout); print("C FAILED")
