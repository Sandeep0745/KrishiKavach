# Testing

After each phase we check that what we planned actually works, before building on it. A phase is done when every **P0** test in its gate passes and the result is written in §11.

## 1. How testing works

- **Test IDs** are `T<phase>-<n>`. Automated tests live in `tests/` with the ID in the file or function name (`test_T1_03_registry_tools`).
- **Auto** tests are Python `unittest` files (pytest can run them too); they start the services they need on spare ports with a temporary data folder. **Manual** tests are done by a person following the steps; they exist because voice, a phone camera and a projector cannot be fully automated in four days.
- A test passes only if the stated pass criterion is met. "Mostly works" is a fail with a note.
- When a test fails: fix it, or apply the phase's "if late" rule in `PhasewiseRoadmap.md`, and record which.
- Claude must run the automated tests itself and report the real output. Claude must not mark a manual test as passed; a person does that.
- Before any gate: `python scripts/smoke.py` must be all green.

**Commands**

| What | Command |
|---|---|
| All automated tests | `.venv\Scripts\python.exe -m unittest discover -s tests -t . -v` |
| One phase | `.venv\Scripts\python.exe -m unittest tests.test_phase1 -v` |
| One test | `.venv\Scripts\python.exe -m unittest tests.test_phase1.T1_08_StateMachine -v` |
| Decision evaluation | `python scripts/eval_s1.py --provider <name>` |
| Metrics of the last run | `python scripts/report.py` |

## 2. Gate G0 — spikes

| ID | Type | What | Steps | Pass |
|---|---|---|---|---|
| T0-1 | Manual | Voice loop on free services (English since 9 Oct 2026) | Run the minimal agent. Speak the 10 utterances of §9.1 in order with each STT option and each free LLM candidate; note transcription errors, time from end of speech to first agent audio, and whether the reply was sensible English. Play one cached audio file as the agent. Speak one line through Piper | A full 10-turn exchange completes with no paid service. Best combination: median ≤ 1.5 s. Cached playback and Piper both work. Results in `TechDecisions.md` §10 |
| T0-2 | Auto + manual | System One providers | Time Laya on the laptop (single decision, and a batch of 30). A person checks whether a Jev key is available free with no card; if yes, make one real request. Run `eval_s1.py` for every provider that works | At least one provider reaches ≥ 85 % on ROUTE and ≥ 80 % on PERIL, with median latency inside NFR-02. Provider order recorded |
| T0-3 | Manual | Browser agent on a free LLM | Read the real free limits in the provider's console. Run the spike against the five-field form three times; count LLM calls | Form submitted correctly 3 of 3 with no rate-limit error; calls and seconds per run recorded; LLM chain for the browser chosen |
| T0-4 | Manual | Edge model on the demo phone | Open the spike page through the tunnel. Classify every photo in `data/eval/edge` (point the phone at a laptop screen or load the files). Then switch to airplane mode and classify one more | ≥ 80 % correct top label on the sample set, or the linear probe is scheduled. Inference ≤ 1.5 s. Works in airplane mode |
| T0-5 | Auto | Scaffold | `python scripts/smoke.py` | Runs and reports each external key as valid or missing |

**G0 passes when** T0-1 to T0-5 pass or their fallback decision is recorded.

## 3. Gate G1 — foundations

