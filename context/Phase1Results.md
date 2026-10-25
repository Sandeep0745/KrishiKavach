# Phase 1 results

What was built and measured in Phase 1 (7 Oct 2026). Everything below was run on the demo laptop unless it says otherwise. Raw output: `run/reports/task-004-phase1.cmd.txt`, `task-005-phase1-web-voice.cmd.txt`, `task-006-voice-text-check.cmd.txt`.

## Gate G1 status

| Test | Kind | Result |
|---|---|---|
| T1-01 Seed | Auto | Pass |
| T1-02 Weather MCP, T1-03 Registry MCP (and mandi fixture) | Auto | Pass |
| T1-04 Decision service, fall-through, report rendering, head maths | Auto | Pass |
| T1-05 Portal form, T1-06 Portal API, T1-07 Portal honesty | Auto | Pass |
| T1-08 Case state machine, slots | Auto | Pass |
| T1-09 Event stream, reset | Auto | Pass |
| T1-11 Dashboard shell | Auto | Pass: pages and files served, sample covers every event type. The headless-browser replay passes in Claude's workspace and is skipped on the laptop (Playwright is not installed in `.venv`) |
| T1-12a Scripted lines | Auto | Pass |
| Live check (`scripts/live_check.py`): six services with the real models | Auto | Pass, 16 of 16 |
| Voice text check (`scripts/voice_text_check.py`): real LiveKit session without audio, real registry MCP, real Groq LLM | Auto | Pass, 7 of 7 |
| **T1-10 One-command start** | Manual | **Not run yet.** A person runs `scripts\dev.py`, then `scripts\smoke.py`, then Ctrl+C |
| **T1-11 Dashboard, seen by a person** | Manual | **Not run yet.** Open `http://localhost:8000/` and run `scripts\replay_events.py` |
| **T1-12 Voice skeleton, spoken** | Manual | **Not run yet.** Double-click `setup\6-voice-console.cmd`, listen and answer in Hindi |

`unittest`: 19 tests, 18 pass and 1 skipped on the laptop (26 s); 19 pass in Claude's workspace.

**G1 is not closed.** The automated part is green. The gate needs T1-10 and T1-12 from a person (T1-11 may be a plain list by the gate rule, and is already better than that).

## Decision models

| Decision | Provider | Accuracy on `data/eval/s1_eval.jsonl` | Median time |
|---|---|---|---|
| ROUTE | `head` (multilingual-e5-small + our softmax head) | 29 of 30 | 21 ms |
| PERIL | `head` | 11 of 12 | about 20 ms |
| TRIAGE | `laya` | 10 of 10 | 141 ms |
| VERIFY | `laya` | 11 of 15 (was 6 of 15 before the Phase 1 fix) | 201 ms |
| any | `llm` fallback (Groq `openai/gpt-oss-20b`) | all correct on a 4-per-decision sample, except VERIFY 2 of 4 | 0.8-2.4 s |

The evaluation set is small (67 examples written by us). Treat these as a sanity check, not a benchmark.

**Fast path threshold.** On the ROUTE examples no fast-path answer was wrong at a confidence of 0.40 or above. `FAST_PATH_MIN=0.5`. The planning value of 0.80 would have sent most plain "yes" answers to the LLM (the live check's "हाँ" scored 0.43 to 0.74 depending on the question).

**VERIFY changes made in Phase 1**
- The second question (`needs_human_review`) was removed. Laya answered "no" to it for every case.
- The report now describes the photo in plain words instead of the label id.
- Result: 6 of 15 became 11 of 15. The four misses: a photo 15 km from the plot, a photo 40 km from the plot, a healthy-crop photo with no hail on record (all three called consistent), and a flattened-crop photo with a hail statement (called inconsistent).
- Decision: numbers are checked by rules, not by the model. Eligibility checks 6, 7, 7a and 7b in `SystemDesign.md` §13 catch every "inconsistent" case in the evaluation set before the model is asked. The model stays as a second opinion. This combined check is measured when the pipeline is built (Phase 3, test E5/E6).

**Per-provider time limits.** The single `S1_TIMEOUT_MS` is gone; each provider has its own limit (head 500 ms, laya 2,000 ms, llm 8,000 ms). The laptop's `.env` still contains the old `S1_TIMEOUT_MS=400` line; it is ignored and can be deleted.

## Voice (item 1.10)

Installed in its own environment, `.venv-voice`: livekit-agents 1.8.5 with the deepgram, sarvam, silero, groq and openai plugins, and mcp 2.3.0.

What the installed version actually offers (checked by printing the signatures and reading the 1.8.5 source):

| Question from `TechDecisions.md` | Answer |
|---|---|
| How to skip the LLM for a scripted reply | Override `Agent.llm_node` and yield the scripted text. Works for spoken and text turns. `on_user_turn_completed` is not called for text input, so it is not used |
| How to play cached audio | `session.say(text, audio=<frames>)` takes ready-made audio frames. This is the hook for the audio cache in Phase 2 |
| LiveKit's own MCP support | **Does not load with MCP SDK 2.x** (it imports 1.x names). The agent calls our MCP servers through `ghante_shared/mcp_client.py`, which also emits `mcp.tool_called` for the dashboard |
| Testing without audio | `AgentSession(llm=...)`, `start(agent, capture_run=True)`, `session.run(user_input=...)`. Used by `scripts/voice_text_check.py` |
| Talking to it on the laptop | `python -m apps.voice.agent console` (the older Python CLI, still shipped; uses the laptop's microphone and speakers). The new console needs the LiveKit CLI, which could not be downloaded |
| Deepgram Hindi | `deepgram.STT(model="nova-3", language="hi")` is accepted by the plugin. Not yet heard with a real voice |
| Sarvam voice | `sarvam.TTS(target_language_code="hi-IN", model="bulbul:v3", speaker="simran")`. Not yet heard |

Text check result: the case is loaded through the registry MCP server (764 ms on the first call), the agent says the `greet` line naming the farmer, then the `event` line naming the village with no LLM call, then the conversation LLM answers a later turn in Hindi. All turns reach the event log as `call.turn`, marked live.

## Dashboard shell (items 1.8, 1.9)

Plain HTML, CSS and JavaScript in `apps/web/`, served by the orchestrator at `/`, with `/farmer` as a placeholder for the phone app. It draws the map as SVG from the snapshot, counts cases itself, and shows the decision ticker, the tool-call log, the agent strip, fallback notices, the live-call panel and the closing banner. Reset and "show map / show live call" work; start, hero call and pause are disabled until the phases that build them.

## Still open from Phase 0

| Item | Needs |
|---|---|
| T0-1 Hindi voice loop: speech recognition quality, response time, how the voice sounds | A person at the microphone. `setup\6-voice-console.cmd` is the first step |
| T0-4 Photo classifier on the phone | A tunnel (cloudflared, to be downloaded on a hotspot), the phone, and 6 to 10 sample photos per label |
| Gemini free limits | Someone to read them in AI Studio |
| Browser agent: where the 43-84 seconds go; visible-browser mode | Phase 3 |

## Usage so far

Groq: 20 requests and about 10,900 tokens for the decision-service fallback tests (2 % and 5 % of one day's allowance), plus one short reply in the voice text check. Sarvam, Deepgram and LiveKit minutes: none used yet.
