# Phase 2 results

What was built and measured in Phase 2 (7 Oct 2026). Raw output from the laptop: `run/reports/task-007` to `task-013`.

**Status in one line:** the hero call is built end to end and passes every check that can be made without a person speaking, on the laptop, with the real models. **No spoken test (T2-01 to T2-14) has been run**, the photo check has not seen a real crop photo, and nothing has been tried on a phone. Gate G2 is therefore not closed.

## What exists now

| Roadmap item | Built | Checked how |
|---|---|---|
| 2.1 Steps, scripted lines, slots through registry MCP | `apps/voice/flow.py`, `lines.py`, `hindi.py`, `brain.py` | Unit tests of the rule table (T2-16); whole calls as text against the real orchestrator, registry MCP server and decision service |
| 2.2 ROUTE per turn, fast path, LLM path | `brain.py`, `services.py`, `extract.py`, `prompts.py` | On the laptop with the real head model and Groq: the script of `Testing.md` §9.2 fills every slot with no question asked twice |
| 2.3 PERIL after the cause; escalation, wrong person, no damage, no consent | `flow.py` | Unit tests; T2-04, T2-06, T2-07, T2-08 pass as text on the laptop |
| 2.4 Interruptions; `call.turn` with timings | `agent.py` | Events and thinking time checked as text. **Interruption and audio timings need a spoken call** |
| 2.4a Audio cache, cache builder, local voice | `speech.py`, `scripts/build_tts_cache.py`, `piper_tts.py` | Cache built on the laptop (47 sentences); replay from cache and the local voice checked with real LiveKit audio frames. **Not yet heard by a person** |
| 2.5 Hero call, accept, decline, end, room token with agent dispatch | `apps/orchestrator/main.py`, `cases.py`, `ghante_shared/livekit_token.py` | Tests; LiveKit's own `TokenVerifier` accepts the token; the farmer page joined a real LiveKit Cloud room with it |
| 2.6 Evidence upload | `POST /api/cases/{id}/evidence` | T2-15 |
| 2.7 Farmer app | `apps/web/farmer.*` | Headless browser with a fake camera (ring, answer, photo, upload, message to the agent, hang up, decline). Real page opened in the laptop's Claude browser pane: libraries load, it rings, a photo is checked and uploaded. **The pane blocks the microphone, so no audio call was possible there; not yet on a phone** |
| 2.8 On-phone photo check | `apps/web/edge-worker.js`, `scripts/build_label_embeddings.py`, `apps/web/edge-test.html` | The real MobileCLIP-S0 ran in the laptop browser. **No real crop photo has been classified** |
| 2.9 Offline queue, service worker | `farmer.js` (IndexedDB), `sw.js` | Headless browser: a photo taken offline arrives within 10 s of reconnecting, marked `captured_offline`. The service worker itself is not exercised by a test |
| 2.10 Photo message to the agent, read-back, consent | `farmer.js`, `agent.py` | Both halves tested separately; **not yet together over a real room** |
| 2.11 Dashboard: Call hero, call-ended state, real photo thumbnail | `apps/web/app.js` | Phase 1 browser test still passes; the new parts have not been seen with a real call |

Automated tests: 57 (`tests/test_phase1.py` 19, `tests/test_phase2.py` 38). On the laptop: 55 pass, 2 skipped (the two headless-browser tests; Playwright is not installed there), 58.5 s. In Claude's workspace all 57 pass.

## Measured on the laptop (final run, task-013, 17:27)

`scripts/voice_text_check.py`, run twice back to back: **25 of 25 checks passed both times.**

