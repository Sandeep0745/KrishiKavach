# KrishiKavach checkout: setup and validation

Validated on 10 October 2026.

## Repairs

- Restored 18 omitted startup, tunnel, reporting and verification scripts from the original project, including dev.py, smoke.py and farmer_link.py.
- Fixed Python selection for fresh installs: uv resolves Python 3.12 when the standard installation and project environment are unavailable.
- Made the smoke regression test independent of a private .env file.
- Added a startup guard for missing environments, missing configuration and occupied service ports. It runs before the launcher schedules any demo reset.

## Local runtime prepared

Installed .venv, .venv-voice and .venv-browser from setup/locks. Reused the original project's local .env, cached TTS/Piper assets, model cache, uv and ngrok. Credentials and runtime assets remain ignored by Git.

These environments currently use Python 3.12 from the original project's .runtime/python directory. Keep that interpreter available. On a different laptop, follow README.md first-time setup and recreate the environments instead of copying them.

## Run this checkout

1. Stop the original demo with Ctrl+C in its service terminal. Standard ports are 8000, 8090, 8101-8103, 8200 and 8300. The startup guard lists any occupied ports.
2. Run setup/7-start-everything.cmd from this checkout. Pass scripted to use scripted filing.
3. Open http://127.0.0.1:8000/ for the dashboard and http://127.0.0.1:8000/farmer for the local farmer page.
4. Keep one ngrok tunnel for the account's assigned domain. An existing tunnel forwarding port 8000 can continue after switching apps. If stopped, run setup/9-stable-farmer-link.cmd; it saves the verified phone URL in var/farmer-link.txt.
5. Connect the phone and run the readiness check before presenting.

## Verification results

- Full core discovery ran 107 tests. Its summary reported one fleet timing failure, one decision-service class startup error and six skipped browser checks. The initial full run was not a clean pass.
- Both decision-service tests passed on an isolated rerun in 8.85 seconds.
- The fleet determinism test passed on an isolated rerun in 111.19 seconds, including two complete district runs. The earlier scenario-finish timeout reported 1825.9 seconds of running time; the cause of that elapsed-time jump was not established. No timeout was relaxed.
- Browser checks passed for dashboard reload/projector layout and the district dashboard. Seven additional web-shell, farmer-page and filing-dashboard tests passed in 73.80 seconds, covering the checks skipped in the core environment. An initial command used an incorrect class name; the corrected class passed.
- All test coverage has passing results across the appropriate environments and targeted reruns; this does not erase the initial failures.
- Seven services started from this checkout on isolated ports with temporary databases. Every /health returned HTTP 200, as did / and /farmer. Those test services were stopped afterward.
- Real head ROUTE and Laya TRIAGE inference passed using the copied cache with HF_HUB_OFFLINE=1. Voice agent and filer imports passed.
- Python compilation across application code, shared code, MCP servers, scripts and tests passed.
- Secrets scan passed: no configured key outside .env. Environments, credentials, tools and runtime assets are ignored.
- The startup guard rejected occupied standard ports without sending a reset.
- smoke.py inspected the original demo still running on standard ports and reported seven readiness issues. Those included a disconnected phone, an unreset scenario, filer readiness and tools absent from the shell PATH. That result does not establish on-stage readiness for this checkout.

## Manual checks remaining

T1-12/T2 spoken phone checks and T4-12: microphone, Hindi conversation, camera permissions, photo classification and complete live filing on the actual phone. T5 rehearsals and hotspot checks remain manual. Only the sandbox portal is used.

## 11 October update

The final English build and runtime recovery fixes are now merged. See [current comparison and validation](FINAL-FOLDER-SYNC.md) for passing full-suite results and remaining phone rehearsal steps. Repeated launches reuse a healthy demo from this checkout without resetting it; another checkout must be stopped first. The current live conversation is in English. The 10 October results above remain historical.