| ID | Type | What | Pass |
|---|---|---|---|
| T1-01 | Auto | Seed | `seed.py` creates 12 villages, 340 farmers, 340 policies; exactly one hero; persona outcome counts equal `SystemDesign.md` §12.2; running it twice gives identical data |
| T1-02 | Auto | Weather MCP | An MCP client lists tools; `list_storm_events("Sehore", …)` returns the scenario event with 12 villages; `get_weather_at` at the hero's plot at 15:30 returns `hail: true`, and at a point 100 km away returns `hail: false` |
| T1-03 | Auto | Registry MCP | Tools listed; `list_farmers_in_villages` returns 340 across all villages; `get_policy` for the hero returns khasra 214; `update_case_slots` changes the case and an event is logged |
| T1-04 | Auto | Decision service | `/decide` works for all four decisions and returns the response shape of `SystemDesign.md` §8.1; with the first provider in a chain disabled, the next provider answers and `fallback_from` is set; an `s1.decision` event reaches the log |
| T1-05 | Auto | Portal form, page by page (posted over HTTP; a real browser fills it in Phase 3) | Fill the three pages with the hero's values, upload a photo, submit; confirmation shows `FCS-` + 6 digits; the claim appears in `/admin/claims` and via `GET /api/claims/{ref}` |
| T1-06 | Auto | Portal API | `POST /api/claims` creates a claim; `POST /api/reset` empties the list |
| T1-07 | Auto | Portal honesty | Every page contains the sandbox banner text; no page contains government names or emblems |
| T1-08 | Auto | Case state machine | Every allowed transition succeeds and emits `case.status_changed`; a disallowed one (`QUEUED → FILED`) raises |
| T1-09 | Auto | Event stream | A stream client (Server-Sent Events) receives `snapshot` on connect and then an event posted to `/internal/events`; the same event is in `logs/events.jsonl` |
| T1-10 | Manual | One-command start | `python scripts/dev.py` starts all processes; `smoke.py` is green; Ctrl+C stops them all |
| T1-11 | Auto + manual | Dashboard shell | Auto: `/`, `/farmer` and `/static/…` are served; the sample covers every event type; with Playwright installed, a headless browser replays the sample and checks dots, counters, ticker, tool log, live-call panel, closing banner, one-screen fit and reset (skipped where Playwright is missing). Manual: open `http://localhost:8000/`, run `replay_events.py`, and watch the map, counters, ticker and agent strip move |
| T1-12 | Auto + manual | Voice skeleton | Auto: `.venv-voice\Scripts\python.exe scripts\voice_text_check.py` runs the agent in a text-only session: the hero case is fetched through registry MCP (in the event log), the `greet` line names the farmer, the `event` line names the village with no LLM call, a later turn is answered by the LLM, every turn is logged as `call.turn`. Manual: double-click `setup\6-voice-console.cmd`; the assistant greets Ramlal ji aloud; answer "Yes, speaking"; it speaks the hail line naming Khajuriya Kalan |

**G1 passes when** T1-01 to T1-10 and T1-12 pass. T1-11 may be a plain list instead of a map.

## 4. Gate G2 — hero call

