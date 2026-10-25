# Phase-wise roadmap

Six phases over four days. A phase ends only when its gate in `Testing.md` passes. If a gate does not pass by its time-box, apply that phase's "if late" rule instead of pushing on.

## 1. Overview

| Phase | Name | When | Outcome | Gate |
|---|---|---|---|---|
| 0 | Setup and spikes | Evening before + Day 1 morning (≤ 4 h) | Accounts work; the four risky parts are each proven in isolation; open choices in `TechDecisions.md` §10 are filled in | G0 |
| 1 | Foundations | Day 1 afternoon and evening | Data, MCP servers, decision service, sandbox portal, orchestrator skeleton, event stream, dashboard shell | G1 |
| 2 | Hero call | Day 2 until late afternoon | A full call on the phone (English since 9 Oct 2026) fills every slot and uploads an on-device-classified photo | G2 |
| 3 | Claim pipeline | Day 2 evening + Day 3 morning | From a completed call to a filed claim in the browser, with the reference read back on the call | G3 |
| 4 | Fleet and dashboard | Day 3 afternoon and evening | Storm → 340 cases → triage → simulated calls → map goes green; the whole demo script runs | G4 |
| 5 | Hardening and demo | Day 4 | Five clean runs, fallbacks rehearsed, backup video, pitch | G5 |

**Rule for the whole build:** by the end of Day 3 everything is integrated. Day 4 adds no features.

## 2. Three tracks

The contracts in `SystemDesign.md` let three streams of work run at once. With fewer people, run them in the order A-B-C inside each phase.

| Track | Owns | Folders |
|---|---|---|
| **A · Voice** | Intake agent, English lines, latency | `apps/voice`, `data/eval` (English examples) |
| **B · Backend** | Orchestrator, pipeline, MCP servers, decision service, filer, portal, simulator | `apps/orchestrator`, `apps/s1`, `apps/filer`, `apps/portal`, `mcp_servers/`, `ghante_shared/`, `scripts/` |
| **C · Web** | Dashboard, farmer app, edge model | `apps/web`, `data/eval/edge` |

When using several Claude Code sessions at once, give each session one track and tell it not to edit other tracks' folders. Shared models in `ghante_shared/` belong to Track B; others request changes.

## 3. Phase 0 — Setup and spikes

**Goal:** remove the four unknowns before building anything on top of them.

**People first (see `HumanSetupChecklist.md`):** accounts and keys, installs, phone, sample photos, a read-aloud review of the scripted lines.

**Build**

| # | Item | Track | Notes |
|---|---|---|---|
| 0.1 | Repo scaffold: layout from `SystemDesign.md` §1, uv workspace on Python 3.12, `.env.example`, `.gitignore`, `scripts/dev.py` stub, `scripts/smoke.py` | B | `git init`; first commit |
| 0.2 | **Spike: voice loop, free services only** (run in Hindi in Phase 0; the call is English since 9 Oct 2026). Minimal LiveKit agent. Compare STT (Deepgram vs Sarvam) and the free LLM candidates on the test utterances; log time from end of speech to first audio. Prove three things: a cached audio file can be played as the agent's speech, Piper works as a local voice, and whether Cartesia through LiveKit's included credit speaks usable Hindi | A | T0-1 |
| 0.3 | **Spike: System One.** Run Laya locally and time it on the laptop CPU, single and batched. A person checks whether a Jev key can be had free with no card. Write the providers behind one function. Write `s1_eval.jsonl` and `eval_s1.py`. Run all available providers | B | T0-2 |
| 0.4 | **Spike: browser agent.** A five-field local HTML form; browser-use fills and submits it in a visible window; time it per LLM | B | T0-3 |
| 0.5 | **Spike: edge model.** A bare page that loads MobileCLIP-S0, classifies a photo from the camera, shows label and milliseconds; open it on the demo phone through the tunnel; test the sample photos; test airplane mode | C | T0-4 |
| 0.6 | Record results and decisions in `TechDecisions.md` §10 | all | |

**Gate G0.** Time-box: 4 hours of working time.

**If late**
- Voice not working after 3 h → switch to Pipecat with the same providers for 1 h more. Still nothing → stop and rethink with the team: the project depends on this.
- No free Jev key → Laya stays first (this is the default plan, not a setback). Laya too slow on CPU → try a quantised ONNX build, then `S1_SIM_CACHE=1`. Laya inaccurate on our set → fit the temperature, reword the criteria, then put `llm` first and say so on stage.
- Browser agent too slow or rate-limited on the free tier → allow more actions per step, shrink the page, try the next free LLM in the chain; if still over 75 s, accept that the scripted fallback will often finish the job and say so on stage.
- Edge accuracy poor → schedule the linear probe for Day 2 morning; someone collects 30 photos per label tonight.

## 4. Phase 1 — Foundations

**Goal:** every service exists, starts with one command, and speaks its contract, even if the logic inside is thin.

