# Phase 4 results

Built and measured on 7 Oct 2026 (night). Run on the team laptop unless it says otherwise. Raw output: `run/reports/task-019-phase4.cmd.txt`.

## What exists now

| Item | State |
|---|---|
| 4.1 Sentinel | Built: asks the weather MCP server for storms, emits `storm.detected` |
| 4.2 Dispatcher | Built: opens 340 cases through the registry MCP server, ranks them with TRIAGE village by village, priority queue, parallel calls with a limit, three attempts, calling hours |
| 4.3 Simulator | Built: scenario clock, personas, simulated call outcomes, the real pipeline with filing through the portal API |
| 4.4 Pause on the hero call | Built: the run pauses when the hero is rung and the presenter resumes it with P. The live farmer is ranked but never called by the Dispatcher |
| 4.5 Dashboard | Built: every farm on the map before the storm, dots by status, countdown, counters, run status line, closing banner, simulated and live labels |
| 4.6 Presenter controls | Built: S, H, P, L, R, plus A and F for the live case. Reset in the browser test took under 10 s |
| 4.7 Tuning | Done: `SIM_SPEED=180`, `MAX_PARALLEL_CALLS=8` |
| 4.8 `scripts/report.py` | Built |

## Gate G4, test by test

| ID | Result |
|---|---|
| T4-01 Detection | Pass (automated): one `storm.detected` with 12 villages, 340 cases, each deadline 15 March 15:30 |
| T4-02 Triage | Pass (automated): 340 TRIAGE decisions, queue in priority order, severe villages rank above moderate above light |
| T4-03 Concurrency and retries | Pass (automated): never more than 8 calls at once; every `no_answer` persona ends `UNREACHABLE` after exactly 3 attempts |
| T4-04 Final totals | **Pass on the laptop with the real models, twice: 312 / 11 / 9 / 5 / 3** |
| T4-05 Real records | Pass: 312 records in the sandbox portal, every reference resolves |
| T4-06 Determinism | Pass (automated): two runs give the same first 20 of the queue and the same final status and attempt count for every case |
| T4-07 Pause and resume | Pass for the P control (automated: no case, call, filing or decision while paused). Pause by the hero call is tested without a phone answering. With a real hero call: not run |
| T4-08 Dashboard truth | Pass in the headless browser test (counters equal `GET /api/state`); not yet looked at by a person on the laptop |
| T4-09 Labels | In the browser test; not yet by eye |
| T4-10 Timing | **Pass on the laptop, twice: 74 s and 73 s** (target 60 to 90), finishing at 19:31 and 19:28 scenario time, 67.97 and 68.03 hours left: the banner reads "312 of 340 claims filed. 68 hours left. 16 need follow-up." |
| T4-11 Reset | Pass in the browser test (clean state in under 10 s); a second run behaves like the first |
| T4-12 Full demo script | **Not run.** Needs the phone and a person |
| T4-13 Projector check | Not run. The browser test checks 1600 × 900 only |

**The gate is not passed yet**: T4-12 needs the team, and T4-07 to T4-09 and T4-13 should be looked at once on the laptop.

## Measurements (laptop, real models, scripted hero)

| What | Measured |
|---|---|
| Fleet running time | 74 s and 73 s |
| All 340 cases ranked after | 18 s (calls start after the first village, about 2 s in) |
| TRIAGE (Laya) | 340 decisions: 88 computed, median 176 ms, 95th percentile 265 ms; 252 repeats from cache |
| VERIFY (Laya) | 312 decisions: 2 computed (364 ms and 523 ms, while ranking was using the model); 310 repeats from cache |
| MCP tool calls | 643: `weather.get_weather_at` 315, `mandi.get_price` 315, `registry.list_farmers_in_villages` 12, `weather.list_storm_events` 1; median 7 ms on a kept-open session |
| Calls | 422: 324 completed, 93 not answered, 5 handed to a person; at most 8 at once |
| Scenario time from detection to filing, simulated farmers | median 89 min, longest 3 h 38 min |
| Events in one run | about 8,500 |

## Decisions made while building, and why

- **Eight calls at a time, not six.** With six, the last first calls went out at about 19:15, their retries fell after 20:00, the calling hours closed and the run finished the next morning with 55 hours left. With eight it finishes at about 19:25.
- **The run starts at the detection time (15:50), not at 15:30.** Nothing happens between the storm and its detection, so the presenter would have watched seven seconds of nothing.
- **Repeated identical decisions are computed once.** 340 TRIAGE and 312 VERIFY decisions at about 180 ms each are two minutes of model time in a 75-second run, on one CPU model that answers one question at a time. So the TRIAGE report gives the distance in whole kilometres (90 distinct reports instead of 263), and for simulated farmers a report that reads exactly like an earlier one in the same run is answered from memory and marked "cached" in the ticker. The live farmer's decisions are always computed. **Say it this way on stage:** "the model ranked the 88 distinct situations in about 180 milliseconds each; farms in the same situation share the answer." Do not say it made 652 separate computations.
- **Every simulated VERIFY report reads the same** (hail photo, hail on record, at the plot, time matches), because the personas who file are all consistent. So VERIFY is computed once or twice per run. That is honest but thin; if the pitch needs VERIFY to show something, add a few inconsistent personas in Phase 5 and adjust the totals.
- **The storm's footprint includes the land of the listed villages.** Six farms of the outer villages lie just outside the 14 km circle. Under the circle alone the weather record said "no hail" for them and the rules sent them to review, which broke the totals.
- **One open MCP session per server** for the orchestrator: a tool call takes about 7 ms instead of opening a session each time (0.7 s in Phase 3).
- **SQLite and the event log were tuned for volume**: `synchronous=NORMAL`, the log file kept open, `stats.updated` at most four times a second.
- **The presenter resumes after the hero call (P)**, as in `DemoScript.md` step 13; the run does not resume by itself.
- With `HERO_SIM=1` (headless runs) the hero is shown as simulated: "Simulated farmers: 340. Live: 0."

## Notes on the test runs

- The Phase 4 tests pass on the laptop (9 tests, 1 skipped for lack of a browser test tool in `.venv`): `run/reports/task-022-phase4-round4.cmd.txt`. The first laptop run failed one check because the laptop's `.env` has `S1_SIM_CACHE=0`; the tests now set the value themselves.
- Two test runs on the laptop (tasks 020 and 022, second part) stopped partway with no error. The second one's last line shows every service dying at the same moment, which is what closing the black task window does. They were repeated and completed.

## Still open

- T4-12, the full demo with the phone, and a look at the dashboard during a run on the laptop and on the projector.
- The laptop's `.env` still has the first template's `MAX_PARALLEL_CALLS=6` and `S1_SIM_CACHE=0`. `setup\7-start-everything.cmd` sets 8 and 1 for its own run. For any other way of starting, change those two lines in `.env`, or the run will end the next morning with 55 hours left.
- Interaction of a real hero call with the run (the hero's pipeline while the fleet is paused) is covered by code and by the Phase 3 tests separately, not together.