| ID | Type | What | Steps | Pass |
|---|---|---|---|---|
| T2-01 | Manual | Ring and connect | Trigger the hero call from the dashboard | Phone rings within 2 s; after accept, two-way audio |
| T2-02 | Manual | Happy path | Speak script §9.2 | All slots filled with the right values (check the dashboard checklist and `GET /api/cases/{id}`); call reaches the photo request |
| T2-03 | Manual | Fast path | During T2-02, look at the turn rows | The plain "yes" turns show `fast`; the log shows no LLM call for them; detail turns show `llm` |
| T2-04 | Manual | Two answers at once | At the damage question say "Yes, the hail flattened more than half the crop" | `damage_confirmed`, `cause_text`/`peril` and `damage_pct` all filled; the agent does not ask for them again |
| T2-05 | Manual | Interruption | Start talking while the agent speaks | Agent audio stops within about half a second and it responds to what was said |
| T2-06 | Manual | Asks for a person | Say "I want to talk to a person" | Agent says the escalation line; case `ESCALATED`; call ends |
| T2-07 | Manual | No damage | Answer "No, the crop is fine" to the damage question | Agent says the no-damage line; case `NO_DAMAGE` |
| T2-08 | Manual | Wrong person | Answer "No, wrong number" to the greeting | Agent apologises and ends; call outcome `wrong_person` |
| T2-09 | Manual | Unclear speech | Mumble or say something unrelated three times in a row | The agent asks again, then says the rephrase line, then the escalation line; case `ESCALATED`; no crash, no loop |
| T2-10 | Manual | Photo on the phone | During the call press "Take photo", photograph a damaged-crop image | Label, confidence and milliseconds shown on the phone; evidence appears on the dashboard with GPS and time; agent moves to the read-back |
| T2-11 | Manual | Not a crop | Photograph a wall | Retake prompt on the phone |
| T2-12 | Manual | Offline capture | Airplane mode on; take a photo from the idle screen; airplane mode off | Classified while offline; appears on the server within 10 s of reconnecting, marked `captured_offline` |
| T2-13 | Manual | No consent | Say "No" at the consent question | Nothing filed; case `ESCALATED` |
| T2-14 | Measure | Voice latency | Run §9.2 twice; `python scripts/report.py` | Fast path median ≤ 0.8 s; LLM path median ≤ 1.5 s, 95th percentile ≤ 2.5 s. If missed, record the real numbers and the cause |
| T2-15 | Auto | Evidence endpoint | `tests.test_phase2.T2_15_Evidence`: post a photo with metadata; post bad ones | Stored, SHA-256 returned and matches the file, `evidence.received` emitted; a wrong label, a wrong file type, an empty file and an unknown case are refused |
| T2-16 | Auto | Turn logic | `tests.test_phase2.T2_16_TurnLogic` (rule table with mocked ROUTE answers) and `T2_Brain` (whole calls as text against the real orchestrator, registry MCP server and decision service) | Every row of the table produces the stated action; the happy path fills all ten slots and reaches `PROCESSING` |
| T2-18 | Auto | Call endpoints | `tests.test_phase2.T2_Calls`, `T2_RingTimeout` | The phone's stream gets `call.incoming` within 2 s; accept returns a token whose claims dispatch the `intake` agent; decline and an unanswered ring end in `NO_ANSWER`; a dropped call can be rung again |
| T2-19 | Auto | Farmer app | `tests.test_phase2.T2_FarmerApp` in a headless browser with a fake camera (skipped where Playwright is missing) | Ring, answer, photo, on-phone result, upload with GPS, message to the agent, hang up, decline; a photo taken offline arrives within 10 s of reconnecting |
| T2-20 | Auto | Voice agent as text | `.venv-voice\Scripts\python.exe scripts\voice_text_check.py` on the laptop: real LiveKit session without audio, real head model, real LLM, real MCP servers | The script of §9.2 fills the expected slots with no question asked twice; plain yes turns are `fast`, detail turns `llm`; T2-04, T2-06, T2-07 and T2-08 behave as stated; the audio cache replays without a synthesis request; the local voice speaks |
| T2-17 | Auto + manual | Audio cache | Run `build_tts_cache.py`, then a happy-path call | Every scripted line plays from cache; `logs/usage.json` shows live TTS characters only for LLM-written sentences, under 500 for the call; with `CREDIT_SAVER=1` it shows none on a paid-credit provider |

**How to run the manual tests.** Double-click `setup\7-start-everything.cmd`; it starts the backend and the voice worker and opens the dashboard and the farmer page. On the laptop alone: press the big button on the farmer page, then "Call hero" on the dashboard, and speak with a headset. With a phone: also run `setup\8-phone-link.cmd` and open the printed `https` address followed by `/farmer` on the phone. `setup\6-voice-console.cmd` tests the conversation with no browser at all.

**G2 passes when** T2-01 to T2-10 and T2-13 to T2-20 pass. T2-11 is P1. T2-12 may be dropped under the cut list (then remove the airplane-mode beat from `DemoScript.md`).

## 5. Gate G3 — claim pipeline

