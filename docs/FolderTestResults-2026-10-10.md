# Folder test results — 10 October 2026

The automated checks use isolated databases and service ports. Filing tests use the scripted sandbox browser, with `CREDIT_SAVER=1`; no paid provider or real insurer portal is involved.

## Repairs

- Removed hidden attributes from Python `.pth` files in the four local environments. Python 3.12.15 ignores hidden startup files, so MCP imports previously failed with `ModuleNotFoundError: pywintypes`.
- Added `setup/repair-python-paths.ps1` to the shared Windows startup helper so copied installations repair these attributes automatically.
- Changed both phone tunnel commands to `127.0.0.1`; the localhost SSH target returned HTTP 502 while the IPv4 target returned HTTP 200.
- Pruned bundled runtimes, browser profiles and tool caches before the secret scan descends into them. Application source, documents and logs remain covered. Regression checks verify vendor exclusions and detection of secrets in application logs without printing the secret.
- Changed smoke service URLs to `127.0.0.1` and made unavailable services contribute to the failure exit status. Added a test with all seven services unavailable.

## Verification

All 102 current automated tests have a passing result across the backend and browser environments, including the new smoke regression. Neither interpreter alone contains every dependency: the backend has NumPy/Jinja2 and the browser environment has Playwright. The individual run summaries below preserve failures and skips rather than claiming one clean combined run.

- Full browser-environment discovery: 101 tests in 510.892 s; 99 passed, 1 NumPy test skipped, 1 portal-form import error because Jinja2 is intentionally in the backend environment. The corresponding NumPy test passed in the backend discovery and portal-form tests passed in the targeted backend recheck. All six browser checks passed in this full run.
- Backend discovery: 101 tests in 443.830 s; 94 passed, 6 browser tests skipped, 1 seed test failed when Windows refused a temporary-file write. The seed test subsequently passed in two independent rechecks.
- Browser checks: farmer camera/upload, offline queue, buffered-tunnel polling, filing/review/retry, district dashboard and projector layout passed using `.venv-browser`. The first selection mistakenly named a nonexistent dashboard class; the corrected `T1_11_WebShell` selection passed all three checks.
- Targeted backend recheck: seed and portal form tests, 3/3 passed.
- Script regression checks: report, secret scanner and smoke failure status, 3/3 passed.
- Python compilation: passed for apps, shared code, MCP servers, scripts and tests.
- JavaScript syntax: `node --check` passed for every file in `apps/web/*.js`.
- Secret scan: passed; `.env` is ignored by Git.

Raw output is in `logs/folder-test-full.txt`, `logs/folder-final-tests.txt`, `logs/folder-regression-tests.txt`, `logs/folder-backend-recheck.txt`, `logs/folder-script-tests.txt` and `logs/folder-smoke.txt`.

## Live readiness and manual checks

Smoke is not fully green: cloudflared and the LiveKit CLI are absent, and the current Filer session has no open browser window. Its IPv4 health endpoint reports scripted and agent support available. The existing SSH tunnel provides the phone link without cloudflared. The `.env` demo values also differ from the measured defaults; the documented `setup/7-start-everything.cmd` sets those values for a demo.

No manual gate is marked passed. A person must still test Hindi microphone audio, the real phone camera/model and offline inference (T0-1, T0-4 and T2 phone checks), the spoken filing flow (T3-08/T3-09), the whole district demo with a phone (T4-12), and the Phase 5 hotspot, cold-start and rehearsal checks.
