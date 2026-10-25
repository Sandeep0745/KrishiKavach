# Phase 5 results

Built and checked on 8 Oct 2026, morning. Run on the team laptop unless it says otherwise. Raw output: `run/reports/task-024-phase5.cmd.txt`, `task-025-phase5-round2.cmd.txt`, `task-026-camera.cmd.txt` and `task-028-gemini.cmd.txt`.

Phase 5 is mostly people's work (five runs with the phone, the hotspot, the video, the rehearsals). This page records what the machine could do and what it found. The steps for the people are in `HumanSetupChecklist.md`, "Checks that need a person for Gate G5".

## What exists now

| Item | State |
|---|---|
| 5.1 Five runs in a row | The machine part is built: `scripts/demo_check.py` plays the whole demo from reset, with the hero call as text against the real agent, models and LLM. The runs with the phone are for the team |
| 5.2 Fallback drills | D1, D2, D4, D6 and D7 are scripted (`scripts/drills.py`); D3, D5, D8 and D9 are for the team |
| 5.3 Backup video | For the team |
| 5.4 Hotspot and projector | Projector sizes checked by machine in the laptop's own Chrome (below). Hotspot run is for the team |
| 5.5 Pitch numbers | For the team, from `scripts/report.py` after the run with the phone. Today's figures are in the slide draft |
| 5.6 Slides | Draft of six slides made from the measured numbers (a Slides artifact) |
| 5.7 Root `README.md` | Written: what it is, how to run it each time and on a new laptop, the architecture picture, what is simulated, the checks |
| Also | Dashboard replay for a dashboard opened mid-demo; decision models warmed at start-up; `smoke.py` on-stage readiness; `secrets_check.py`; `setup\2c-install-packages.cmd` with package lists frozen from the laptop |

## Gate G5, test by test