| ID | Type | What | Pass |
|---|---|---|---|
| T3-01 | Auto | Evidence node | For the hero case with a stored photo: pack has weather record with `hail: true`, a distance from plot, and the photo hash |
| T3-02 | Auto | Eligibility rules | Each persona in §10 gets the expected verdict and reasons |
| T3-03 | Auto | Deadline rule | A case with scenario time after `deadline_at` is `ineligible` with the reason "outside 72 hours" |
| T3-04 | Manual | Browser agent | `POST /file` in `agent` mode for the hero: the visible browser fills all three pages, uploads the photo, submits | Reference returned; every field in the portal record equals the form sent; time ≤ 75 s; at most 12 LLM calls. Run 5 times, spaced so the free rate limit is not the cause of failure: at least 4 succeed in agent mode |
| T3-05 | Auto | Scripted fill | `POST /file` in `scripted` mode | Same checks; time ≤ 15 s; 5 of 5 |
| T3-06 | Manual | Automatic fallback | In `auto` mode, set `FILING_TIMEOUT_S=5` | Agent starts, fallback takes over, claim filed, `fallback.used` event, dashboard shows "scripted fallback" |
| T3-07 | Auto | Portal failure | Stop the portal, run the pipeline | Case ends `FAILED` with a reason; orchestrator stays up; restart portal and re-run succeeds |
| T3-08 | Manual | Full hero flow | From ring to reference with the phone, speaking §9.2 | Agent reads the reference on the same call; message card arrives on the phone; case `FILED`; dashboard shows time-to-file ≤ 3 min 30 s |
| T3-09 | Manual | Slow filing | Set an artificial 100 s delay in the filer | Agent says the slow line and ends the call; message card arrives when filing completes |
| T3-10 | Auto | MCP used by two clients | After T3-08, the event log has `mcp.tool_called` with `client: intake` and with `client: pipeline` |
| T3-11 | Auto | Pipeline events | One run emits `agent.started`/`agent.finished` for evidence, eligibility, filing, followup in order, and `claim.filed` |
| T3-12 | Auto (P1) | Reviewer approval | Persona E4 ends in review; `POST /api/cases/{id}/review` with approve files the claim; the log has the approval with `agent: system` and a human marker |

**G3 passes when** all of T3-01 to T3-11 pass. If T3-04 fails its 4-of-5 bar, G3 may pass with `FILING_MODE=auto` provided T3-06 passes; return to T3-04 after G4.

## 6. Gate G4 — fleet and dashboard

| ID | Type | What | Pass |
|---|---|---|---|
| T4-01 | Auto | Detection | Starting the scenario emits one `storm.detected` with 12 villages and creates 340 cases with `deadline_at` = event time + 72 h |
| T4-02 | Auto | Triage | 340 TRIAGE decisions logged; queue order is non-increasing in priority; cases in `severe` villages have a higher mean priority than `light` ones |
| T4-03 | Auto | Concurrency and retries | At no time are more than `MAX_PARALLEL_CALLS` cases in `CALLING`/`IN_CALL`; `no_answer` personas end `UNREACHABLE` after exactly 3 attempts |
| T4-04 | Auto | Final totals | Run the scenario headless with the hero auto-completed by a test persona: final counts equal `SystemDesign.md` §12.2 (312 / 11 / 9 / 5 / 3) |
| T4-05 | Auto | Real records | The portal has exactly as many claims as there are `FILED` cases, and every `claim_ref` resolves |
| T4-06 | Auto | Determinism | Two runs from reset give the same final totals and the same first 20 queue entries |
| T4-07 | Manual | Pause and resume | Trigger the hero call mid-run | Clock and fleet freeze; they resume when the presenter presses P (as in `DemoScript.md` step 13); no simulated case changed state during the pause. The freeze and resume are also tested automatically with the P control |
| T4-08 | Manual | Dashboard truth | During a run compare the counters with `GET /api/state` three times | Always equal |
| T4-09 | Manual | Labels | Look at the dashboard at any moment | "Simulated: N · Live: 1" visible; hero dot labelled LIVE |
| T4-10 | Manual | Timing | Run with defaults | Fleet completes in 60–90 real seconds (excluding the hero pause); final banner reads "312 of 340 claims filed · 68 hours left" |
| T4-11 | Manual | Reset | Press reset, then start again | Clean state in under 10 s; second run behaves like the first |
| T4-12 | Manual | **Full demo script** | Run `DemoScript.md` from the top with the phone | Every beat happens in order with no manual fix |
| T4-13 | Manual | Projector check | Dashboard at 1920×1080 and at 1366×768 | Nothing clipped or scrolling; text readable from the back of a room |