| # | Item | Track | Requirements |
|---|---|---|---|
| 1.1 | Shared models; SQLite; `seed.py` producing 12 villages, 340 farmers with policies and personas, the hero | B | FR-02 |
| 1.2 | Scenario file `sehore_hail.json` | B | FR-01 |
| 1.3 | MCP weather (replay mode) and MCP registry | B | FR-70, FR-71 |
| 1.4 | Decision service with the four decisions, provider fall-through, event emission | B | FR-80, FR-81, FR-82 |
| 1.5 | Sandbox portal: three pages, confirmation, admin list, JSON API, reset | B | FR-60, FR-61, FR-62 |
| 1.6 | Orchestrator skeleton: case store and state machine, event bus, JSONL log, `/api/events/stream`, `/api/state`, `/internal/events`, reset | B | NFR-11 |
| 1.7 | `scripts/dev.py` starts everything; `smoke.py` goes green | B | NFR-08 |
| 1.7a | Usage log, `scripts/usage.py`, credit-saver mode | B | NFR-12, NFR-14 |
| 1.8 | Web app shell: routes `/` and `/farmer`, event-stream client, event store; dashboard layout with map, counters, ticker, agent strip rendering from `replay_events.py` | C | FR-51 to FR-54 (rendering only) |
| 1.9 | A hand-written `events_sample.jsonl` covering every event type | C | — |
| 1.10 | Intake agent skeleton: joins a room, loads the case through registry MCP, speaks the `greet` and `event` lines | A | FR-11, FR-73 |

**Gate G1.** Time-box: end of Day 1.

**If late:** drop 1.9/1.8 polish (keep a plain list view of events), keep everything in Track B.

## 5. Phase 2 — Hero call

**Goal:** the complete conversation, on the phone, with the photo.

| # | Item | Track | Requirements |
|---|---|---|---|
| 2.1 | Conversation steps and scripted lines (`flow.py`); slot store through registry MCP | A | FR-12 |
| 2.2 | Per-turn hook: ROUTE call, fast-path rules, LLM path with `record_slots` | A | FR-13 |
| 2.3 | PERIL decision after the cause; escalation, wrong person, no damage, no consent paths | A | FR-15, FR-16 |
| 2.4 | Interruption handling tuned; `call.turn` events with stage latencies | A | FR-14, NFR-01 |
| 2.4a | `speak()` with the audio cache, `build_tts_cache.py`, Piper adapter, cached clips for the reference number | A | FR-21, NFR-14 |
| 2.5 | Orchestrator: `/api/hero/call`, call accept/decline, room token, agent dispatch, `/api/farmer/{id}/stream` | B | FR-10 |
| 2.6 | Evidence upload endpoint, file hashing, `evidence.received` | B | FR-31 |
| 2.7 | Farmer app: idle, incoming call (ring), in call, photo flow | C | FR-10 |
| 2.8 | Edge model in a Web Worker, precomputed label embeddings, result card, retake rule | C | FR-30, FR-33 (P1) |
| 2.9 | Offline queue and service worker caching | C | FR-32 |
| 2.10 | Data message from app to agent when evidence is uploaded; agent proceeds to read-back and consent | A + C | FR-12 |
| 2.11 | Hero overlay on the dashboard: transcript, path and milliseconds per turn, slot checklist, evidence card | C | FR-55 |

**Gate G2.** Time-box: Day 2, 17:00.

**If late**
- Fast path unstable → keep ROUTE for escalation and logging only, send every turn to the LLM, and show the decision in the ticker. Restore the fast path in Phase 5 if time allows.
- Offline queue not done → keep on-device inference (the core of FR-30), drop FR-32 from the demo, and remove the airplane-mode beat from the script.
- Phone audio problems → run the farmer app in a laptop browser window with a headset.

## 6. Phase 3 — Claim pipeline

**Goal:** consent on the call leads to a reference number spoken on the same call.

| # | Item | Track | Requirements |
|---|---|---|---|
| 3.1 | LangGraph graph with the four nodes and edges; pipeline state; `agent.*` events | B | FR-40 to FR-44 |
| 3.2 | Evidence node: weather at the spot, distance from plot, pack saved | B | FR-40 |
| 3.3 | Eligibility node: the eight checks, VERIFY, verdict and reasons | B | FR-41 |
| 3.4 | Filer service: browser-use agent mode against the portal | B | FR-42 |
| 3.5 | Filer scripted mode and `auto` fall-through; `filing.step` events | B | FR-43 |
| 3.6 | Follow-up node: status, time-to-file, message card to the phone | B | FR-44 |
| 3.7 | `/api/cases/{id}/pipeline/run`; Intake agent waits, then speaks the reference; slow and failure paths | A + B | FR-17 |
| 3.8 | Dashboard: agent strip and MCP log live; filing progress in the hero overlay; message card on the phone | C | FR-54, FR-55 |
| 3.9 | P1: reviewer approval of a case sent to review (do this one first: it is the on-stage recovery if the photo is misread) | B + C | FR-59 |
| 3.10 | P1: mandi MCP and loss estimate; evidence pack page; browser mirror | B + C | FR-45, FR-46, FR-57, FR-72 |

