# Technology decisions

Each decision lists what we chose, why, what we fall back to, and what was actually verified on 6 Oct 2026. Library APIs and free-tier limits move quickly: **before writing code against any library below, open its current documentation and confirm the calls, and before relying on a free limit, read it in that provider's own console.** The snippets and numbers here show the shape, not a guarantee.

## 0. The budget rule

**The project spends nothing.** Only three kinds of thing are allowed:

1. Software that runs on our own laptop or phone (open models, open-source libraries).
2. Free tiers that need no payment method.
3. One-time signup credits that need no payment method.

**No account used by this project ever gets a card, UPI mandate or any other payment method attached.** With no payment method an account cannot be charged; when a free limit runs out the service simply stops, and our fallback takes over. Anything that needs a payment method to sign up is not used.

Each team member may use their own account on a service. Do not create duplicate accounts to get around a limit.

## 1. Summary

| Area | Choice (all free) | First fallback | Second fallback |
|---|---|---|---|
| Language/runtime | Python 3.12 (uv), Node 20+ | — | — |
| Voice framework | LiveKit Agents (Python, ~1.8) on LiveKit Cloud free plan | Pipecat (open source) | Pre-recorded call |
| Speech-to-text | Deepgram Nova-3, Indian English `en-IN` (signup credit) | Sarvam Saaras v4 (signup credit) | Groq Whisper large-v3 (free tier) |
| Text-to-speech | Pre-synthesised audio cache for scripted lines + Sarvam Bulbul v3 for live replies (signup credit) | Cartesia through LiveKit's included monthly credit | Piper English voice, local, unlimited |
| Conversation LLM | Free tier, chosen in Phase 0: Groq or Gemini | The other of the two | Next free provider in the chain |
| System One | Laya multilingual, run locally (open model) | Jev, only if its signup credit is available without a card | Free-tier LLM with constrained output, labelled as fallback |
| Edge model | MobileCLIP-S0 zero-shot in the browser (transformers.js) | Linear probe on MobileCLIP embeddings | Binary damaged/healthy |
| Orchestration | LangGraph for the claim pipeline; plain asyncio for dispatcher and simulator | Plain Python functions in sequence | — |
| MCP | Official Python SDK 2.x (`MCPServer`), streamable HTTP | stdio transport | — |
| Browser agent | browser-use (open source) with a free-tier LLM, visible Chromium | Scripted Playwright fill | — |
| Backend | Starlette + uvicorn, SQLite through the standard library, Server-Sent Events for the live streams | — | — |
| Frontend | Plain HTML, CSS and JavaScript modules served by the orchestrator (no build step); SVG district map | MapLibre GL from a CDN for a richer map | — |
| Phone access | cloudflared quick tunnel to the orchestrator port (free, no account) | Same Wi-Fi with a self-signed certificate | — |
| Weather, prices | Open-Meteo (free, no key); data.gov.in (free key) | Fixture files | — |

## 2. Voice

**Choice:** LiveKit Agents with a cascaded pipeline (STT → decision service → LLM → TTS).

**Why cascaded and not a speech-to-speech model:** we need a hook between "farmer finished speaking" and "LLM starts", because that is where the System One model routes the turn. A cascaded pipeline gives us that hook and lets us show per-stage timings.

**Why LiveKit:** WebRTC transport, turn handling, interruption handling, a browser client SDK, and built-in MCP tool support in the Python agent framework. The framework is open source; LiveKit Cloud's free plan carries the audio.

### 2.1 Speech-to-text

| Order | Provider | Free allowance | Notes |
|---|---|---|---|
| 1 | **Deepgram Nova-3**, language `en-IN` (Indian English; was `hi` until 9 Oct 2026) | $200 signup credit, no card | Streaming. The credit is far more than four days can use |
| 2 | Sarvam Saaras v4, `en-IN` | Part of the ₹100 signup credit (₹30 per hour of audio) | Built for Indian languages and Indian English |
| 3 | Groq Whisper large-v3 | Free tier: 20 requests/min, 2,000/day, 7,200 audio seconds/hour | Not streaming: needs voice-activity detection to cut the utterance, then one request. Slower but unlimited in practice |

Phase 0 compared 1 and 2 on the Hindi test utterances; the English utterances of `Testing.md` §9 must be compared again. Pick the more accurate one; on a tie pick Deepgram because its credit is much larger.

### 2.2 Text-to-speech

TTS is the scarce resource, so the design avoids calling it:

1. **Audio cache.** Every scripted line in `SystemDesign.md` §10.2 is synthesised once and saved to disk. Lines with variables are synthesised for the hero's actual values (the hero is fixed), so a normal hero call plays almost entirely from cache: no API call, no cost, and no synthesis delay.
2. **Live synthesis** only for sentences the LLM writes (a few per call) and for the reference number.