**G4 passes when** T4-01 to T4-12 pass.

## 7. Gate G5 — demo readiness

| ID | Type | What | Pass |
|---|---|---|---|
| T5-01 | Manual | Five in a row | Run the full demo script five times consecutively, resetting between runs. Any manual fix resets the count to zero | 5 of 5 |
| T5-02 | Manual | Hotspot only | Laptop and phone on a mobile hotspot, venue-like conditions | One full clean run; latencies recorded |
| T5-03 | Manual | Cold start | Reboot the laptop; follow only the run instructions in the root `README.md` | Demo ready in under 10 minutes |
| T5-04 | Manual | All fallback drills in §8 | — | Each behaves as described |
| T5-05 | Manual | Backup video | Play it on the demo laptop with sound | Plays; shows a complete clean run; under 3 minutes |
| T5-06 | Manual | Timed rehearsal | Present with slides and demo three times | Within the allotted time each time |
| T5-07 | Auto | Report | `python scripts/report.py` after a clean run | Prints all metrics; numbers copied into the slides |
| T5-08 | Manual | Honesty and language review | Read every slide and every dashboard label against `ArchitectureDesign.md` §7; check farmer-facing text and speech and the dashboard are all English (NFR-13) | Nothing claims more than was measured or built |
| T5-09 | Manual | Secrets | Search the repo and logs for key strings | None found; `.env` is git-ignored |
| T5-10 | Manual | Zero spend | Open each provider's billing page; run `python scripts/usage.py` | Nothing charged; no payment method on any account; enough allowance left on each service for at least 10 more full runs |

**G5 passes when** all pass.

**What a machine does for G5 (built in Phase 5).** These help; they do not replace the manual rows above.