**Gate G3.** Time-box: Day 3, 13:00.

**If late:** `FILING_MODE=scripted` for now and move on to Phase 4; come back to agent mode after G4. Skip 3.10; keep 3.9 if at all possible.

## 7. Phase 4 — Fleet and dashboard

**Goal:** the district story around the hero, and the full demo script.

| # | Item | Track | Requirements |
|---|---|---|---|
| 4.1 | Sentinel: scenario start → `storm.detected` through weather MCP | B | FR-01 |
| 4.2 | Dispatcher: open cases, TRIAGE in batches village by village, priority queue, concurrency, retries, calling window | B | FR-02, FR-03, FR-04 |
| 4.3 | Simulator: clock, personas, simulated call outcomes, pipeline with `filing_mode=api` | B | FR-50 |
| 4.4 | Pause on hero call, resume after; hero removed from the queue until triggered | B | FR-56 |
| 4.5 | Dashboard: storm animation, dots by status, countdown, counters, final banner, simulated/live labels | C | FR-51, FR-52, FR-58 |
| 4.6 | Presenter controls and keyboard shortcuts; reset in under 10 s | B + C | FR-56, NFR-07 |
| 4.7 | Tune `SIM_SPEED` and `MAX_PARALLEL_CALLS` so the fleet finishes in 60–90 real seconds at "68 hours left" | B | FR-52 |
| 4.8 | `scripts/report.py` | B | NFR-11 |

**Gate G4.** Time-box: end of Day 3.

**If late:** show counters and a simple grid of dots instead of a map; keep triage real. The map is presentation; the counts are the substance.

## 8. Phase 5 — Hardening and demo

**Goal:** it works every time, and the team can present it.

| # | Item | Who |
|---|---|---|
| 5.1 | Five consecutive full runs from reset; fix what breaks; no new features | all |
| 5.2 | Fallback drills from `Testing.md` §8 | all |
| 5.3 | Record the backup video of a clean run (screen + phone + audio) | person |
| 5.4 | Run on the hotspot only; run on the actual projector resolution | person |
| 5.5 | Fill the pitch numbers from `scripts/report.py` | person |
| 5.6 | Slides (5–6): problem and the 72-hour rule; what exists and the gap; the demo; architecture with the six components; real vs simulated and measured numbers; path to deployment | person, with Claude |
| 5.7 | `README.md` in the project root: what it is, how to run, architecture picture, what is simulated | Claude |
| 5.8 | Rehearse the talk with the script three times, with a timer | all |
| 5.9 | P1/P2 items only if 5.1–5.8 are done | — |

**Gate G5.** Time-box: three hours before submission.

## 9. Cut list

If the build is behind, cut in this order. Nothing above the line is ever cut.

| Order | Cut | Effect on the demo |
|---|---|---|
| — | **Never cut:** live call, on-phone classification, System One decisions on screen, MCP servers, browser filling the form, the counters | — |
| 1 | P2 items (Marathi, satellite) | None |
| 2 | Browser mirror in the dashboard (FR-57) | Show the Chromium window beside the dashboard instead |
| 3 | Mandi MCP and loss estimate (FR-45, FR-72) | Two MCP servers instead of three |
| 4 | Evidence pack page (FR-46) | Evidence shown only as a card |
| 5 | Side questions (FR-18) | Agent escalates when asked something off-script |
| 6 | Offline queue (FR-32) | Drop the airplane-mode beat; on-device inference still shown |
| 7 | Map → grid of dots | Less striking, same information |
| 8 | Fast path → all turns through the LLM | System One still routes and is shown; voice is a little slower |
| 9 | Browser agent → scripted only | Lose "agentic browser use" as a live claim; avoid if at all possible |

## 10. Stretch items, in order

Only after G4.

1. Browser mirror in the dashboard (FR-57).
2. Evidence pack page with loss estimate (FR-45, FR-46).
3. Pre-synthesised audio for fixed lines (lower fast-path latency).
4. Linear-probe edge model, if not already done.
5. A second scenario (unseasonal rain on harvested crop) to show generality.
6. Marathi (FR-20).
7. Satellite before/after (FR-47), using free Copernicus Sentinel-2 data.

## 11. Working with Claude Code

- Start each session with: "Read `CLAUDE.md` and the `context` folder. We are in Phase N, Track X. Build items N.a to N.b. Stop when the tests for those items in `Testing.md` pass, and report what you ran."
- One phase (or one track of a phase) per session. Long sessions drift.
- Ask Claude to check a library's current documentation before using it, and to say when a call in `TechDecisions.md` turned out to be different.
- After each gate: commit, update the status table in `context/README.md`, fill the results log in `Testing.md`.
- When something in this plan proves wrong, have Claude update the documents in the same session as the code.
- Keep `CREDIT_SAVER=1` while building. Switch it off only for voice tests and rehearsals, and run `python scripts/usage.py` each evening.
