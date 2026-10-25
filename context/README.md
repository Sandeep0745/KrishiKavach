# 72 Ghante — project context

**One line:** when a storm hits, our agents phone every affected insured farmer in Hindi, English, Malayalam or Tamil, and file their crop-loss intimation before the 72-hour window closes.

**Hackathon:** Teckashy · **Track:** Agriculture & Climate · **Build window:** 4 days · **Plan locked:** 6 Oct 2026

This folder is the single source of truth for the build. Code must follow it. If something here turns out to be wrong, change the document first (see "Changing the plan"), then the code.

## Reading order

| # | File | What it answers |
|---|---|---|
| 1 | `README.md` | What we are building, what is locked, what is still assumed |
| 2 | `ProblemStudy.md` | Why this problem, who it is for, what exists, the facts and their sources |
| 3 | `Requirements.md` | What the system must do, with priorities (P0/P1/P2) and acceptance criteria |
| 4 | `TechDecisions.md` | Every stack choice, why, its fallback, and what must be re-verified |
| 5 | `ArchitectureDesign.md` | Components, boundaries, main flows, what is real vs simulated |
| 6 | `SystemDesign.md` | Repo layout, ports, schemas, APIs, events, prompts, state machines |
| 7 | `PhasewiseRoadmap.md` | Phase 0–5, what is built when, exit gate for each phase |
| 8 | `Testing.md` | The checks behind each gate, how to run them, and the results log |
| 9 | `DemoScript.md` | The stage demo, second by second, with the fallback for each beat |
| 10 | `HumanSetupChecklist.md` | Accounts, keys, hardware and data only a person can provide |
| 11 | `Phase0Results.md` | What was measured in Phase 0 and the decisions that followed |
| 12 | `Phase1Results.md` | What was built and measured in Phase 1, and which gate checks still need a person |
| 13 | `Phase2Results.md` | What was built and measured in Phase 2, what was fixed after the first laptop run, and what is still unverified |
| 15 | `Phase4Results.md` | What was built and measured in Phase 4: the district run, its timing and totals, why repeated decisions are cached, and what is still unverified |
| 14 | `Phase3Results.md` | What was built and measured in Phase 3: the pipeline, the browser agent's timing, the VERIFY wording experiment, the first spoken test, and what is still unverified |
| 16 | `Phase5Results.md` | What the machine checked for Gate G5: the whole demo rehearsed as text, the fallback drills, the dashboard in the laptop's Chrome, the secrets check, what was fixed, and what the team still has to do |

`CLAUDE.md` in the project root tells Claude Code to read this folder before doing anything.

## What is locked

1. **Problem:** the 72-hour crop-loss intimation window under PMFBY. We do not widen it to general farm advice.
2. **Product shape:** proactive and outbound. The system detects the storm and calls the farmer; the farmer never has to find an app.
3. **Demo shape:** one live call in Hindi, English, Malayalam or Tamil end to end (the "hero" farmer), inside a district-scale fleet of simulated farmers on a map.
4. **Six expected components, each with a real job:**

| Component | Job | Implementation |
|---|---|---|
| Ultra-low-latency voice | The whole farmer interface | LiveKit Agents 1.8; Sarvam Saaras v4 detects and translates farmer speech; Bulbul v3 and language-specific audio caches speak replies; local Piper backs up English |
| System One decision model | Triage ranking, per-utterance routing, peril classification, evidence check | Two small local decision models behind our own decision service: Laya (open model) for triage and evidence checks, and our own trained head for the live call (English since 9 Oct 2026). Jev is paid and not used |
| Edge model | Crop-damage photo classified on the phone, works with no network | MobileCLIP-S0 in the browser via transformers.js |
| Multi-agent orchestration | Seven agents with separate roles | LangGraph pipeline + LiveKit voice agent + dispatcher |
| MCP | Weather, farmer/policy registry, mandi prices | Three MCP servers (official Python SDK 2.x), used by both the voice agent and the pipeline through our own MCP client |
| Agentic browser use | Fills and submits the claim form | browser-use (open source) with a free-tier LLM, driving a visible Chromium window |

5. **Zero spend.** Only open-source software, free tiers and signup credits that need no payment method. No account gets a card attached. Details in `TechDecisions.md` §0 and §9.
6. **Honesty rules** (non-negotiable, see `ArchitectureDesign.md` §7):
   - The claim portal is our own clearly labelled sandbox. We never touch a government system and never copy government branding.
   - All farmer data is synthetic.
   - The dashboard always shows which farmers are simulated and which call is live.
   - A fallback that fires during the demo is shown as a fallback, not disguised.

## Scope in one table