| Helps with | How | Checks |
|---|---|---|
| T5-01 | `.venv-voice\Scripts\python.exe scripts\demo_check.py` (five runs, about 15 minutes) | From reset, each run: storm starts; cases are ranked and being called when the hero is rung 15 s in; the district pauses for the live call and nothing in it moves during the call; the hero call is played as text (the lines of §9.2) against the real Intake agent, decision models and LLM; the photo is uploaded; the report is filed in the browser (agent, or its labelled fallback) and the agent reads the reference out; after P the district finishes on 312 / 11 / 9 / 5 / 3, "68 hours left", 60 to 90 s, one portal record per filed case. Not checked: voice, phone, camera, room |
| T5-04 | `.venv\Scripts\python.exe scripts\drills.py` | D1, D2, D4, D6, D7 of §8 with the real models and keys. D3, D5, D8 and D9 stay manual |
| T4-13, T5-01 | `tests/test_phase5.py` `T5_Dashboard` | A dashboard opened or reloaded mid-demo shows the run so far exactly once (live-call transcript, ticker, tool calls, fallback notice, the run's true counts) and fits 1920 × 1080 and 1366 × 768 with nothing clipped or scrolling. On the laptop it runs from `.venv-browser` with the installed Chrome |
| T5-07 | `tests/test_phase5.py` `T5_Scripts` | `report.py` reads a run's event log |
| T5-09 | `.venv\Scripts\python.exe scripts\secrets_check.py` | No `.env` value anywhere else in the project or logs; nothing shaped like a provider key; `.env` git-ignored |
| T5-03 | `scripts\smoke.py` "On-stage readiness" | Scenario reset, phone connected, decision models loaded and warmed, Filer window open, browser agent usable |

## 8. Fallback drills

Each drill is done once on Day 4 so the team has seen the failure and the recovery.

| # | Break it by | Expected behaviour | Recover by |
|---|---|---|---|
| D1 | Disabling the first System One provider | Ticker shows the next provider with a fallback marker; demo continues | Re-enable |
| D2 | `FILING_TIMEOUT_S=5` | Scripted fill completes; label shown | Restore value |
| D3 | A wrong key for the speech provider in use | Voice worker logs a clear error at start; `smoke.py` is red for speech | Switch `STT_PROVIDER`/`TTS_PROVIDER`, restart voice worker |
| D4 | A wrong key for the first LLM in `LLM_CHAIN` | The next provider in the chain answers; `fallback.used` logged | Fix the key |
| D9 | `TTS_PROVIDER=piper` (as if the speech credit had run out) | Scripted lines still play from cache in the demo voice; LLM-written sentences are spoken by Piper; the call completes | Restore value |
| D5 | Turning off the phone's Wi-Fi mid-call | Call drops; case shows call outcome `dropped`; presenter can re-trigger the hero call and the collected slots are kept | Reconnect, press [H] |
| D6 | Killing the filer process during filing | Case `FAILED` with reason; orchestrator alive | `dev.py --only filer`, re-run pipeline from the dashboard |
| D7 | Killing the orchestrator | Dashboard shows "disconnected" and reconnects when it is back | Restart, reset |
| D8 | Disconnecting the laptop from the internet | `smoke.py` red; presenter switches to the backup video | Reconnect |

## 9. English test material

Read these aloud naturally, in the accent of a farmer from the region if possible. (Until 9 Oct 2026 this material was in Hindi.)

### 9.1 Ten utterances for the voice spike

1. Yes, speaking.
2. Yes, there is a lot of damage.
3. Hail fell, the whole crop is flattened.
4. Around half past three in the afternoon.
5. More than half the field is ruined.
6. The crop was standing, harvesting was still left.
7. When will I get the money?
8. No, not that field, it is the other one.
9. I want to talk to a person.
10. Yes, please do it.

### 9.2 Happy-path script for the hero call

| Agent asks about | Farmer says |
|---|---|
| Identity | Yes, speaking. |
| Damage | Yes, there is a lot of damage. |
| Khasra 214 | Yes, that is the field. |
| Cause | Hail fell, the wheat is completely flattened. |
| Time | Around half past three in the afternoon. |
| Extent | More than half, about seventy percent. |
| Stage | The crop was standing. |
| Photo | (takes the photo) |
| Consent | Yes, please do it. |

Expected slots: identity ✓, damage ✓, khasra ✓, peril `hailstorm`, loss time 15:30 on the scenario date, damage 70 %, stage `standing`, consent ✓.

### 9.3 Variations to try at least once each

- Indian-English phrasing: "Yes ji, full damage happened."
- Long answer with a story before the fact.
- A number said differently: "three quarters of the field", "seven parts out of ten".
- Background noise (a fan, a TV).
- A long silence before answering.
- A question in the middle: "When will the surveyor come?"

## 10. Eligibility test personas (T3-02)

| Persona | Set-up | Expected verdict | Expected reason |
|---|---|---|---|
| E1 Hero | Active policy, wheat, hail, standing, photo `hail_damage` 0.8, 120 m from plot, weather `hail: true` | `eligible` | — |
| E2 Lapsed | Policy status `lapsed` | `ineligible` | Policy not active |
| E3 Pest | Cause "Insects attacked the crop" → peril `not_covered` | `ineligible` | Peril not covered |
| E4 Far away | Photo taken 15 km from the plot | `review` | Photo location far from insured plot |
| E5 Healthy photo | Statement says 80 % hail damage, photo `healthy` 0.85 | `review` | Evidence inconsistent: the photo shows a healthy crop (rule 6) |
| E6 No hail on record | Weather at the spot `hail: false`, statement says hail | `review` | Evidence inconsistent: the weather record shows no hail (rule 7a) |
| E7 Not a crop | Photo `not_a_crop` | `review` | No usable photo |
| E8 Harvested, hail | Stage `harvested`, peril `hailstorm` | `eligible` | — |

E5 and E6 are decided by plain rules (6 and 7a), as planned after the Phase 1 evaluation; VERIFY is asked only when every rule has passed. All eight personas are in `tests/test_phase3.py` (`T3_02_EligibilityRules`), and E2, E3, E4 and E7 also run through the whole pipeline there.

## 11. Results log

Fill in as gates are attempted. Keep failed attempts; they are useful later.

| Date and time | Gate | Tests failed (IDs) | What was done | Passed? | By |
|---|---|---|---|---|---|
| | G0 | | | | |
| 7 Oct 2026, 14:43-14:56 | G1 | none in the automated part | 19 unittest tests (18 pass, 1 skipped: no Playwright on the laptop), live check 16/16, voice text check 7/7. Manual T1-10, T1-11 (by eye) and T1-12 (spoken) not run yet | Not yet: waiting for the manual checks | Claude |
| 7 Oct 2026, 16:33 | G2 | T2-08 and the happy path in the first text run (network: slow new HTTPS connections to the LLM; and a check script that did not follow the agent) | Fixed: LLM connection kept open, check follows the agent's question, events sent in order | Not yet | Claude |
| 7 Oct 2026, 16:48-17:24 | G2 | Runs 2 to 6: no internet (run 2); cause asked twice, values the farmer never said, one 6.9 s request (run 3); Groq rate limit on a second call (run 5); an unasked LLM sentence (run 6) | Each fixed, see `Phase2Results.md` | Not yet | Claude |
| 7 Oct 2026, 17:27 | G2 | none in the automated part | T2-15, T2-16, T2-18, T2-20 pass on the laptop (57 tests: 55 pass, 2 skipped; voice text check 25 of 25, twice). T2-19 passes in Claude's workspace only. Real farmer page and real photo model checked in the laptop's browser pane. T2-01 to T2-14 and T2-17 (spoken, phone) not run | Not yet: waiting for the spoken tests | Claude |
| 7 Oct 2026, 21:42-22:29 | G3 | Run 1: the hero's own case sent to review by VERIFY; browser agent switched off by a blank setting. Run 2: browser agent over 75 s, 0 of 3. Run 3: one agent for the whole form needs 182 s (token allowance per minute) | VERIFY report reworded without figures (120 of 120 consistent cases pass); browser agent rebuilt as one small agent per page (3 calls, about 31 s). See `Phase3Results.md` | Not yet. Automated part passes on the laptop: 88 tests (85 pass, 3 skipped), voice text check 27 of 27, T3-04 5 of 5 (headless), T3-05, T3-06, T3-07, T3-10, T3-11, T3-12. Waiting for T3-08 and T3-09 by voice and one look at the visible window | Claude |
| 7 Oct 2026, 23:13-23:25 | G4 | In Claude's workspace before the laptop run: with 6 parallel calls the retries ran past 20:00 and the run ended next morning; 6 farms outside the storm circle went to review | 8 parallel calls; footprint includes the listed villages' land; repeated identical decisions computed once. See `Phase4Results.md` | Not yet. On the laptop with the real models: totals 312/11/9/5/3 twice, 74 s and 73 s, "68 hours left", 312 portal records. Automated T4-01 to T4-06 pass. Waiting for T4-12 (full demo with the phone) and a look at T4-07 to T4-09 and T4-13 | Claude |
| 8 Oct 2026, 10:31-11:19 | G5 | Rehearsal A1, the first call after start-up, ended early (handed to a person after 4 turns); drill D4 (no second LLM: Gemini `gemini-3.8-flash` answered 429; fixed with `gemini-3.1-flash-lite`, D4 then passed); T2 phone page in the laptop's Chrome 155 (its fake camera disappears after first use); secrets check tripped on exception names in old reports; T1-09 written before the replay | Decision models now answer one practice question at start-up; key check ignores capitalised names; T1-09 updated; the page asks for the camera three times and logs why it failed. See `Phase5Results.md` | Not yet. Machine part on the laptop: rehearsal 3 of 3 from a cold start (and 3 of 4 before the fix), drills 10 of 10 after the backup fix, secrets check, dashboard in Chrome at 1920 × 1080 and 1366 × 768. Waits for the team's steps 16-24 in `HumanSetupChecklist.md` | Claude |

### Measured numbers (copy from `scripts/report.py`)

| Metric | Target | Measured | Run date |
|---|---|---|---|
| Voice response, fast path, median | ≤ 0.8 s | | |
| Voice response, LLM path, median | ≤ 1.5 s | | |
| Voice response, LLM path, 95th percentile | ≤ 2.5 s | | |
| System One decision, median (provider: ___) | ≤ 250 ms | ROUTE on the head 19 ms (8 decisions), TRIAGE on Laya 162 ms (89 computed), VERIFY on Laya 221 ms (3 computed); rehearsal B3, text call | 8 Oct 2026 |
| ROUTE accuracy on eval set | ≥ 85 % | | |
| PERIL accuracy on eval set | ≥ 80 % | | |
| On-phone classification time | ≤ 1.5 s | | |
| Edge accuracy on sample photos | ≥ 80 % | | |
| Filing time, browser agent | ≤ 75 s | median 32 s, slowest 32 s (5 runs, no window, final setting) | 8 Oct 2026 |
| Browser agent success rate | ≥ 4 of 5 | 5 of 5, every field correct | 8 Oct 2026 |
| Hero ring to reference | ≤ 3 min 30 s | | |
| Fleet completion (real seconds) | 60–90 s | 74 s and 73 s (real models, scripted hero) | 7 Oct 2026 |
| Live TTS characters per hero call | ≤ 500 | | |
| LLM calls per browser-agent filing | ≤ 12 | 3 | 8 Oct 2026 |
| Money spent | ₹0 | | |

## Automatic weather checks

Automated: safe weather does not start; hazardous current/forecast records do; stale, malformed and missing weather fail closed; MCP errors do not synthesize storms; busy scenarios and cooldown suppress duplicate starts across reset/restart; loopback controls reject remote origins; the demo automatically opens 340 cases without POST /api/scenario/start; browser panel survives reload and fits existing projector sizes. Live: request Open-Meteo for all 12 coordinates and record actual result without forcing risk. Manual: demonstrate clear weather, wait 20 seconds, observe automatic storm and district calls, then trigger the live farmer call and finish the established phone flow.


## Multilingual intake update — 11 October 2026

The live call starts in the supported primary language of the farmer's state: Madhya Pradesh/Sehore Hindi, Tamil Nadu Tamil, Kerala Malayalam, otherwise English. Only Hindi, English, Malayalam and Tamil are enabled. Saaras v4 streaming uses language="unknown", mode="translate": detected source-language metadata selects speech, while the English translation feeds existing S1/slot guards. Explicit requests override automatic detection; an unclear/unsupported detection or a short English yes/no does not change the current language. Requests to change language or repeat a misunderstood question do not grant identity or consent and do not consume the question retry budget. Bulbul v3 receives the selected language per utterance; scripted questions have fixed source translations requiring a native-speaker review and the cache key includes language. English Piper is restricted to English. Non-English speech may use signup credits even with CREDIT_SAVER=1 if not cached. Dashboard transcripts are labelled as translated with the source language. Provider failure is reported, never disguised as successful speech. Automated and synthetic audio tests are separate from the required human phone rehearsal; Commit eligibility for this prototype was accepted by the user after real-phone Hindi/English and automated farmer-browser Malayalam/Tamil checks; physical-phone Malayalam/Tamil and native-speaker review remain outstanding.

References: https://docs.sarvam.ai/api-reference/speech-to-text/transcribe/ws ; https://docs.sarvam.ai/api/getting-started/models/saaras ; installed LiveKit Agents 1.8.5 Sarvam plugin (STT final alternatives.language/confidence, TTS update_options).


Multilingual browser rehearsal: scripts/multilingual_browser_check.py opens the actual farmer web app in Chrome, answers a real LiveKit call, and injects explicitly synthetic Malayalam then Tamil microphone audio. Check STT source-language metadata, localized agent turns, received non-silent audio in the browser, and unchanged identity/consent slots for language requests. This is an automated browser/WebRTC test, not a physical-phone or native-speaker review. It resets the synthetic scenario; do not run during another rehearsal.