| Order | Provider | Free allowance | Notes |
|---|---|---|---|
| 0 | Disk cache | Unlimited | Built by `scripts/build_tts_cache.py` |
| 1 | **Sarvam Bulbul v3**, `en-IN`, voice `simran` | ₹100 signup credit ≈ 33,000 characters if spent only on TTS | Indian-English voice; used for building the cache and for live replies |
| 2 | Cartesia `sonic-3` through LiveKit Inference | $2.50 of inference credit a month, included in the free LiveKit plan | No extra key. Indian-English voice quality and the size of the allowance in characters must be checked in Phase 0 |
| 3 | **Piper**, voice `en_US-lessac-medium` (Piper has no Indian-English voice) | Unlimited, local, CPU | More robotic, but never runs out. Needs a small adapter to LiveKit's TTS interface |

**Budget arithmetic (estimate):** building the cache ≈ 2,500 characters once. A hero call then needs about 300–500 live characters ≈ ₹1–1.5 of Sarvam credit. So one ₹100 credit covers roughly 60–80 full calls. Development uses text mode and Piper, so the credit is kept for rehearsals and the demo.

### 2.3 Verified and not verified

**Verified**
- Install: `pip install "livekit-agents[sarvam,silero]"`; MCP extra: `livekit-agents[mcp]~=1.8`.
- Sarvam's LiveKit guide: `sarvam.STT(language="hi-IN", model="saaras:v4", mode="transcribe", flush_signal=True)`, `sarvam.TTS(language_code="hi-IN", model="bulbul:v3", speaker=...)`, `AgentSession(turn_detection="stt", min_endpointing_delay=0.07)`, no separate VAD. Voices: Priya, Simran, Ishita, Kavya; Aditya, Anand, Rohan.
- Deepgram: $200 free credit on signup, no card; Nova-3 supports Hindi (`hi`) for streaming, and its `multi` option includes Hindi.
- LiveKit Cloud free plan: 1,000 agent-session minutes and 5,000 WebRTC minutes a month, 5 concurrent agent sessions, no card (third-party listing); $2.50 monthly inference credit that does not roll over (LiveKit's own repository).
- Sarvam: ₹100 credit on signup; STT ₹30/hour; TTS ₹30 per 10,000 characters.
- Groq free tier, no card: Whisper limits as in the table above.
- Piper has two Hindi voices, both medium quality. The original repository was archived in October 2025; the voices still work, and a maintained fork exists.
- MCP attachment in LiveKit: `mcp.MCPToolset(id=..., mcp_server=mcp.MCPServerHTTP("http://host/mcp"))` in `tools=[...]`. Python only.

**Verified on the installed livekit-agents 1.8.5 (Phase 1, see `Phase1Results.md`)**
- Skipping the LLM: override `Agent.llm_node` and yield the scripted text. `on_user_turn_completed` is not called for text input, so the turn logic lives in `llm_node`.
- Cached audio: `session.say(text, audio=<async iterable of rtc.AudioFrame>)`.
- Plugin calls (language changed to English on 9 Oct 2026): `deepgram.STT(model="nova-3", language="en-IN")`; `sarvam.TTS(target_language_code="en-IN", model="bulbul:v3", speaker="simran")` (the parameter is `target_language_code`, not `language_code`; v3 voices include simran, priya, ishita, kavya, ritu, pooja, aditya, rohan); `groq.LLM(model=...)`.
- LiveKit's own MCP toolsets (`livekit.agents.mcp`) fail to import with MCP SDK 2.x. We call our MCP servers from function tools through `ghante_shared/mcp_client.py` instead.
- Text-only testing: `AgentSession(llm=...)`, `start(agent, capture_run=True)`, `session.run(user_input=...)`.
- Local talk test: `python -m apps.voice.agent console` (older Python CLI, uses `sounddevice`). The newer console needs the LiveKit CLI.
- Server and dispatch: `AgentServer()`, `@server.rtc_session(agent_name="intake")`; with an agent name the worker joins only rooms it is dispatched to (`RoomConfiguration` / `RoomAgentDispatch` in the farmer's token).

**Verified in Phase 2 (see `Phase2Results.md`)**
- LiveKit's own `TokenVerifier` accepts the room token made by `ghante_shared/livekit_token.py` and reads the agent dispatch from it.
- `tts_node` can be overridden to yield `rtc.AudioFrame`s from WAV files; LiveKit resamples them to the room's rate.
- Per-turn timings are on the assistant `ChatMessage.metrics` (`llm_node_ttft`, `tts_node_ttfb`, `e2e_latency`); the `metrics_collected` event is deprecated in 1.8.5.
- `python -m apps.voice.agent dev` and `start` both run the worker; hot reload was removed from the Python CLI.
- Piper 1.8.0: `PiperVoice.load(path)`, `voice.synthesize(text)` yields chunks with `audio_int16_bytes` and `sample_rate` (22,050 Hz).
- Browser SDK names used by the farmer app (`LivekitClient.Room`, `RoomEvent.TrackSubscribed`, `RoomEvent.Disconnected`, `Track.Kind.Audio`, `localParticipant.publishData(bytes, {reliable, topic})`) exist in livekit-client 2.22.3.

**Not verified — needs a person at the microphone (T0-1)**
- Turn detection settings when STT is Deepgram rather than Sarvam.
- Whether Cartesia through LiveKit Inference speaks Hindi acceptably.
- Real latency from our network in India.

**Fallbacks**
1. Swap STT or TTS by environment variable (§8).
2. If LiveKit itself blocks us on Day 1, rebuild the loop in Pipecat with the same providers.
3. If voice is unusable on demo day, play the backup recording.

## 3. Conversation LLM

**Choice:** free tiers only, selected in Phase 0. `LLM_CHAIN` lists providers in order; on a rate-limit error the next one is used and `fallback.used` is emitted.

| Candidate | Free limits found on 6 Oct 2026 | Good for |
|---|---|---|
| **Groq** — `openai/gpt-oss-20b`, `openai/gpt-oss-120b`, Qwen models | 30 requests/min, 1,000 requests/day, **8,000 tokens/min**, 200,000 tokens/day; no card | Voice turns: very fast, prompts are small |
| **Gemini** (Google AI Studio) — Flash and Flash-Lite | Reported 15–30 requests/min, 1,500 requests/day, 1M tokens/min; no card. **Sources disagree; read the real limits in AI Studio** | Browser agent (large prompts), and second in line for voice |
| Others if needed: Cerebras free tier, OpenRouter `:free` models, a small local model through Ollama | Not checked | Extra links in the chain |

**Consequences**
- Keep the voice prompt short (under about 1,200 tokens) so Groq's 8,000 tokens/min allows a normal conversation.
- Simulated farmers never call an LLM.
- Which model speaks the best simple Hindi is unknown: the Phase 0 test decides (T0-1). Selection rule: fewest slot errors first, then lowest median time-to-first-token.

## 4. System One decision model

**What it is:** a model that takes a state and a set of typed questions (choice, yes/no, score) and returns answers with probabilities in one pass, without generating text. Jev (TypeSafe AI, September 2026) is the named example in the problem statement. Laya (Convai Innovations, Apache-2.0) is an open model of the same kind with a compatible interface.

**Choice:** our own small HTTP service (`apps/s1`) with one endpoint. Callers never talk to a provider directly. The service tries providers in the order given by the chain for that decision (`S1_CHAIN_TEXT` or `S1_CHAIN_REPORT`).

| Provider | What | Cost | Notes |
|---|---|---|---|
| `head` (first for ROUTE and PERIL) | `intfloat/multilingual-e5-small` sentence encoder plus softmax heads trained on our own labelled English replies (`data/eval`; Hindi until 9 Oct 2026, first drafted in `scripts/spikes/intent_data.py`) | Free, unlimited | Measured 29/30 (ROUTE) and 11/12 (PERIL) at 19 ms on CPU. Non-generative, returns probabilities. Needs a temperature fit and data reviewed by a Hindi speaker |
| `laya` (first for TRIAGE and VERIFY) | `convaiinnovations/laya-multilingual`, run on the laptop | Free, unlimited | `pip install laya`, ~650 MB download, Hindi supported. ~33–40 ms on a T4 GPU; **CPU speed on our laptop must be measured**. Quantised ONNX builds exist on Hugging Face if CPU is slow |
| `jev` (use only if free) | TypeSafe Jev, `POST https://api.typesafe.ai/v1/systemone` | One source says open signup at `console.typesafe.ai` with $5 free credit since 21 Sep 2026; another says waitlist only. **Unclear.** | If a key can be had with no payment method, put `jev` first in the chain: it is the model named in the problem statement and $5 is far more than we need. If signup asks for a card, skip it |
| `llm` | The conversation LLM with JSON output | Free tier | Honest fallback; shown in the ticker as "LLM fallback" |

The OpenRouter route to Jev is paid and is not used.

**Verified**
- Jev request shape: `{"model": "jev-latest", "state": "...", "questions": {"name": {"type": "choice", "options": [...]}}}`; types `choice`, `score`, `noul` (yes/no); each answer carries a confidence. Reported latency 70–500 ms.
- Laya: three checkpoints; multilingual is mmBERT-base, 322M parameters, 1,024-token context; usage `laya.load("convaiinnovations/laya-multilingual").predict(state, questions)`; question fields `type`, `instructions`, `criteria`.
- Laya's own model card warns: base checkpoints are weak without tuning on some benchmarks, raw confidences are over-confident until temperature-calibrated, `score` is its weakest question type, and `noul` can be swayed by label wording.

**Consequences for our design**
- We use `choice` and `noul` only. Ranking is computed from choice probabilities.
- Option lists stay short (≤ 8).
- We ship a labelled evaluation set and a script, fit a temperature on it for Laya, and choose the provider order by measured accuracy and latency.
- Rules and arithmetic (the 72-hour check, policy status) are code, not model calls.
- Measured in Phase 4: with repeats of identical reports computed once (88 of 340 TRIAGE and 2 of 312 VERIFY computed), all cases are ranked 18 s into the run and the fleet finishes in 73-74 s.
- Local CPU speed limits fleet-scale use: 340 triage decisions plus about 310 verify decisions per run. Triage therefore runs village by village in batches, most severe village first, so calling can start before all villages are ranked. If measured CPU time is above about 100 ms per decision, simulated cases use decisions precomputed by the same model in a warm-up pass (`S1_SIM_CACHE=1`), and the ticker marks them "cached". Hero decisions are always live.
- If Hindi accuracy is poor, the service also sends an English gloss of the utterance.

## 5. Edge model

**Choice:** MobileCLIP-S0 (`Xenova/mobileclip_s0`) running in the phone's browser with `@huggingface/transformers`, used zero-shot against text prompts for our five labels. Open model, runs on the phone, free.

**Why:** no training needed, about 66 MB total (vision about 23 MB, text about 43 MB), runs on WebAssembly so it needs no WebGPU, and the browser caches it so it works offline after first load.

**Verified:** model id, the loading code shape, sizes, and the advice to load the vision tower at `fp16` and the text tower at `q8`.

**Not verified:** accuracy on crop-damage photos, and speed on our phone. Both are measured in Phase 0 (T0-4).

**Design details**
- Label text embeddings are precomputed at build time and shipped as JSON, so the phone runs only the vision tower.
- Several prompt phrasings per label, averaged.

**Fallbacks**
1. **Linear probe:** about 30 photos per label, MobileCLIP image embeddings, logistic regression in a notebook, weights shipped as a small JSON file and applied in JavaScript.
2. **Binary:** collapse to "damaged" vs "healthy".

## 6. Orchestration

**Choice:** LangGraph `StateGraph` (open source) for the claim pipeline (Evidence → Eligibility → Filing → Follow-up, with conditional edges). The Sentinel, Dispatcher and simulator are plain asyncio tasks. The Intake agent is the LiveKit voice agent.

**What "agent" means here:** a component with its own role, tools and slice of state, visible as a unit on the dashboard. Not every agent calls an LLM, and we say so if asked.

**MCP from LangGraph:** `langchain-mcp-adapters` (`MultiServerMCPClient`). Verify the current API before use.

**Fallback:** if LangGraph costs more than two hours of trouble, replace the graph with four async functions called in sequence with `if` branches, keeping node names and events.

**As built (Phase 3):** LangGraph 1.2.14 is installed in `.venv` and runs the pipeline on the laptop (`StateGraph`, `add_conditional_edges`, `ainvoke`). The same graph description also builds on a 60-line runner in `pipeline/graph.py`, used where LangGraph is not installed; `GET /health` says which is in use. The pipeline calls the MCP servers through our own `ghante_shared/mcp_client.py` (client name `pipeline`), not through `langchain-mcp-adapters`: one MCP client for every agent, and one dependency fewer.

## 7. Browser agent

**Choice:** browser-use (open source, Python 3.12) driving a visible Chromium window against our sandbox portal, in its own process (`apps/filer`), with a **free-tier LLM** from `BROWSER_LLM_CHAIN` (Gemini first, because its tokens-per-minute allowance fits page-sized prompts).

The vendor's hosted model (`ChatBrowserUse`) is a paid service and is not used.

**Verified:** install is `uv pip install browser-use` then `uvx browser-use install`; Python 3.12 is required; LLM wrappers include `ChatGoogle`, `ChatOpenAI`, `ChatAnthropic`, `ChatGroq`.

**Why its own process:** on Windows, Playwright needs an event loop that can spawn subprocesses; a separate process avoids clashes with the web server and isolates crashes.

**As built (Phase 3)**
- The Filer starts Chrome itself with a debugging port and its own profile. browser-use 0.13.11 connects with `Browser(cdp_url=..., keep_alive=True, allowed_domains=[...])`; Playwright 1.63 connects with `chromium.connect_over_cdp(...)`. Both work in the same visible window, which is what makes the fall-through from agent to scripted fill possible. No Chromium download is needed.
- **One agent per page, not one for the whole form.** The free tier's limit is tokens per minute (8,000 for `openai/gpt-oss-120b`), not requests. One agent for the form: 7 requests, 182 s, most of it waiting for the allowance. One small agent per page, stopped when the page changes: 3 requests, about 8,400 tokens, about 30 s. Calls confirmed in 0.13.11: `Tools(exclude_actions=[...])`, `register_should_stop_callback`, `register_new_step_callback(state, output, step)`, `use_judge=False`, `directly_open_url=False`, `fallback_llm`, `history.usage.total_tokens`.
- **Models tried on the three-page form (free tier, 7 Oct):** Groq `openai/gpt-oss-120b` correct; Groq `qwen/qwen3.8-27b` could not upload the photo; Groq `openai/gpt-oss-20b` cannot produce the action format ("Tool choice is none, but model called a tool"); Gemini `gemini-3.8-flash` answered 503 "high demand". So the agent uses gpt-oss-120b, and the scripted fill is the fallback that matters.

**Designing for free-tier limits**
- **Few LLM calls per filing.** Allow several actions per agent step so one call fills a whole page of fields. Target: 6–12 LLM calls for the three pages, not 30–40.
- **Small pages.** The portal's HTML is minimal, so each prompt is small.
- **Development uses the scripted fill.** `FILING_MODE=scripted` is the default while building; agent mode is switched on for its own tests, rehearsals and the demo. Every agent run is counted in the usage log.
- **Time and step limits** (75 s, 20 steps). On failure, timeout or a rate-limit error, the scripted Playwright fill finishes the job on the same browser (FR-43) and the dashboard says so.
- `FILING_MODE=agent|scripted|auto` (`auto` = agent, then scripted on failure; the demo setting).

## 8. Fallback matrix

All switches are free options.

| Dependency | Symptom | Switch | Result |
|---|---|---|---|
| STT | Errors, lag, or credit used up | `STT_PROVIDER=deepgram\|sarvam\|groq` | Next provider |
| TTS | Errors, lag, or credit used up | `TTS_PROVIDER=sarvam\|cartesia_lk\|piper` (cache is always tried first) | Next provider; Piper never runs out |
| Conversation LLM | Rate limit or slow | Automatic along `LLM_CHAIN` | Next free provider |
| System One | Error or > `S1_TIMEOUT_MS` | Automatic along `S1_CHAIN_TEXT` / `S1_CHAIN_REPORT` | Next provider, marked in the ticker |
| Browser agent | Stuck, > 75 s, or rate-limited | Automatic in `auto` mode | Scripted fill, labelled |
| MobileCLIP zero-shot | Wrong labels | `EDGE_MODE=probe` or `binary` | Linear probe or binary |
| Open-Meteo | Unreachable | `WEATHER_MODE=replay` (demo default) | Scenario file |
| Mandi API | No key or unreachable | `MANDI_MODE=fixture` | Fixture prices |
| Venue internet | Down | Phone hotspot | Same demo |
| Everything | Unrecoverable on stage | Play backup video | Narrated recording |

## 9. Free limits and how we stay inside them

| Service | Free allowance (as found; confirm in the console) | Card needed? | What uses it | Runs out → |
|---|---|---|---|---|
| LiveKit Cloud | 1,000 agent minutes/month, 5 concurrent sessions, $2.50 inference credit/month | No | Every voice call | A full call is about 3 minutes, so about 300 calls a month: enough, but check the usage log. If it runs out: text console for testing, backup video for the demo |
| Deepgram | $200 signup credit | No | STT | Sarvam STT, then Groq Whisper |
| Sarvam | ₹100 signup credit | No | TTS cache build + live replies | Cartesia via LiveKit, then Piper |
| Groq | 1,000 requests/day, 8,000 tokens/min, 200,000 tokens/day per chat model | No | Voice LLM | Gemini |
| Gemini (AI Studio) | Reported about 1,500 requests/day on Flash; unconfirmed. On the team key (8 Oct): `gemini-3.8-flash` 429 (no free quota); `gemini-3.1-flash-lite` and `gemini-flash-lite-latest` answer | No | Backup voice LLM; second browser-agent model | Groq / scripted fill |
| TypeSafe (Jev) | Reported $5 signup credit; unconfirmed | Unknown — if yes, skip | System One (optional) | Laya |
| Laya, MobileCLIP, Piper, browser-use, LangGraph, MCP SDK, Playwright | Open source, local | — | — | — |
| Open-Meteo, cloudflared quick tunnel, data.gov.in | Free | No | Weather, phone access, prices | Fixtures |

**Credit-saver mode.** `CREDIT_SAVER=1` is the default during development: TTS uses the cache and Piper only, `FILING_MODE=scripted`, System One is Laya, and voice work is done in the agent's text console where possible. Set `CREDIT_SAVER=0` for voice tests, rehearsals and the demo.

**Usage log.** Each process adds to `logs/usage.json`: STT seconds, live TTS characters, LLM requests and tokens per provider, System One calls per provider, browser-agent runs. `python scripts/usage.py` prints it with an estimate of what is left of each allowance. Check it each evening.

**What zero budget costs us**
- We may not be able to say "Jev" on stage, only "an open System One model of the same kind". If the free Jev credit exists, this cost disappears.
- Live TTS is rationed, so rehearsals with real voice are limited to a few dozen.
- The browser agent may hit a rate limit mid-form; the scripted fallback covers it, visibly.
- Free limits can change without notice. Every one has a local or second-provider fallback.

## 10. Phase 0 results

Filled in during Phase 0. Until then every row is "pending".

| Spike | Question | Result | Decision |
|---|---|---|---|
| T0-1 | STT: Deepgram vs Sarvam on the Hindi utterances (errors out of 10) | pending | pending |
| T0-1 | Conversation LLM: slot errors and median time-to-first-token per free candidate | pending | pending |
| T0-1 | Voice response time over 10 turns, median and worst | pending | pending |
| T0-1 | Cached audio playback works; Piper adapter works; Cartesia-through-LiveKit Hindi acceptable? | pending | pending |
| T0-2 | Jev: can a key be obtained with no payment method? | No. Signup is paid | Not used |
| T0-2 | Laya on our laptop CPU: milliseconds per decision, single and batched | About 175 ms for a 3-option question; about 500 ms for 7 options plus a yes/no; 340 triage decisions about 61 s | Use for TRIAGE and VERIFY; rank village by village |
| T0-2 | Accuracy per S1 provider | Laya: TRIAGE 6/6 on English reports; Hindi ROUTE about 50 %, English ROUTE 15-18/24; PERIL 9/9 in English, 4-5/9 in Hindi. Trained head (e5-small + softmax): ROUTE 29/30, PERIL 11/12, 19 ms | **ROUTE and PERIL: trained head. TRIAGE and VERIFY: Laya.** Details in `Phase0Results.md` |
| T0-3 | Browser agent: LLM calls and seconds for the 5-field test form, per free LLM | Groq `openai/gpt-oss-120b`: 3/3 correct, 3 steps, 43-84 s. Gemini `gemini-3.8-flash`: 1/3, frequent 503 errors. Free limits in AI Studio not read yet | `BROWSER_LLM_CHAIN=groq:openai/gpt-oss-120b,gemini:gemini-3.8-flash`. Find where the seconds go in Phase 3 |
| T0-4 | Edge model: accuracy on sample photos, inference time on the demo phone | pending | pending |

## 11. Change log

| Date | Change | Reason | Files updated |
|---|---|---|---|
| 6 Oct 2026 | Plan locked | — | all |
| 9 Oct 2026 | **The call is in English only.** Every scripted line, the LLM prompt, the phone app, the message card and the synthetic farmers' answers are English; Hindi is removed everywhere (no `name_hi`, no `village_hi`, no `text_en` gloss, `message.text_hi` is now `message.text`). Speech: Deepgram Nova-3 `en-IN`, Sarvam Saaras `en-IN`, Sarvam Bulbul v3 `en-IN` voice `simran`, Piper `en_US-lessac-medium`. `apps/voice/hindi.py` is replaced by `words.py` (spoken times, reference numbers, causes). The word checks in `flow.py` (share, time, stage, question words) and the sentence splitter in `speech.py` are English. The `head` decision model is trained on new English examples (`route_train.jsonl` 151, `peril_train.jsonl` 56) and `s1_eval.jsonl` ROUTE and PERIL are English. `scripts/seed.py` regenerates the same 340 farmers with English answers only (outcomes unchanged). Deepgram `en-IN` on Nova-3 and Sarvam `en-IN` with `simran` were checked against the providers' current documentation through third-party listings, as the official pages could not be reached. **Not measured yet:** the head's English accuracy and fast-path threshold (`scripts/eval_s1.py --provider head` on the laptop; Hugging Face was not reachable from the build machine), English speech-to-text accuracy, the English audio cache (rebuild with `scripts/build_tts_cache.py`). `Phase0Results.md` to `Phase5Results.md` describe the Hindi build and are kept as the record of what was measured | Requested by the team: the farmer side must be English | `context/README.md`, `SystemDesign.md`, `TechDecisions.md`, `Requirements.md`, `ArchitectureDesign.md`, `Testing.md`, `DemoScript.md`, `HumanSetupChecklist.md`, `PhasewiseRoadmap.md`, `ProblemStudy.md`, root `README.md`, `setup/SETUP-TONIGHT.md`, `.env.example`, `setup/2c-install-packages.cmd`, code, data and tests |
| 8 Oct 2026 | **Phase 5 hardening.** A dashboard that connects or reloads mid-demo gets the recent events replayed after the snapshot, then a `tallies` event with the run's true counts. The decision service answers one made-up ROUTE, PERIL and TRIAGE question at start-up and lists them under `warmed` in `/health`; `smoke.py` and `demo_check.py` wait for it. `/health` on the orchestrator reports `hero_phones`. New checks: `demo_check.py` (whole demo, several runs), `drills.py`, `secrets_check.py` (capitalised names such as `APIConnectionError` are not keys). Farmer page: the camera is asked for again with simpler settings before falling back to the gallery picker. New laptops: `setup\2c-install-packages.cmd` installs the package lists frozen from the team laptop (`setup/locks/`). Dashboard tests on the laptop run from `.venv-browser` with the installed Chrome. Voice LLM backups are now Groq `gpt-oss-120b`, Gemini `gemini-3.1-flash-lite`, Gemini `gemini-flash-lite-latest` (`gemini-3.8-flash` has no free quota on the team key; drill D4 passes with the new backups). `DemoScript.md` wording matched to the screen. Which voice speaks the read-back (`CREDIT_SAVER`) is left to the team | The first rehearsal after start-up ended early while later ones passed; old reports tripped the key check; the phone-page test failed when the camera was opened a second time in the laptop's Chrome; T5-03 needs a README a person can follow from cold | SystemDesign, Testing, HumanSetupChecklist, DemoScript, README (root and context), CLAUDE.md, SETUP-TONIGHT, Phase5Results |
| 7 Oct 2026 | **Phase 4 build choices.** `MAX_PARALLEL_CALLS` 6 → 8. The run starts at the detection time. `S1_SIM_CACHE` now defaults to 1 and is keyed on what the model reads (the rendered report); it is emptied on reset; the TRIAGE report gives distance in whole kilometres. Replay weather footprint = the circle plus 2 km around each listed village. The orchestrator keeps one MCP session open per server. SQLite `synchronous=NORMAL`; event log file kept open; `stats.updated` throttled. Simulated evidence has no photo file (`edge_mode: simulated`). `time_to_file_s` for simulated cases is scenario time from the opening of the case. New events `scenario.state` and `scenario.finished`; snapshot carries `farms` and `scenario`; new endpoints `scenario/start`, `pause`, `resume`, `queue`. The hero call pauses the run and the presenter resumes it (P). With `HERO_SIM=1` the hero is shown as simulated | Measurements in `Phase4Results.md` | SystemDesign, TechDecisions, Testing, README, CLAUDE.md, DemoScript, .env.example |
| 7 Oct 2026 | **Phase 3 build choices.** Pipeline graph runs on LangGraph where installed and on a built-in runner otherwise; state key `evidence` renamed `pack`. Eligibility: VERIFY is asked only when every rule passed; a missing cause or stage gives `review`; the weather record is looked up at the recorded storm time when the farmer's time is within 180 minutes of it; rule 7a covers every peril. VERIFY report reworded without figures. State machine gains `FAILED → FILING` (retry). `pipeline/run` answers `pending` when filing outlasts the wait. New event `review.decision`; new endpoints `review` and `evidence-pack`; dashboard keys A (approve) and F (file again). Filer: starts Chrome itself and shares the window between browser-use and Playwright through the debugging port; browser agent is one small agent per page; every page on the first model of `BROWSER_LLM_CHAIN`; `FILING_MODE` unset means `scripted` while `CREDIT_SAVER=1`. A live case approved by a reviewer with no photo is filed through the portal API and says so. Service-to-service addresses use `127.0.0.1` (the name `localhost` cost 2 s per request on Windows). Voice: no early replies on half-heard sentences, the read-back cannot be interrupted, one change to the call at a time | Phase 3 measurements and the first spoken test (`Phase3Results.md`, `Phase2Results.md`) | SystemDesign, TechDecisions, Testing, README, CLAUDE.md, .env.example |
| 7 Oct 2026 | **Phase 2 build choices.** On the LLM path the model only extracts (one JSON-mode request per turn); the agent's questions are always scripted lines. A plain yes/no skips the LLM only when the reply has five words or fewer. `no` at the greeting ends as wrong person; `no` at the plot question escalates. State machine gains `EVIDENCE → ESCALATED`. The room token is made with the standard library and carries the agent dispatch. Speech is cached per sentence; local Piper voice (`hi_IN-priyamvada-medium`, piper-tts 1.8.0) is the free fallback and the only live voice while `CREDIT_SAVER=1`. The LLM connection is kept open and opened at call start. Farmer app loads `livekit-client` 2.22.3 and `@huggingface/transformers` 3.8.1 from jsDelivr; photo is taken inside the page; vision model `fp32`; label embeddings built in Python with onnxruntime. Decision models preload at service start. Phone link falls back to `ssh -R` through localhost.run when cloudflared is missing. `TTS_PROVIDER` is no longer read | One LLM call per turn and scripted wording keep latency and speech cost down and make the call testable as text; a new TLS handshake per turn cost 5-10 s on the team's Wi-Fi; LiveKit's MCP support does not load with SDK 2.x; no npm build; GitHub downloads fail on the team's network | SystemDesign, TechDecisions, Testing, Phase2Results, README, HumanSetupChecklist, CLAUDE.md |
| 7 Oct 2026 | **Phase 1 closing changes.** VERIFY asks one question (`evidence_consistent`); numbers and weather are checked by eligibility rules 6-7b before the model. One time limit per decision provider (`S1_TIMEOUT_MS_HEAD/_LAYA/_LLM`) replaces `S1_TIMEOUT_MS`. `FAST_PATH_MIN=0.5`. Dashboard is a no-build page with an SVG map; counters are counted from cases; the closing banner counts only cases a person must act on; reset is a double press; key L shows or hides the live-call panel. Voice runs in `.venv-voice` on livekit-agents 1.8.5; scripted replies come from `Agent.llm_node`; MCP is called through our own client because LiveKit's MCP support does not load with SDK 2.x; `dev.py` starts the voice worker only with `--voice`. `post_event` leaves `live` unset unless the caller knows it | Laya answered "no" to the review question every time and missed number-based cases; a 20 ms model and a 2 s hosted model cannot share one time limit; measured ROUTE confidences; no npm on this network; the installed LiveKit version | SystemDesign, TechDecisions, Testing, DemoScript, Phase1Results, README, CLAUDE.md, .env.example |
| 7 Oct 2026 | **Phase 1 build choices.** Starlette instead of FastAPI; standard-library sqlite3 instead of SQLModel; Server-Sent Events instead of WebSockets (`/api/events/stream`, `/api/farmer/{id}/stream`); MCP SDK 2.x (`MCPServer`, `mcp.Client`); `unittest` instead of pytest; shared package at the root as `ghante_shared/`; MCP servers in `mcp_servers/`; `S1_TIMEOUT_MS` raised from 400 to 1500; added `POST /api/cases` as a development helper; the web app will be plain HTML/JS served by the orchestrator instead of Vite + React | Fewer dependencies to install on a network where package downloads fail; the installed MCP SDK is 2.x and renamed its classes; Laya takes 175-500 ms on CPU; everything could be tested end to end before it reached the laptop | SystemDesign, TechDecisions, Testing, ArchitectureDesign, PhasewiseRoadmap, CLAUDE.md |
| 7 Oct 2026 | **System One split into two providers.** `head` (multilingual-e5-small encoder + softmax heads trained on our Hindi examples) answers ROUTE and PERIL; `laya` answers TRIAGE and VERIFY from short English reports. Chains are now per decision. Browser agent LLM is Groq `openai/gpt-oss-120b` first, Gemini second. Jev confirmed paid and dropped | Phase 0 measurements: Laya is about 50 % on Hindi replies but 6/6 on English triage; the head is 29/30 at 19 ms; Gemini free tier returned 503 errors | TechDecisions, SystemDesign, Phase0Results, .env.example |
| 6 Oct 2026 | **Zero-budget rule.** Removed all paid options: Jev via OpenRouter, the paid browser-agent model, paid top-ups for speech and LLM, real telephony (FR-19). Laya is now the default System One provider; Jev only if free without a card. STT moved to Deepgram's signup credit; TTS now cache-first with Sarvam's signup credit, then LiveKit's included credit, then local Piper. Added credit-saver mode and a usage log | Team has no budget | all |

| 10 Oct 2026 | Add an optional ngrok free development-domain launcher for one reusable farmer URL. The account token stays in `.env`; the launcher checks the local app, discovers and verifies the HTTPS endpoint, then saves `/farmer` to `var/farmer-link.txt`. Keep the existing temporary tunnel helper as a fallback. | Judges need one bookmark across restarts. A code change cannot reserve a public domain without an account. ngrok's documented free assigned domain supports this without buying a domain; the laptop and tunnel must remain running. | scripts/farmer_link.py, setup/9-stable-farmer-link.cmd, setup/SINGLE-FARMER-LINK.md, .env.example, README, SystemDesign |
| 10 Oct 2026 | Use `127.0.0.1` for phone tunnels and smoke service checks; count unreachable services as readiness failures | The SSH tunnel returned 502 when `localhost` resolved to a different address; smoke could time out on the name and did not count failed service checks | setup/8-phone-link.cmd, scripts/smoke.py, tests/test_phase5.py |
| 10 Oct 2026 | Repair hidden `.pth` files in project-local Python environments during Windows startup; prune bundled runtimes and tool caches from the source/log secret scan | Python 3.12.15 skips hidden `.pth` files, breaking pywin32 after a copied setup. Browser profile databases and vendor fixtures produce false key matches and slow the scan | setup/local-runtime.cmd, setup/repair-python-paths.ps1, scripts/secrets_check.py, Testing |
| 10 Oct 2026 | Restore omitted runtime and verification scripts from the original project. | GitHub copy could not execute its documented launchers or checks. | scripts, TechDecisions |
| 10 Oct 2026 | Resolve Python 3.12 through uv on fresh installs; preserve a valid existing project interpreter. | Installer previously referenced a nonexistent .venv on fresh checkouts. | setup/2c-install-packages.cmd |
| 10 Oct 2026 | Check local environments, configuration and service ports before the full-demo launcher schedules a reset. | A second checkout must not reset another running demo when its own services cannot bind. | scripts/check_startup.py, setup/7-start-everything.cmd |
| 11 Oct 2026 | Merge the final English-only demo while retaining GitHub runtime, stable-link and verification repairs. | Synchronize the final delivery without reintroducing prior startup and scan regressions. | Application, English fixtures, tests, context and README |

## Automatic weather watch — 11 October 2026

Use Open-Meteo Forecast API for this educational, non-commercial prototype: no key, current and hourly fields, UTC timestamps, explicit metric units, batch coordinates for the 12 seeded villages, five-minute polling. IMD district warnings remain a possible official corroboration source; WeatherAPI requires a key. Add `get_crop_risk` to weather MCP. The orchestrator owns polling, persisted six-hour trigger cooldown and scenario-start state checks. Fail closed on missing, stale or unavailable weather; never replace an API failure with a synthetic storm. Live forecasts trigger the existing labelled sandbox hail scenario, not a real claim or proof of loss. Separate presenter-controlled demo weather follows the same parser and trigger, labelled simulated, with a 20-second clear-to-danger transition. Local demo controls require loopback client/Host/Origin; public clients can read weather status only.


## Multilingual intake update — 11 October 2026

The live call starts in the supported primary language of the farmer's state: Madhya Pradesh/Sehore Hindi, Tamil Nadu Tamil, Kerala Malayalam, otherwise English. Only Hindi, English, Malayalam and Tamil are enabled. Saaras v4 streaming uses language="unknown", mode="translate": detected source-language metadata selects speech, while the English translation feeds existing S1/slot guards. Explicit requests override automatic detection; an unclear/unsupported detection or a short English yes/no does not change the current language. Requests to change language or repeat a misunderstood question do not grant identity or consent and do not consume the question retry budget. Bulbul v3 receives the selected language per utterance; scripted questions have fixed source translations requiring a native-speaker review and the cache key includes language. English Piper is restricted to English. Non-English speech may use signup credits even with CREDIT_SAVER=1 if not cached. Dashboard transcripts are labelled as translated with the source language. Provider failure is reported, never disguised as successful speech. Automated and synthetic audio tests are separate from the required human phone rehearsal; Commit eligibility for this prototype was accepted by the user after real-phone Hindi/English and automated farmer-browser Malayalam/Tamil checks; physical-phone Malayalam/Tamil and native-speaker review remain outstanding.

References: https://docs.sarvam.ai/api-reference/speech-to-text/transcribe/ws ; https://docs.sarvam.ai/api/getting-started/models/saaras ; installed LiveKit Agents 1.8.5 Sarvam plugin (STT final alternatives.language/confidence, TTS update_options).