| Real for every farmer | Real only for the hero farmer | Simulated |
|---|---|---|
| Storm detection, System One triage ranking, eligibility rules, claim record created in the sandbox portal | Voice call, on-phone photo classification, browser agent filling the form | The other farmers' answers (scripted personas), the clock (compressed), the storm (replayed scenario file) |

## Assumptions still to confirm

These were not confirmed when the plan was written. The plan works either way, but tell Claude if any is wrong.

| # | Assumption | If wrong |
|---|---|---|
| A1 | Team of 2–4 people, with Claude Code writing most of the code | With 1 person: drop P1 items, use the cut list in `PhasewiseRoadmap.md` |
| A2 | Four working days, integration finished by end of Day 3 | With 3 days: merge Phase 5 into the evening of Day 3 and apply the cut list |
| A3 | Windows 11 laptop, no dedicated GPU needed | Nothing changes; a GPU only makes local Laya faster |
| A4 | An Android phone with Chrome is available for the farmer side | Use a second laptop browser window sized as a phone |
| A5 | Team members can each sign up for the free services in `HumanSetupChecklist.md` without a card | If a service now demands a card, skip it and use the next fallback in `TechDecisions.md` §8 |
| A6 | The demo is given in person with a projector and venue Wi-Fi or a hotspot | For a recorded-only submission, Phase 5 becomes video production |

## Changing the plan

1. Write the change and the reason in the change log at the bottom of `TechDecisions.md`.
2. Update every file the change touches (search for the old name or number).
3. Only then change code.

Do not silently drift. A wrong document is worse than no document, because the next Claude session will trust it.

## Status

| Phase | State | Gate passed on |
|---|---|---|
| 0 Setup and spikes | in progress: setup, System One and browser agent done (`Phase0Results.md`); voice loop (T0-1) and phone classifier (T0-4) still need a person | |
| 1 Foundations | built; automated checks pass on the laptop (`Phase1Results.md`); gate waits for the manual checks T1-10 and T1-12 | |
| 2 Hero call | built; every check that needs no person passes on the laptop (`Phase2Results.md`); gate waits for the spoken and phone tests T2-01 to T2-14 and T2-17 | |
| 3 Claim pipeline | built; every check that needs no person passes on the laptop (`Phase3Results.md`), including the browser agent 5 of 5; gate waits for T3-08 and T3-09 by voice and a look at the visible browser window | |
| 4 Fleet and dashboard | built; on the laptop with the real models the district run gives 312/11/9/5/3 in 73-74 s with "68 hours left" (`Phase4Results.md`); gate waits for the full demo with the phone (T4-12) and a look at the dashboard during a run | |
| 5 Hardening and demo | machine part done on the laptop (`Phase5Results.md`): the whole demo rehearsed 3 of 3 from a cold start (hero call as text), fallback drills 10 of 10, secrets check, dashboard in Chrome at both projector sizes, root README, slide draft; gate waits for the team: five runs with the phone, hotspot, cold start, the manual drills, backup video, rehearsals, honesty review, zero-spend check (`HumanSetupChecklist.md` steps 16-24) | |

Update this table when a gate in `Testing.md` passes.


## Multilingual intake update — 11 October 2026

The live call starts in the supported primary language of the farmer's state: Madhya Pradesh/Sehore Hindi, Tamil Nadu Tamil, Kerala Malayalam, otherwise English. Only Hindi, English, Malayalam and Tamil are enabled. Saaras v4 streaming uses language="unknown", mode="translate": detected source-language metadata selects speech, while the English translation feeds existing S1/slot guards. Explicit requests override automatic detection; an unclear/unsupported detection or a short English yes/no does not change the current language. Requests to change language or repeat a misunderstood question do not grant identity or consent and do not consume the question retry budget. Bulbul v3 receives the selected language per utterance; scripted questions have fixed source translations requiring a native-speaker review and the cache key includes language. English Piper is restricted to English. Non-English speech may use signup credits even with CREDIT_SAVER=1 if not cached. Dashboard transcripts are labelled as translated with the source language. Provider failure is reported, never disguised as successful speech. Automated and synthetic audio tests are separate from the required human phone rehearsal; Commit eligibility for this prototype was accepted by the user after real-phone Hindi/English and automated farmer-browser Malayalam/Tamil checks; physical-phone Malayalam/Tamil and native-speaker review remain outstanding.

References: https://docs.sarvam.ai/api-reference/speech-to-text/transcribe/ws ; https://docs.sarvam.ai/api/getting-started/models/saaras ; installed LiveKit Agents 1.8.5 Sarvam plugin (STT final alternatives.language/confidence, TTS update_options).