| Measure | Result |
|---|---|
| ROUTE (trained head) per farmer turn | Median 24 ms; every turn answered by the head |
| Thinking time, fast path (no audio) | Median 26 to 35 ms |
| Thinking time, LLM path (no audio) | Median 792 and 958 ms in the two runs; slowest 1.5 s |
| LLM use per call | 5 requests, about 6,100 tokens (about 1,230 per request). Groq's free limit is 8,000 tokens a minute per model, so one call fits and two calls in the same minute may not; the backup model then answers |
| Turns that took the fast path in the §9.2 script | Greeting, plot, consent. "हाँ, बहुत नुकसान हुआ है" scored 0.43 on ROUTE, below `FAST_PATH_MIN` 0.5, so it went to the LLM |
| Audio cache | 26 lines = 47 sentences = 2,059 characters synthesised once with Sarvam (voice `simran`, 22,050 Hz): 6.2 % of the ₹100 credit. A second run synthesises nothing |
| Local voice (Piper `hi_IN-priyamvada-medium`) | 4.8 s of speech; first audio 2.5 to 3 s after a cold start (voice loading), about 0.35 s once loaded |
| Photo check in the laptop browser (MobileCLIP-S0, fp32, WebAssembly, one thread) | Model ready in 11 s the first time (download), 0.75 s from cache; **240 ms per photo** (median of 5 generated pictures; 273 ms in the farmer app). The phone will be slower |
| Label embeddings | Built (`apps/web/label_embeddings.json`, 5 labels × 512). Text similarity between labels: `lodged` and `healthy` are 0.92 alike, the closest pair; expect confusion there until real photos say otherwise |
| Farmer page with the real libraries | livekit-client 2.22.3 loaded; ring arrived; accepting returned a token and the room connected (the only error was the pane's blocked microphone); a generated picture was labelled, uploaded and stored; with no GPS fix the plot location was recorded (`gps_source: plot`) |

These timings are thinking time only. Speech recognition before it and the first audio after it are not included; only a spoken call measures NFR-01.

## What went wrong on the way, and what was changed

| Seen in | Problem | Change |
|---|---|---|
| Run 1 (task-007) | Each LLM request opened a new HTTPS connection: 5 to 10 s on this Wi-Fi, one timeout | One connection per provider kept open and opened at call start |
| Run 1 | The check spoke its lines in a fixed order even when the agent repeated a question | The check answers the question the agent is on |
| Run 1 | Turns could reach the log out of order | Events are sent by one background thread |
| Run 2 (task-008) | The laptop had no internet (name lookups failed); nothing could be judged | Run repeated |
| Run 3 (task-009) | The cause was asked twice: the PERIL model was unsure about a long sentence although the LLM also said hail | The peril is accepted when both name the same cause |
| Run 3 | The LLM turned "गेहूँ पूरा बिछ गया" into 100 percent damage, and filled the time and crop stage nobody had stated | Prompt tightened; then checks in code: a share, a time or a crop stage is taken outside its own question only if the farmer used a word for it |
| Run 3 | One LLM request took 6.9 s | If there is no answer after 2 s the request is sent again on a second connection; the first answer wins |
| Run 5 (task-011) | Second call straight after the first: Groq HTTP 429 (tokens per minute); the agent said "please repeat" three times and escalated | Prompt shortened by a fifth; `LLM_BACKUPS` adds a second Groq model and Gemini after `LLM_CHAIN` |
| Run 6 (task-012) | The LLM volunteered a sentence (with "72" as digits) when the farmer had asked nothing | Its sentence is spoken only after a question; digits become Hindi words |
| Browser check | A refused microphone showed "call could not connect" | The app now says the microphone permission is missing |

## Decisions taken in Phase 2

- **The LLM extracts, the script speaks.** One JSON request per LLM turn; the agent's questions are always scripted lines (`SystemDesign.md` §10.3).
- **Code, not the LLM, decides what counts as said.** Yes/no slots only for the question asked; share, time and crop stage only with a matching word; consent never early.
- **A plain yes/no is fast-pathed only when the reply has five words or fewer**; at the read-back a "no" with more than two words is read as a correction.
- **`EVIDENCE → ESCALATED` added to the state machine.**
- **Speech is cached per sentence**, Sarvam and Piper in separate folders. With `CREDIT_SAVER=1` no Sarvam request is made for a sentence that is not cached.
- **The photo is taken inside the page**, not with the system camera app.
- **Vision model `fp32`** by default (the plan said `fp16`); changeable with `?dtype=`.
- **Label embeddings are built in Python** on the laptop.
- **Decision models are loaded when the decision service starts.**
- **The phone link without cloudflared** is `ssh -R` through localhost.run (`setup\8-phone-link.cmd`).

## Not done, and why

| Item | State |
|---|---|
| T2-01 to T2-14 (spoken) | Need a person. Steps in `HumanSetupChecklist.md` |
| T2-17 Audio cache in a real call | Cache is built; needs one spoken call and a look at `scripts\usage.py` |
| Accuracy of the photo check (T0-4), time on the phone, airplane mode | Needs the team's photos and the phone: `/static/edge-test.html` |
| The backup LLM model in action | Not triggered in the last runs (no rate limit was hit); covered by a unit test only |
| Multi-threaded WebAssembly for the photo check | Not enabled. Do it only if the phone needs more than 1.5 s per photo |
| Linear probe / binary mode for the photo check | Not built; only needed if zero-shot accuracy is below 80 % |
| Reference number from cached digit clips | Not built; that one sentence is synthesised live (about 70 characters per call) |
| `scripts/report.py` (T2-14 numbers) | Not written; the timings are in `call.turn` events in `logs/events.jsonl` |
| Deterministic parsing of time, share and crop stage (would take three more turns off the LLM) | Not built. Worth doing in Phase 5 if the LLM path is too slow or the token limit bites during rehearsals |

## Update, 7 Oct 2026, 21:00-21:15: first spoken test

`setup\6-voice-console.cmd` on the laptop with speakers. Four attempts; the fourth ran the whole call correctly (all eight answers understood, consent taken after the read-back, call ended). What the first three showed and what was changed is in `Phase3Results.md` under "Found and fixed on the way". The spoken tests with the dashboard and a phone (T2-01 onwards) are still to be done by a person.
