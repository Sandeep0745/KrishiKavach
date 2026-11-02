# Final-folder comparison and GitHub update

Compared on 11 October 2026. Source: `KrishiKavach_Final/KrishiKavach_Final/KrishiKavach`. Destination: `KrishiKavach(GitHub)`.

## Comparison

Before editing, 71 source files differed, 97 existed only in the final folder, and 18 existed only in the GitHub folder. Text comparison normalized UTF-8 BOMs and line endings; `.env`, Git metadata, virtual environments, tools, caches, logs and runtime data were excluded. The [initial file inventory](folder-comparison-2026-10-11.json) lists the relative paths.

| Area | Applied update |
| --- | --- |
| Farmer and dashboard pages | English copy, layout and interaction changes |
| Voice | English fixed prompts, speech settings, answer parsing and local Piper fallback; replaced obsolete `hindi.py` with `words.py` |
| Decision service | English route/peril training and evaluation sets, English simulator replies and classifier settings |
| Data and pipeline | Updated 340 synthetic farmer records, registry response and claim details |
| Tests and planning | English fixtures, regression checks, demo script and design documentation |
| Project explanation | Copied `72-Ghante-Project-Explained.pdf` unchanged |

Preserved the GitHub checkout's local-runtime loading, Python 3.12 setup, startup prerequisites, stable ngrok domain configuration, ignored credentials/runtime directories, required-service smoke failures and secret-scanner pruning. Existing architecture, boundaries and historical result documents remain. Earlier Hindi measurements and spike experiments are historical; they are not evidence for the English build.

The final folder's `HTTP`, `run/go.cmd`, `run/tasks/` and `run/reports/` were omitted: they contain scratch output, one-off task runners, screenshots, logs and temporary tunnel links. Copying these would not improve the runnable application. The new ignore rules keep generated task/report folders out of later commits.

Also carried forward the previously repaired older project's filing recovery and reusable launchers. AI failure now reconnects to the form and uses scripted filing in automatic mode; confirmation is checked before fallback so a submitted claim is not duplicated. Repeated startup reuses a complete healthy demo only when its orchestrator identifies this checkout. An existing matching ngrok tunnel is verified and reused.

## Validation before commits

| Check | Result |
| --- | --- |
| Full core discovery | 109 tests, OK; six Playwright checks skipped in core environment; 418.612 seconds |
| Chrome web/farmer/dashboard checks | Nine tests, all passed; covers all six core browser skips; 172.629 seconds |
| Recovery, startup and tunnel checks | 21 tests, all passed; 27.165 seconds |
| Final startup source check | Seven tests, all passed; 9.973 seconds |
| End-to-end filing and form contracts after recovery merge | Seven tests, all passed; 31.680 seconds |
| Real isolated startup | Seven service health endpoints healthy, dashboard and farmer page HTTP 200; own checkout reused, another checkout rejected |
| English head, offline | ROUTE 29/30 (97%), median 32 ms / p95 37 ms; PERIL 12/12, median 33 ms / p95 35 ms |
| Local English speech | Voice agent import passed; Piper produced 2.1 seconds of speech using `en_US-lessac-medium` |
| Syntax and security | Python compilation, four web JavaScript syntax checks, JSON parsing, Git whitespace checks and secret scan passed |

One initial ownership regression failed because an empty owner resolved to the working directory. The code now requires a nonempty owner; the corrected suite and real-service tests passed before committing. Core discovery also printed SSL socket resource warnings at interpreter shutdown without test failures.

Test logs are local, ignored files: `logs/final-sync-core-tests.txt`, `logs/final-sync-browser-tests.txt`, `logs/final-sync-recovery-tests.txt`, `logs/final-sync-startup-tests.txt` and `logs/final-sync-pipeline-tests.txt`. Model measurements are in `logs/s1_eval_head.json`.

## Run this checkout

1. Stop any demo running from a different folder using Ctrl+C in that demo's terminal. Do not run two copies on the standard ports.
2. Run `setup/7-start-everything.cmd` here. Use `setup/7-start-everything.cmd scripted` to demonstrate filing without an AI provider.
3. Open the dashboard at `http://127.0.0.1:8000/` and farmer page at `http://127.0.0.1:8000/farmer`.
4. Run `setup/9-stable-farmer-link.cmd` for the account's persistent phone URL; the verified link is saved to `var/farmer-link.txt`. Keep the backend and tunnel running.
5. Run the readiness check with `.venv/Scripts/python.exe scripts/smoke.py` and complete the actual phone rehearsal before presenting.

Private keys remain in ignored `.env`. The local Piper setting was changed to `en_US-lessac-medium`, and that voice was downloaded into ignored `var/piper`. A fresh laptop needs its own environments and voice assets; see README setup instructions. Existing local environments still depend on the original project's Python runtime, as documented in [checkout validation](KRISHIKAVACH-RUNNABILITY.md).

The English Sarvam cache was checked with `--dry-run` only; it still needs English audio generation or English cache assets. Local English Piper is prepared as the fallback. No fresh live microphone, camera, public phone call or real-provider AI filing was exercised in this comparison task. Those checks remain a rehearsal step; the automated recovery tests simulate provider failures and use the sandbox portal.