| ID | Result |
|---|---|
| T5-01 Five in a row | Machine part: see "Demo rehearsals" below. With the phone: not run |
| T5-02 Hotspot | Not run |
| T5-03 Cold start | Not run. The root README now has the steps; `smoke.py` lists what must be OK |
| T5-04 Drills | See "Drills" below for D1, D2, D4, D6, D7. D3, D5, D8, D9 not run |
| T5-05 Backup video | Not made |
| T5-06 Timed rehearsal | Not run |
| T5-07 Report | Pass (automated): `report.py` reads a run's log; `demo_check.py` prints the report of its last run |
| T5-08 Honesty and language | Partly: `DemoScript.md` lines corrected where they did not match the screen (see below). A person must still read the slides and labels |
| T5-09 Secrets | **Pass on the laptop**: 225 files scanned, no value from `.env` anywhere else, no key-shaped text, `.env` git-ignored |
| T5-10 Zero spend | Not checked (needs each provider's billing page) |

## Demo rehearsals (`demo_check.py`, laptop, real models and LLM, hero call as text)

| Run | Hero | Ring to reference (text, no speech) | District | Hours left |
|---|---|---|---|---|
| A1 (first call after start-up) | **Ended early**: escalated after 4 farmer turns, 7 s | — | 311 filed, 6 escalated (the hero among them), 75 s | 67.92 |
| A2 | Filed by the browser agent, reference read out | 58.5 s | 312 / 11 / 9 / 5 / 3, 72 s | 68.05 |
| A3 | Same | 37.4 s | 312 / 11 / 9 / 5 / 3, 72 s | 68.05 |
| A4 | Same | 36.1 s | 312 / 11 / 9 / 5 / 3, 72 s | 68.04 |
| A5 | Stopped: the task window closed during the run | — | — | — |
| B1 (first call after start-up, with the warm-up) | Filed by the browser agent, reference read out | 82.3 s | 312 / 11 / 9 / 5 / 3, 77 s | 67.83 |
| B2 | Filed by the browser agent, reference read out | 39.0 s | 312 / 11 / 9 / 5 / 3, 74 s | 67.95 |
| B3 | Same | 45.4 s | 312 / 11 / 9 / 5 / 3, 72 s | 68.04 |

In every run nothing in the district moved during the live call, and the portal held one record per filed case. Round B: **3 of 3 passed** (`DEMO CHECK PASSED`).

`report.py` on run B3 (a text call, so these are thinking times, not speech): fast path median 25 ms (3 turns); language-model path median 803 ms, slowest 1.2 s (5 turns); ROUTE median 19 ms and PERIL 14 ms on the head; TRIAGE 89 computed at median 162 ms and 251 repeats from cache; VERIFY 3 computed at median 221 ms and 309 repeats; the browser agent filed in 38 s with 26 form actions; no fallbacks. The "photo checked in 41 ms" line in that report is the value the rehearsal script sends with its stand-in photo, not a measurement.

**The first call after start-up.** Run A1 ended in 7 seconds with the hero handed to a person, while A2 to A4 passed with the same script. The run had no record of the turns (the check now prints them), so the cause is not proven. The likely one: each decision model's first answer after loading is much slower than the next; the head has 500 ms per ROUTE decision before the LLM is asked instead, and the LLM also judges distress, which ends a call with a hand-over. On stage the first call after start-up is the one that matters, so the decision service now answers one made-up ROUTE, PERIL and TRIAGE question as soon as it has loaded, and `smoke.py` and `demo_check.py` wait for that. B1, the first call after a fresh start with the warm-up, passed. If a first call ever ends early again, `demo_check.py` prints each turn with the path, the rule and the decision that ended it.

## Dashboard in the laptop's Chrome

The dashboard tests had always been skipped on the laptop (no Playwright in `.venv`). They now run from `.venv-browser`, which has Playwright, with the installed Chrome 155:

| Test | Result |
|---|---|
| A dashboard opened mid-demo shows the live call, the ticker, the tool calls and the fallback notice once, with the run's true counts, and fits 1920 × 1080 and 1366 × 768 with nothing clipped or scrolling (also after a reload) | Pass |
| T1-11 pages, sample replay | Pass |
| T3 filing progress, reviewer approval, filing again | Pass |
| T4-08 the district run on the dashboard, 1600 × 900 | Pass |
| T2 phone page: ring, answer, photo, upload, hang-up | Pass up to the second time the camera is opened; see below |

Screenshots of the projector sizes: `run/reports/task-024-shots/`.

**The camera opened a second time.** In the laptop's Chrome 155 (no window, fake camera) the first camera of the session started, and every later one (retake, cancel and open again, open while offline) did not: the page fell back to the gallery picker. In Playwright's own Chromium all five openings work. The page now logs why the camera did not start, and the cause is Chrome's fake test camera, not the page: after the first camera of the session is released, Chrome 155 reports **no camera at all** (`NotFoundError: Requested device not found`; a direct request outside the app sees 0 cameras), with or without a window. Its first picture was also only 2 pixels wide. A real phone's camera does not disappear, but this means the retake has **not been checked in a real browser with a real camera**: do it once on the phone (DemoScript step 8 relies on it). The page now also asks for the camera three times with simpler settings before falling back to the gallery, which helps phones whose camera refuses to restart for a moment.

## Drills (`drills.py`, laptop, real models and keys)

| Drill | Result |
|---|---|
| D1 first decision provider broken | **Pass**: the head answered, the ticker row is marked and the dashboard got one fallback notice |
| D2 browser agent given 5 s | **Pass**: the scripted fill finished the form in 12 s and the switch was announced ("the agent took longer than 5 seconds") |
| D4 first LLM's key wrong | **Fail at first, pass after the fix (below)**: both Groq models refused the wrong key (401) as intended, and the next one, Gemini `gemini-3.8-flash`, answered 429 (quota). No LLM answered, so on a live call the agent would ask the farmer to repeat and hand over after three tries. See below |
| D6 Filer killed while filing | **Pass**: the case went to FAILED with a reason, the orchestrator stayed up, and filing again after restarting the Filer filed it (scripted) |
| D7 orchestrator killed | **Pass**: back in 1.2 s with its cases; reset works afterwards |

9 of 10 checks on the first run. **D4 then showed that the conversation had no working second LLM**: `gemini-3.8-flash` has no free quota on this key. `scripts/spikes/gemini_probe.py` asked every Flash and Gemma model the key can see the call's extraction question (8 Oct, 17:19): `gemini-flash-lite-latest` (1.1 s), `gemini-3.1-flash-lite` (1.3 s), `gemini-3.1-flash-lite-preview` (1.3 s), `gemini-3.5-flash-lite` (1.8 s) and `gemini-3-flash-preview` (5.1 s) answered correctly; `gemini-2.5-flash` and `-lite` are closed to new users (404), `gemini-3.5-flash`, `gemini-flash-latest` and `gemma-4-31b-it` timed out, `gemma-4-26b-a4b-it` gave 500, `gemini-omni-flash-preview` 429. **D4 repeated with `gemini-flash-lite-latest` as the backup: pass**, answered in 1.9 s after both Groq models refused the wrong key. The built-in backups (`apps/voice/extract.py`) are now Groq `gpt-oss-120b`, then `gemini-3.1-flash-lite`, then `gemini-flash-lite-latest`, and `.env.example` names `gemini-3.1-flash-lite`. The browser agent's second model is unchanged (`gemini-3.8-flash`, untested as a browser agent); its real fallback is the scripted fill, which D2 and D6 exercise.

## Other findings and fixes

- **Secrets check, first run:** 56 matches in two old task reports, all exception names with a key's shape (`APIConnectionError` 48 times, `APIConnectOptions`, `APIStatusError`, `APITimeoutError`). No key value was found. The check now ignores capitalised words; the second run passed.
- **A test written before the replay** (T1-09) expected the next event straight after the snapshot; it now expects the replay and the `tallies` event first. All tests in `.venv`: 100 run, that one failure, 5 skipped (the browser tests, which now run from `.venv-browser`).
- **`demo_check.py` printed the room token** of each rehearsal call into its report. It now prints only the room name. The token expires; no key was printed.
- **Package lists for a new laptop:** `.venv` 85 packages, `.venv-voice` 95, `.venv-browser` 109, frozen from the laptop; installing each list into its own environment would change nothing (dry run). Not yet tried on a second machine.
- **Demo script** lines that did not match the screen: the readiness check, the Filer window, the TRIAGE timing line (now "each distinct situation in about 180 milliseconds; farms in the same situation share the answer"), the pause message, the evidence card, the filed line, the simulated label.

## Decisions for the team

- **Which voice reads the details back and the reference number.** With `CREDIT_SAVER=1` (the laptop's setting) the fixed lines are Sarvam from the audio cache and the per-call sentences are the local Piper voice, so the voice changes at the moment the reference is read. With `CREDIT_SAVER=0` Sarvam speaks those too, a few hundred characters of free credit per call. Pick one before the five runs and keep it.
- The slide numbers are today's; replace them with `report.py` output after the run with the phone.

## Not verified

- Everything with the phone, the room, the hotspot and a person's voice (T5-01 to T5-06 as written).
- The camera opened twice on a real phone (the retake in DemoScript step 8).
- `setup\2c-install-packages.cmd` on a second machine.
- The LLM fallback during a spoken call (drill D4 checks the extraction alone).
- Your laptop's own `.env`: if its `LLM_CHAIN` still names `gemini:gemini-3.8-flash`, each fallback first wastes one refused request (about half a second) before the working backups; changing it to `gemini:gemini-3.1-flash-lite` saves that.
